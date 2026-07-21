"""Verify host-backed PC Disk commands through the supplied BS2 firmware."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from qns.input_driver import ASCII_TO_BNS_KEY
from tools.bs2_stdio_harness import E_CHORD, reach_stdio_editor_command_loop, send_stdio_chord
from tools.stdio_process import BNSStdioProcess
from tools.verify_bs2_help import C_CHORD, send_stdio_text

S_CHORD = ASCII_TO_BNS_KEY[ord("S")]
D_KEY = ASCII_TO_BNS_KEY[ord("d")]
L_KEY = ASCII_TO_BNS_KEY[ord("l")]
S_KEY = ASCII_TO_BNS_KEY[ord("s")]
LOAD_PROOF_TEXT = "pc disk live proof"
SAVED_FILE_PREFIX = b"Braille 'n Speak Two Thousand Mini Help File\r"
PROOF_SPEECH = (
    "P",
    "E",
    "S",
    "E1",
    "D",
    "I",
    "S",
    "K",
    "L",
    "I",
    "V",
    "P",
    "R",
    "U",
    "U",
    "F",
)
EDITOR_COMMAND_LOOP_PC = 0xD657


def _finish_filename_prompt(process: BNSStdioProcess) -> None:
    """Submit a storage filename and require return to the editor loop."""
    process.arm_pc_watch(EDITOR_COMMAND_LOOP_PC, timeout=60)
    process.send_keyboard(chord=E_CHORD)
    accepted = False
    completed = False

    def command_completed(event: dict[str, object]) -> bool:
        nonlocal accepted, completed
        if (
            event.get("device") == "keyboard"
            and event.get("state") == "accepted"
            and event.get("chord") == E_CHORD
        ):
            accepted = True
        elif (
            event.get("device") == "cpu"
            and event.get("event") == "pc-watch"
            and event.get("pc") == EDITOR_COMMAND_LOOP_PC
        ):
            completed = True
        return accepted and completed

    process.wait_for(
        command_completed,
        "storage command return to the editor loop",
        timeout=60,
    )


def _run_pc_disk_commands(rom: Path, disk_root: Path) -> None:
    """Run directory, load, and save against one disposable host root."""
    load_path = disk_root / "load.txt"
    saved_path = disk_root / "saved.txt"
    load_path.write_text(LOAD_PROOF_TEXT, encoding="ascii")

    with BNSStdioProcess(
        rom,
        model="bs2",
        pc_disk_dir=disk_root,
        power_on_input=True,
    ) as process:
        reach_stdio_editor_command_loop(process)
        serial_start = (len(process.serial[0]), len(process.serial[1]))
        try:
            send_stdio_chord(process, S_CHORD)
            send_stdio_chord(process, S_KEY)
            send_stdio_text(process, saved_path.name)
            _finish_filename_prompt(process)

            send_stdio_chord(process, S_CHORD)
            send_stdio_chord(process, D_KEY)
            send_stdio_text(process, "*.txt")
            _finish_filename_prompt(process)

            send_stdio_chord(process, S_CHORD)
            send_stdio_chord(process, L_KEY)
            send_stdio_text(process, load_path.name)
            _finish_filename_prompt(process)

            send_stdio_chord(process, C_CHORD, wait_ready=False)
            process.wait_for_speech_suffix(
                PROOF_SPEECH,
                "loaded host text spoken by firmware",
                timeout=60,
            )
        except TimeoutError as error:
            serial = (
                bytes(process.serial[0][serial_start[0] :]),
                bytes(process.serial[1][serial_start[1] :]),
            )
            raise RuntimeError(
                "PC Disk firmware command stalled; "
                f"serial0={serial[0].hex(' ')}; serial1={serial[1].hex(' ')}"
            ) from error

    actual = saved_path.read_bytes()
    if not actual.startswith(SAVED_FILE_PREFIX):
        raise RuntimeError(
            "firmware PC Disk save did not contain the current Mini Help file; "
            f"prefix={actual[: len(SAVED_FILE_PREFIX)].hex(' ')}"
        )


def verify_pc_disk_through_stdio(rom: Path) -> None:
    """Verify PC Disk commands against a temporary host directory."""
    with tempfile.TemporaryDirectory(prefix="qns-pc-disk-") as directory:
        _run_pc_disk_commands(rom, Path(directory))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    args = parser.parse_args()
    verify_pc_disk_through_stdio(args.rom)


if __name__ == "__main__":
    main()
