"""Import and execute a BS2 external program through the real firmware path."""

from __future__ import annotations

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path

from z180 import Reg

from qns.memory import Memory
from tools import bs2_stdio_harness
from tools.bs2_harness import BS2Harness
from tools.stdio_process import BNSStdioProcess

CYCLE_LIMIT = 100_000_000

O_CHORD = 0x55
F_KEY = 0x0B
X_CHORD = 0x6D
DOT5_CHORD = 0x50

FLASH_INITIALIZATION_PC = 0x1BDA
BSNAME_SPEECH_MARKER = (
    "A",
    "E1",
    "D",
    "T",
    "U",
    "U",
    "B",
    "R",
    "A",
    "E",
    "L",
    "I",
    "N",
    "THV",
    "I",
    "S",
    "F",
    "E",
    "L",
    "D",
    "EH",
    "N",
    "T",
    "ER",
    "E",
    "K",
    "OU",
    "ER",
    "D",
    "W",
    "EH",
    "N",
    "YI",
    "U",
    "U",
    "AH",
    "ER",
    "D",
    "UH1",
    "N",
)
CALSORT_SPEECH_MARKER = (
    "R",
    "ER",
    "ER",
    "K",
    "OO",
    "D",
    "N",
    "AH",
    "T",
    "O",
    "OU",
    "P",
    "EH1",
    "N",
    "D",
    "A",
    "E1",
    "T",
    "B",
    "OO",
    "K",
)


def is_flash_initialization_prompt(names: list[str]) -> bool:
    """Return whether retained speech ends with the exact first-boot prompt."""
    prompt_size = len(bs2_stdio_harness.FLASH_INITIALIZATION_PROMPT)
    return tuple(names[-prompt_size:]) == bs2_stdio_harness.FLASH_INITIALIZATION_PROMPT


def is_file_initialization_prompt(names: list[str]) -> bool:
    """Return whether retained speech ends with the exact cold-reset prompt."""
    prompt_size = len(bs2_stdio_harness.FILE_INITIALIZATION_PROMPT)
    return tuple(names[-prompt_size:]) == bs2_stdio_harness.FILE_INITIALIZATION_PROMPT


def is_folder_initialization_prompt(names: list[str]) -> bool:
    """Return whether retained speech ends with the exact folder prompt."""
    prompt_size = len(bs2_stdio_harness.FOLDER_INITIALIZATION_PROMPT)
    return tuple(names[-prompt_size:]) == bs2_stdio_harness.FOLDER_INITIALIZATION_PROMPT


def is_wipeout_prompt(names: list[str]) -> bool:
    """Return whether retained speech ends with the exact file-area prompt."""
    prompt_size = len(bs2_stdio_harness.WIPEOUT_PROMPT)
    return tuple(names[-prompt_size:]) == bs2_stdio_harness.WIPEOUT_PROMPT


def is_flash_confirmation_prompt(names: list[str]) -> bool:
    """Return whether speech ends with the exact destructive-action confirmation."""
    prompt_size = len(bs2_stdio_harness.FLASH_CONFIRMATION_PROMPT)
    return tuple(names[-prompt_size:]) == bs2_stdio_harness.FLASH_CONFIRMATION_PROMPT


