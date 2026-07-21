"""Verify supplied BS2 full help through real firmware stdio workflows."""

from __future__ import annotations

import argparse
from pathlib import Path

from qns.input_driver import ASCII_TO_BNS_KEY
from tools.stdio_process import BNSStdioProcess
from tools.verify_bs2_external_program import (
    E_CHORD,
    F_KEY,
    FILE_COMMAND_PROMPT,
    O_CHORD,
    reach_stdio_editor_command_loop,
    receive_stdio_file,
    require_persisted_resources,
    send_stdio_chord,
)

R_CHORD = 0x57
DOT4_CHORD = 0x48
F_CHORD = 0x4B
HELP_CHORD = 0x79
C_CHORD = 0x49
Z_CHORD = 0x75
HELP_OPEN_MARKER = ("HF", "EH", "L", "P", "I", "Z", "O", "OU", "P", "EH1", "N")
HELP_TITLE_END = (
    "HF", "EH", "L", "P", "F", "AH", "E", "L", "J", "U", "U1", "L", "AH", "E1",
    "W", "UH1", "N", "N", "AH", "E", "N", "N", "AH", "E", "N", "N", "AH", "E", "N",
)


def send_stdio_text(process: BNSStdioProcess, text: str) -> None:
    """Deliver text and require firmware acceptance of every mapped character."""
    process.send_keyboard(text=text)
    for character in text:
        process.wait_for_keyboard(
            "accepted",
            chord=ASCII_TO_BNS_KEY[ord(character)],
            timeout=60,
        )
    process.wait_for_keyboard("ready", timeout=60)


def _wait_for_speech_sequence(
    process: BNSStdioProcess,
    start: int,
    sequence: tuple[str, ...],
    description: str,
) -> int:
    """Return the end of a retained speech sequence at or after ``start``."""
    if not sequence:
        raise ValueError("speech sequence must not be empty")

    def sequence_end() -> int | None:
        stop = len(process.speech_names) - len(sequence) + 1
        for index in range(start, max(start, stop)):
            if tuple(process.speech_names[index : index + len(sequence)]) == sequence:
                return index + len(sequence)
        return None

    end = sequence_end()
    if end is None:
        process.wait_for(
            lambda _event: sequence_end() is not None,
            description,
            timeout=60,
        )
        end = sequence_end()
    assert end is not None
    return end


def read_help_title(
    process: BNSStdioProcess,
    *,
    open_help: bool = True,
) -> tuple[str, ...]:
    """Open firmware Help, speak its current line, and return emitted phonemes."""
    open_start = len(process.speech_names) if open_help else 0
    if open_help:
        send_stdio_chord(process, HELP_CHORD)
    _wait_for_speech_sequence(
        process,
        open_start,
        HELP_OPEN_MARKER,
        "help is open",
    )
    speech_start = len(process.speech_names)
    send_stdio_chord(process, C_CHORD)
    speech_end = _wait_for_speech_sequence(
        process,
        speech_start,
        HELP_TITLE_END,
        "complete full-help title line",
    )
    return tuple(process.speech_names[speech_start:speech_end])


def verify_help_through_stdio(rom: Path, state: Path, help_file: Path) -> None:
    """Import, rename, read, persist, and reread the supplied full help file."""
    with BNSStdioProcess(
        rom,
        model="bs2",
        state=state,
        power_on_input=True,
    ) as process:
        reach_stdio_editor_command_loop(process)

        send_stdio_chord(process, O_CHORD)
        send_stdio_chord(process, F_KEY)
        process.wait_for_speech_suffix(
            FILE_COMMAND_PROMPT,
            "Enter file command prompt",
            timeout=60,
        )
        receive_stdio_file(process, help_file)

        send_stdio_chord(process, F_CHORD)
        send_stdio_text(process, help_file.name)
        send_stdio_chord(process, E_CHORD)
        send_stdio_chord(process, DOT4_CHORD)
        send_stdio_chord(process, R_CHORD)
        send_stdio_text(process, "help")
        send_stdio_chord(process, E_CHORD)
        process.wait_for_speech_suffix(
            FILE_COMMAND_PROMPT,
            "post-rename Enter file command prompt",
            timeout=60,
        )
        send_stdio_chord(process, E_CHORD)
        send_stdio_chord(process, E_CHORD)
        imported_title = read_help_title(process)
        send_stdio_chord(process, Z_CHORD)
        process.request_stop(timeout=60)

    require_persisted_resources(state, (help_file,))

    with BNSStdioProcess(rom, model="bs2", state=state) as process:
        process.wait_for_keyboard("ready", timeout=60)
        reloaded_title = read_help_title(process, open_help=False)
        send_stdio_chord(process, Z_CHORD)
        process.request_stop(timeout=60)

    print(f"imported: {help_file.name} ({help_file.stat().st_size} bytes) as help")
    print("imported title phonemes:", " ".join(imported_title))
    print("reloaded: help from persisted flash")
    print("reloaded title phonemes:", " ".join(reloaded_title))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify supplied BS2 full help through JSONL stdio",
    )
    parser.add_argument("rom", type=Path)
    parser.add_argument("state", type=Path)
    parser.add_argument("help_file", type=Path)
    args = parser.parse_args()

    verify_help_through_stdio(args.rom, args.state, args.help_file)


if __name__ == "__main__":
    main()
