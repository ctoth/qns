"""Tests for BNS firmware-facing behavior."""

import subprocess
import sys
from io import BytesIO

import pytest

from qns.bns import (
    _ASCII_TO_BNS_KEY,
    _BS2_COMBYT_PHYSICAL,
    _BS2_IIB_PHYSICAL,
    BNS,
    _read_stdin_character,
)


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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console input")
def test_interactive_windows_stdin_reads_one_key_without_newline(monkeypatch):
    """Console keys must reach the BNS immediately without an extra Enter chord."""
    import msvcrt

    class InteractiveInput:
        @staticmethod
        def isatty():
            return True

    characters = iter(("\xe0", "ignored-extended-key", "O"))
    monkeypatch.setattr(sys, "stdin", InteractiveInput())
    monkeypatch.setattr(msvcrt, "getwch", lambda: next(characters))

    assert _read_stdin_character() == "O"


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


def test_power_on_stdin_holds_i_until_firmware_initializes_combyt(monkeypatch):
    """The documented I-chord is down before cycle one and released by WARM0."""
    characters = iter(("I", ""))
    monkeypatch.setattr(
        "qns.bns._read_stdin_character",
        lambda: next(characters),
    )

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("qns.bns.threading.Thread", ImmediateThread)
    bns = BNS(model="bs2", stdin_device="keyboard", power_on_input=True)
    observed = []

    class PowerOnCPU:
        halted = False
        pc = 0

        @staticmethod
        def set_irq(_line, _state):
            pass

        def run(self, cycles):
            observed.append((bns.keyboard.dots, bns.keyboard._key_down))
            bns._mem_write(_BS2_COMBYT_PHYSICAL, 0x64)
            return cycles

    bns.cpu = PowerOnCPU()
    bns.run(max_cycles=1_000)

    assert observed == [(0x4A, True)]
    assert not bns.keyboard._key_down


@pytest.mark.parametrize("character", ["", "i", "O"])
def test_power_on_stdin_requires_documented_uppercase_i(monkeypatch, character):
    """No nearby or missing stdin character may select the hard-reset path."""
    monkeypatch.setattr("qns.bns._read_stdin_character", lambda: character)
    bns = BNS(model="bs2", stdin_device="keyboard", power_on_input=True)

    with pytest.raises(RuntimeError, match="uppercase I"):
        bns.run(max_cycles=1_000)


def test_power_on_stdin_rejects_non_keyboard_channel():
    """A serial byte cannot be silently reinterpreted as a keyboard chord."""
    with pytest.raises(ValueError, match="requires keyboard stdin"):
        BNS(stdin_device="serial0", power_on_input=True)


def test_keyboard_stdin_waits_for_firmware_key_phases(monkeypatch):
    """Queued input starts at a stable wait and spans both `_IIB` ISR phases."""
    characters = iter(("y", ""))
    monkeypatch.setattr(
        "qns.bns._read_stdin_character",
        lambda: next(characters),
    )

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("qns.bns.threading.Thread", ImmediateThread)
    bns = BNS(model="bs2", stdin_device="keyboard")
    observed = []

    class KeyPhaseCPU:
        halted = False
        pc = 0x1BDA

        def __init__(self):
            self.calls = 0

        @staticmethod
        def set_irq(_line, _state):
            pass

        def run(self, cycles):
            self.calls += 1
            self.halted = True
            observed.append(
                (
                    bns.keyboard.dots,
                    bns.keyboard._key_down,
                    bns.keyboard.latched,
                )
            )
            if self.calls == 3:
                bns.memory.write(_BS2_IIB_PHYSICAL, 0x3D)
                bns.keyboard.keyclr_write(bns.keyboard.keyclr_port, 0)
            elif self.calls == 4:
                bns.memory.write(_BS2_IIB_PHYSICAL, 0)
                bns.keyboard.keyclr_write(bns.keyboard.keyclr_port, 0)
            return cycles

    bns.cpu = KeyPhaseCPU()
    bns.run(max_cycles=4_000)

    assert observed == [
        (0, False, False),
        (0, False, False),
        (0x3D, True, True),
        (0x3D, False, True),
    ]
    assert bns.memory.read(_BS2_IIB_PHYSICAL) == 0
    assert not bns.keyboard.latched


def test_address_trace_retains_causal_write_event_once():
    """Overlapping trace selectors must retain one exact instruction event."""
    bns = BNS(trace_writes=0xF000, trace_writes_range=(0xF000, 0xF000))
    bns.memory.load_rom(bytes((
        0x3E, 0x5A,        # LD A,5Ah (6 cycles)
        0x32, 0x00, 0xF0,  # LD (F000h),A
        0x18, 0xFE,        # JR $
    )))

    bns.cpu.run(100)

    assert bns.traced_writes == [(6, 0x0002, 0xF000, 0x5A)]


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


def test_bsplus_port_a0_controls_rs232_transceiver_power():
    """MAXON and MAXOFF use bit zero of the BSPLUS RS-232 power latch."""
    bns = BNS()

    assert not bns.rs232_power_enabled
    assert bns._io_read(0xA0) == 0xFF

    bns._io_write(0xA0, 1)
    assert bns.rs232_power_enabled

    bns._io_write(0xA0, 0)
    assert not bns.rs232_power_enabled

    bns._io_write(0xA0, 9)
    assert bns.rs232_power_enabled


def test_bs2_uses_bsnew_combined_power_latch():
    """BS2 power writes expose the documented BSNEW OUTSEL bit fields."""
    bns = BNS(model="bs2")

    bns._io_write(0xA0, 0x8C)
    assert bns.power_latch == 0x8C
    assert not bns.rs232_power_enabled
    assert not bns.speech_power_enabled
    assert bns.flash_power_enabled
    assert bns.disk_power_enabled
    assert bns.charge_output_high

    bns._io_write(0xA0, 0xAF)
    assert bns.rs232_power_enabled
    assert bns.speech_power_enabled


