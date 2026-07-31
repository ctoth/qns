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
import sys
import threading
import time
from dataclasses import dataclass, field

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

# Win32 virtual key codes.  Every source here speaks them: the console
# reports them, win32-input-mode forwards them, and the VT decoder below
# translates escape sequences into them, so one vocabulary reaches the
# chord tables however the keys arrived.
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_MENU = 0x12
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_F1 = 0x70
VK_F2 = 0x71
VK_F3 = 0x72
# Emulator controls rather than chords: the BNS has no function keys, so
# these are free to mean something to the host.
VK_F4 = 0x73
VK_F5 = 0x74


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
                event = _parse_record(bytes(buffer[escape + 2 : final]))
                if event is not None:
                    events.append(event)
            else:
                # Some other CSI sequence - a status reply, or an ordinary
                # key from a terminal that ignored the mode.  Hand it back
                # as text so the caller's fallback can make sense of it.
                text.append(buffer[escape : final + 1].decode("latin-1"))
            index = final + 1

        del buffer[:index]
        return events, "".join(text)

    @property
    def pending(self) -> bool:
        """Whether an unfinished sequence is being held for its rest."""
        return bool(self._buffer)

    def flush(self) -> str:
        """Give up on an unfinished sequence and hand back its bytes.

        A record split across reads is worth waiting for; a bare ESC that
        stays bare is the Escape key, and would otherwise be held here
        forever.  The caller decides which by how long it has waited.
        """
        text = self._buffer.decode("latin-1")
        self._buffer.clear()
        return text


# Final bytes that name a key: CSI arrows and Home/End, and the SS3
# finals xterm sends for F1-F4.
_VT_FINAL_KEYS = {
    "A": VK_UP,
    "B": VK_DOWN,
    "C": VK_RIGHT,
    "D": VK_LEFT,
    "H": VK_HOME,
    "F": VK_END,
    "P": VK_F1,
    "Q": VK_F2,
    "R": VK_F3,
    "S": VK_F4,
}

# The numbers a `CSI n ~` sequence names a key with.
_VT_TILDE_KEYS = {
    1: VK_HOME,
    2: VK_INSERT,
    3: VK_DELETE,
    4: VK_END,
    5: VK_PRIOR,
    6: VK_NEXT,
    7: VK_HOME,
    8: VK_END,
    11: VK_F1,
    12: VK_F2,
    13: VK_F3,
    14: VK_F4,
    15: VK_F5,
}

# Control characters that are a key in their own right.  Return is not
# among them: whether a line ending means the Enter key or merely the end
# of a line depends on where the bytes came from, so the decoder decides.
_VT_CONTROL_KEYS = {
    "\x7f": VK_BACK,
    "\x08": VK_BACK,
    "\t": VK_TAB,
}


def _parse_vt_sequence(text: str) -> tuple[int, KeyEvent | None]:
    """Read one escape sequence, returning what it spells and its length.

    A length of zero means the sequence is incomplete: the rest may still
    arrive, or the Escape may have been a key on its own, which only a
    quiet interval can settle.
    """
    if len(text) < 2:
        return 0, None
    if text[1] not in ("[", "O"):
        # Escape followed by something else - Alt+key, say.  The Escape
        # stands alone and the rest is read as itself.
        return 1, KeyEvent(vk=VK_ESCAPE, scan=0, char="", down=True)

    index = 2
    while index < len(text) and not (_CSI_FINAL_LOW <= ord(text[index]) <= _CSI_FINAL_HIGH):
        index += 1
    if index >= len(text):
        return 0, None

    final = text[index]
    numbers = [int(part) if part.isdigit() else 0 for part in text[2:index].split(";")]
    if final == "~":
        vk = _VT_TILDE_KEYS.get(numbers[0] if numbers else 0)
    else:
        vk = _VT_FINAL_KEYS.get(final)
    if vk is None:
        # A status reply, or a key with no chord: consumed, not spoken.
        return index + 1, None

    # xterm's modifier parameter is one plus a bitmask of shift, alt, ctrl.
    modifier = numbers[1] if len(numbers) > 1 else 1
    bits = modifier - 1 if modifier else 0
    control_state = (
        (SHIFT_PRESSED if bits & 1 else 0)
        | (LEFT_ALT_PRESSED if bits & 2 else 0)
        | (LEFT_CTRL_PRESSED if bits & 4 else 0)
    )
    return index + 1, KeyEvent(vk=vk, scan=0, char="", down=True, control_state=control_state)


