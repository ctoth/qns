"""Six-key Braille entry: decoding key transitions and assembling chords."""

import contextlib
import io
import os
from pathlib import Path

from qns.bns import _six_key_reader
from qns.keysource import KeyEvent, Win32InputDecoder
from qns.loader import InputBoundary
from qns.sixkey import SixKeyAssembler, TimedChordAssembler

# The linked NFB99 English chord-acceptance addresses, as tests/test_bns.py
# installs them: enough for a run loop to accept a keyboard at all.
_ANY_BOUNDARY = InputBoundary(0x4327C, 0x41A32, 0x1AF5, 0x41653, 0x0A0D, 0x414AF)

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
    return KeyEvent(
        vk=vk or (ord(char.upper()) if char else 0),
        scan=0,
        char=char,
        down=down,
        control_state=control_state,
    )


def test_dvorak_layout_spells_the_same_cell_from_different_keys():
    """Braille 'c' is dots 1+4: f+j on the default layout, u+h on Dvorak."""
    default = SixKeyAssembler(layout="6-key")
    dvorak = SixKeyAssembler(layout="6-key-dvorak")

    def spell(assembler, first, second):
        chords = []
        for event in (
            press(first),
            press(second),
            press(first, down=False),
            press(second, down=False),
        ):
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
    assert list(assembler.feed(press(vk=VK_HOME, control_state=LEFT_CTRL_PRESSED))) == [0x47]


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
    assert list(assembler.poll(now=0.030)) == []  # still within the chord
    assert list(assembler.poll(now=0.050)) == [0x03]
    assert list(assembler.poll(now=0.060)) == []  # committed only once


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


def test_ctrl_arrows_take_precedence_over_the_plain_arrows():
    from qns.keysource import LEFT_CTRL_PRESSED
    from qns.sixkey import VK_LEFT, VK_RIGHT

    assembler = SixKeyAssembler(layout="6-key")
    ctrl = LEFT_CTRL_PRESSED

    assert list(assembler.feed(press(vk=VK_RIGHT))) == [0x60]  # space+6
    assert list(assembler.feed(press(vk=VK_LEFT))) == [0x44]  # space+3
    # Held with Ctrl the same keys are the dot-5 and dot-2 chords.
    assert list(assembler.feed(press(vk=VK_RIGHT, control_state=ctrl))) == [0x50]
    assert list(assembler.feed(press(vk=VK_LEFT, control_state=ctrl))) == [0x42]


CTRL_C_RECORD = b"\x1b[67;46;3;1;8;1_"


def test_ctrl_c_is_recognised_in_a_key_record():
    """win32-input-mode reports Ctrl-C instead of sending 0x03."""
    events, text = Win32InputDecoder().feed(CTRL_C_RECORD)

    assert text == ""
    assert events[0].interrupt is True
    # The release must not count, or the run would stop twice.
    release, _ = Win32InputDecoder().feed(b"\x1b[67;46;3;0;8;1_")
    assert release[0].interrupt is False


def test_reader_stops_reading_at_ctrl_c(monkeypatch):
    """Keys after the interrupt are never assembled into chords."""
    chords, actions = _control_actions(
        b"\x1b[70;33;102;1;0;1_" + CTRL_C_RECORD + b"\x1b[83;31;115;1;0;1_",
        monkeypatch,
    )

    assert actions == ["exit"]
    assert chords == []


def test_named_keys_are_decoded_before_the_timing_fallback(monkeypatch):
    """A terminal that ignores the mode still names its keys, in VT.

    Read as characters instead, their final bytes are dot keys: `ESC [ D`
    for Left ends in the dot-3 key, so the arrow used to spell a cell
    nobody typed.
    """
    chords, actions = _control_actions(b"fd\x1b[D\n", monkeypatch)

    # The half-built cell goes first, then Left's own chord - space+3.
    assert chords == [0x03, 0x44]
    assert actions == []


def test_vt_ctrl_arrows_keep_their_own_chords(monkeypatch):
    """xterm spells Ctrl+Left `ESC [ 1 ; 5 D`; it is the dot-2 chord."""
    chords, actions = _control_actions(b"\x1b[1;5D", monkeypatch)

    assert chords == [0x42]
    assert actions == []


def test_ss3_function_keys_reach_the_controls(monkeypatch):
    """xterm's F4 is `ESC O S`, whose final byte is the dot-2 key."""
    chords, actions = _control_actions(b"\x1bOS", monkeypatch)

    assert (chords, actions) == ([], ["exit"])

    chords, actions = _control_actions(b"\x1b[15~", monkeypatch)  # F5
    assert (chords, actions) == ([], ["restart"])


