"""Tests for BNS firmware-facing behavior."""

import base64
import json
import subprocess
import sys
from io import BytesIO, StringIO

import pytest
from z180 import Reg

from qns.bns import (
    BNS,
    _read_stdin_character,
)
from qns.cli import main as bns_main
from qns.input_driver import (
    ASCII_TO_BNS_KEY,
    keyboard_input_chord,
    tns_input_scan,
)
from qns.loader import InputBoundary
from qns.profiles import PROFILES
from qns.stdio import JSONLOutput

# Chord-acceptance addresses of the linked NFB99 English ROMs, as
# discovered by qns.loader.find_input_boundary and originally proven in
# NOTES.md.  Behavioral tests install these directly instead of loading
# the real packages.
INPUT_BOUNDARIES: dict[str, InputBoundary] = {
    "bsp": InputBoundary(0x4327C, 0x41A32, 0x1AF5, 0x41653, 0x0A0D, 0x414AF),
    "bs2": InputBoundary(0x4327D, 0x41A33, 0x1BD3, 0x41654, 0x0A7E, 0x414B0),
    "bsl": InputBoundary(0x433E5, 0x41A34, 0x1CF9, 0x41653, 0x0A97, 0x414AF),
    "bl2": InputBoundary(0x433E6, 0x41A35, 0x1DB4, 0x41654, 0x0AF5, 0x414B0),
    "bl4": InputBoundary(0x433F0, 0x41A3B, 0x1FC0, 0x4165A, 0x0B36, 0x414B6),
    "tns": InputBoundary(0x4329D, 0x41A38, 0x1E16, 0x41659, 0x0AF9, 0x414B5),
}


def _build_update_package(image_offset, firmware):
    package = bytearray(image_offset)
    package[2:5] = b"BNS"
    package[image_offset - 6:image_offset - 2] = len(firmware).to_bytes(
        4,
        "little",
    )

    crc = 0
    for byte in firmware:
        high_bit = crc & 0x8000
        crc = (crc << 1) & 0xFFFF
        crc = (crc & 0xFF00) | ((crc + byte) & 0xFF)
        if high_bit:
            crc ^= 0xA097
    package[image_offset - 2:image_offset] = crc.to_bytes(2, "little")
    return bytes(package) + firmware


@pytest.mark.parametrize("image_offset", [0x3000, 0x7000, 0x8000])
def test_load_rom_discovers_aligned_update_image_from_length_and_crc(
    tmp_path,
    image_offset,
):
    firmware = bytes(range(251)) * 1000
    package_path = tmp_path / "firmware.bns"
    package_path.write_bytes(_build_update_package(image_offset, firmware))
    bns = BNS()

    bns.load_rom(package_path)

    assert bytes(bns.memory.rom[:len(firmware)]) == firmware
    assert bytes(bns.memory.ram[:len(firmware)]) == firmware
    assert len(bns.memory.rom) == 256 * 1024


def test_load_rom_rejects_update_package_without_valid_image_crc(tmp_path):
    firmware = bytes(range(64))
    package = bytearray(_build_update_package(0x7000, firmware))
    package[-1] ^= 0xFF
    package_path = tmp_path / "corrupt.bns"
    package_path.write_bytes(package)
    bns = BNS()

    with pytest.raises(ValueError, match="found 0"):
        bns.load_rom(package_path)


def test_english_stdio_characters_use_firmware_keyboard_chords():
    """Terminal characters map to physical English keyboard chords."""
    assert ASCII_TO_BNS_KEY[ord("a")] == 0x01
    assert ASCII_TO_BNS_KEY[ord("z")] == 0x35
    assert ASCII_TO_BNS_KEY[ord("A")] == 0x41
    assert ASCII_TO_BNS_KEY[ord("0")] == 0x34
    assert ASCII_TO_BNS_KEY[ord(" ")] == 0x40
    assert ASCII_TO_BNS_KEY[ord("\n")] == 0x8D
    assert ASCII_TO_BNS_KEY[ord("\r")] == 0x8D
    assert ASCII_TO_BNS_KEY[0x7F] == 0x78
    assert keyboard_input_chord("\n") == 0x68
    assert keyboard_input_chord("\r") == 0x68


def test_tns_stdio_uses_source_defined_qwerty_pic_codes():
    assert keyboard_input_chord("a", "tns") == 0x94
    assert keyboard_input_chord(" ", "tns") == 0xA9
    assert keyboard_input_chord("\n", "tns") == 0xDB
    assert keyboard_input_chord("\x1b", "tns") == 0x89


