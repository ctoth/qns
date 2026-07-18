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


def test_bsplus_port_80_is_watchdog_read_and_speech_power_write():
    """The speech-only BSP model must not expose a display at port 0x80."""
    bns = BNS()

    assert not hasattr(bns, "display")
    assert bns._io_read(0x80) == 0xFF

    bns._io_write(0x80, 1)
    assert bns.speech_power_enabled

    bns._io_write(0x80, 0)
    assert not bns.speech_power_enabled

    for port in (0x81, 0x82, 0x83):
        assert bns._io_read(port) == 0xFF
