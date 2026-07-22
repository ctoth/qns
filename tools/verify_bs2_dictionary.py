"""Verify the supplied BS2 spell dictionary through real firmware stdio."""

from __future__ import annotations

import argparse
from pathlib import Path

from qns.input_driver import ASCII_TO_BNS_KEY
from tools.bs2_stdio_harness import (
    E_CHORD,
    FILE_COMMAND_PROMPT,
    Y_KEY,
    reach_stdio_editor_command_loop,
    receive_stdio_file,
    send_stdio_chord,
)
from tools.stdio_process import BNSStdioProcess
from tools.verify_bs2_external_program import (
    F_KEY,
    O_CHORD,
    require_persisted_resources,
)
from tools.verify_bs2_help import F_CHORD, send_stdio_text

CREATE_KEY = ASCII_TO_BNS_KEY[ord("c")]
FLASH_FOLDER_KEY = ASCII_TO_BNS_KEY[ord("1")]
RAM_FOLDER_KEY = ASCII_TO_BNS_KEY[ord("0")]
SPACE_KEY = ASCII_TO_BNS_KEY[ord(" ")]
SPELLCHECK_KEY = 0x21
STATUS_CHORD = 0x4C
W_KEY = ASCII_TO_BNS_KEY[ord("w")]
DONE_SUFFIX = ("D", "UH1", "N")
TEST_FILE_NAME = "spellchk.txt"
TEST_WORD = "the"


def run_spellcheck(process: BNSStdioProcess, description: str) -> None:
    """Spellcheck the current word and require firmware completion."""
    send_stdio_chord(process, O_CHORD)
    send_stdio_chord(process, SPELLCHECK_KEY)
    send_stdio_chord(process, W_KEY)
    process.wait_for_speech_suffix(
        DONE_SUFFIX,
        description,
        timeout=60,
    )


def verify_dictionary_through_stdio(
    rom: Path,
    state: Path,
    dictionary: Path,
) -> None:
    """Import, use, persist, and reuse the supplied spell dictionary."""
    with BNSStdioProcess(
        rom,
        model="bs2",
        state=state,
        reset="cold",
    ) as process:
        reach_stdio_editor_command_loop(process)

        send_stdio_chord(process, STATUS_CHORD)
        send_stdio_chord(process, F_CHORD)
        send_stdio_chord(process, Y_KEY)
        send_stdio_chord(process, E_CHORD)

        send_stdio_chord(process, O_CHORD)
        send_stdio_chord(process, F_KEY)
        process.wait_for_speech_suffix(
            FILE_COMMAND_PROMPT,
            "Enter file command prompt",
            timeout=60,
        )
        send_stdio_chord(process, SPACE_KEY)
        send_stdio_chord(process, FLASH_FOLDER_KEY)
        receive_stdio_file(process, dictionary)

        send_stdio_chord(process, RAM_FOLDER_KEY)
        send_stdio_chord(process, CREATE_KEY)
        send_stdio_text(process, TEST_FILE_NAME)
        send_stdio_chord(process, E_CHORD)
        send_stdio_text(process, TEST_WORD)
        run_spellcheck(process, "imported dictionary spellcheck completion")
        process.request_stop(timeout=60)

    require_persisted_resources(state, (dictionary,))

    with BNSStdioProcess(rom, model="bs2", state=state) as process:
        process.wait_for_keyboard("ready", timeout=60)
        run_spellcheck(process, "reloaded dictionary spellcheck completion")
        process.request_stop(timeout=60)

    print(f"imported: {dictionary.name} ({dictionary.stat().st_size} bytes)")
    print(f"spellchecked: {TEST_WORD} before and after restart")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify supplied BS2 spell dictionary through JSONL stdio",
    )
    parser.add_argument("rom", type=Path)
    parser.add_argument("state", type=Path)
    parser.add_argument("dictionary", type=Path)
    args = parser.parse_args()

    verify_dictionary_through_stdio(args.rom, args.state, args.dictionary)


if __name__ == "__main__":
    main()
