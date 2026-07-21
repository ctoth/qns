"""Property authorities for the real-ROM BS2 external-program verifier."""

import binascii

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from qns.input_driver import ASCII_TO_BNS_KEY
from tools.verify_bs2_external_program import (
    BSNAME_SPEECH_MARKER,
    CALSORT_SPEECH_MARKER,
    DOT5_CHORD,
    E_CHORD,
    F_KEY,
    FILE_COMMAND_PROMPT,
    FILE_INITIALIZATION_PROMPT,
    FLASH_CONFIRMATION_PROMPT,
    FLASH_INITIALIZATION_PROMPT,
    FLASH_INITIALIZATION_Y_KEY,
    FOLDER_INITIALIZATION_PROMPT,
    O_CHORD,
    POWER_ON_INITIALIZE_CHORD,
    R_KEY,
    SOH,
    STX,
    T_CHORD,
    WIPEOUT_PROMPT,
    X_CHORD,
    Y_KEY,
    _program_speech_marker,
    crc16_xmodem,
    execute_selected_stdio_program,
    expected_program_cbar,
    is_file_initialization_prompt,
    is_flash_confirmation_prompt,
    is_flash_initialization_prompt,
    is_folder_initialization_prompt,
    is_wipeout_prompt,
    reach_editor_command_loop,
    reach_stdio_editor_command_loop,
    receive_stdio_file,
    require_persisted_resources,
    transfer_stdio_ymodem,
    verify_persisted_stdio_program,
    verify_through_stdio,
    ymodem_packet,
)


def test_flash_initialization_uses_firmware_brlyes_chord():
    """The English ROM's BRLYES is lowercase y, not uppercase Y."""
    assert FLASH_INITIALIZATION_Y_KEY == ASCII_TO_BNS_KEY[ord("y")]
    assert FLASH_INITIALIZATION_Y_KEY != ASCII_TO_BNS_KEY[ord("Y")]


def test_next_external_program_uses_dot5_chord_not_bare_dot5():
    """FILEP C5 is raw dot 5 plus the BNS chord/space bit."""
    assert DOT5_CHORD == 0x50
    assert DOT5_CHORD != 0x10


def test_persisted_program_restart_uses_normal_power_on(monkeypatch, tmp_path):
    """Reload must not cold-reset and erase the flash it is meant to verify."""
    launches = []
    instances = []

    class Process:
        speech_names = []

        def __init__(self, rom, **kwargs):
            launches.append((rom, kwargs))
            self.chords = []
            instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, _error_type, _error, _traceback):
            return False

        def wait_for_keyboard(self, _state, **_kwargs):
            return {}

        def send_keyboard(self, *, chord):
            self.chords.append(chord)

        def wait_for_speech_suffix(self, _suffix, _description, **_kwargs):
            pass

        def arm_pc_watch(self, _address, **_kwargs):
            pass

        def wait_for_pc_watch(self, _address, **_kwargs):
            return {"cycle": 1, "pc": 0x1000, "cbar": 0x81}

        def request_stop(self, **_kwargs):
            pass

    monkeypatch.setattr(
        "tools.verify_bs2_external_program.BNSStdioProcess",
        Process,
    )
    rom = tmp_path / "bs2eng.bns"
    state = tmp_path / "bs2.state"
    program = tmp_path / "bsname.bns"
    program.write_bytes(b"\x18\x0cBNS\0\xef\x1a\x05\x62")

    verify_persisted_stdio_program(rom, state, program)

    process = launches[0]
    assert process == (rom, {"model": "bs2", "state": state})
    assert instances[0].chords == [O_CHORD, F_KEY, DOT5_CHORD, X_CHORD]


def test_editor_loop_accepts_exact_linked_command_loop_epoch():
    """The verifier uses the retained STARTA epoch, not the deleted heuristic."""
    class Firmware:
        _command_loop_write_count = 1

        class CPU:
            pc = 0xD657

        cpu = CPU()

    class Harness:
        bns = Firmware()

        @staticmethod
        def wait_for_key():
            pass

    reach_editor_command_loop(Harness())


