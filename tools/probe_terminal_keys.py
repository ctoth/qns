#!/usr/bin/env python3
"""Probe what key information this terminal can actually deliver.

Six-key braille entry needs to know when a chord is *finished*, which a
plain pty cannot say: it carries characters, not key transitions.  Two
terminal protocols do carry transitions over the same pty:

  * Windows Terminal's win32-input-mode (CSI ? 9001 h), which forwards the
    full Win32 KEY_EVENT_RECORD - virtual key, scan code, key-down flag,
    control-key state - as `CSI Vk;Sc;Uc;Kd;Cs;Rc _`.
  * The kitty keyboard protocol (CSI > flags u) with the "report event
    types" flag, which appends `:1` press / `:2` repeat / `:3` release to
    its `CSI ... u` reports.

This script asks the terminal which it supports, then lets you press keys
under each so the raw bytes are visible.  Run it from the terminal you
actually type into:

    uv run tools/probe_terminal_keys.py
"""

from __future__ import annotations

import os
import select
import sys
import termios
import time
import tty

PROBE_SECONDS = 6.0


def drain(fd: int, timeout: float) -> bytes:
    """Collect everything the terminal sends within `timeout` seconds."""
    deadline = time.monotonic() + timeout
    chunks: list[bytes] = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            continue
        data = os.read(fd, 4096)
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks)


def show(label: str, data: bytes) -> None:
    if not data:
        print(f"  {label}: (nothing)")
        return
    printable = repr(data.decode("latin-1"))
    print(f"  {label}: {printable}")


def write(fd: int, text: str) -> None:
    os.write(fd, text.encode("ascii"))


def query(fd: int, label: str, request: str, timeout: float = 0.35) -> bytes:
    """Send a request and report the reply, if any."""
    write(fd, request)
    reply = drain(fd, timeout)
    show(label, reply)
    return reply


def interactive(fd: int, prompt: str) -> bytes:
    print(f"\n{prompt}")
    print(f"  (recording {PROBE_SECONDS:.0f}s - press and release some keys)")
    write(fd, "\r\n")
    data = drain(fd, PROBE_SECONDS)
    show("bytes", data)
    return data


def main() -> int:
    if not sys.stdin.isatty():
        print("stdin is not a terminal; run this directly from your terminal.")
        return 1

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    print(f"TERM={os.environ.get('TERM')!r} "
          f"WT_SESSION={'set' if os.environ.get('WT_SESSION') else 'unset'} "
          f"TERM_PROGRAM={os.environ.get('TERM_PROGRAM')!r}")

    try:
        tty.setraw(fd)

        print("\n[1] Terminal identification")
        query(fd, "DA1 (CSI c)", "\x1b[c")
        query(fd, "XTVERSION (CSI > 0 q)", "\x1b[>0q")

        print("\n[2] Kitty keyboard protocol support")
        kitty = query(fd, "current flags (CSI ? u)", "\x1b[?u")
        supports_kitty = b"u" in kitty and kitty.startswith(b"\x1b[?")

        baseline = interactive(
            fd,
            "[3] Plain pty - press 'f', then 'f'+'d' together, then release.",
        )

        if supports_kitty:
            write(fd, "\x1b[>15u")  # disambiguate + report events + all keys
            interactive(
                fd,
                "[4] Kitty protocol enabled - press 'f', then 'f'+'d' together.",
            )
            write(fd, "\x1b[<u")
        else:
            print("\n[4] Kitty protocol: no reply to the flags query; skipping.")

        write(fd, "\x1b[?9001h")  # win32-input-mode
        win32 = interactive(
            fd,
            "[5] win32-input-mode enabled - press 'f', then 'f'+'d' together,\n"
            "    then press and release Alt on its own.",
        )
        write(fd, "\x1b[?9001l")

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    print("\n--- summary ---")
    print(f"kitty keyboard protocol: {'yes' if supports_kitty else 'no'}")
    win32_ok = b"_" in win32
    print(f"win32-input-mode:        {'yes' if win32_ok else 'no'}")
    if not supports_kitty and not win32_ok:
        print("Neither protocol answered: chord ends must be inferred from timing.")
    else:
        print("A protocol answered: real key-release detection is available.")
    print(f"plain-pty bytes seen:    {len(baseline)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
