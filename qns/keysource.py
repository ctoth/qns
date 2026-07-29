"""Key transitions from the host terminal.

A pty carries characters, not key transitions, so a terminal normally
cannot say when a key came back up - and six-key Braille entry needs
exactly that.  Windows Terminal's win32-input-mode closes the gap: after
`CSI ? 9001 h` the terminal forwards the full Win32 `KEY_EVENT_RECORD` as

    CSI Vk ; Sc ; Uc ; Kd ; Cs ; Rc _

carrying the virtual key, scan code, unicode character, **key-down flag**,
control-key state and repeat count.  That reaches a WSL process through
the same pty, and `ReadConsoleInput` supplies identical fields to a native
Windows process, so one decoder serves both.

Terminals that ignore the mode simply keep sending characters; the decoder
passes those through untouched so a caller can fall back to inferring
chord ends from timing.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass

ENABLE_WIN32_INPUT_MODE = "\x1b[?9001h"
DISABLE_WIN32_INPUT_MODE = "\x1b[?9001l"

# Win32 ControlKeyState bits, as reported in the record's Cs field.
RIGHT_ALT_PRESSED = 0x0001
LEFT_ALT_PRESSED = 0x0002
RIGHT_CTRL_PRESSED = 0x0004
LEFT_CTRL_PRESSED = 0x0008
SHIFT_PRESSED = 0x0010

_CSI_FINAL_LOW = 0x40
_CSI_FINAL_HIGH = 0x7E


@dataclass(frozen=True)
class KeyEvent:
    """One key transition: which key, which direction, which modifiers."""

    vk: int
    scan: int
    char: str
    down: bool
    control_state: int = 0
    repeat: int = 1

    @property
    def interrupt(self) -> bool:
        """Whether this is Ctrl-C, however the terminal spelled it.

        Asking for key transitions costs the usual route out.  In
        win32-input-mode the terminal reports Ctrl-C as a record rather
        than sending 0x03, so the pty's line discipline never sees it and
        raises no signal; on a Windows console, reporting it as a record
        at all means turning off the processing that would have raised
        one.  Either way the interrupt has to be recognised here.
        """
        return self.down and (
            self.char == "\x03" or (self.ctrl and self.vk == 0x43)  # 'C'
        )

    @property
    def ctrl(self) -> bool:
        return bool(self.control_state & (LEFT_CTRL_PRESSED | RIGHT_CTRL_PRESSED))

    @property
    def alt(self) -> bool:
        return bool(self.control_state & (LEFT_ALT_PRESSED | RIGHT_ALT_PRESSED))

    @property
    def shift(self) -> bool:
        return bool(self.control_state & SHIFT_PRESSED)


class Win32InputDecoder:
    """Split a terminal byte stream into key transitions and plain text.

    Records may straddle reads, so an incomplete sequence stays buffered
    until the rest of it arrives rather than being mistaken for text.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> tuple[list[KeyEvent], str]:
        """Consume bytes, returning decoded transitions and leftover text."""
        self._buffer.extend(data)
        events: list[KeyEvent] = []
        text: list[str] = []
        index = 0
        buffer = self._buffer

        while index < len(buffer):
            escape = buffer.find(0x1B, index)
            if escape == -1:
                text.append(buffer[index:].decode("latin-1"))
                index = len(buffer)
                break

            if escape > index:
                text.append(buffer[index:escape].decode("latin-1"))
                index = escape

            if escape + 1 >= len(buffer):
                break  # bare ESC so far; the rest may still arrive
            if buffer[escape + 1] != 0x5B:  # '['
                text.append("\x1b")
                index = escape + 1
                continue

            final = _find_final(buffer, escape + 2)
            if final is None:
                break  # incomplete CSI; wait for more bytes
            if buffer[final] == 0x5F:  # '_'
                event = _parse_record(bytes(buffer[escape + 2:final]))
                if event is not None:
                    events.append(event)
            else:
                # Some other CSI sequence - a status reply, or an ordinary
                # key from a terminal that ignored the mode.  Hand it back
                # as text so the caller's fallback can make sense of it.
                text.append(buffer[escape:final + 1].decode("latin-1"))
            index = final + 1

        del buffer[:index]
        return events, "".join(text)


def _find_final(buffer: bytearray, start: int) -> int | None:
    """Index of the CSI sequence's final byte, or None if still incomplete."""
    for position in range(start, len(buffer)):
        if _CSI_FINAL_LOW <= buffer[position] <= _CSI_FINAL_HIGH:
            return position
    return None