def test_bs2_wires_bq2010_data_line_between_power_latch_and_port_b():
    """BSNEW bit-5 writes and port-B bit 3 must share the timed gauge line."""
    bns = BNS(model="bs2")

    class TimedCPU:
        cycle_count = 0

    timed_cpu = TimedCPU()
    bns.cpu = timed_cpu

    def write_line(high: bool, cycle: int) -> None:
        timed_cpu.cycle_count = cycle
        bns._io_write(0xA0, 0x20 if high else 0)

    write_line(False, 0)
    write_line(True, 18_020)
    cycle = 24_012
    for bit in range(8):
        write_line(False, cycle)
        low_cycles = 324 if 0x03 & (1 << bit) else 12_820
        write_line(True, cycle + low_cycles)
        cycle += 20_290

    timed_cpu.cycle_count = 184_900
    assert bns._io_read(0x81) == 0xF7

    timed_cpu.cycle_count = 194_400
    assert bns._io_read(0x81) == 0xFF


def test_bs2_owns_8255_and_high_bank_ports():
    """BS2 must not apply the BSPLUS speech latch to its 8255 port A."""
    bns = BNS(model="bs2")

    bns._io_write(0x80, 0x55)
    bns._io_write(0x83, 0xA2)
    bns._io_write(0xE0, 0x08)

    assert not bns.speech_power_enabled
    assert bns._io_read(0x80) == 0xFF
    assert bns._io_read(0x83) == 0xFF
    assert bns.parallel_ports[3] == 0xA2
    assert bns.high_bank_latch == 0x08
    assert bns.memory.high_bank_latch == 0x08
    assert len(bns.memory.flash) == 2 * 1024 * 1024


def test_bs2_wires_clock_pic_to_csio_and_8255_c4_strobe():
    """The BSNEW PIC must receive CSIO commands only on the C4 rising edge."""
    bns = BNS(model="bs2")

    bns.cpu._csio_tx(4)
    assert bns.cpu._csio_rx() == -1

    bns._io_write(0x83, 0x09)

    assert bns.parallel_ports[2] & 0x10
    assert bns.cpu._csio_rx() != -1


def test_bsl_wires_braille_display_to_csio():
    """The B_LITE profile must answer the firmware's attached-display poll."""
    bns = BNS(model="bsl")

    bns.cpu._csio_tx(0x81)

    assert bns.cpu._csio_rx() == 0x0A
    assert bns.cpu._csio_rx() == -1

    bns._io_write(0x83, 0x08)
    assert not bns.parallel_ports[2] & 0x10


def test_bns_rejects_unknown_hardware_model():
    with pytest.raises(ValueError, match="Unsupported BNS model: unknown"):
        BNS(model="unknown")


def test_run_keeps_advancing_native_time_while_cpu_is_halted():
    """HALT waits for hardware interrupts; it does not terminate emulation."""
    bns = BNS()

    class HaltedCPU:
        halted = True
        pc = 0x1234

        def __init__(self):
            self.chunks = []

        def run(self, cycles):
            self.chunks.append(cycles)
            return cycles

    cpu = HaltedCPU()
    bns.cpu = cpu

    bns.run(max_cycles=2000)

    assert cpu.chunks == [1000, 1000]
    assert bns.stats["cycles"] == 2000


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


def test_unselected_serial_output_is_silent(capsys):
    """Firmware serial bytes are not unsolicited console diagnostics."""
    bns = BNS()
    capsys.readouterr()

    bns._serial_transmit(0, ord("M"))
    bns._serial_transmit(1, ord("E"))

    assert capsys.readouterr().out == ""


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


def test_cli_state_round_trip_preserves_rom_shadow_ram(tmp_path):
    """A later process must read bytes written behind ROM by an earlier one."""
    state_path = tmp_path / "bsp.state"
    writer_rom = tmp_path / "state-writer.bin"
    writer_rom.write_bytes(bytes((
        0x3E, 0x5A,        # LD A,5Ah
        0x32, 0x00, 0xF0,  # LD (F000h),A: shadow RAM behind ROM
        0x18, 0xFE,        # JR to itself
    )))

    writer = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(writer_rom),
            "--cycles",
            "5000",
            "--input",
            "serial0",
            "--output",
            "serial0",
            "--state",
            str(state_path),
        ),
        input=b"",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert writer.returncode == 0, writer.stderr.decode(errors="replace")
    assert state_path.exists()
    assert b"Initializing nonvolatile RAM state" in writer.stderr
    assert b"Saved nonvolatile RAM state" in writer.stderr

    reader_rom = tmp_path / "state-reader.bin"
    reader_rom.write_bytes(bytes((
        0x3E, 0x64,        # LD A,64h: 8-N-1, transmit and receive enabled
        0xED, 0x39, 0x00,  # OUT0 (CNTLA0),A
        0x3E, 0x02,        # LD A,2: BSP's initial 9600-baud divisor
        0xED, 0x39, 0x02,  # OUT0 (CNTLB0),A
        0x3A, 0x00, 0xF0,  # LD A,(F000h): restored shadow RAM
        0xED, 0x39, 0x06,  # OUT0 (TDR0),A
        0x18, 0xFE,        # JR to itself
    )))

    reader = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(reader_rom),
            "--cycles",
            "200000",
            "--input",
            "serial0",
            "--output",
            "serial0",
            "--state",
            str(state_path),
        ),
        input=b"",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert reader.returncode == 0, reader.stderr.decode(errors="replace")
    assert reader.stdout == b"\x5A"
    assert b"Loaded nonvolatile RAM state" in reader.stderr
