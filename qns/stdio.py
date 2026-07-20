"""Structured standard-I/O events for the software BNS runtime."""

import base64
import binascii
import json
import threading
from dataclasses import dataclass
from typing import TextIO


@dataclass(frozen=True)
class KeyboardInput:
    """Text or one raw BNS chord received from standard input."""

    value: str | int


@dataclass(frozen=True)
class SerialInput:
    """Binary bytes received for one Z180 ASCI channel."""

    channel: int
    data: bytes


def parse_input_event(line: str) -> KeyboardInput | SerialInput:
    """Parse and validate one newline-delimited JSON input event."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON input event: {error.msg}") from error

    if not isinstance(event, dict):
        raise ValueError("input event must be a JSON object")

    device = event.get("device")
    if device == "keyboard":
        has_text = "text" in event
        has_chord = "chord" in event
        if has_text == has_chord:
            raise ValueError("keyboard event requires exactly one of text or chord")
        if has_text:
            text = event["text"]
            if not isinstance(text, str):
                raise ValueError("keyboard text must be a string")
            return KeyboardInput(text)

        chord = event["chord"]
        if isinstance(chord, bool) or not isinstance(chord, int) or not 0 <= chord <= 0xFF:
            raise ValueError("keyboard chord must be an integer from 0 through 255")
        return KeyboardInput(chord)

    if device in ("serial0", "serial1"):
        data = event.get("data")
        if not isinstance(data, str):
            raise ValueError("serial data must be a base64 string")
        try:
            decoded = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("serial data is not valid base64") from error
        return SerialInput(channel=int(device[-1]), data=decoded)

    raise ValueError("input event device must be keyboard, serial0, or serial1")


class JSONLOutput:
    """Write atomic, immediately flushed JSONL device events."""

    def __init__(self, stream: TextIO):
        self._stream = stream
        self._lock = threading.Lock()

    def emit(self, device: str, **payload: object) -> None:
        """Write one device event without interleaving concurrent producers."""
        event = {"device": device, **payload}
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._stream.write(f"{line}\n")
            self._stream.flush()

    def emit_serial(self, channel: int, data: bytes) -> None:
        """Write binary ASCI output using the protocol's base64 representation."""
        encoded = base64.b64encode(data).decode("ascii")
        self.emit(f"serial{channel}", data=encoded)