def test_named_keys_reach_a_real_terminal_reader(monkeypatch):
    """The same keys, over a pty in cbreak, as the emulator runs it."""
    import sys
    import threading
    import time

    import pytest

    # Windows has neither, and reaches these keys through the console
    # reader instead; the decoding they exercise is shared.
    pty = pytest.importorskip("pty")
    tty = pytest.importorskip("tty")

    master, slave = pty.openpty()
    tty.setcbreak(slave)

    class _Tty:
        def fileno(self):
            return slave

        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", _Tty())
    chords, actions = [], []
    reader = threading.Thread(
        target=_six_key_reader,
        args=("6-key", chords.append, actions.append),
        daemon=True,
    )
    reader.start()

    def expect(count, what):
        deadline = time.monotonic() + 5.0
        while len(chords) < count and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(chords) == count, f"{what}: {[hex(c) for c in chords]}"

    try:
        # Escape is only distinguishable from a sequence by the silence
        # that follows it.
        os.write(master, b"\x1b")
        expect(1, "escape")
        # Left, whose final byte is the dot-3 key read as a character.
        os.write(master, b"\x1b[D")
        expect(2, "left")
        os.write(master, b"fd")
        expect(3, "f+d")

        assert chords == [0x75, 0x44, 0x03]

        # xterm's F4 ends in the dot-2 key, and must still exit.
        os.write(master, b"\x1bOS")
        deadline = time.monotonic() + 5.0
        while not actions and time.monotonic() < deadline:
            time.sleep(0.01)
        assert actions == ["exit"]
        assert chords == [0x75, 0x44, 0x03]
    finally:
        os.close(master)
        os.close(slave)


def test_a_lone_escape_settles_as_the_escape_key(monkeypatch):
    """Escape shares its first byte with every sequence, so it waits."""
    from qns.keysource import VK_ESCAPE, VTKeyDecoder

    decoder = VTKeyDecoder(timeout=0.04)

    assert list(decoder.feed("\x1b", now=0.000)) == []
    assert list(decoder.poll(now=0.020)) == []  # the rest may still arrive
    settled = list(decoder.poll(now=0.050))
    assert [event.vk for event in settled] == [VK_ESCAPE]

    # Reaching the end of the input settles it too, clock or no clock.
    piped = VTKeyDecoder(timeout=None)
    assert list(piped.feed("\x1b", now=0.0)) == []
    assert [event.vk for event in piped.flush()] == [VK_ESCAPE]


def test_escape_and_enter_spell_their_chords_over_a_pipe(monkeypatch):
    """Redirected input keeps the line ending as its cell delimiter."""
    chords, actions = _control_actions(b"fd\nj\n\x1b", monkeypatch)

    # f+d, then j, then Escape's chord: space+1+3+5+6.
    assert chords == [0x03, 0x08, 0x75]
    assert actions == []


def _bare_machine(*, armed: bool):
    """A machine with only the control-request state its methods touch."""
    import threading

    import qns.bns

    machine = qns.bns.BNS.__new__(qns.bns.BNS)
    machine.restart_requested = False
    machine._control_lock = threading.Lock()
    machine._controls_armed = armed
    machine._pending_control = None
    return machine


def test_a_control_pressed_before_the_run_loop_waits_for_it(monkeypatch):
    """An early F5 must not interrupt setup, where nothing cleans up.

    The reader is running before the run loop reaches its try/finally,
    so a key already queued would otherwise raise KeyboardInterrupt into
    the terminal setup: raw terminal left raw, audio left running, and
    the restart the key asked for never performed.
    """
    import pytest

    import qns.bns

    interrupted = []
    monkeypatch.setattr(qns.bns, "_interrupt_emulation", lambda: interrupted.append(True))

    machine = _bare_machine(armed=False)
    machine._request_control("restart")

    # Recorded, but the main thread is left alone until it can unwind.
    assert machine.restart_requested is True
    assert interrupted == []

    # Arming is the run loop saying its cleanup handler is in place; the
    # held control is honoured there, through the same exit as any other.
    with pytest.raises(KeyboardInterrupt):
        machine._arm_controls()

    # And it is honoured once only.
    machine._arm_controls()

    machine._disarm_controls()
    machine._request_control("exit")
    assert interrupted == []