@pytest.mark.parametrize(
    ("character", "scan", "shifted"),
    (
        ("a", 0x94, False),
        ("A", 0x94, True),
        ("1", 0x8B, False),
        ("!", 0x8B, True),
        ("0", 0xCF, False),
        (")", 0xCF, True),
        ("-", 0xD7, False),
        ("_", 0xD7, True),
        ("=", 0xDF, False),
        ("+", 0xDF, True),
        ("[", 0xD0, False),
        ("{", 0xD0, True),
        ("]", 0xD8, False),
        ("}", 0xD8, True),
        (";", 0xDC, False),
        (":", 0xDC, True),
        ("'", 0xD3, False),
        ('"', 0xD3, True),
        (",", 0xCB, False),
        ("<", 0xCB, True),
        (".", 0xC2, False),
        (">", 0xC2, True),
        ("/", 0xCA, False),
        ("?", 0xCA, True),
        ("\\", 0xE0, False),
        ("|", 0xE0, True),
        ("`", 0xB9, False),
        ("~", 0xB9, True),
        ("\t", 0x91, False),
        ("\b", 0xED, False),
        ("\x1b", 0x89, False),
        ("\n", 0xDB, False),
        (" ", 0xA9, False),
    ),
)
def test_tns_stdio_selects_source_defined_scan_and_shift(
    character,
    scan,
    shifted,
):
    assert tns_input_scan(character) == (scan, shifted)


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


@pytest.mark.parametrize("model", ["bsp", "bs2", "bsl", "bl2", "bl4", "tns"])
def test_command_loop_gate_requires_linked_starta_instruction(model):
    """Early timer initialization cannot open stdin before linked STARTA."""
    bns = BNS(model=model)
    bns._input_boundary = INPUT_BOUNDARIES[model]

    bns._observe_write(
        INPUT_BOUNDARIES[model].command_loop_timer,
        0,
        pc=0x1234,
        cycle=0,
    )
    assert bns._command_loop_write_count == 0

    bns._observe_write(
        INPUT_BOUNDARIES[model].command_loop_timer,
        0,
        pc=INPUT_BOUNDARIES[model].command_loop_timer_pc,
        cycle=0,
    )
    assert bns._command_loop_write_count == 1


@pytest.mark.parametrize(
    ("model", "reset", "chord"),
    [
        (model, reset, chord)
        for model in ("bsp", "bs2", "bsl", "bl2", "bl4")
        for reset, chord in (("warm", 0x7F), ("cold", 0x4A))
    ],
)
def test_classic_reset_holds_source_defined_chord_until_warm0_completes(
    model,
    reset,
    chord,
):
    bns = BNS(model=model, reset=reset)
    bns._input_boundary = INPUT_BOUNDARIES[model]
    observed = []

    def execute_budget(cycles):
        observed.append((bns.keyboard.dots, bns.keyboard._key_down))
        bns._observe_write(
            INPUT_BOUNDARIES[model].reset_complete,
            0x64,
            pc=0,
            cycle=0,
        )
        return cycles

    bns._execute_budget = execute_budget
    bns.run(max_cycles=1_000)

    assert observed == [(chord, True)]
    assert not bns.keyboard._key_down


@pytest.mark.parametrize(
    ("reset", "make_scans", "release_scans"),
    (
        ("warm", (0xA1, 0x81), (0x01, 0x21)),
        ("cold", (0xC9, 0xA1, 0x81), (0x01, 0x21, 0x49)),
    ),
)
def test_tns_reset_delivers_source_defined_modifier_sequence(
    reset,
    make_scans,
    release_scans,
):
    bns = BNS(model="tns", reset=reset)
    bns._input_boundary = INPUT_BOUNDARIES["tns"]
    observed = []
    reset_completed = False
    status_checked = False

    def execute_budget(cycles):
        nonlocal reset_completed, status_checked
        if not status_checked:
            bns._read_tns_status(0xE0)
            status_checked = True
        if bns.keyboard.latched:
            observed.append(bns.keyboard.read(bns.keyboard.port))
        if not reset_completed and tuple(observed) == make_scans:
            bns._observe_write(
                INPUT_BOUNDARIES["tns"].reset_complete,
                0x64,
                pc=0,
                cycle=0,
            )
            reset_completed = True
        return cycles

    bns._execute_budget = execute_budget
    bns.run(max_cycles=10_000)

    assert tuple(observed) == make_scans + release_scans


def test_reset_discards_host_bytes_pending_at_native_serial_boundaries():
    bns = BNS(model="bsl", core="direct")
    bns._pending_asci_rx = [0x41, 0x42]
    bns._pending_csio_rx = 0x43

    bns.reset()

    assert bns._pending_asci_rx == [None, None]
    assert bns._pending_csio_rx is None