def test_stdio_initialization_waits_for_prompt_after_keyboard_ready():
    """A ready event before complete prompt speech must not end first boot."""
    outbound = []
    boundaries = []

    class Process:
        speech_names = []

        @staticmethod
        def send_keyboard(*, chord):
            outbound.append(("keyboard", {"chord": chord}))

        @staticmethod
        def send_event(device, **payload):
            outbound.append((device, payload))

        def wait_for(self, predicate, description, **kwargs):
            boundaries.append((description, kwargs))
            if len(boundaries) == 1:
                events = (
                    {"device": "keyboard", "state": "accepted", "chord": POWER_ON_INITIALIZE_CHORD},
                    {"device": "cpu", "event": "watch-armed", "pc": 0xD657},
                    {"device": "keyboard", "state": "ready"},
                    {"device": "speech"},
                )
                for event in events[:-1]:
                    assert not predicate(event)
                self.speech_names.extend(FLASH_INITIALIZATION_PROMPT)
                assert predicate(events[-1])
                return events[-1]

            events = (
                {"device": "keyboard", "state": "accepted", "chord": FLASH_INITIALIZATION_Y_KEY},
                {"device": "cpu", "event": "pc-watch", "pc": 0xD657},
                {"device": "keyboard", "state": "ready"},
            )
            for event in events[:-1]:
                assert not predicate(event)
            assert predicate(events[-1])
            return events[-1]

    reach_stdio_editor_command_loop(Process())

    assert outbound == [
        ("keyboard", {"chord": POWER_ON_INITIALIZE_CHORD}),
        ("cpu", {"watch_pc": 0xD657}),
        ("keyboard", {"chord": FLASH_INITIALIZATION_Y_KEY}),
    ]
    assert boundaries == [
        ("BS2 initialization prompt or editor command loop", {"timeout": 60}),
        ("BS2 initialization prompt or editor command loop", {"timeout": 60}),
    ]


@given(program_length=st.integers(min_value=0, max_value=0xFFFF))
def test_external_program_cbar_matches_firmware_rounding(program_length: int):
    """The entry map follows BS.ASM's 16-bit length-plus-0x1fff calculation."""
    header = bytearray(10)
    header[2:6] = b"BNS\0"
    header[8:10] = program_length.to_bytes(2, "little")
    rounded_length = program_length + 0x1FFF
    expected = (
        0x11
        if rounded_length > 0xFFFF
        else ((rounded_length >> 8) & 0xF0) | 0x01
    )
    assert expected_program_cbar(bytes(header)) == expected


def test_bsname_header_requires_entry_cbar_81():
    """The supplied BSNAME length 0x6205 maps common area 1 at page 8."""
    header = b"\x18\x0cBNS\0\xef\x1a\x05\x62"
    assert expected_program_cbar(header) == 0x81


def test_supplied_programs_use_their_own_real_speech_authority(tmp_path):
    assert _program_speech_marker(tmp_path / "bsname.bns") == BSNAME_SPEECH_MARKER
    assert _program_speech_marker(tmp_path / "CALSORT.BNS") == CALSORT_SPEECH_MARKER
    assert _program_speech_marker(tmp_path / "other.bns") is None


def test_explicit_speech_marker_requires_post_exit_key_acceptance():
    chords = []
    speech_waits = []
    keyboard_waits = []

    class Process:
        @staticmethod
        def arm_pc_watch(address, **kwargs):
            assert address == 0x1000
            assert kwargs == {"timeout": 60}

        @staticmethod
        def wait_for_pc_watch(address, **kwargs):
            assert address == 0x1000
            assert kwargs == {"timeout": 60}
            return {"cycle": 123, "pc": 0x1000, "cbar": 0x21}

        @staticmethod
        def send_keyboard(*, chord):
            chords.append(chord)

        @staticmethod
        def wait_for_speech_suffix(suffix, description, **kwargs):
            speech_waits.append((suffix, description, kwargs))

        @staticmethod
        def wait_for_keyboard(state, **kwargs):
            keyboard_waits.append((state, kwargs))

    marker = ("D", "UH1", "N")
    entry = execute_selected_stdio_program(
        Process(),
        0x21,
        marker,
        require_return_key=True,
    )

    assert entry == {"cycle": 123, "pc": 0x1000, "cbar": 0x21}
    assert chords == [X_CHORD, E_CHORD]
    assert speech_waits == [(marker, "external program speech", {"timeout": 60})]
    assert keyboard_waits == [
        ("accepted", {"chord": E_CHORD, "timeout": 60}),
        ("ready", {"timeout": 60}),
    ]