def test_control_requests_unwind_the_run_loop(monkeypatch):
    """Both controls leave through the run loop's KeyboardInterrupt path."""
    import qns.bns

    interrupted = []
    monkeypatch.setattr(qns.bns, "_interrupt_emulation", lambda: interrupted.append(True))

    machine = _bare_machine(armed=True)

    machine._request_control("exit")
    assert interrupted == [True]
    assert machine.restart_requested is False

    machine._request_control("restart")
    assert interrupted == [True, True]
    assert machine.restart_requested is True


def _control_actions(data: bytes, monkeypatch):
    """Run the reader over `data`, returning (chords, control actions)."""
    import sys

    import qns.bns

    read_fd, write_fd = os.pipe()
    os.write(write_fd, data)
    os.close(write_fd)
    monkeypatch.setattr(sys, "stdin", _PipeStdin(read_fd))

    chords, actions = [], []
    try:
        qns.bns._six_key_reader("6-key", chords.append, actions.append)
    finally:
        os.close(read_fd)
    return chords, actions


def test_f4_exits_and_f5_restarts(monkeypatch):
    from qns.sixkey import VK_F4, VK_F5

    def down(vk):
        return f"\x1b[{vk};0;0;1;0;1_".encode()

    chords, actions = _control_actions(down(VK_F4), monkeypatch)
    assert (chords, actions) == ([], ["exit"])

    chords, actions = _control_actions(down(VK_F5), monkeypatch)
    assert (chords, actions) == ([], ["restart"])

    # Releasing them asks for nothing, and neither is a chord.
    chords, actions = _control_actions(f"\x1b[{VK_F4};0;0;0;0;1_".encode(), monkeypatch)
    assert (chords, actions) == ([], [])


def test_ctrl_c_still_asks_to_exit(monkeypatch):
    chords, actions = _control_actions(CTRL_C_RECORD, monkeypatch)
    assert (chords, actions) == ([], ["exit"])


def test_reader_uses_the_console_the_run_loop_opened():
    """The daemon reader is handed a reader; it must never open one."""
    from qns.bns import _six_key_reader
    from qns.sixkey import VK_F4

    batches = [
        [press("f"), press("d")],
        [press("f", down=False), press("d", down=False)],
        [press(vk=VK_F4)],
    ]

    def read_events():
        if not batches:
            raise OSError("cancelled")
        return batches.pop(0)

    chords, actions = [], []
    _six_key_reader("6-key", chords.append, actions.append, read_events)

    assert chords == [0x03]  # f=dot 1, d=dot 2
    assert actions == ["exit"]


def test_console_mode_is_released_when_a_finite_run_ends(monkeypatch):
    """A run that simply reaches its cycle budget must hand the console back.

    The reader owns nothing: it is a daemon blocked in a read, whose
    frames are never unwound, so a mode it held would outlive the
    process and leave the invoking console without echo or line input.
    """
    import sys
    import threading

    import qns.bns
    from qns.bns import BNS

    monkeypatch.setattr(sys, "platform", "win32")
    opened, closed = [], []
    reading = threading.Event()

    @contextlib.contextmanager
    def fake_console():
        opened.append(threading.current_thread().name)
        cancelled = threading.Event()

        def read_events():
            reading.set()
            cancelled.wait()  # as ReadConsoleInput blocks, until cancelled
            raise OSError("cancelled")

        try:
            yield read_events
        finally:
            cancelled.set()
            closed.append(threading.current_thread().name)

    monkeypatch.setattr(qns.bns, "windows_console_key_events", fake_console)

    machine = BNS(stdin_device="6-key")
    machine._input_boundary = _ANY_BOUNDARY
    monkeypatch.setattr(BNS, "_execute_budget", lambda self, cycles: cycles)

    machine.run(max_cycles=1000)

    assert reading.wait(2.0), "the reader never reached the console"
    assert opened == ["MainThread"]
    assert closed == ["MainThread"]


def test_console_handle_follows_the_current_stdin(monkeypatch):
    """A substituted stdin must not be bypassed for the process console."""
    import sys
    import types

    import pytest

    from qns.keysource import stdin_console_handle

    asked = []
    fake_msvcrt = types.ModuleType("msvcrt")
    fake_msvcrt.get_osfhandle = lambda fd: asked.append(fd) or 0x1234
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    monkeypatch.setattr(sys, "stdin", _PipeStdin(7))
    assert stdin_console_handle() == 0x1234
    assert asked == [7]

    # A stream with no descriptor at all has no handle to offer.
    monkeypatch.setattr(sys, "stdin", io.StringIO("fd\n"))
    with pytest.raises(OSError):
        stdin_console_handle()


