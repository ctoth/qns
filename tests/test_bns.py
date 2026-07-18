"""Tests for BNS firmware-facing behavior."""

import subprocess
import sys
from io import BytesIO

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


def test_bsplus_maps_msm6242_clock_window_at_port_60():
    """The BSP must see its direct-bus RTC rather than floating port values."""
    bns = BNS()

    assert bns._io_read(0x6F) == 0x04
    bns._io_write(0x6D, 1)
    assert bns._io_read(0x6D) == 1
    bns._io_write(0x6D, 0)
    assert bns._io_read(0x6D) == 0

    for port in range(0x60, 0x6D):
        assert 0 <= bns._io_read(port) <= 9


def test_serial_standard_streams_select_one_asci_channel():
    """Raw serial input and output must not leak across ASCI channels."""
    output = BytesIO()
    bns = BNS(
        stdin_device="serial0",
        serial_output=output,
        serial_output_channel=0,
    )
    bns._serial_input_queue.put(0x5A)

    assert bns._serial_receive(1) == -1
    assert bns._serial_receive(0) == 0x5A
    assert bns._serial_receive(0) == -1

    bns._serial_transmit(1, 0x58)
    bns._serial_transmit(0, 0x41)
    assert output.getvalue() == b"A"


def test_cli_serial_standard_io_round_trip(tmp_path):
    """A firmware byte must travel from stdin through ASCI and back to stdout."""
    echo_rom = tmp_path / "serial-echo.bin"
    echo_rom.write_bytes(bytes((
        0x3E, 0x64,        # LD A,64h: 8-N-1, transmit and receive enabled
        0xED, 0x39, 0x00,  # OUT0 (CNTLA0),A
        0x3E, 0x02,        # LD A,2: BSP's initial 9600-baud divisor
        0xED, 0x39, 0x02,  # OUT0 (CNTLB0),A
        0xED, 0x38, 0x04,  # IN0 A,(STAT0)
        0xE6, 0x80,        # AND RDRF
        0x28, 0xF9,        # JR Z back to the status read
        0xED, 0x38, 0x08,  # IN0 A,(RDR0)
        0xED, 0x39, 0x06,  # OUT0 (TDR0),A
        0x18, 0xF0,        # JR back to the status read
    )))

    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(echo_rom),
            "--cycles",
            "200000",
            "--input",
            "serial0",
            "--output",
            "serial0",
        ),
        input=b"Z",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout == b"Z"
    assert b"Input: STDIN (serial0)" in result.stderr