def reach_editor_command_loop(harness: BS2Harness) -> None:
    """Complete the real first-boot dialogue and reach the editor key loop."""
    bns = harness.bns
    harness.wait_for_key()
    if bns._command_loop_write_count > 0 and bns.cpu.reg(Reg.PC) == 0xD657:
        return

    names = [
        phoneme.name
        for phoneme in bns.ssi263.get_phonemes(include_pauses=False)
    ]
    file_initialization = is_file_initialization_prompt(names)
    flash_initialization = is_flash_initialization_prompt(names)
    folder_initialization = is_folder_initialization_prompt(names)
    wipeout = is_wipeout_prompt(names)
    if bns.cpu.reg(Reg.PC) != FLASH_INITIALIZATION_PC or not (
        file_initialization or flash_initialization or folder_initialization or wipeout
    ):
        raise RuntimeError(
            f"unexpected BS2 boot wait; pc={bns.cpu.reg(Reg.PC):04X} "
            f"speech_tail=[{' '.join(names[-40:])}]"
        )

    if folder_initialization:
        harness.chord(bs2_stdio_harness.FLASH_INITIALIZATION_Y_KEY)
        reach_editor_command_loop(harness)
        return

    speech_cursor = len(bns.ssi263.phoneme_log)
    harness.chord(bs2_stdio_harness.FLASH_INITIALIZATION_Y_KEY)
    harness.run_until(
        lambda: is_flash_confirmation_prompt(
            [
                phoneme.name
                for phoneme in bns.ssi263.get_phonemes(
                    start=speech_cursor,
                    include_pauses=False,
                )
            ]
        ),
        "BS2 destructive-action confirmation prompt",
        context=lambda: (
            "response_speech=["
            + " ".join(
                phoneme.name
                for phoneme in bns.ssi263.get_phonemes(
                    start=speech_cursor,
                    include_pauses=False,
                )
            )
            + "]"
        ),
    )
    harness.wait_for_key()
    if bns._command_loop_write_count > 0 and bns.cpu.reg(Reg.PC) == 0xD657:
        return

    response_names = [
        phoneme.name
        for phoneme in bns.ssi263.get_phonemes(
            start=speech_cursor,
            include_pauses=False,
        )
    ]
    if bns.cpu.reg(Reg.PC) != FLASH_INITIALIZATION_PC or not is_flash_confirmation_prompt(
        response_names
    ):
        raise RuntimeError(
            f"unexpected flash confirmation wait; pc={bns.cpu.reg(Reg.PC):04X} "
            f"response_speech=[{' '.join(response_names)}]"
        )

    harness.chord(bs2_stdio_harness.FLASH_INITIALIZATION_Y_KEY)
    if wipeout:
        harness.run_until(
            lambda: (
                bns._command_loop_write_count > 0
                and bns.cpu.reg(Reg.PC) == 0xD657
            ),
            "BS2 editor command loop after file-area initialization",
        )
    else:
        reach_editor_command_loop(harness)


def reject_disk_probes(
    harness: BS2Harness,
    context: str,
) -> tuple[int, list[str]]:
    """Reject the firmware's channel-1/channel-0 disk-drive probes."""
    bns = harness.bns
    traces: list[str] = []
    cursor = harness.wait_for_serial(1, 0, bytes((0x05,)), "ASCI1 disk-drive ENQ")
    harness.queue_serial(bytes((bs2_stdio_harness.NAK,)))
    traces.append(harness.wait_for_receive(1, "ASCI1 NAK", context=context))

    harness.select_serial(0)
    combyt_trace = ",".join(
        f"{value:02X}@{cycle}/pc={pc:04X}" for cycle, pc, _address, value in bns.traced_writes
    )
    cursor = harness.wait_for_serial(
        0,
        cursor,
        bytes((0x05,)),
        "ASCI0 disk-drive ENQ",
        context=f"{context}; {'; '.join(traces)}; COMBYT=[{combyt_trace}]",
    )
    harness.queue_serial(bytes((bs2_stdio_harness.NAK,)))
    traces.append(harness.wait_for_receive(0, "ASCI0 NAK"))
    return cursor, traces


def transfer_ymodem(harness: BS2Harness, cursor: int, program: Path) -> None:
    """Send one file and an empty batch terminator to the firmware receiver."""
    program_data = program.read_bytes()
    header = program.name.encode("ascii") + b"\0" + str(len(program_data)).encode("ascii") + b"\0"
    header = header.ljust(128, b"\0")

    cursor = harness.wait_for_serial(
        0,
        cursor,
        bytes((bs2_stdio_harness.CRC_REQUEST,)),
        "initial YMODEM CRC request",
    )
    harness.queue_serial(bs2_stdio_harness.ymodem_packet(0, header, 128))
    cursor = harness.wait_for_serial(
        0,
        cursor,
        bytes((bs2_stdio_harness.ACK, bs2_stdio_harness.CRC_REQUEST)),
        "header ACK and data CRC request",
    )

    for block_number, offset in enumerate(range(0, len(program_data), 1_024), start=1):
        payload = program_data[offset : offset + 1_024].ljust(
            1_024,
            bytes((bs2_stdio_harness.CPM_EOF,)),
        )
        harness.queue_serial(
            bs2_stdio_harness.ymodem_packet(block_number & 0xFF, payload, 1_024)
        )
        cursor = harness.wait_for_serial(
            0,
            cursor,
            bytes((bs2_stdio_harness.ACK,)),
            f"data block {block_number} ACK",
        )

    harness.queue_serial(bytes((bs2_stdio_harness.EOT,)))
    cursor = harness.wait_for_serial(
        0,
        cursor,
        bytes((bs2_stdio_harness.ACK, bs2_stdio_harness.CRC_REQUEST)),
        "EOT ACK and batch CRC request",
    )
    harness.queue_serial(bs2_stdio_harness.ymodem_packet(0, bytes(128), 128))
    harness.wait_for_serial(
        0,
        cursor,
        bytes((bs2_stdio_harness.ACK,)),
        "empty batch header ACK",
    )


