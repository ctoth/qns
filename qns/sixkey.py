"""Six-key Braille entry: host key transitions to firmware chords.

The emulated keyboard latches a whole dot pattern - `BrailleKeyboard.press`
takes a bitmask and the firmware ISR reads that port once - so the firmware
never sees an individual key going down.  A chord must therefore be
assembled on the host and handed over complete.

That needs key *releases*, which a plain pty does not carry.  Windows
Terminal's win32-input-mode does (see `qns.keysource`), and so does
`ReadConsoleInput` on native Windows, so the assembler here consumes key
transitions and commits a chord when the last key of it comes back up -
the same moment the hardware would.  `TimedKeyDecoder` covers terminals
that report no releases by synthesizing the missing releases after a gap,
so the same assembler remains the only owner of chord completion.

Bit assignment follows `ASCII_TO_BNS_KEY`: bits 0-5 are dots 1-6 and bit 6
is the space bar ('a' is 0x01, 'b' 0x03, 'c' 0x09, 'd' 0x19, all dot 1
based, and the space chord is 0x40).
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

# The virtual key codes are Win32's, and shared with the terminal
# decoders, so they live with the key source.  Named here too, because
# this is where they mean a chord.
from .keysource import (  # noqa: F401  (re-exported for callers)
    LEFT_CTRL_PRESSED,
    VK_BACK,
    VK_DOWN,
    VK_END,
    VK_ESCAPE,
    VK_F4,
    VK_F5,
    VK_HOME,
    VK_LEFT,
    VK_MENU,
    VK_NEXT,
    VK_PRIOR,
    VK_RETURN,
    VK_RIGHT,
    VK_SPACE,
    VK_UP,
    KeyEvent,
    VTKeyDecoder,
    Win32InputDecoder,
)

DOT_BITS = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20)
SPACE_BIT = 0x40

# Dot keys per layout, in dot order 1-6.
SIX_KEY_LAYOUTS: dict[str, str] = {
    "6-key": "fdsjkl",
    "6-key-dvorak": "ueohtn",
}

# Named keys that stand in for a whole chord.  Each is the exact byte the
# user could also produce by chording the dots by hand, so these are
# aliases rather than a separate class of input.
NAMED_CHORDS: dict[int, int] = {
    VK_BACK: SPACE_BIT | 0x01 | 0x02,  # space+1+2
    VK_ESCAPE: SPACE_BIT | 0x01 | 0x04 | 0x10 | 0x20,  # space+1+3+5+6
    VK_RETURN: SPACE_BIT | 0x01 | 0x10,  # space+1+5
    VK_UP: SPACE_BIT | 0x01,  # space+1
    VK_DOWN: SPACE_BIT | 0x08,  # space+4
    VK_LEFT: SPACE_BIT | 0x04,  # space+3
    VK_RIGHT: SPACE_BIT | 0x20,  # space+6
    VK_PRIOR: SPACE_BIT | 0x02 | 0x04,  # space+2+3
    VK_NEXT: SPACE_BIT | 0x10 | 0x20,  # space+5+6
}

# Named keys that mean a different chord while Ctrl is held.  These take
# precedence over NAMED_CHORDS, so Ctrl+Left is the dot-2 chord rather
# than the plain Left arrow's space+3.
CTRL_NAMED_CHORDS: dict[int, int] = {
    VK_HOME: SPACE_BIT | 0x01 | 0x02 | 0x04,  # ctrl+home  -> space+1+2+3
    VK_END: SPACE_BIT | 0x08 | 0x10 | 0x20,  # ctrl+end   -> space+4+5+6
    VK_RIGHT: SPACE_BIT | 0x10,  # ctrl+right -> dot-5 chord
    VK_LEFT: SPACE_BIT | 0x02,  # ctrl+left  -> dot-2 chord
}


def _warn_stderr(message: str) -> None:
    print(f"[Input] {message}", file=sys.stderr)


def layout_dot_bits(layout: str) -> dict[str, int]:
    """Map one layout's lower-case dot keys to their chord bits."""
    try:
        keys = SIX_KEY_LAYOUTS[layout]
    except KeyError:
        raise ValueError(f"unknown six-key layout: {layout}") from None
    return {key: bit for key, bit in zip(keys, DOT_BITS)}