@pytest.mark.parametrize(
    ("model", "capture_site", "spbuf", "shape"),
    (
        ("bsp", 0xBC9B, 0xD657, "bsp"),
        ("bs2", 0xBC9A, 0xD658, "bsp"),
        ("bsl", 0xAD86, 0xD657, "nfb99-braille-lite"),
        ("bl2", 0xBC4D, 0xD658, "nfb99-braille-lite"),
        ("bl4", 0xAD81, 0xD65E, "2003-braille-lite"),
        ("tns", 0xAD71, 0xD65D, "bsp"),
    ),
)
def test_english_speech_observes_each_linked_pretranslation_buffer(
    tmp_path,
    model,
    capture_site,
    spbuf,
    shape,
):
    """English output is exact firmware text, not inverse-phoneme guessing.

    The capture site is discovered from the loaded image's MFULL3
    signature, so each case loads a synthetic ROM carrying that
    signature at the linked address.
    """
    from test_loader import make_mfull3_image

    rom_path = tmp_path / "signature.rom"
    rom_path.write_bytes(make_mfull3_image(capture_site, spbuf, shape))

    spoken = []
    bns = BNS(model=model, core="direct", english_callback=spoken.append)
    bns.load_rom(rom_path)
    message = b"enter file command"
    physical_spbuf = (0x34 << 12) + spbuf
    for offset, value in enumerate(message):
        bns.memory.write(physical_spbuf + offset, value)
    bns.memory.ram[:10] = bytes((
        0x3E, 0x34,
        0xED, 0x39, 0x38,
        0x3E, 0xC6,
        0xED, 0x39, 0x3A,
    ))
    for _ in range(4):
        bns.step()
    bns.cpu.set_reg(Reg.HL, spbuf)
    bns.cpu.set_reg(Reg.BC, 4)
    bns.cpu.set_reg(Reg.PC, capture_site)

    bns._observe_instruction_boundary()
    bns.cpu.set_reg(Reg.PC, capture_site + 1)
    bns._observe_instruction_boundary()

    assert spoken == ["enter file command"]


def test_english_speech_ignores_unrelated_instruction_fetches():
    spoken = []
    bns = BNS(model="bsp", core="direct", english_callback=spoken.append)
    bns.cpu.set_reg(Reg.PC, 0x1234)
    bns._observe_instruction_boundary()

    assert spoken == []


def test_tns_owns_source_defined_hardware_ports():
    """TNS must not inherit the incompatible BSPLUS or BL4 port map."""
    bns = BNS(model="tns")

    assert bns.ssi263.base_port == 0x90
    assert bns.keyboard.port == 0xD0
    assert bns.clock_pic is not None
    assert bns.display is None
    assert bns.io.read(0xE0) == 0xFF

    bns.keyboard.press(0xA1)
    assert bns.io.read(0xE0) == 0xFE
    assert bns.io.read(0xD0) == 0xA1
    assert bns.io.read(0xE0) == 0xFF

    bns.io.write(0x80, 1)
    bns.io.write(0xB0, 0x5A)
    bns.io.write(0xC0, 0xA5)
    bns.io.write(0xE0, 0x69)

    assert bns.speech_power_enabled
    assert bns.power_latch == 0x5A
    assert bns.parallel_ports[0] == 0xA5
    assert bns.high_bank_latch == 0x69


@pytest.mark.parametrize("model", ["bsp", "bs2", "bsl", "bl2", "bl4"])
def test_keyboard_stdin_waits_for_firmware_key_phases(monkeypatch, model):
    """An unconsumed queued key is retried before the next host key starts."""
    characters = iter(("y", "b", ""))
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
    bns = BNS(model=model, stdin_device="keyboard")
    bns._input_boundary = INPUT_BOUNDARIES[model]
    observed = []
    calls = 0

    def observe_write(address, value):
        bns.memory.write(address, value)
        bns._observe_write(address, value, pc=0, cycle=calls * 1_000)

    def execute_budget(cycles):
        nonlocal calls
        calls += 1
        observed.append((bns.keyboard.dots, bns.keyboard._key_down, bns.keyboard.latched))
        if calls == 2:
            bns._observe_input_boundary(INPUT_BOUNDARIES[model].keyboard_wait_pc)
        elif calls == 3:
            observe_write(INPUT_BOUNDARIES[model].keyboard_input_buffer, 0x3D)
            observe_write(INPUT_BOUNDARIES[model].keyboard_queue_count, 1)
            bns.keyboard.keyclr_write(bns.keyboard.keyclr_port, 0)
        elif calls == 4:
            bns.memory.write(INPUT_BOUNDARIES[model].keyboard_input_buffer, 0)
            bns.keyboard.keyclr_write(bns.keyboard.keyclr_port, 0)
        elif calls == 5:
            observe_write(INPUT_BOUNDARIES[model].keyboard_queue_count, 0)
        elif calls == 6:
            observe_write(INPUT_BOUNDARIES[model].keyboard_input_buffer, 0x3D)
            observe_write(INPUT_BOUNDARIES[model].keyboard_queue_count, 1)
            bns.keyboard.keyclr_write(bns.keyboard.keyclr_port, 0)
        elif calls == 7:
            bns.memory.write(INPUT_BOUNDARIES[model].keyboard_input_buffer, 0)
            bns.keyboard.keyclr_write(bns.keyboard.keyclr_port, 0)
        elif calls == 8:
            bns._observe_input_boundary(INPUT_BOUNDARIES[model].keyboard_wait_pc)
            observe_write(INPUT_BOUNDARIES[model].keyboard_queue_count, 0)
        elif calls == 9:
            observe_write(INPUT_BOUNDARIES[model].keyboard_input_buffer, 0x03)
            observe_write(INPUT_BOUNDARIES[model].keyboard_queue_count, 1)
            bns.keyboard.keyclr_write(bns.keyboard.keyclr_port, 0)
        elif calls == 10:
            bns.memory.write(INPUT_BOUNDARIES[model].keyboard_input_buffer, 0)
            bns.keyboard.keyclr_write(bns.keyboard.keyclr_port, 0)
        elif calls == 11:
            bns._observe_input_boundary(INPUT_BOUNDARIES[model].keyboard_wait_pc)
            observe_write(INPUT_BOUNDARIES[model].keyboard_queue_count, 0)
        return cycles

    bns._execute_budget = execute_budget
    bns.run(max_cycles=11_000)

    assert observed == [
        (0, False, False),
        (0, False, False),
        (0x3D, True, True),
        (0x3D, False, True),
        (0, False, False),
        (0x3D, True, True),
        (0x3D, False, True),
        (0, False, False),
        (0x03, True, True),
        (0x03, False, True),
        (0, False, False),
    ]
    assert bns.memory.read(INPUT_BOUNDARIES[model].keyboard_input_buffer) == 0
    assert not bns.keyboard.latched