@dataclass
class VTKeyDecoder:
    """Split terminal text into named-key events and ordinary characters.

    A terminal that ignores win32-input-mode still names its special keys,
    just in escape sequences rather than records.  Those have to be read
    before the characters reach a chord assembler, which knows only dot
    letters: Left arrives as `ESC [ D`, whose final byte is the dot-3 key
    on the default layout, and xterm's F4 as `ESC O S`, whose final byte
    is dot 2.  Passed through, they would spell cells nobody typed.

    A lone Escape is the same first byte as the start of a sequence, so it
    is settled the same way a chord's end is: by a quiet interval.  With
    `timeout` None - redirected input, which has no timing worth reading -
    an unfinished sequence waits for `flush` instead.
    """

    timeout: float | None = 0.04
    newline_is_return: bool = True
    _buffer: str = field(default="", init=False)
    _deadline: float | None = field(default=None, init=False)

    def feed(self, text: str, now: float | None = None):
        """Consume text, yielding KeyEvents and plain characters in order."""
        self._buffer += text
        yield from self._drain(now)

    def flush(self, now: float | None = None):
        """Settle an unfinished sequence: its Escape was a key after all."""
        if self._buffer.startswith("\x1b"):
            self._buffer = self._buffer[1:]
            yield KeyEvent(vk=VK_ESCAPE, scan=0, char="", down=True)
        yield from self._drain(now)

    def poll(self, now: float | None = None):
        """Settle a pending Escape once its quiet interval has elapsed."""
        if self._deadline is None:
            return
        now = time.monotonic() if now is None else now
        if now >= self._deadline:
            yield from self.flush(now)

    @property
    def wait_timeout(self) -> float | None:
        """Seconds until a pending Escape settles, for a blocking read."""
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())

    def _drain(self, now: float | None):
        while self._buffer:
            character = self._buffer[0]
            if character != "\x1b":
                self._buffer = self._buffer[1:]
                vk = _VT_CONTROL_KEYS.get(character)
                if vk is None and self.newline_is_return and character in "\r\n":
                    vk = VK_RETURN
                if vk is None:
                    yield character
                else:
                    yield KeyEvent(vk=vk, scan=0, char="", down=True)
                continue

            consumed, event = _parse_vt_sequence(self._buffer)
            if consumed == 0:
                # Incomplete: wait for the rest, or for the quiet interval
                # that proves the Escape was a key by itself.
                if self._deadline is None:
                    self._deadline = (
                        None
                        if self.timeout is None
                        else (time.monotonic() if now is None else now) + self.timeout
                    )
                return
            self._buffer = self._buffer[consumed:]
            self._deadline = None
            if event is not None:
                yield event
        self._deadline = None


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
    for raw_field in fields:
        if not raw_field:
            values.append(0)  # omitted parameters default to zero
            continue
        try:
            values.append(int(raw_field))
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


KEY_EVENT = 0x0001
FOCUS_EVENT = 0x0010
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004


def stdin_console_handle() -> int:
    """The OS handle behind the *current* `sys.stdin`.

    Deliberately not `GetStdHandle`: a caller may hold a console and
    still have replaced `sys.stdin` with a pipe - a test harness driving
    the emulator does exactly that - and opening the process console then
    would read the user's keyboard instead of the stream it was handed.
    Whether the handle is a console at all is left to `GetConsoleMode`.

    Raises OSError when stdin has no OS handle to speak of.
    """
    import msvcrt

    try:
        fileno = sys.stdin.fileno()
    except (AttributeError, ValueError, OSError) as error:
        raise OSError("standard input has no descriptor") from error
    try:
        handle = msvcrt.get_osfhandle(fileno)
    except OSError as error:
        raise OSError("standard input has no OS handle") from error
    if handle in (0, -1):
        raise OSError("no standard input handle")
    return handle