def test_persisted_resource_authority_requires_each_exact_payload(tmp_path):
    from qns.memory import Memory

    state = tmp_path / "assets.state"
    first = tmp_path / "help.hlp"
    second = tmp_path / "calsort.msg"
    first.write_bytes(b"full help payload")
    second.write_bytes(b"message resource payload")
    memory = Memory(flash_size=2 * 1024 * 1024)
    memory.flash[100:117] = first.read_bytes()
    memory.ram[200:224] = second.read_bytes()
    memory.save_state(state)

    require_persisted_resources(state, (first, second))

    missing = tmp_path / "spell.dic"
    missing.write_bytes(b"dictionary payload not present")
    with pytest.raises(RuntimeError, match="spell.dic"):
        require_persisted_resources(state, (first, missing))


def test_receive_stdio_file_uses_real_file_menu_and_ymodem_sequence(
    monkeypatch,
    tmp_path,
):
    file_path = tmp_path / "calsort.msg"
    file_path.write_bytes(b"messages")
    chords = []
    sent = []
    serial_responses = []
    transfers = []
    boundaries = []

    class Process:
        serial = (bytearray(b"zero"), bytearray(b"one"))

        def wait_for(self, predicate, description, **kwargs):
            boundaries.append((description, kwargs))
            if len(boundaries) == 1:
                events = (
                    {"device": "keyboard", "state": "ready"},
                    {"device": "keyboard", "state": "accepted", "chord": T_CHORD},
                    {"device": "serial1"},
                )
                for event in events[:-1]:
                    assert not predicate(event)
                self.serial[1].extend(bytes((0x05,)))
                assert predicate(events[-1])
                return events[-1]

            self.serial[0].extend(bytes((0x05,)))
            event = {"device": "serial0"}
            assert predicate(event)
            return event

        @staticmethod
        def send_keyboard(*, chord):
            sent.append(chord)

        @staticmethod
        def send_serial(channel, data):
            serial_responses.append((channel, data))

    monkeypatch.setattr(
        "tools.verify_bs2_external_program.send_stdio_chord",
        lambda _process, chord, **kwargs: chords.append((chord, kwargs)),
    )
    monkeypatch.setattr(
        "tools.verify_bs2_external_program.transfer_stdio_ymodem",
        lambda process, cursor, path: transfers.append((process, cursor, path)),
    )
    process = Process()

    receive_stdio_file(process, file_path)

    assert sent == [T_CHORD]
    assert chords == [
        (R_KEY, {}),
        (Y_KEY, {"wait_ready": False}),
    ]
    assert serial_responses == [
        (1, bytes((0x15,))),
        (0, bytes((0x15,))),
    ]
    assert boundaries == [
        (
            "T-chord acceptance, transfer prompt ready, and ASCI1 disk-drive ENQ",
            {"timeout": 60},
        ),
        ("ASCI0 disk-drive ENQ", {"timeout": 60}),
    ]
    assert transfers == [(process, 5, file_path)]


def test_ymodem_final_ack_retains_ready_before_file_command_prompt(tmp_path):
    program = tmp_path / "hello.bns"
    program.write_bytes(b"program")
    boundaries = []

    class Process:
        serial = (bytearray(), bytearray())
        speech_names = []

        @staticmethod
        def wait_for_serial(*_args, **_kwargs):
            raise AssertionError("independent serial wait would discard ready")

        @staticmethod
        def send_serial(_channel, _data):
            pass

        def wait_for(self, predicate, description, **kwargs):
            boundaries.append((description, kwargs))
            suffixes = (
                bytes((0x43,)),
                bytes((0x06, 0x43)),
                bytes((0x06,)),
                bytes((0x06, 0x43)),
                bytes((0x06,)),
            )
            if len(boundaries) == 1:
                ready = {"device": "keyboard", "state": "ready"}
                assert not predicate(ready)
            self.serial[0].extend(suffixes[len(boundaries) - 1])
            serial = {"device": "serial0"}
            if len(boundaries) < 5:
                assert predicate(serial)
                return serial
            assert not predicate(serial)
            self.speech_names.extend(FILE_COMMAND_PROMPT)
            speech = {"device": "speech"}
            assert predicate(speech)
            return speech

    transfer_stdio_ymodem(Process(), 0, program)

    assert boundaries == [
        ("initial YMODEM CRC request", {"timeout": 60}),
        ("header ACK and data CRC request", {"timeout": 60}),
        ("data block 1 ACK", {"timeout": 60}),
        ("EOT ACK and batch CRC request", {"timeout": 60}),
        (
            "empty batch ACK, post-import file command prompt, and keyboard ready",
            {"timeout": 60},
        ),
    ]