def test_jsonl_stdin_routes_keyboard_and_both_serial_channels(monkeypatch):
    events = "\n".join(
        (
            json.dumps({"device": "keyboard", "text": "a"}),
            json.dumps({"device": "serial0", "data": "AA=="}),
            json.dumps({"device": "serial1", "data": "/w=="}),
            "",
        )
    )
    monkeypatch.setattr(sys, "stdin", StringIO(events))
    output_stream = StringIO()

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("qns.bns.threading.Thread", ImmediateThread)
    bns = BNS(
        model="bsp",
        stdin_device="jsonl",
        stdio_output=JSONLOutput(output_stream),
    )
    bns._input_boundary = INPUT_BOUNDARIES["bsp"]
    observed = []
    calls = 0

    def observe_write(address, value):
        bns.memory.write(address, value)
        bns._observe_write(address, value, pc=0, cycle=calls * 1_000)

    def execute_budget(cycles):
        nonlocal calls
        calls += 1
        observed.append((bns.keyboard.dots, bns._serial_receive(0), bns._serial_receive(1)))
        if calls == 2:
            bns._observe_input_boundary(INPUT_BOUNDARIES["bsp"].keyboard_wait_pc)
        elif calls == 3:
            observe_write(INPUT_BOUNDARIES["bsp"].keyboard_input_buffer, 0x01)
            observe_write(INPUT_BOUNDARIES["bsp"].keyboard_queue_count, 1)
            bns.keyboard.keyclr_write(bns.keyboard.keyclr_port, 0)
        elif calls == 4:
            bns.memory.write(INPUT_BOUNDARIES["bsp"].keyboard_input_buffer, 0)
            bns.keyboard.keyclr_write(bns.keyboard.keyclr_port, 0)
            bns._observe_input_boundary(INPUT_BOUNDARIES["bsp"].keyboard_wait_pc)
            observe_write(INPUT_BOUNDARIES["bsp"].keyboard_queue_count, 0)
        return cycles

    bns._execute_budget = execute_budget
    bns.run(max_cycles=5_000)

    assert observed[0] == (0, 0x00, 0xFF)
    assert observed[2][0] == 0x01
    keyboard_events = [
        event
        for line in output_stream.getvalue().splitlines()
        if (event := json.loads(line))["device"] == "keyboard"
    ]
    assert keyboard_events == [
        {"device": "keyboard", "state": "accepted", "chord": 0x01},
        {"device": "keyboard", "state": "ready"},
    ]