def _parse_record(payload: bytes) -> KeyEvent | None:
    """Build a KeyEvent from a win32-input-mode parameter list."""
    fields = payload.split(b";")
    values: list[int] = []
    for field in fields:
        if not field:
            values.append(0)  # omitted parameters default to zero
            continue
        try:
            values.append(int(field))
        except ValueError:
            return None
    values.extend([0] * (6 - len(values)))
    vk, scan, unicode_char, key_down, control_state, repeat = values[:6]
    return KeyEvent(
        vk=vk,
        scan=scan,
        char=chr(unicode_char) if unicode_char else "",
        down=bool(key_down),
        control_state=control_state,
        repeat=max(1, repeat),
    )


STD_INPUT_HANDLE = -10
KEY_EVENT = 0x0001
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004


def _console_input_structures():
    """Build the ctypes view of INPUT_RECORD, on Windows only."""
    import ctypes
    from ctypes import wintypes

    class _CharUnion(ctypes.Union):
        _fields_ = [("UnicodeChar", wintypes.WCHAR),
                    ("AsciiChar", ctypes.c_char)]

    class KeyEventRecord(ctypes.Structure):
        _fields_ = [("bKeyDown", wintypes.BOOL),
                    ("wRepeatCount", wintypes.WORD),
                    ("wVirtualKeyCode", wintypes.WORD),
                    ("wVirtualScanCode", wintypes.WORD),
                    ("uChar", _CharUnion),
                    ("dwControlKeyState", wintypes.DWORD)]

    class _EventUnion(ctypes.Union):
        _fields_ = [("KeyEvent", KeyEventRecord)]

    class InputRecord(ctypes.Structure):
        _fields_ = [("EventType", wintypes.WORD), ("Event", _EventUnion)]

    return ctypes, InputRecord


@contextlib.contextmanager
def windows_console_key_events():
    """Yield a reader of real key transitions from the Windows console.

    `ReadConsoleInput` reports the same `KEY_EVENT_RECORD` fields
    win32-input-mode forwards over a pty, so a native Windows run gets
    true releases too rather than having to infer chord ends from timing.
    Line, echo and processed input are all turned off for the duration.
    Turning processing off is what lets Ctrl-C be seen here at all - the
    console would otherwise swallow it to raise a signal - so the caller
    must act on `KeyEvent.interrupt` itself.  Ctrl-Break is not enough on
    its own: not every keyboard has the key.

    Raises OSError when standard input is not a console - a redirected
    stdin, for instance - so the caller can fall back.
    """
    ctypes, InputRecord = _console_input_structures()
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    if handle == wintypes.HANDLE(-1).value or not handle:
        raise OSError("no standard input handle")

    saved = wintypes.DWORD()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(saved)):
        raise OSError(ctypes.get_last_error(), "standard input is not a console")

    mode = saved.value & ~(
        ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT | ENABLE_PROCESSED_INPUT
    )
    if not kernel32.SetConsoleMode(handle, mode):
        raise OSError(ctypes.get_last_error(), "could not set console mode")

    def read_events() -> list[KeyEvent]:
        """Block for the next console records, returning key transitions."""
        buffer = (InputRecord * 32)()
        count = wintypes.DWORD()
        if not kernel32.ReadConsoleInputW(
            handle, ctypes.byref(buffer), 32, ctypes.byref(count)
        ):
            raise OSError(ctypes.get_last_error(), "ReadConsoleInput failed")
        events = []
        for record in buffer[:count.value]:
            if record.EventType != KEY_EVENT:
                continue
            key = record.Event.KeyEvent
            character = key.uChar.UnicodeChar
            events.append(KeyEvent(
                vk=key.wVirtualKeyCode,
                scan=key.wVirtualScanCode,
                char="" if character in ("", "\x00") else character,
                down=bool(key.bKeyDown),
                control_state=key.dwControlKeyState,
                repeat=max(1, key.wRepeatCount),
            ))
        return events

    try:
        yield read_events
    finally:
        kernel32.SetConsoleMode(handle, saved.value)


@contextlib.contextmanager
def win32_input_mode(fd: int | None):
    """Ask the terminal for key transitions, and always stop asking.

    Leaving the mode enabled would leave the user's shell receiving
    records instead of characters, so the disable is unconditional.  A
    terminal that does not implement the mode ignores both sequences.
    """
    if fd is None:
        yield False
        return
    try:
        os.write(fd, ENABLE_WIN32_INPUT_MODE.encode("ascii"))
    except OSError:
        yield False
        return
    try:
        yield True
    finally:
        with contextlib.suppress(OSError):
            os.write(fd, DISABLE_WIN32_INPUT_MODE.encode("ascii"))