def _console_input_structures():
    """Build the ctypes view of INPUT_RECORD, on Windows only."""
    import ctypes
    from ctypes import wintypes

    class _CharUnion(ctypes.Union):
        _fields_ = [("UnicodeChar", wintypes.WCHAR), ("AsciiChar", ctypes.c_char)]

    class KeyEventRecord(ctypes.Structure):
        _fields_ = [
            ("bKeyDown", wintypes.BOOL),
            ("wRepeatCount", wintypes.WORD),
            ("wVirtualKeyCode", wintypes.WORD),
            ("wVirtualScanCode", wintypes.WORD),
            ("uChar", _CharUnion),
            ("dwControlKeyState", wintypes.DWORD),
        ]

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

    Enter this from the thread that owns the run's cleanup, not from the
    reader itself: a reader blocked in `ReadConsoleInput` when the run
    ends never returns to unwind, and a daemon thread's frames are not
    unwound at exit either, so the console would keep line input, echo
    and processing switched off after the process is gone.  Leaving
    scope therefore cancels the reader as well as restoring the mode -
    the cancelled reader raises OSError, and a synthetic focus record
    unblocks it if it is already waiting.

    Raises OSError when the current standard input is not a console - a
    redirected stdin, or one a caller substituted - so the caller can
    fall back to reading that stream instead.
    """
    handle = stdin_console_handle()
    ctypes, InputRecord = _console_input_structures()
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    saved = wintypes.DWORD()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(saved)):
        raise OSError(ctypes.get_last_error(), "standard input is not a console")

    mode = saved.value & ~(ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT | ENABLE_PROCESSED_INPUT)
    if not kernel32.SetConsoleMode(handle, mode):
        raise OSError(ctypes.get_last_error(), "could not set console mode")

    cancelled = threading.Event()

    def read_events() -> list[KeyEvent]:
        """Block for the next console records, returning key transitions.

        Raises OSError once the context has been left, so a reader that
        outlives the run stops rather than competing with the shell for
        the console it has just handed back.
        """
        if cancelled.is_set():
            raise OSError("console reader cancelled")
        buffer = (InputRecord * 32)()
        count = wintypes.DWORD()
        read = kernel32.ReadConsoleInputW(handle, ctypes.byref(buffer), 32, ctypes.byref(count))
        if cancelled.is_set():
            raise OSError("console reader cancelled")
        if not read:
            raise OSError(ctypes.get_last_error(), "ReadConsoleInput failed")
        events = []
        for record in buffer[: count.value]:
            if record.EventType != KEY_EVENT:
                continue
            key = record.Event.KeyEvent
            character = key.uChar.UnicodeChar
            events.append(
                KeyEvent(
                    vk=key.wVirtualKeyCode,
                    scan=key.wVirtualScanCode,
                    char="" if character in ("", "\x00") else character,
                    down=bool(key.bKeyDown),
                    control_state=key.dwControlKeyState,
                    repeat=max(1, key.wRepeatCount),
                )
            )
        return events

    def wake_reader() -> None:
        """Return a waiting ReadConsoleInput, without spelling a key.

        A focus record is a record the reader discards, so unblocking it
        cannot be mistaken for input by this process or the next one.
        """
        record = InputRecord()
        record.EventType = FOCUS_EVENT
        written = wintypes.DWORD()
        kernel32.WriteConsoleInputW(handle, ctypes.byref(record), 1, ctypes.byref(written))

    try:
        yield read_events
    finally:
        cancelled.set()
        with contextlib.suppress(OSError):
            wake_reader()
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