def test_bsl_keyboard_stdin_uses_exact_command_loop_epoch(monkeypatch):
    """Timer-woken top-level BSL input starts at linked STARTA."""
    characters = iter(("a", ""))
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
    bns = BNS(model="bsl", stdin_device="keyboard")
    bns._input_boundary = INPUT_BOUNDARIES["bsl"]
    observed = []
    calls = 0

    def observe_write(address, value, pc=0):
        bns.memory.write(address, value)
        bns._observe_write(address, value, pc=pc, cycle=calls * 1_000)

    def execute_budget(cycles):
        nonlocal calls
        calls += 1
        observed.append((bns.keyboard.dots, bns.keyboard._key_down, bns.keyboard.latched))
        if calls == 1:
            observe_write(
                INPUT_BOUNDARIES["bsl"].command_loop_timer,
                0,
                INPUT_BOUNDARIES["bsl"].command_loop_timer_pc,
            )
        elif calls == 2:
            observe_write(INPUT_BOUNDARIES["bsl"].keyboard_input_buffer, 0x01)
            observe_write(INPUT_BOUNDARIES["bsl"].keyboard_queue_count, 1)
            bns.keyboard.keyclr_write(bns.keyboard.keyclr_port, 0)
        elif calls == 3:
            bns.memory.write(INPUT_BOUNDARIES["bsl"].keyboard_input_buffer, 0)
            bns.keyboard.keyclr_write(bns.keyboard.keyclr_port, 0)
        elif calls == 4:
            bns._observe_input_boundary(INPUT_BOUNDARIES["bsl"].keyboard_wait_pc)
            observe_write(INPUT_BOUNDARIES["bsl"].keyboard_queue_count, 0)
        return cycles

    bns._execute_budget = execute_budget
    bns.run(max_cycles=4_000)

    assert observed == [
        (0, False, False),
        (0x01, True, True),
        (0x01, False, True),
        (0, False, False),
    ]
    assert not bns.keyboard.latched


@pytest.mark.parametrize(
    ("character", "expected", "accepted"),
    (
        ("A", [0xE1, 0x94, 0x14, 0x61], 0x94),
        ("~", [0xE1, 0xA1, 0xB9, 0x39, 0x21, 0x61], 0xB9),
    ),
)
def test_tns_modified_stdin_preserves_physical_modifier_sequence(
    monkeypatch,
    character,
    expected,
    accepted,
):
    monkeypatch.setattr(
        sys,
        "stdin",
        StringIO(json.dumps({"device": "keyboard", "text": character}) + "\n"),
    )

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("qns.bns.threading.Thread", ImmediateThread)
    output_stream = StringIO()
    bns = BNS(
        model="tns",
        stdin_device="jsonl",
        stdio_output=JSONLOutput(output_stream),
    )
    bns._input_boundary = INPUT_BOUNDARIES["tns"]
    observed = []
    calls = 0
    queued = False
    consumed = False

    def execute_budget(cycles):
        nonlocal calls, queued, consumed
        calls += 1
        code = None
        if bns.keyboard.latched:
            code = bns.keyboard.read(0xD0)
            observed.append(code)
        if calls == 1:
            bns._observe_input_boundary(INPUT_BOUNDARIES["tns"].keyboard_wait_pc)
        elif code == accepted and not queued:
            bns.memory.write(INPUT_BOUNDARIES["tns"].keyboard_queue_count, 1)
            bns._observe_write(
                INPUT_BOUNDARIES["tns"].keyboard_queue_count,
                1,
                pc=0,
                cycle=calls * 1_000,
            )
            queued = True
        elif queued and not consumed:
            bns._observe_input_boundary(INPUT_BOUNDARIES["tns"].keyboard_wait_pc)
            bns.memory.write(INPUT_BOUNDARIES["tns"].keyboard_queue_count, 0)
            bns._observe_write(
                INPUT_BOUNDARIES["tns"].keyboard_queue_count,
                0,
                pc=0,
                cycle=calls * 1_000,
            )
            consumed = True
        return cycles

    bns._execute_budget = execute_budget
    bns.run(max_cycles=8_000)

    assert observed == expected
    keyboard_events = [
        event
        for line in output_stream.getvalue().splitlines()
        if (event := json.loads(line))["device"] == "keyboard"
    ]
    assert keyboard_events == [
        {"device": "keyboard", "state": "accepted", "chord": accepted},
        {"device": "keyboard", "state": "ready"},
    ]


def test_address_trace_retains_causal_write_event_once():
    """Overlapping trace selectors must retain one exact instruction event."""
    bns = BNS(
        core="direct",
        trace_writes=0xF000,
        trace_writes_range=(0xF000, 0xF000),
    )
    bns.memory.load_rom(bytes((
        0x3E, 0x5A,        # LD A,5Ah (6 cycles)
        0x32, 0x00, 0xF0,  # LD (F000h),A
        0x18, 0xFE,        # JR $
    )))

    bns._execute_budget(100)

    # z-core resets DCNTL to F0h, so external-memory fetch waits move the
    # second instruction's callback entry from the incumbent's cycle 6 to 12.
    assert bns.traced_writes == [(12, 0x0002, 0xF000, 0x5A)]


def test_bsplus_port_80_is_watchdog_read_and_speech_power_write():
    """The speech-only BSP model must not expose a display at port 0x80."""
    bns = BNS()

    assert bns.display is None
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

    def write_line(high: bool, cycle: int) -> None:
        bns._callback_cycle = cycle
        bns._io_write(0xA0, 0x20 if high else 0)

    write_line(False, 0)
    write_line(True, 18_020)
    cycle = 24_012
    for bit in range(8):
        write_line(False, cycle)
        low_cycles = 324 if 0x03 & (1 << bit) else 12_820
        write_line(True, cycle + low_cycles)
        cycle += 20_290

    bns._callback_cycle = 184_900
    assert bns._io_read(0x81) == 0xF7

    bns._callback_cycle = 194_400
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

    bns._csio_device.transmit(4)
    assert bns._csio_device.receive() == -1

    bns._io_write(0x83, 0x09)

    assert bns.parallel_ports[2] & 0x10
    assert bns._csio_device.receive() != -1


