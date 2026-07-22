"""Drive the shipped BNS JSONL process boundary."""

from __future__ import annotations

import base64
import json
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class BNSStdioProcess:
    """A bounded JSONL client for one real ``qns.bns`` subprocess."""

    def __init__(
        self,
        rom: Path,
        *,
        model: str,
        state: Path | None = None,
        pc_disk_dir: Path | None = None,
        reset: str | None = None,
        cycles: int = 0,
    ):
        command = [
            sys.executable,
            "-m",
            "qns.bns",
            str(rom),
            "--model",
            model,
            "--stdio",
            "jsonl",
            "--cycles",
            str(cycles),
        ]
        if state is not None:
            command.extend(("--state", str(state)))
        if pc_disk_dir is not None:
            command.extend(("--pc-disk-dir", str(pc_disk_dir)))
        if reset is not None:
            command.extend(("--reset", reset))

        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        if self.process.stdin is None or self.process.stdout is None or self.process.stderr is None:
            raise RuntimeError("failed to open BNS subprocess standard streams")

        self._events: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._stderr_lock = threading.Lock()
        self.speech_names: list[str] = []
        self.serial = (bytearray(), bytearray())

        threading.Thread(
            target=self._read_stdout,
            daemon=True,
            name="bns-jsonl-stdout",
        ).start()
        threading.Thread(
            target=self._read_stderr,
            daemon=True,
            name="bns-jsonl-stderr",
        ).start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("BNS JSONL output event is not an object")
                self._events.put(event)
        except BaseException as error:
            self._events.put(error)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            with self._stderr_lock:
                self._stderr_lines.append(line.rstrip())

    def stderr(self) -> str:
        """Return diagnostics captured from the child process."""
        with self._stderr_lock:
            return "\n".join(self._stderr_lines)

    def send_event(self, device: str, **payload: object) -> None:
        """Send one immediately flushed JSONL input event."""
        if self.process.poll() is not None:
            raise RuntimeError(
                f"BNS subprocess exited with {self.process.returncode}; stderr=[{self.stderr()}]"
            )
        assert self.process.stdin is not None
        event = {"device": device, **payload}
        self.process.stdin.write(json.dumps(event, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def send_keyboard(self, *, text: str | None = None, chord: int | None = None) -> None:
        """Send text or one raw physical chord to the keyboard device."""
        if (text is None) == (chord is None):
            raise ValueError("send_keyboard requires exactly one of text or chord")
        if text is not None:
            self.send_event("keyboard", text=text)
        else:
            self.send_event("keyboard", chord=chord)

    def send_serial(self, channel: int, data: bytes) -> None:
        """Send binary data to one ASCI channel."""
        encoded = base64.b64encode(data).decode("ascii")
        self.send_event(f"serial{channel}", data=encoded)

    def next_event(self, timeout: float) -> dict[str, Any]:
        """Return the next event while retaining speech and serial history."""
        try:
            item = self._events.get(timeout=timeout)
        except queue.Empty as error:
            status = self.process.poll()
            raise TimeoutError(
                f"no BNS event within {timeout:.1f}s; returncode={status}; "
                f"speech_tail=[{' '.join(self.speech_names[-40:])}]; "
                f"stderr=[{self.stderr()}]"
            ) from error
        if isinstance(item, BaseException):
            raise RuntimeError(f"invalid BNS JSONL output: {item}") from item

        device = item.get("device")
        if device == "speech":
            name = item.get("name")
            if isinstance(name, str) and name != "PA":
                self.speech_names.append(name)
        elif device in ("serial0", "serial1"):
            data = item.get("data")
            if not isinstance(data, str):
                raise RuntimeError(f"serial output event lacks base64 data: {item}")
            try:
                decoded = base64.b64decode(data, validate=True)
            except ValueError as error:
                raise RuntimeError(
                    f"serial output event has invalid base64 data: {item}"
                ) from error
            self.serial[int(device[-1])].extend(decoded)
        return item

    def wait_for(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        description: str,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Consume events until one satisfies ``predicate`` or the bound expires."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                event = self.next_event(remaining)
            except TimeoutError as error:
                raise TimeoutError(
                    f"timed out waiting for {description}: {error}"
                ) from error
            if predicate(event):
                return event
        raise TimeoutError(f"BNS did not produce {description} within {timeout:.1f}s")

    def wait_for_keyboard(
        self,
        state: str,
        *,
        chord: int | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Wait for a firmware-derived keyboard flow-control event."""
        return self.wait_for(
            lambda event: (
                event.get("device") == "keyboard"
                and event.get("state") == state
                and (chord is None or event.get("chord") == chord)
            ),
            f"keyboard {state}",
            timeout=timeout,
        )

    def wait_for_speech_suffix(
        self,
        suffix: tuple[str, ...],
        description: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        """Wait until non-pause speech ends with an exact phoneme suffix."""
        if not suffix:
            raise ValueError("speech suffix must not be empty")
        if tuple(self.speech_names[-len(suffix):]) == suffix:
            return
        self.wait_for(
            lambda _event: tuple(self.speech_names[-len(suffix):]) == suffix,
            description,
            timeout=timeout,
        )

    def wait_for_serial(
        self,
        channel: int,
        start: int,
        suffix: bytes,
        description: str,
        *,
        timeout: float = 30.0,
    ) -> int:
        """Wait for exact ASCI bytes after ``start`` and return the new cursor."""
        if not suffix:
            raise ValueError("serial suffix must not be empty")
        if bytes(self.serial[channel][start:]).endswith(suffix):
            return len(self.serial[channel])
        self.wait_for(
            lambda _event: bytes(self.serial[channel][start:]).endswith(suffix),
            description,
            timeout=timeout,
        )
        return len(self.serial[channel])

    def arm_pc_watch(self, address: int, *, timeout: float = 30.0) -> None:
        """Arm the native logical-PC watch and require its causal acknowledgment."""
        self.send_event("cpu", watch_pc=address)
        self.wait_for(
            lambda event: (
                event.get("device") == "cpu"
                and event.get("event") == "watch-armed"
                and event.get("pc") == address
            ),
            f"PC {address:04X} watch acknowledgment",
            timeout=timeout,
        )

    def wait_for_pc_watch(
        self,
        address: int,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Wait for the exact native hit event for a previously armed PC watch."""
        return self.wait_for(
            lambda event: (
                event.get("device") == "cpu"
                and event.get("event") == "pc-watch"
                and event.get("pc") == address
            ),
            f"PC {address:04X} watch hit",
            timeout=timeout,
        )

    def request_stop(self, *, timeout: float = 30.0) -> None:
        """Request orderly exit and require confirmation after post-run work."""
        self.send_event("system", action="stop")
        self.wait_for(
            lambda event: (
                event.get("device") == "system"
                and event.get("state") == "exited"
            ),
            "graceful system exit",
            timeout=timeout,
        )
        try:
            returncode = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("BNS did not exit after graceful-stop confirmation") from error
        if returncode != 0:
            raise RuntimeError(
                f"BNS graceful stop exited with {returncode}; stderr=[{self.stderr()}]"
            )

    def stop(self) -> None:
        """Stop the verification subprocess without saving its disposable state."""
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def __enter__(self) -> BNSStdioProcess:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.stop()
