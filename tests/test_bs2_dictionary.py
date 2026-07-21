"""Authorities for the supplied BS2 spell-dictionary stdio workflow."""

from tools.bs2_stdio_harness import E_CHORD, FILE_COMMAND_PROMPT, Y_KEY
from tools.verify_bs2_dictionary import (
    CREATE_KEY,
    DONE_SUFFIX,
    FLASH_FOLDER_KEY,
    RAM_FOLDER_KEY,
    SPACE_KEY,
    SPELLCHECK_KEY,
    STATUS_CHORD,
    TEST_FILE_NAME,
    TEST_WORD,
    W_KEY,
    verify_dictionary_through_stdio,
)
from tools.verify_bs2_external_program import (
    F_KEY,
    O_CHORD,
)
from tools.verify_bs2_help import F_CHORD


def test_dictionary_workflow_imports_checks_persists_and_restarts(
    monkeypatch,
    tmp_path,
):
    rom = tmp_path / "bs2eng.bns"
    state = tmp_path / "bs2.state"
    dictionary = tmp_path / "spell.dic"
    dictionary.write_bytes(b"dictionary")
    launches = []
    processes = []
    chords = []
    texts = []
    received = []
    persisted = []
    speech_waits = []

    class Process:
        def __init__(self, launched_rom, **kwargs):
            self.number = len(processes)
            self.sent = []
            launches.append((launched_rom, kwargs))
            processes.append(self)

        def __enter__(self):
            return self

        def __exit__(self, _error_type, _error, _traceback):
            return False

        def send_keyboard(self, **payload):
            self.sent.append(payload)

        @staticmethod
        def wait_for_keyboard(*_args, **_kwargs):
            pass

        def wait_for_speech_suffix(self, suffix, description, **kwargs):
            speech_waits.append((self.number, suffix, description, kwargs))

        @staticmethod
        def request_stop(**_kwargs):
            pass

    monkeypatch.setattr("tools.verify_bs2_dictionary.BNSStdioProcess", Process)
    monkeypatch.setattr(
        "tools.verify_bs2_dictionary.reach_stdio_editor_command_loop",
        lambda _process: None,
    )
    monkeypatch.setattr(
        "tools.verify_bs2_dictionary.send_stdio_chord",
        lambda process, chord: chords.append((process.number, chord)),
    )
    monkeypatch.setattr(
        "tools.verify_bs2_dictionary.send_stdio_text",
        lambda process, value: texts.append((process.number, value)),
    )
    monkeypatch.setattr(
        "tools.verify_bs2_dictionary.receive_stdio_file",
        lambda process, path: received.append((process.number, path)),
    )
    monkeypatch.setattr(
        "tools.verify_bs2_dictionary.require_persisted_resources",
        lambda saved, resources: persisted.append((saved, resources)),
    )

    verify_dictionary_through_stdio(rom, state, dictionary)

    assert TEST_WORD == "the"
    assert launches == [
        (rom, {"model": "bs2", "state": state, "power_on_input": True}),
        (rom, {"model": "bs2", "state": state}),
    ]
    assert processes[0].sent == []
    assert processes[1].sent == []
    assert received == [(0, dictionary)]
    assert persisted == [(state, (dictionary,))]
    assert texts == [
        (0, TEST_FILE_NAME),
        (0, TEST_WORD),
    ]
    assert chords == [
        (0, STATUS_CHORD),
        (0, F_CHORD),
        (0, Y_KEY),
        (0, E_CHORD),
        (0, O_CHORD),
        (0, F_KEY),
        (0, SPACE_KEY),
        (0, FLASH_FOLDER_KEY),
        (0, RAM_FOLDER_KEY),
        (0, CREATE_KEY),
        (0, E_CHORD),
        (0, O_CHORD),
        (0, SPELLCHECK_KEY),
        (0, W_KEY),
        (1, O_CHORD),
        (1, SPELLCHECK_KEY),
        (1, W_KEY),
    ]
    assert speech_waits == [
        (0, FILE_COMMAND_PROMPT, "Enter file command prompt", {"timeout": 60}),
        (0, DONE_SUFFIX, "imported dictionary spellcheck completion", {"timeout": 60}),
        (1, DONE_SUFFIX, "reloaded dictionary spellcheck completion", {"timeout": 60}),
    ]