def test_bsl_wires_braille_display_to_csio():
    """The B_LITE profile must answer the firmware's attached-display poll."""
    bns = BNS(model="bsl")

    bns._csio_device.transmit(0x81)

    assert bns._csio_device.receive() == 0x0A
    assert bns._csio_device.receive() == -1

    bns._io_write(0x83, 0x08)
    assert not bns.parallel_ports[2] & 0x10


def test_bl2_combines_bsnew_devices_with_parallel_display():
    """BL2 uses BSNEW storage/clock ports and clocks its display through C0-C2."""
    bns = BNS(model="bl2")
    display_controls = []
    bns.display.write_control = display_controls.append

    assert len(bns.memory.flash) == 2 * 1024 * 1024
    assert bns.clock_pic is not None
    assert bns.gas_gauge is not None

    bns._io_write(0x83, 3)
    assert display_controls == [3]

    bns._csio_device.transmit(4)
    bns._io_write(0x83, 9)
    assert bns._csio_device.receive() != -1


def test_bl4_owns_split_keyboard_parallel_display_and_four_megabyte_flash():
    """BL4 uses its source-defined ports without borrowing BL2 addresses."""
    bns = BNS(model="bl4")
    display_controls = []
    bns.display.write_control = display_controls.append

    assert len(bns.memory.flash) == 4 * 1024 * 1024
    assert bns.ssi263.base_port == 0x90
    assert bns.keyboard.port == 0xB0
    assert bns.keyboard.keyclr_port == 0xD0

    bns.keyboard.press(0x41)
    assert bns._io_read(0xB0) == 0x01
    assert bns._io_read(0xC0) == 0x01
    bns._io_write(0xD0, 0)
    assert not bns.keyboard.latched

    bns._io_write(0xA3, 3)
    assert display_controls == [3]
    bns._csio_device.transmit(4)
    bns._io_write(0xA3, 9)
    assert bns._csio_device.receive() != -1

    bns._io_write(0x80, 0x93)
    assert bns.rs232_power_enabled
    assert bns.speech_power_enabled
    assert bns.disk_power_enabled
    assert bns.charge_output_high
    assert bns._io_read(0xE0) == 0xFF

    bns._io_write(0xE0, 2)
    bns._io_write(0xF0, 0x0F)
    assert bns.bl4_latch == 2
    assert bns.memory.high_bank_latch == 0x0F


def test_bns_rejects_unknown_hardware_model():
    with pytest.raises(ValueError, match="Unsupported BNS model: unknown"):
        BNS(model="unknown")


def test_bns_rejects_unknown_z_core_path():
    with pytest.raises(ValueError, match="Unsupported z-core path: unknown"):
        BNS(core="unknown")


@pytest.mark.parametrize(
    ("model", "flash_size"),
    (
        ("bsp", 0),
        ("bs2", 2 * 1024 * 1024),
        ("bsl", 0),
        ("bl2", 2 * 1024 * 1024),
        ("bl4", 4 * 1024 * 1024),
        ("tns", 0),
    ),
)
def test_direct_machine_uses_each_profile_region_contract(model, flash_size):
    """Each direct machine owns low RAM and maps only real flash apertures."""
    bns = BNS(model=model, core="direct")

    assert isinstance(bns.memory.ram, memoryview)
    assert len(bns.memory.ram) == PROFILES[model].ram_size
    assert len(bns.memory.rom) == PROFILES[model].rom_size
    assert len(bns.memory.flash) == flash_size

    bns.memory.load_rom(bytes((
        0x3E, 0x80,        # LD A,80h
        0xED, 0x39, 0x38,  # OUT0 (CBR),A
        0x3A, 0x00, 0xF0,  # LD A,(F000h)
    )))
    if flash_size:
        bns.memory.set_high_bank_latch(0x08)
        bns.memory.flash[0xF000] = 0x5A

    for _ in range(3):
        bns.step()

    assert bns.cpu.mmu_translate(0xF000) == 0x8F000
    assert bns.cpu.reg(Reg.AF) >> 8 == (0x5A if flash_size else 0xFF)


def test_direct_external_write_callback_does_not_reenter_machine():
    """A flash bus callback uses captured BNS state, not borrowed Machine APIs."""
    bns = BNS(model="bs2", core="direct")
    bns.memory.load_rom(bytes((
        0x3E, 0x80,        # LD A,80h
        0xED, 0x39, 0x38,  # OUT0 (CBR),A
        0x3E, 0x5A,        # LD A,5Ah
        0x32, 0x00, 0xF0,  # LD (F000h),A through the External region
    )))

    for _ in range(4):
        bns.step()

    assert bns.stats["writes"] == 1