def test_stdio_resources_precede_program_and_share_persistence_authority(
    monkeypatch,
    tmp_path,
):
    rom = tmp_path / "bs2eng.bns"
    state = tmp_path / "assets.state"
    message = tmp_path / "calsort.msg"
    help_file = tmp_path / "bs2eng.hlp"
    program = tmp_path / "calsort.bns"
    message.write_bytes(b"messages")
    help_file.write_bytes(b"help")
    program.write_bytes(b"\x18\x0cBNS\0\xef\x1a\x05\x62")
    received = []
    persisted = []

    class Process:
        speech_names = []

        def __enter__(self):
            return self

        def __exit__(self, _error_type, _error, _traceback):
            return False

        @staticmethod
        def send_keyboard(*, chord):
            assert chord == 0x4A

        @staticmethod
        def wait_for_speech_suffix(*_args, **_kwargs):
            pass

        @staticmethod
        def wait_for_keyboard(*_args, **_kwargs):
            pass

        @staticmethod
        def request_stop(**_kwargs):
            pass

    monkeypatch.setattr(
        "tools.verify_bs2_external_program.BNSStdioProcess",
        lambda *_args, **_kwargs: Process(),
    )
    monkeypatch.setattr(
        "tools.verify_bs2_external_program.reach_stdio_editor_command_loop",
        lambda _process: None,
    )
    monkeypatch.setattr(
        "tools.verify_bs2_external_program.send_stdio_chord",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "tools.verify_bs2_external_program.receive_stdio_file",
        lambda _process, path: received.append(path),
    )
    monkeypatch.setattr(
        "tools.verify_bs2_external_program.execute_selected_stdio_program",
        lambda *_args, **_kwargs: {"cycle": 1, "pc": 0x1000, "cbar": 0x81},
    )
    monkeypatch.setattr(
        "tools.verify_bs2_external_program.require_persisted_resources",
        lambda saved, paths: persisted.append((saved, paths)),
    )

    verify_through_stdio(
        rom,
        state,
        program,
        persist=True,
        resources=(message, help_file),
    )

    assert received == [message, help_file, program]
    assert persisted == [(state, (message, help_file))]


@pytest.mark.parametrize("program", [b"", b"\0" * 10, b"\0\0BNS"])
def test_external_program_cbar_rejects_missing_header(program: bytes):
    """An entry-map assertion is invalid without the firmware's BNS header."""
    with pytest.raises(ValueError, match="lacks the BNS header"):
        expected_program_cbar(program)


@given(prefix=st.lists(st.text(max_size=8), max_size=40))
def test_flash_initialization_prompt_allows_arbitrary_prior_speech(
    prefix: list[str],
):
    """Only the exact retained suffix identifies the first-boot dialogue."""
    assert is_flash_initialization_prompt(prefix + list(FLASH_INITIALIZATION_PROMPT))


def test_flash_initialization_prompt_rejects_partial_or_altered_speech():
    """A nearby boot utterance must not authorize an automatic response."""
    assert not is_flash_initialization_prompt(list(FLASH_INITIALIZATION_PROMPT[:-1]))
    altered = [*FLASH_INITIALIZATION_PROMPT[:-1], "M"]
    assert not is_flash_initialization_prompt(altered)


@given(prefix=st.lists(st.text(max_size=8), max_size=40))
def test_file_initialization_prompt_allows_arbitrary_prior_speech(
    prefix: list[str],
):
    """Only the exact retained suffix identifies the cold-reset dialogue."""
    assert is_file_initialization_prompt(prefix + list(FILE_INITIALIZATION_PROMPT))