def require_persisted_resources(state: Path, resources: tuple[Path, ...]) -> None:
    """Require each ordinary resource verbatim in saved BS2 RAM or flash."""
    memory = Memory(flash_size=2 * 1024 * 1024)
    memory.load_state(state)
    regions = (bytes(memory.ram), bytes(memory.flash))
    for resource in resources:
        payload = resource.read_bytes()
        if not payload or not any(payload in region for region in regions):
            raise RuntimeError(
                f"persisted BS2 state lacks exact payload for {resource.name}"
            )


def _program_speech_marker(program: Path) -> tuple[str, ...] | None:
    """Return the observed speech authority for a supplied external program."""
    return {
        "bsname.bns": BSNAME_SPEECH_MARKER,
        "calsort.bns": CALSORT_SPEECH_MARKER,
    }.get(program.name.lower())


def verify_through_stdio(
    rom: Path,
    state: Path,
    program: Path,
    *,
    persist: bool = False,
    resources: tuple[Path, ...] = (),
    expected_speech: tuple[str, ...] | None = None,
    require_return_key: bool = False,
) -> None:
    """Import and execute a program through the shipped CLI subprocess."""
    expected_cbar = expected_program_cbar(program.read_bytes())
    with BNSStdioProcess(
        rom,
        model="bs2",
        state=state,
        reset="cold",
    ) as process:
        bs2_stdio_harness.reach_stdio_editor_command_loop(process)
        speech_start = len(process.speech_names)

        bs2_stdio_harness.send_stdio_chord(process, O_CHORD)
        bs2_stdio_harness.send_stdio_chord(process, F_KEY)
        process.wait_for_speech_suffix(
            bs2_stdio_harness.FILE_COMMAND_PROMPT,
            "Enter file command prompt",
            timeout=60,
        )

        for file_path in (*resources, program):
            bs2_stdio_harness.receive_stdio_file(process, file_path)
        bs2_stdio_harness.send_stdio_chord(process, DOT5_CHORD)

        entry = bs2_stdio_harness.execute_selected_stdio_program(
            process,
            expected_cbar,
            expected_speech or _program_speech_marker(program),
            require_return_key=require_return_key,
        )
        phonemes = process.speech_names[speech_start:]
        if persist:
            process.request_stop(timeout=60)

    if persist and resources:
        require_persisted_resources(state, resources)

    for file_path in (*resources, program):
        print(f"imported: {file_path.name} ({file_path.stat().st_size} bytes)")
    print(
        f"entry: cycle={entry['cycle']} pc={entry['pc']:04X} "
        f"cbar={entry['cbar']:02X}"
    )
    if require_return_key:
        print("return-key: E-chord accepted and firmware ready")
    print("serial: ASCI1 ENQ/NAK; ASCI0 ENQ/NAK; YMODEM complete")
    print("phonemes:", " ".join(phonemes))