def test_six_key_is_rejected_for_the_typewriter_model():
    """TNS scans are not Braille bitmasks; dot 1 would be a reset code."""
    import pytest

    import qns.cli

    for layout in ("6-key", "6-key-dvorak"):
        with pytest.raises(SystemExit):
            qns.cli.main(["--model", "tns", "--input", layout, "roms/bspeng.bns"])


def test_terminal_probe_loads_without_posix_terminal_modules(monkeypatch):
    """The documented probe must reach its Windows path, not ImportError."""
    import builtins
    import importlib.util
    import sys
    from pathlib import Path

    real_import = builtins.__import__

    def refuse_posix(name, *args, **kwargs):
        if name in ("termios", "tty", "select"):
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(builtins, "__import__", refuse_posix)

    probe = Path(__file__).resolve().parents[1] / "tools" / "probe_terminal_keys.py"
    spec = importlib.util.spec_from_file_location("probe_terminal_keys", probe)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.POSIX is False
    assert callable(module.probe_windows_console)


def test_restart_reexecs_the_original_command_line(monkeypatch):
    import sys

    import qns.cli

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "executable", "/venv/bin/python3")
    monkeypatch.setattr(
        sys, "orig_argv", ["/usr/bin/python3", "-m", "qns.bns", "--audio", "rom.bns"]
    )
    execs = []
    monkeypatch.setattr(qns.cli.os, "execv", lambda path, argv: execs.append((path, argv)))

    qns.cli._restart_with_same_settings()

    # argv[0] is sys.executable, not sys.orig_argv[0]: under `uv run` on
    # Windows those differ, and only sys.executable is guaranteed to have
    # this project's venv (and so its dependencies) importable.
    assert execs == [
        (
            "/venv/bin/python3",
            ["/venv/bin/python3", "-m", "qns.bns", "--audio", "rom.bns"],
        )
    ]


def test_windows_restart_waits_for_the_replacement(monkeypatch):
    """Windows has no in-process exec, so the shell must keep waiting on us."""
    import subprocess
    import sys

    import pytest

    import qns.cli

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", r"C:\venv\Scripts\python.exe")
    monkeypatch.setattr(sys, "orig_argv", ["python.exe", "-m", "qns.bns", "rom.bns"])
    monkeypatch.setattr(qns.cli.os, "execv", lambda path, argv: pytest.fail("execv on Windows"))
    waited = []

    def run_child(argv):
        waited.append(argv)
        return subprocess.CompletedProcess(argv, 3)

    monkeypatch.setattr(qns.cli.subprocess, "run", run_child)

    with pytest.raises(SystemExit) as exit_info:
        qns.cli._restart_with_same_settings()

    # sys.executable, not sys.orig_argv[0]: see the matching regression
    # note in test_restart_reexecs_the_original_command_line.
    assert waited == [[r"C:\venv\Scripts\python.exe", "-m", "qns.bns", "rom.bns"]]
    assert exit_info.value.code == 3


def test_failed_restart_exits_rather_than_carrying_on(monkeypatch):
    import sys

    import pytest

    import qns.cli

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "orig_argv", ["/nonexistent/python", "-m", "qns.bns"])

    def refuse(path, argv):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(qns.cli.os, "execv", refuse)

    with pytest.raises(SystemExit):
        qns.cli._restart_with_same_settings()


def test_restart_saves_nonvolatile_state_before_execing(tmp_path, monkeypatch):
    """F5 must not discard the emulated battery-backed RAM.

    The state file is written among the post-run actions, so a restart
    that execs before them would resume with the session's RAM thrown
    away - the opposite of keeping the same settings.
    """
    import sys

    import pytest

    import qns.cli

    rom = Path("roms/bspeng.bns")
    if not rom.is_file():
        pytest.skip(f"local proprietary ROM is unavailable: {rom}")

    state = tmp_path / "state.bin"
    original_run = qns.cli.BNS.run

    def run_then_ask_for_restart(self, *args, **kwargs):
        result = original_run(self, *args, **kwargs)
        self.restart_requested = True
        return result

    saved_when_execed = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(qns.cli.BNS, "run", run_then_ask_for_restart)
    monkeypatch.setattr(
        qns.cli.os, "execv", lambda path, argv: saved_when_execed.append(state.exists())
    )

    qns.cli.main(
        [
            "--cycles",
            "1000",
            "--input",
            "none",
            "--state",
            str(state),
            str(rom),
        ]
    )

    assert saved_when_execed == [True]
    assert state.stat().st_size > 0
