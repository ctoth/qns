"""Show six-key chords reaching the firmware, end to end.

Feeds host key input through the real reader - decoder, assembler and all -
then hands the assembled chords to a running machine and reports what the
firmware says back.  Both input styles are exercised: the win32-input-mode
records a terminal sends when it reports key releases, and the
line-delimited characters a redirected stdin sends when it does not.

The chord is held back until the greeting has finished.  The driver's
ready gate opens partway through that utterance, and a chord delivered
while the firmware is speaking is accepted into its input buffer and then
dropped without ever being queued.

    uv run investigations/six_key_delivery.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from qns.bns import BNS, _six_key_reader
from qns.input_driver import ChordInputDriver

ROM = Path("roms/bspeng.bns")
MAX_CYCLES = 200_000_000
GREETING_CYCLES = 80_000_000

VK_SPACE = 0x20


def record(vk: int, char: str, *, down: bool) -> bytes:
    """One win32-input-mode key transition, as the terminal would send it."""
    return f"\x1b[{vk};0;{ord(char) if char else 0};{1 if down else 0};0;1_".encode()


def chords_from(data: bytes, *, tty: bool) -> list[int]:
    """Run the real reader over `data`, returning the chords it assembles."""
    read_fd, write_fd = os.pipe()
    os.write(write_fd, data)
    os.close(write_fd)

    class Stdin:
        def fileno(self):
            return read_fd

        def isatty(self):
            return tty

    saved, sys.stdin = sys.stdin, Stdin()
    chords: list[int] = []
    try:
        _six_key_reader("6-key", chords.append)
    finally:
        sys.stdin = saved
        os.close(read_fd)
    return chords


def main() -> None:
    # The 1-3-5 chord: dots 1, 3 and 5 with the space bar, which on the
    # default layout is space held with 'f', 's' and 'k'.  Pressing them
    # together and letting go is what ends the chord.
    keys = ((VK_SPACE, " "), (0x46, "f"), (0x53, "s"), (0x4B, "k"))
    held = b"".join(record(vk, char, down=True) for vk, char in keys)
    held += b"".join(record(vk, char, down=False) for vk, char in reversed(keys))

    by_release = chords_from(held, tty=True)
    by_line = chords_from(b" fsk\n", tty=False)
    print(f"chords_from_key_releases={[hex(c) for c in by_release]}")
    print(f"chords_from_redirected_line={[hex(c) for c in by_line]}")
    assert by_release == by_line == [0x55], "the two input styles must agree"

    spoken: list[str] = []
    accepted: list[int] = []
    original_accept = ChordInputDriver._accept
    original_tick = ChordInputDriver.tick
    seeded = False

    def traced_tick(self) -> None:
        nonlocal seeded
        if not seeded and self._bns.stats.get("cycles", 0) >= GREETING_CYCLES:
            seeded = True
            for chord in by_release:
                self.queue.put(chord)
        original_tick(self)

    def note_accept(self) -> None:
        if self._chord:
            accepted.append(self._chord)
        original_accept(self)

    def say(text: str) -> None:
        spoken.append(text)

    ChordInputDriver.tick = traced_tick
    ChordInputDriver._accept = note_accept

    bns = BNS(core="direct", stdin_device="6-key", english_callback=say)
    bns.load_rom(ROM)
    bns.run(max_cycles=MAX_CYCLES)

    print(f"chords_accepted_by_firmware={[hex(c) for c in accepted]}")
    print(f"firmware_said={spoken}")
    assert accepted == [0x55], "the firmware did not consume the chord"
    assert "option" in spoken, "the 1-3-5 chord did not reach the options menu"
    print("OK: the 1-3-5 chord opened options")


if __name__ == "__main__":
    main()
