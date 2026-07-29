"""Six-key Braille entry: host key transitions to firmware chords.

The emulated keyboard latches a whole dot pattern - `BrailleKeyboard.press`
takes a bitmask and the firmware ISR reads that port once - so the firmware
never sees an individual key going down.  A chord must therefore be
assembled on the host and handed over complete.

That needs key *releases*, which a plain pty does not carry.  Windows
Terminal's win32-input-mode does (see `qns.keysource`), and so does
`ReadConsoleInput` on native Windows, so the assembler here consumes key
transitions and commits a chord when the last key of it comes back up -
the same moment the hardware would.  `TimedChordAssembler` covers
terminals that report no releases, by inferring the chord's end from a
gap in arrival times instead.

Bit assignment follows `ASCII_TO_BNS_KEY`: bits 0-5 are dots 1-6 and bit 6
is the space bar ('a' is 0x01, 'b' 0x03, 'c' 0x09, 'd' 0x19, all dot 1
based, and the space chord is 0x40).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field

# The virtual key codes are Win32's, and shared with the terminal
# decoders, so they live with the key source.  Named here too, because
# this is where they mean a chord.
from .keysource import (  # noqa: F401  (re-exported for callers)
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
    VK_BACK: SPACE_BIT | 0x01 | 0x02,                  # space+1+2
    VK_ESCAPE: SPACE_BIT | 0x01 | 0x04 | 0x10 | 0x20,  # space+1+3+5+6
    VK_RETURN: SPACE_BIT | 0x01 | 0x10,                # space+1+5
    VK_UP: SPACE_BIT | 0x01,                           # space+1
    VK_DOWN: SPACE_BIT | 0x08,                         # space+4
    VK_LEFT: SPACE_BIT | 0x04,                         # space+3
    VK_RIGHT: SPACE_BIT | 0x20,                        # space+6
    VK_PRIOR: SPACE_BIT | 0x02 | 0x04,                 # space+2+3
    VK_NEXT: SPACE_BIT | 0x10 | 0x20,                  # space+5+6
}

# Named keys that mean a different chord while Ctrl is held.  These take
# precedence over NAMED_CHORDS, so Ctrl+Left is the dot-2 chord rather
# than the plain Left arrow's space+3.
CTRL_NAMED_CHORDS: dict[int, int] = {
    VK_HOME: SPACE_BIT | 0x01 | 0x02 | 0x04,  # ctrl+home  -> space+1+2+3
    VK_END: SPACE_BIT | 0x08 | 0x10 | 0x20,   # ctrl+end   -> space+4+5+6
    VK_RIGHT: SPACE_BIT | 0x10,               # ctrl+right -> dot-5 chord
    VK_LEFT: SPACE_BIT | 0x02,                # ctrl+left  -> dot-2 chord
}


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
    A key already held repeats (terminals auto-repeat while held) and is
    ignored; the chord accumulates every dot pressed during it, so
    releasing one finger early still spells the whole cell.
    """

    layout: str = "6-key"
    _dot_bits: dict[str, int] = field(init=False)
    _held: set[int] = field(default_factory=set, init=False)
    _accumulated: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._dot_bits = layout_dot_bits(self.layout)

    def feed(self, event: KeyEvent) -> Iterator[int]:
        """Consume one key transition, yielding any completed chord."""
        bit = self._chord_bit(event)
        if bit is not None:
            if event.down:
                self._held.add(bit)
                self._accumulated |= bit
            elif bit in self._held:
                self._held.discard(bit)
                if not self._held and self._accumulated:
                    yield self._accumulated
                    self._accumulated = 0
            return

        if not event.down:
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

    def _chord_bit(self, event: KeyEvent) -> int | None:
        """Return the chord bit this key contributes, if it is a chord key."""
        if event.vk in (VK_SPACE, VK_MENU):
            return SPACE_BIT
        if event.char:
            return self._dot_bits.get(event.char.lower())
        return None


@dataclass
class TimedChordAssembler:
    """Assemble chords from characters alone, ending them on a time gap.

    A terminal that reports no releases leaves only arrival time to say
    where one cell stops and the next starts.  Keys pressed together
    arrive within a few milliseconds of each other, while successive cells
    are separated by far more, so a quiet interval ends the chord.  A key
    that repeats within one chord must be a new cell - the same finger
    cannot press twice at once - and commits the pending one immediately.

    A timeout of None disables the clock entirely, leaving only explicit
    flushes to end a cell.  Redirected input uses that: piped bytes all
    arrive at once, so their arrival times say nothing, and a line ending
    - which is not a dot key, and so flushes - delimits the cell instead.
    """

    layout: str = "6-key"
    timeout: float | None = 0.04
    _dot_bits: dict[str, int] = field(init=False)
    _accumulated: int = field(default=0, init=False)
    _seen: set[int] = field(default_factory=set, init=False)
    _deadline: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._dot_bits = layout_dot_bits(self.layout)

    def feed_char(self, character: str, now: float | None = None) -> Iterator[int]:
        """Consume one character, yielding any chord it completes."""
        now = time.monotonic() if now is None else now
        bit = SPACE_BIT if character == " " else self._dot_bits.get(character.lower())
        if bit is None:
            yield from self.flush()
            return
        if bit in self._seen:
            yield from self.flush()
        self._accumulated |= bit
        self._seen.add(bit)
        self._deadline = None if self.timeout is None else now + self.timeout

    def flush(self) -> Iterator[int]:
        """Commit whatever cell is pending."""
        if self._accumulated:
            yield self._accumulated
        self._accumulated = 0
        self._seen.clear()
        self._deadline = None

    def poll(self, now: float | None = None) -> Iterator[int]:
        """Commit the pending cell once its quiet interval has elapsed."""
        if self._deadline is None:
            return
        now = time.monotonic() if now is None else now
        if now >= self._deadline:
            yield from self.flush()

    @property
    def wait_timeout(self) -> float | None:
        """Seconds until the pending cell expires, for a blocking read."""
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())