def test_direct_event_overflow_is_a_fatal_observer_error():
    """Lost native write events must never be cleared and ignored."""
    bns = BNS(core="direct")
    bns.memory.load_rom(bytes((
        0x3E, 0x5A,        # LD A,5Ah
        0x32, 0x00, 0xF0,  # LD (F000h),A
        0x18, 0xFB,        # JR back to the write
    )))

    bns.cpu.run(300_000)

    with pytest.raises(RuntimeError, match="z-core memory events were lost"):
        bns._process_memory_events()


def test_run_keeps_advancing_native_time_while_cpu_is_halted():
    """HALT waits for hardware interrupts; it does not terminate emulation."""
    bns = BNS(core="direct")
    bns.memory.load_rom(b"\x76")

    bns.run(max_cycles=2000)

    assert bns.cpu.halted()
    assert bns.stats["cycles"] >= 2000


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


def test_native_asci_queue_round_trip_uses_bns_execution_owner():
    output = BytesIO()
    bns = BNS(
        core="direct",
        stdin_device="serial0",
        serial_output=output,
        serial_output_channel=0,
    )
    bns.memory.load_rom(bytes((
        0x3E, 0x64,
        0xED, 0x39, 0x00,
        0x3E, 0x02,
        0xED, 0x39, 0x02,
        0xED, 0x38, 0x04,
        0xE6, 0x80,
        0x28, 0xF9,
        0xED, 0x38, 0x08,
        0xED, 0x39, 0x06,
        0x18, 0xF1,
    )))
    bns._serial_input_queue.put(0x5A)

    rdrf_seen = False
    while bns.cpu.cycle_count() < 200_000:
        bns._execute_budget(1_000)
        rdrf_seen |= bool(bns.cpu.io_reg_peek(0x04) & 0x80)

    diagnostics = {
        "pc": bns.cpu.reg(Reg.PC),
        "cntla0": bns.cpu.io_reg_peek(0x00),
        "cntlb0": bns.cpu.io_reg_peek(0x02),
        "stat0": bns.cpu.io_reg_peek(0x04),
        "tdr0": bns.cpu.io_reg_peek(0x06),
        "rdr0": bns.cpu.io_reg_peek(0x08),
        "icr": bns.cpu.io_reg_peek(0x3F),
        "pending": bns._pending_asci_rx,
        "rdrf_seen": rdrf_seen,
    }
    assert output.getvalue() == b"Z", repr(diagnostics)


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
        0x18, 0xF1,        # JR back to the status read
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
    assert result.stdout == b"Z", result.stderr.decode(errors="replace")
    assert b"Input: STDIN (serial0)" in result.stderr


def test_cli_jsonl_round_trip_keeps_binary_serial_separate_from_diagnostics(tmp_path):
    echo_rom = tmp_path / "serial-echo.bin"
    echo_rom.write_bytes(bytes((
        0x3E, 0x64,
        0xED, 0x39, 0x00,
        0x3E, 0x02,
        0xED, 0x39, 0x02,
        0xED, 0x38, 0x04,
        0xE6, 0x80,
        0x28, 0xF9,
        0xED, 0x38, 0x08,
        0xED, 0x39, 0x06,
        0x18, 0xF1,
    )))
    input_event = json.dumps(
        {
            "device": "serial0",
            "data": base64.b64encode(b"Z").decode("ascii"),
        }
    ).encode()

    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(echo_rom),
            "--cycles",
            "200000",
            "--stdio",
            "jsonl",
        ),
        input=input_event + b"\n",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert [json.loads(line) for line in result.stdout.splitlines()] == [
        {"device": "serial0", "data": "Wg=="},
        {"device": "system", "state": "exited"},
    ]
    assert b"Input: STDIN (jsonl)" in result.stderr


def test_cli_jsonl_reports_existing_native_pc_watch(tmp_path):
    watch_rom = tmp_path / "watch.bin"
    watch_rom.write_bytes(
        bytes((0xC3, 0x10, 0x00))
        + bytes(13)
        + bytes((0x18, 0xFE))
    )

    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(watch_rom),
            "--cycles",
            "5000",
            "--stdio",
            "jsonl",
            "--watch-pc",
            "0x10",
        ),
        input=b"",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(events) == 2
    event = events[0]
    assert event["device"] == "cpu"
    assert event["event"] == "pc-watch"
    assert event["pc"] == 0x10
    assert event["cycle"] > 0
    assert event["cbar"] == 0xF0
    assert events[1] == {"device": "system", "state": "exited"}