@dataclass
class SixKeyAssembler:
    """Assemble chords from key transitions, committing on full release.

    Space and Alt both contribute the space bar's bit, so `space`+`f` and
    `alt`+`f` produce the same chord as the physical space bar with dot 1.
    Held state is keyed by physical virtual-key identity, not chord bit or
    release character: distinct Space and Alt keys remain distinct, and a
    modifier-changing release still matches its press.

    A repeated record with a repeat count is legitimate auto-repeat and is
    ignored.  A fresh down for an already-held key instead indicates that
    focus may have been lost along with its release, so the uncertain chord
    is abandoned.  The horizon is the corresponding time-based recovery
    when no duplicate record arrives.
    """

    layout: str = "6-key"
    horizon: float | None = 2.0
    clock: Callable[[], float] = time.monotonic
    warn: Callable[[str], None] = _warn_stderr
    _dot_bits: dict[str, int] = field(init=False)
    _held: dict[tuple[str, int | str], tuple[int, float]] = field(
        default_factory=dict,
        init=False,
    )
    _accumulated: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._dot_bits = layout_dot_bits(self.layout)

    def feed(self, event: KeyEvent) -> Iterator[int]:
        """Consume one key transition, yielding any completed chord."""
        now = self.clock()
        self._expire(now)
        identity = self._key_identity(event)

        if not event.down:
            if identity in self._held:
                del self._held[identity]
                if not self._held and self._accumulated:
                    yield self._accumulated
                    self._accumulated = 0
            return

        bit = self._chord_bit(event)
        if bit is not None:
            if identity in self._held:
                if event.repeat > 1:
                    return
                self._abandon("abandoned six-key chord after repeated key-down")
            self._held[identity] = (bit, now)
            self._accumulated |= bit
            return

        named = CTRL_NAMED_CHORDS.get(event.vk) if event.ctrl else None
        if named is None:
            named = NAMED_CHORDS.get(event.vk)
        if named is not None:
            # A named key stands alone; abandon any half-built cell so a
            # stray dot cannot leak into the next chord.
            self._held.clear()
            self._accumulated = 0
            yield named

    def poll(self) -> Iterator[int]:
        """Abandon a chord once any held key crosses the safety horizon."""
        self._expire(self.clock())
        yield from ()

    @property
    def wait_timeout(self) -> float | None:
        """Seconds until the oldest held key reaches the safety horizon."""
        if self.horizon is None or not self._held:
            return None
        oldest = min(pressed_at for _, pressed_at in self._held.values())
        return max(0.0, oldest + self.horizon - self.clock())

    @staticmethod
    def _key_identity(event: KeyEvent) -> tuple[str, int | str]:
        """Stable identity for one physical key, with a character fallback."""
        if event.vk:
            return ("vk", event.vk)
        return ("char", event.char.casefold())

    def _chord_bit(self, event: KeyEvent) -> int | None:
        """Return the chord bit this key contributes, if it is a chord key."""
        if event.vk in (VK_SPACE, VK_MENU):
            return SPACE_BIT
        if event.char:
            return self._dot_bits.get(event.char.lower())
        return None

    def _expire(self, now: float) -> None:
        if self.horizon is None:
            return
        if any(now - pressed_at >= self.horizon for _, pressed_at in self._held.values()):
            self._abandon("abandoned six-key chord after a stuck-key horizon")

    def _abandon(self, message: str) -> None:
        if not self._held and not self._accumulated:
            return
        self._held.clear()
        self._accumulated = 0
        self.warn(message)


@dataclass
class TimedKeyDecoder:
    """Turn plain chord characters into normalized down/up transitions.

    A terminal that reports no releases leaves only arrival time to say
    where one cell stops and the next starts.  Keys pressed together arrive
    before the quiet deadline; reaching it synthesizes their releases.
    Repeating a character first releases the pending cell because the same
    physical finger cannot go down twice at once.

    A timeout of None disables the clock.  Redirected input uses that mode:
    line endings and end-of-input explicitly release the pending keys.
    """

    layout: str = "6-key"
    timeout: float | None = 0.04
    clock: Callable[[], float] = time.monotonic
    _dot_bits: dict[str, int] = field(init=False)
    _held: dict[tuple[str, int], KeyEvent] = field(default_factory=dict, init=False)
    _deadline: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._dot_bits = layout_dot_bits(self.layout)

    def feed_char(self, character: str, now: float | None = None) -> Iterator[KeyEvent]:
        """Consume one character, yielding ordered synthetic transitions."""
        now = self.clock() if now is None else now
        if character == " ":
            vk = VK_SPACE
            identity = ("vk", vk)
        elif character.lower() in self._dot_bits:
            vk = ord(character.upper())
            identity = ("vk", vk)
        else:
            yield from self.flush()
            if character == "\x03":
                yield KeyEvent(
                    vk=ord("C"),
                    scan=0,
                    char=character,
                    down=True,
                    control_state=LEFT_CTRL_PRESSED,
                )
            return

        if identity in self._held:
            yield from self.flush()
        event = KeyEvent(vk=vk, scan=0, char=character, down=True)
        self._held[identity] = event
        self._deadline = None if self.timeout is None else now + self.timeout
        yield event

    def flush(self) -> Iterator[KeyEvent]:
        """Synthesize releases for every pending character, in press order."""
        for event in self._held.values():
            yield KeyEvent(
                vk=event.vk,
                scan=event.scan,
                char=event.char,
                down=False,
                control_state=event.control_state,
            )
        self._held.clear()
        self._deadline = None

    def poll(self, now: float | None = None) -> Iterator[KeyEvent]:
        """Release the pending cell once its quiet interval has elapsed."""
        if self._deadline is None:
            return
        now = self.clock() if now is None else now
        if now >= self._deadline:
            yield from self.flush()

    @property
    def wait_timeout(self) -> float | None:
        """Seconds until pending synthetic releases, for a blocking read."""
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - self.clock())


