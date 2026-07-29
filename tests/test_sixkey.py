"""Six-key Braille entry: decoding key transitions and assembling chords."""

import os

from qns.bns import _six_key_reader
from qns.keysource import KeyEvent, Win32InputDecoder
from qns.sixkey import SixKeyAssembler, TimedChordAssembler

# Captured from a live WSL terminal by tools/probe_terminal_keys.py: Alt
# pressed and released, Alt pressed again, then 'd' and 'f' pressed
# together and released.  The control-key state corroborates itself -
# 0x22 (LEFT_ALT_PRESSED|NUMLOCK_ON) while Alt is held, 0x20 once it is
# released.
PROBE_CAPTURE = (
    b"\x1b[18;56;0;1;34;1_"
    b"\x1b[18;56;0;0;32;1_"
    b"\x1b[18;56;0;1;34;1_"
    b"\x1b[68;32;100;1;34;1_"
    b"\x1b[70;33;102;1;34;1_"
    b"\x1b[68;32;100;0;34;1_"
    b"\x1b[70;33;102;0;34;1_"
    b"\x1b[18;56;0;0;32;1_"
)


def test_decoder_reads_captured_win32_records():
    events, text = Win32InputDecoder().feed(PROBE_CAPTURE)

    assert text == ""
    assert [(event.vk, event.char, event.down) for event in events] == [
        (0x12, "", True),
        (0x12, "", False),
        (0x12, "", True),
        (0x44, "d", True),
        (0x46, "f", True),
        (0x44, "d", False),
        (0x46, "f", False),
        (0x12, "", False),
    ]
    assert events[3].alt is True
    assert events[7].alt is False


def test_assembler_commits_captured_chord_on_full_release():
    """The capture is Alt alone, then Alt held with 'd' and 'f' together."""
    events, _ = Win32InputDecoder().feed(PROBE_CAPTURE)
    assembler = SixKeyAssembler(layout="6-key")

    chords = [chord for event in events for chord in assembler.feed(event)]

    # Alt stands in for the space bar, 'f' is dot 1 and 'd' is dot 2, so
    # the second chord is space+1+2 - the same byte the Backspace key
    # produces, reached by hand.
    assert chords == [0x40, 0x43]


def press(char="", vk=0, *, down=True, control_state=0):
    return KeyEvent(vk=vk or (ord(char.upper()) if char else 0),
                    scan=0, char=char, down=down, control_state=control_state)


def test_dvorak_layout_spells_the_same_cell_from_different_keys():
    """Braille 'c' is dots 1+4: f+j on the default layout, u+h on Dvorak."""
    default = SixKeyAssembler(layout="6-key")
    dvorak = SixKeyAssembler(layout="6-key-dvorak")

    def spell(assembler, first, second):
        chords = []
        for event in (press(first), press(second),
                      press(first, down=False), press(second, down=False)):
            chords.extend(assembler.feed(event))
        return chords

    assert spell(default, "f", "j") == [0x09]
    assert spell(dvorak, "u", "h") == [0x09]


def test_named_keys_emit_once_and_respect_ctrl():
    from qns.keysource import LEFT_CTRL_PRESSED
    from qns.sixkey import VK_ESCAPE, VK_HOME

    assembler = SixKeyAssembler(layout="6-key")

    assert list(assembler.feed(press(vk=VK_ESCAPE))) == [0x75]
    # Only the down transition speaks; the release must not repeat it.
    assert list(assembler.feed(press(vk=VK_ESCAPE, down=False))) == []
    # Home alone is not a BNS chord - only Ctrl+Home is.
    assert list(assembler.feed(press(vk=VK_HOME))) == []
    assert list(
        assembler.feed(press(vk=VK_HOME, control_state=LEFT_CTRL_PRESSED))
    ) == [0x47]


def test_decoder_buffers_a_record_split_across_reads():
    decoder = Win32InputDecoder()
    record = b"\x1b[70;33;102;1;34;1_"

    for cut in (1, 3, 8, len(record) - 1):
        events, text = decoder.feed(record[:cut])
        assert events == [] and text == "", f"emitted early at cut {cut}"
        events, text = decoder.feed(record[cut:])
        assert text == ""
        assert [(event.char, event.down) for event in events] == [("f", True)]


def test_decoder_passes_plain_characters_through_untouched():
    """A terminal that ignores the mode keeps sending characters."""
    events, text = Win32InputDecoder().feed(b"fdffdfd\x1bf")

    assert events == []
    assert text == "fdffdfd\x1bf"


def test_timed_fallback_ends_a_chord_on_a_quiet_interval():
    assembler = TimedChordAssembler(layout="6-key", timeout=0.04)

    assert list(assembler.feed_char("f", now=0.000)) == []
    assert list(assembler.feed_char("d", now=0.005)) == []
    assert list(assembler.poll(now=0.030)) == []   # still within the chord
    assert list(assembler.poll(now=0.050)) == [0x03]
    assert list(assembler.poll(now=0.060)) == []   # committed only once


def test_timed_fallback_treats_a_repeated_key_as_a_new_cell():
    """One finger cannot press the same key twice inside one chord."""
    assembler = TimedChordAssembler(layout="6-key", timeout=0.04)

    assert list(assembler.feed_char("f", now=0.000)) == []
    assert list(assembler.feed_char("f", now=0.010)) == [0x01]
    assert list(assembler.poll(now=0.060)) == [0x01]


class _PipeStdin:
    """Stand in for a redirected stdin backed by a real descriptor."""

    def __init__(self, fd):
        self._fd = fd

    def fileno(self):
        return self._fd

    def isatty(self):
        return False


def test_reader_delimits_redirected_input_by_line(monkeypatch):
    """Piped bytes carry no timing, so a line ending ends the cell."""
    import sys

    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"fd\nj\nfjl\n")
    os.close(write_fd)
    monkeypatch.setattr(sys, "stdin", _PipeStdin(read_fd))

    chords = []
    try:
        _six_key_reader("6-key", chords.append)
    finally:
        os.close(read_fd)

    # f=dot1, d=dot2, j=dot4, l=dot6
    assert chords == [0x03, 0x08, 0x29]