def test_cli_jsonl_arms_native_pc_watch_during_execution(tmp_path):
    watch_rom = tmp_path / "dynamic-watch.bin"
    watch_rom.write_bytes(
        bytes((0xC3, 0x10, 0x00))
        + bytes(13)
        + bytes((0x18, 0xFE))
    )
    watch_event = json.dumps({"device": "cpu", "watch_pc": 0x10}).encode()

    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(watch_rom),
            "--cycles",
            "500000",
            "--stdio",
            "jsonl",
        ),
        input=watch_event + b"\n",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[0] == {
        "device": "cpu",
        "event": "watch-armed",
        "pc": 0x10,
    }
    assert events[1]["device"] == "cpu"
    assert events[1]["event"] == "pc-watch"
    assert events[1]["pc"] == 0x10
    assert events[1]["cycle"] > 0


def test_cli_prints_retained_bl2_display_to_standard_output(tmp_path):
    """The built-in display is observable without a hardware adapter."""
    idle_rom = tmp_path / "idle.rom"
    idle_rom.write_bytes(bytes((0x18, 0xFE)))

    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(idle_rom),
            "--model",
            "bl2",
            "--cycles",
            "1000",
            "--display",
            "codes",
        ),
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert "Display codes: " + " ".join(["00"] * 18) in result.stdout.decode()


def test_cli_jsonl_emits_complete_speech_and_display_events(
    monkeypatch,
    tmp_path,
    capsys,
):
    idle_rom = tmp_path / "idle.rom"
    idle_rom.write_bytes(bytes((0x18, 0xFE)))
    frame = bytes(range(18))

    def emit_devices(bns: BNS, max_cycles: int = 0) -> None:
        bns._english_callback("help is open")
        bns.ssi263.write(bns.ssi263.base_port + bns.ssi263.REG_CTRLAMP, 0x0F)
        bns.display._frame_callback(frame)

    monkeypatch.setattr(BNS, "run", emit_devices)
    monkeypatch.setattr(
        sys,
        "argv",
        ["qns.bns", str(idle_rom), "--model", "bl2", "--stdio", "jsonl"],
    )

    bns_main()

    captured = capsys.readouterr()
    assert [json.loads(line) for line in captured.out.splitlines()] == [
        {"device": "speech", "text": "help is open"},
        {
            "device": "speech",
            "code": 0,
            "name": "PA",
            "ipa": "",
            "example": "pause",
        },
        {"device": "display", "cells": list(frame)},
        {"device": "system", "state": "exited"},
    ]
    assert "Loaded ROM" in captured.err


def test_cli_state_round_trip_preserves_v3_effective_ram(tmp_path):
    """A later process running the same ROM must see the saved effective RAM."""
    state_path = tmp_path / "bsp.state"
    state_rom = tmp_path / "state-round-trip.bin"
    state_rom.write_bytes(bytes((
        0x3E, 0x64,
        0xED, 0x39, 0x00,
        0x3E, 0x02,
        0xED, 0x39, 0x02,
        0x3A, 0x00, 0xF0,
        0xB7,
        0x20, 0x07,
        0x3E, 0x41,
        0x32, 0x00, 0xF0,
        0x18, 0x02,
        0x3E, 0x5A,
        0xED, 0x39, 0x06,
        0x18, 0xFE,
    )))

    writer = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(state_rom),
            "--core",
            "direct",
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

    assert writer.returncode == 0, writer.stderr.decode(errors="replace")
    assert state_path.exists()
    assert b"Initializing nonvolatile RAM state" in writer.stderr
    assert b"Saved nonvolatile RAM state" in writer.stderr
    assert writer.stdout == b"A"

    reader = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(state_rom),
            "--core",
            "direct",
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


def test_cli_state_dir_creates_directory_state(tmp_path):
    state_dir = tmp_path / "bs2-state"
    idle_rom = tmp_path / "idle.bin"
    idle_rom.write_bytes(bytes((0x18, 0xFE)))

    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(idle_rom),
            "--model",
            "bs2",
            "--core",
            "direct",
            "--cycles",
            "5000",
            "--input",
            "serial0",
            "--output",
            "serial0",
            "--state-dir",
            str(state_dir),
        ),
        input=b"",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert state_dir.is_dir()
    assert {path.name for path in state_dir.iterdir()} == {
        "flash.bin",
        "ram.bin",
    }
    assert (state_dir / "flash.bin").stat().st_size == 2 * 1024 * 1024
    assert b"Initializing nonvolatile state directory" in result.stderr
    assert b"Saved nonvolatile state directory" in result.stderr

    reloaded = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(idle_rom),
            "--model",
            "bs2",
            "--core",
            "direct",
            "--cycles",
            "5000",
            "--input",
            "serial0",
            "--output",
            "serial0",
            "--state-dir",
            str(state_dir),
        ),
        input=b"",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert reloaded.returncode == 0, reloaded.stderr.decode(errors="replace")
    assert b"Loaded nonvolatile state directory" in reloaded.stderr