def test_file_initialization_prompt_rejects_flash_or_altered_speech():
    """The file-system prompt must not be confused with the flash prompt."""
    assert not is_file_initialization_prompt(list(FLASH_INITIALIZATION_PROMPT))
    altered = [*FILE_INITIALIZATION_PROMPT[:-1], "M"]
    assert not is_file_initialization_prompt(altered)


@given(prefix=st.lists(st.text(max_size=8), max_size=40))
def test_folder_initialization_prompt_allows_arbitrary_prior_speech(
    prefix: list[str],
):
    """Only the exact retained suffix identifies the folder dialogue."""
    assert is_folder_initialization_prompt(prefix + list(FOLDER_INITIALIZATION_PROMPT))


def test_folder_initialization_prompt_rejects_file_or_altered_speech():
    """The folder prompt must not be confused with the file-system prompt."""
    assert not is_folder_initialization_prompt(list(FILE_INITIALIZATION_PROMPT))
    altered = [*FOLDER_INITIALIZATION_PROMPT[:-1], "M"]
    assert not is_folder_initialization_prompt(altered)


@given(prefix=st.lists(st.text(max_size=8), max_size=40))
def test_wipeout_prompt_allows_arbitrary_prior_speech(prefix: list[str]):
    """Only the exact retained suffix identifies the file-area dialogue."""
    assert is_wipeout_prompt(prefix + list(WIPEOUT_PROMPT))


def test_wipeout_prompt_rejects_folder_or_altered_speech():
    """The file-area prompt must not be confused with folder initialization."""
    assert not is_wipeout_prompt(list(FOLDER_INITIALIZATION_PROMPT))
    altered = [*WIPEOUT_PROMPT[:-1], "M"]
    assert not is_wipeout_prompt(altered)


@given(prefix=st.lists(st.text(max_size=8), max_size=40))
def test_flash_confirmation_prompt_allows_arbitrary_prior_speech(
    prefix: list[str],
):
    """The second destructive-action prompt is matched as an exact suffix."""
    assert is_flash_confirmation_prompt(prefix + list(FLASH_CONFIRMATION_PROMPT))


def test_flash_confirmation_prompt_rejects_partial_or_altered_speech():
    """The second BRLYES response requires the complete confirmation prompt."""
    assert not is_flash_confirmation_prompt(list(FLASH_CONFIRMATION_PROMPT[:-1]))
    altered = [*FLASH_CONFIRMATION_PROMPT[:-1], "M"]
    assert not is_flash_confirmation_prompt(altered)


@settings(max_examples=100, deadline=None)
@given(data=st.binary(max_size=4096))
def test_crc16_xmodem_matches_standard_library(data: bytes):
    """Verifier CRC must match an independent CRC-16/XMODEM implementation."""
    assert crc16_xmodem(data) == binascii.crc_hqx(data, 0)


@settings(max_examples=64, deadline=None)
@given(
    block_number=st.integers(min_value=0, max_value=255),
    block_size=st.sampled_from((128, 1024)),
    data=st.data(),
)
def test_ymodem_packet_has_valid_envelope_and_crc(
    block_number: int,
    block_size: int,
    data: st.DataObject,
):
    """Every generated packet must carry an exact payload and valid complement/CRC."""
    payload = data.draw(st.binary(min_size=block_size, max_size=block_size))

    packet = ymodem_packet(block_number, payload, block_size)

    assert packet[0] == (SOH if block_size == 128 else STX)
    assert packet[1] == block_number
    assert packet[2] == 0xFF - block_number
    assert packet[3:-2] == payload
    assert int.from_bytes(packet[-2:], "big") == binascii.crc_hqx(payload, 0)
    assert len(packet) == block_size + 5


@given(
    payload=st.binary(max_size=64),
    block_size=st.sampled_from((128, 1024)),
)
def test_ymodem_packet_rejects_wrong_payload_size(payload: bytes, block_size: int):
    """Packet construction must reject every non-block-sized payload."""
    with pytest.raises(ValueError, match="expected"):
        ymodem_packet(0, payload, block_size)