@dataclass
class SixKeyInputDecoder:
    """Decode one terminal byte stream into one ordered KeyEvent stream.

    Win32 input records already carry real transitions.  VT named keys are
    normalized to the same vocabulary, while remaining chord characters go
    through `TimedKeyDecoder` to acquire synthetic releases.  The public
    methods yield only `KeyEvent`s, so callers cannot reorder records and
    text by consuming separate collections.
    """

    layout: str = "6-key"
    timeout: float | None = 0.04
    newline_is_return: bool = True
    clock: Callable[[], float] = time.monotonic
    _win32: Win32InputDecoder = field(default_factory=Win32InputDecoder, init=False)
    _vt: VTKeyDecoder = field(init=False)
    _timed: TimedKeyDecoder = field(init=False)
    _record_deadline: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._vt = VTKeyDecoder(
            timeout=self.timeout,
            newline_is_return=self.newline_is_return,
        )
        self._timed = TimedKeyDecoder(
            layout=self.layout,
            timeout=self.timeout,
            clock=self.clock,
        )

    def feed(self, data: bytes, now: float | None = None) -> Iterator[KeyEvent]:
        """Consume bytes and yield normalized transitions in byte-stream order."""
        now = self.clock() if now is None else now
        yield from self._consume_win32(self._win32.feed(data), now)
        self._set_record_deadline(now)

    def poll(self, now: float | None = None) -> Iterator[KeyEvent]:
        """Settle every decoder whose quiet interval has elapsed."""
        now = self.clock() if now is None else now
        if self._record_deadline is not None and now >= self._record_deadline:
            stale = self._win32.flush_stale()
            self._record_deadline = None
            if stale:
                yield from self._consume_win32(stale, now)
                # Quiet already proved these bytes complete.  Do not make a
                # bare Escape wait through a second identical deadline.
                yield from self._consume_vt(self._vt.flush(now), now)
        yield from self._consume_vt(self._vt.poll(now), now)
        yield from self._timed.poll(now)

    def flush(self, now: float | None = None) -> Iterator[KeyEvent]:
        """Settle all pending input at end-of-stream."""
        now = self.clock() if now is None else now
        self._record_deadline = None
        yield from self._consume_win32(self._win32.flush(), now)
        yield from self._consume_vt(self._vt.flush(now), now)
        yield from self._timed.flush()

    @property
    def wait_timeout(self) -> float | None:
        """Seconds until the earliest decoder deadline."""
        waiting = [
            timeout
            for timeout in (
                self._record_wait_timeout,
                self._vt.wait_timeout,
                self._timed.wait_timeout,
            )
            if timeout is not None
        ]
        return min(waiting) if waiting else None

    @property
    def _record_wait_timeout(self) -> float | None:
        if self._record_deadline is None:
            return None
        return max(0.0, self._record_deadline - self.clock())

    def _set_record_deadline(self, now: float) -> None:
        self._record_deadline = (
            now + self.timeout
            if self.timeout is not None and self._win32.stale_flushable
            else None
        )

    def _consume_win32(
        self,
        items: list[KeyEvent | str],
        now: float,
    ) -> Iterator[KeyEvent]:
        for item in items:
            if isinstance(item, KeyEvent):
                yield from self._timed.flush()
                yield item
            else:
                yield from self._consume_vt(self._vt.feed(item, now), now)

    def _consume_vt(self, items, now: float) -> Iterator[KeyEvent]:
        for item in items:
            if isinstance(item, KeyEvent):
                yield from self._timed.flush()
                yield item
            else:
                yield from self._timed.feed_char(item, now)
