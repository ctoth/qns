"""Tests for BNS firmware-facing behavior."""

from qns.bns import _ASCII_TO_BNS_KEY, BNS


def test_english_stdio_characters_use_firmware_keyboard_chords():
    """Terminal characters map to the raw chords in the English ROM table."""
    assert _ASCII_TO_BNS_KEY[ord("a")] == 0x01
    assert _ASCII_TO_BNS_KEY[ord("z")] == 0x35
    assert _ASCII_TO_BNS_KEY[ord("A")] == 0x41
    assert _ASCII_TO_BNS_KEY[ord("0")] == 0x34
    assert _ASCII_TO_BNS_KEY[ord(" ")] == 0x40
    assert _ASCII_TO_BNS_KEY[ord("\n")] == 0x8D
    assert _ASCII_TO_BNS_KEY[ord("\r")] == 0x8D
    assert _ASCII_TO_BNS_KEY[0x7F] == 0x78


def test_bsp_command_loop_gate_requires_starta_bg_task_sequence():
    """One initialization write cannot open stdin before STARTA."""
    bns = BNS()

    bns._mem_write(0x41653, 0)
    assert not bns._bsp_command_loop_ready

    bns._mem_write(0x41653, 1)
    bns._mem_write(0x41653, 0)
    assert not bns._bsp_command_loop_ready

    bns._mem_write(0x41653, 0)
    assert bns._bsp_command_loop_ready
