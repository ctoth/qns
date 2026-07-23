"""Property authorities for the real-ROM BS2 external-program verifier."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from z180 import Reg

from tools.bs2_stdio_harness import (
    FILE_INITIALIZATION_PROMPT,
    FLASH_CONFIRMATION_PROMPT,
    FLASH_INITIALIZATION_PROMPT,
    FOLDER_INITIALIZATION_PROMPT,
    WIPEOUT_PROMPT,
)
from tools.verify_bs2_external_program import (
    BSNAME_SPEECH_MARKER,
    CALSORT_SPEECH_MARKER,
    DOT5_CHORD,
    F_KEY,
    O_CHORD,
    X_CHORD,
    _program_speech_marker,
    expected_program_cbar,
    is_file_initialization_prompt,
    is_flash_confirmation_prompt,
    is_flash_initialization_prompt,
    is_folder_initialization_prompt,
    is_wipeout_prompt,
    reach_editor_command_loop,
    require_persisted_resources,
    verify_persisted_stdio_program,
    verify_through_stdio,
)


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
            @staticmethod
            def reg(register):
                assert register == Reg.PC
                return 0xD657

        cpu = CPU()

    class Harness:
        bns = Firmware()

        @staticmethod
        def wait_for_key():
            pass

    reach_editor_command_loop(Harness())


@given(program_length=st.integers(min_value=0, max_value=0xFFFF))
def test_external_program_cbar_matches_firmware_rounding(program_length: int):
    """The entry map follows BS.ASM's 16-bit length-plus-0x1fff calculation."""
    header = bytearray(10)
    header[2:6] = b"BNS\0"
    header[8:10] = program_length.to_bytes(2, "little")
    rounded_length = program_length + 0x1FFF
    expected = 0x11 if rounded_length > 0xFFFF else ((rounded_length >> 8) & 0xF0) | 0x01
    assert expected_program_cbar(bytes(header)) == expected


def test_bsname_header_requires_entry_cbar_81():
    """The supplied BSNAME length 0x6205 maps common area 1 at page 8."""
    header = b"\x18\x0cBNS\0\xef\x1a\x05\x62"
    assert expected_program_cbar(header) == 0x81


def test_supplied_programs_use_their_own_real_speech_authority(tmp_path):
    assert _program_speech_marker(tmp_path / "bsname.bns") == BSNAME_SPEECH_MARKER
    assert _program_speech_marker(tmp_path / "CALSORT.BNS") == CALSORT_SPEECH_MARKER
    assert _program_speech_marker(tmp_path / "other.bns") is None


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
        "tools.verify_bs2_external_program.bs2_stdio_harness.reach_stdio_editor_command_loop",
        lambda _process: None,
    )
    monkeypatch.setattr(
        "tools.verify_bs2_external_program.bs2_stdio_harness.send_stdio_chord",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "tools.verify_bs2_external_program.bs2_stdio_harness.receive_stdio_file",
        lambda _process, path: received.append(path),
    )
    monkeypatch.setattr(
        "tools.verify_bs2_external_program.bs2_stdio_harness.execute_selected_stdio_program",
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
