"""Authorities for the supplied BS2 full-help stdio workflow."""

from qns.bns import _ASCII_TO_BNS_KEY
from tools.verify_bs2_external_program import E_CHORD, F_KEY, O_CHORD
from tools.verify_bs2_help import (
    C_CHORD,
    DOT4_CHORD,
    F_CHORD,
    HELP_CHORD,
    HELP_OPEN_MARKER,
    HELP_TITLE_END,
    R_CHORD,
    Z_CHORD,
    read_help_title,
    send_stdio_text,
    verify_help_through_stdio,
)


def test_stdio_text_waits_for_each_firmware_accepted_character():
    events = []

    class Process:
        @staticmethod
        def send_keyboard(**payload):
            events.append(("send", payload))

        @staticmethod
        def wait_for_keyboard(state, **payload):
            events.append((state, payload))

    send_stdio_text(Process(), "help")

    assert events == [
        ("send", {"text": "help"}),
        ("accepted", {"chord": _ASCII_TO_BNS_KEY[ord("h")], "timeout": 60}),
        ("accepted", {"chord": _ASCII_TO_BNS_KEY[ord("e")], "timeout": 60}),
        ("accepted", {"chord": _ASCII_TO_BNS_KEY[ord("l")], "timeout": 60}),
        ("accepted", {"chord": _ASCII_TO_BNS_KEY[ord("p")], "timeout": 60}),
        ("ready", {"timeout": 60}),
    ]


def test_help_title_waits_for_open_marker_and_exact_title_end(monkeypatch):
    chords = []
    speech_waits = []

    class Process:
        speech_names = ["prior"]

        def wait_for(self, predicate, description, **kwargs):
            self.speech_names.extend(("B", "R", *HELP_TITLE_END, "AFTER"))
            assert predicate({"device": "speech"})
            speech_waits.append((description, kwargs))

    monkeypatch.setattr(
        "tools.verify_bs2_help.send_stdio_chord",
        lambda process, chord: (
            chords.append(chord),
            process.speech_names.extend((*HELP_OPEN_MARKER, "overshoot"))
            if chord == HELP_CHORD
            else None,
        ),
    )
    process = Process()

    assert read_help_title(process) == ("B", "R", *HELP_TITLE_END)
    assert chords == [HELP_CHORD, C_CHORD]
    assert speech_waits == [
        ("complete full-help title line", {"timeout": 60}),
    ]


def test_help_workflow_imports_renames_reads_persists_and_restarts(
    monkeypatch,
    tmp_path,
):
    rom = tmp_path / "bs2eng.bns"
    state = tmp_path / "bs2.state"
    help_file = tmp_path / "bs2eng.hlp"
    help_file.write_bytes(b"full help")
    launches = []
    processes = []
    chords = []
    received = []
    persisted = []

    class Process:
        def __init__(self, launched_rom, **kwargs):
            self.number = len(processes)
            self.speech_names = (
                list(HELP_OPEN_MARKER) if self.number == 1 else []
            )
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

        @staticmethod
        def wait_for_speech_suffix(*_args, **_kwargs):
            pass

        @staticmethod
        def request_stop(**_kwargs):
            pass

    monkeypatch.setattr("tools.verify_bs2_help.BNSStdioProcess", Process)
    monkeypatch.setattr(
        "tools.verify_bs2_help.reach_stdio_editor_command_loop",
        lambda _process: None,
    )

    def record_chord(process, chord):
        chords.append((process.number, chord))
        if chord == HELP_CHORD:
            process.speech_names.extend(HELP_OPEN_MARKER)
        elif chord == C_CHORD:
            process.speech_names.extend(HELP_TITLE_END)

    monkeypatch.setattr(
        "tools.verify_bs2_help.send_stdio_chord",
        record_chord,
    )
    monkeypatch.setattr(
        "tools.verify_bs2_help.receive_stdio_file",
        lambda process, path: received.append((process.number, path)),
    )
    monkeypatch.setattr(
        "tools.verify_bs2_help.require_persisted_resources",
        lambda saved, resources: persisted.append((saved, resources)),
    )

    verify_help_through_stdio(rom, state, help_file)

    assert launches == [
        (rom, {"model": "bs2", "state": state, "power_on_input": True}),
        (rom, {"model": "bs2", "state": state}),
    ]
    assert processes[0].sent == [
        {"chord": 0x4A},
        {"text": "bs2eng.hlp"},
        {"text": "help"},
    ]
    assert processes[1].sent == []
    assert received == [(0, help_file)]
    assert persisted == [(state, (help_file,))]
    assert chords == [
        (0, O_CHORD),
        (0, F_KEY),
        (0, F_CHORD),
        (0, E_CHORD),
        (0, DOT4_CHORD),
        (0, R_CHORD),
        (0, E_CHORD),
        (0, E_CHORD),
        (0, E_CHORD),
        (0, HELP_CHORD),
        (0, C_CHORD),
        (0, Z_CHORD),
        (1, C_CHORD),
        (1, Z_CHORD),
    ]