def verify_persisted_stdio_program(rom: Path, state: Path, program: Path) -> None:
    """Restart from saved flash and execute the program without retransferring it."""
    expected_cbar = expected_program_cbar(program.read_bytes())
    with BNSStdioProcess(
        rom,
        model="bs2",
        state=state,
    ) as process:
        process.wait_for_keyboard("ready", timeout=60)
        speech_start = len(process.speech_names)

        bs2_stdio_harness.send_stdio_chord(process, O_CHORD)
        bs2_stdio_harness.send_stdio_chord(process, F_KEY)
        process.wait_for_speech_suffix(
            bs2_stdio_harness.FILE_COMMAND_PROMPT,
            "persisted Enter file command prompt",
            timeout=60,
        )
        bs2_stdio_harness.send_stdio_chord(process, DOT5_CHORD)
        entry = bs2_stdio_harness.execute_selected_stdio_program(
            process,
            expected_cbar,
            _program_speech_marker(program),
        )
        phonemes = process.speech_names[speech_start:]
        process.request_stop(timeout=60)

    print(f"reloaded: {program.name} from persisted flash")
    print(
        f"reentry: cycle={entry['cycle']} pc={entry['pc']:04X} "
        f"cbar={entry['cbar']:02X}"
    )
    print("reloaded phonemes:", " ".join(phonemes))


def expected_program_cbar(program: bytes) -> int:
    """Derive the launch CBAR exactly as BS.ASM::_execute_program does."""
    if len(program) < 10 or program[2:6] != b"BNS\0":
        raise ValueError("external program lacks the BNS header")
    program_length = int.from_bytes(program[8:10], "little")
    rounded_length = program_length + 0x1FFF
    if rounded_length > 0xFFFF:
        return 0x11
    return ((rounded_length >> 8) & 0xF0) | 0x01


def run_until_program_entry(
    harness: BS2Harness,
    expected_cbar: int,
) -> tuple[int, int, int]:
    """Require the external-program launcher MMU and real entry point."""
    bns = harness.bns
    start_cycle = bns.cpu.cycle_count()
    while bns.cpu.cycle_count() - start_cycle < CYCLE_LIMIT:
        harness.advance()
        if bns.cpu.pc_watch_hits() and bns._pc_watch_cbar == expected_cbar:
            return bns._pc_watch_cycle, 0x1000, bns._pc_watch_cbar
    phonemes = bns.ssi263.get_phonemes(include_pauses=False)
    speech_tail = " ".join(phoneme.name for phoneme in phonemes[-80:])
    raise RuntimeError(
        f"external program entry not observed; pc={bns.cpu.reg(Reg.PC):04X} "
        f"cbar={bns.cpu.io_reg_peek(0x3A):02X} "
        f"entry_watch={bns.cpu.pc_watch_hits()} "
        f"entry_cbar={bns._pc_watch_cbar:02X} "
        f"expected_cbar={expected_cbar:02X} "
        f"speech_tail=[{speech_tail}]"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom", type=Path)
    parser.add_argument("state", type=Path)
    parser.add_argument("program", type=Path)
    parser.add_argument(
        "--resource",
        action="append",
        type=Path,
        default=[],
        help="import a required ordinary file before the external program",
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="verify through the shipped JSONL CLI process boundary",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="save the imported program and execute it from a fresh process",
    )
    parser.add_argument(
        "--expected-speech",
        nargs="+",
        metavar="PHONEME",
        help="exact phoneme suffix required before proving post-exit E-chord acceptance",
    )
    args = parser.parse_args()

    if args.persist and not args.stdio:
        parser.error("--persist requires --stdio")
    if args.stdio:
        verify_through_stdio(
            args.rom,
            args.state,
            args.program,
            persist=args.persist,
            resources=tuple(args.resource),
            expected_speech=(
                tuple(args.expected_speech) if args.expected_speech is not None else None
            ),
            require_return_key=args.expected_speech is not None,
        )
        if args.persist:
            verify_persisted_stdio_program(args.rom, args.state, args.program)
        return

    with redirect_stdout(io.StringIO()):
        harness = BS2Harness(
            args.rom,
            args.state,
            cycle_limit=CYCLE_LIMIT,
            serial_channel=1,
            trace_writes=0x414B0,
        )
        bns = harness.bns
        serial_output = harness.serial

        loaded_combyt = bns.memory.read(0x414B0)
        bns._arm_pc_watch(0x07F2)

        # A real blank BS2 must be hard-initialized by holding I-chord while
        # power is applied.  Keep it held until WARM0 reaches the linked
        # COMBYT initializer, then deliver the physical key-up edge.
        bns.keyboard.press(bs2_stdio_harness.COLD_RESET_CHORD)
        harness.run_until(
            lambda: bns.cpu.pc_watch_hits() > 0,
            "BS2 power-on hard-reset initializer",
            context=lambda: (
                f"combyt={bns.memory.read(0x414B0):02X},"
                f"cbr={bns.cpu.io_reg_peek(0x38):02X},"
                f"bbr={bns.cpu.io_reg_peek(0x39):02X},"
                f"cbar={bns.cpu.io_reg_peek(0x3A):02X}"
            ),
        )
        bns.keyboard.release()

        reach_editor_command_loop(harness)
        boot_context = (
            f"loaded_COMBYT={loaded_combyt:02X},"
            f"command_COMBYT={bns.memory.read(0x414B0):02X},"
            f"initializer_hits={bns.cpu.pc_watch_hits()},"
            f"initializer_cycle={bns._pc_watch_cycle}"
        )
        speech_start = len(bns.ssi263.phoneme_log)

        chord_phases: list[str] = []
        serial_event_cursor = 0
        for phase, chord in (("O", O_CHORD), ("f", F_KEY)):
            harness.chord(chord)
            harness.wait_for_key()
            chord_phases.append(f"{phase}=[{serial_output.format_events(serial_event_cursor)}]")
            serial_event_cursor = len(serial_output.events)

        harness.chord(bs2_stdio_harness.T_CHORD)
        t_delivered_cycle = bns.cpu.cycle_count()
        chord_phases.append(f"T=[{serial_output.format_events(serial_event_cursor)}]")
        serial_event_cursor = len(serial_output.events)
        probe_context = (
            f"{boot_context},T_delivered={t_delivered_cycle},"
            f"chord_phases=[{';'.join(chord_phases)}]"
        )
        serial_cursor, probe_traces = reject_disk_probes(harness, probe_context)
        chord_phases.append(f"disk_probes=[{serial_output.format_events(serial_event_cursor)}]")
        serial_event_cursor = len(serial_output.events)

        harness.chord(bs2_stdio_harness.R_KEY)
        harness.wait_for_key()
        chord_phases.append(f"r=[{serial_output.format_events(serial_event_cursor)}]")
        serial_event_cursor = len(serial_output.events)
        harness.chord(bs2_stdio_harness.Y_KEY)
        harness.wait_for_speech()
        chord_phases.append(f"y=[{serial_output.format_events(serial_event_cursor)}]")
        serial_event_cursor = len(serial_output.events)
        harness.chord(bs2_stdio_harness.E_CHORD)
        chord_phases.append(f"E=[{serial_output.format_events(serial_event_cursor)}]")
        transfer_ymodem(harness, serial_cursor, args.program)
        harness.run_until(
            lambda: (
                bns._command_loop_write_count > 0
                and bns.cpu.reg(Reg.PC) == 0xD657
            ),
            "BS2 editor command loop after YMODEM import",
        )

        for phase, chord in (("O-after-import", O_CHORD), ("f-after-import", F_KEY)):
            harness.chord(chord)
            harness.wait_for_key()
            chord_phases.append(
                f"{phase}=[{serial_output.format_events(serial_event_cursor)}]"
            )
            serial_event_cursor = len(serial_output.events)

        harness.chord(DOT5_CHORD)
        harness.wait_for_key()
        chord_phases.append(
            f"dot5-next-program=[{serial_output.format_events(serial_event_cursor)}]"
        )

        expected_cbar = expected_program_cbar(args.program.read_bytes())
        bns._arm_pc_watch(0x1000)
        harness.chord(X_CHORD)
        entry_cycle, entry_pc, entry_cbar = run_until_program_entry(
            harness,
            expected_cbar,
        )

    phonemes = bns.ssi263.get_phonemes(start=speech_start, include_pauses=False)
    print(f"imported: {args.program.name} ({args.program.stat().st_size} bytes)")
    print(f"entry: cycle={entry_cycle} pc={entry_pc:04X} cbar={entry_cbar:02X}")
    for trace in probe_traces:
        print(f"serial: {trace}")
    print("phonemes:", " ".join(phoneme.name for phoneme in phonemes))


if __name__ == "__main__":
    main()
