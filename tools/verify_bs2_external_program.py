"""Import and execute a BS2 external program through the real firmware path."""

from __future__ import annotations

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path

from qns.memory import Memory
from tools.bs2_harness import BS2Harness
from tools.stdio_process import BNSStdioProcess

CYCLE_LIMIT = 100_000_000

O_CHORD = 0x55
F_KEY = 0x0B
T_CHORD = 0x5E
R_KEY = 0x17
Y_KEY = 0x3D
E_CHORD = 0x51
X_CHORD = 0x6D
DOT5_CHORD = 0x50
POWER_ON_INITIALIZE_CHORD = 0x4A

SOH = 0x01
STX = 0x02
EOT = 0x04
ACK = 0x06
NAK = 0x15
CRC_REQUEST = ord("C")
CPM_EOF = 0x1A

FLASH_INITIALIZATION_PC = 0x1BDA
FLASH_INITIALIZATION_Y_KEY = 0x3D
FLASH_INITIALIZATION_PROMPT = (
    "I",
    "N",
    "I",
    "SCH",
    "AE1",
    "L",
    "AH",
    "E1",
    "Z",
    "F",
    "L",
    "AE",
    "SCH",
    "S",
    "I",
    "S",
    "T",
    "EH",
    "M",
    "EH",
    "N",
    "T",
    "ER",
    "W",
    "AH",
    "E",
    "OU",
    "ER",
    "EH",
    "N",
)
FILE_INITIALIZATION_PROMPT = (
    "I",
    "N",
    "I",
    "SCH",
    "AE1",
    "L",
    "AH",
    "E1",
    "Z",
    "F",
    "AH",
    "E",
    "L",
    "S",
    "I",
    "S",
    "T",
    "EH",
    "M",
    "EH",
    "N",
    "T",
    "ER",
    "W",
    "AH",
    "E",
    "OU",
    "ER",
    "EH",
    "N",
)
FOLDER_INITIALIZATION_PROMPT = (
    "I",
    "N",
    "I",
    "SCH",
    "AE1",
    "L",
    "AH",
    "E1",
    "Z",
    "F",
    "O",
    "OU",
    "L",
    "D",
    "ER",
    "S",
    "I",
    "S",
    "T",
    "EH",
    "M",
    "EH",
    "N",
    "T",
    "ER",
    "W",
    "AH",
    "E",
    "OU",
    "ER",
    "EH",
    "N",
)
WIPEOUT_PROMPT = (
    "D",
    "I",
    "L",
    "E",
    "T",
    "AW",
    "LF",
    "D",
    "A",
    "E",
    "T",
    "UH1",
    "I",
    "N",
    "F",
    "AH",
    "E",
    "L",
    "EH",
    "R",
    "E",
    "UH1",
    "EH",
    "N",
    "T",
    "ER",
    "W",
    "AH",
    "E",
    "OU",
    "ER",
    "EH",
    "N",
)
FLASH_CONFIRMATION_PROMPT = (
    "AH",
    "ER",
    "YI",
    "U",
    "U",
    "SCH",
    "O",
    "ER",
    "EH",
    "N",
    "T",
    "ER",
    "W",
    "AH",
    "E",
    "OU",
    "ER",
    "EH",
    "N",
)
FILE_COMMAND_PROMPT = (
    "EH",
    "N",
    "T",
    "ER",
    "F",
    "AH",
    "E",
    "L",
    "K",
    "UH1",
    "M",
    "AE",
    "N",
    "D",
)
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


def crc16_xmodem(data: bytes) -> int:
    """Return the CRC-16/XMODEM value used by the firmware."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def ymodem_packet(block_number: int, payload: bytes, block_size: int) -> bytes:
    """Build one CRC-protected YMODEM packet."""
    if len(payload) != block_size:
        raise ValueError(f"payload is {len(payload)} bytes, expected {block_size}")
    marker = SOH if block_size == 128 else STX
    crc = crc16_xmodem(payload)
    return bytes((marker, block_number, 0xFF - block_number)) + payload + crc.to_bytes(2, "big")


def is_flash_initialization_prompt(names: list[str]) -> bool:
    """Return whether retained speech ends with the exact first-boot prompt."""
    prompt_size = len(FLASH_INITIALIZATION_PROMPT)
    return tuple(names[-prompt_size:]) == FLASH_INITIALIZATION_PROMPT


def is_file_initialization_prompt(names: list[str]) -> bool:
    """Return whether retained speech ends with the exact cold-reset prompt."""
    prompt_size = len(FILE_INITIALIZATION_PROMPT)
    return tuple(names[-prompt_size:]) == FILE_INITIALIZATION_PROMPT


def is_folder_initialization_prompt(names: list[str]) -> bool:
    """Return whether retained speech ends with the exact folder prompt."""
    prompt_size = len(FOLDER_INITIALIZATION_PROMPT)
    return tuple(names[-prompt_size:]) == FOLDER_INITIALIZATION_PROMPT


def is_wipeout_prompt(names: list[str]) -> bool:
    """Return whether retained speech ends with the exact file-area prompt."""
    prompt_size = len(WIPEOUT_PROMPT)
    return tuple(names[-prompt_size:]) == WIPEOUT_PROMPT


def is_flash_confirmation_prompt(names: list[str]) -> bool:
    """Return whether speech ends with the exact destructive-action confirmation."""
    prompt_size = len(FLASH_CONFIRMATION_PROMPT)
    return tuple(names[-prompt_size:]) == FLASH_CONFIRMATION_PROMPT


def reach_editor_command_loop(harness: BS2Harness) -> None:
    """Complete the real first-boot dialogue and reach the editor key loop."""
    bns = harness.bns
    harness.wait_for_key()
    if bns._command_loop_write_count > 0 and bns.cpu.pc == 0xD657:
        return

    names = [
        phoneme.name
        for phoneme in bns.ssi263.get_phonemes(include_pauses=False)
    ]
    file_initialization = is_file_initialization_prompt(names)
    flash_initialization = is_flash_initialization_prompt(names)
    folder_initialization = is_folder_initialization_prompt(names)
    wipeout = is_wipeout_prompt(names)
    if bns.cpu.pc != FLASH_INITIALIZATION_PC or not (
        file_initialization or flash_initialization or folder_initialization or wipeout
    ):
        raise RuntimeError(
            f"unexpected BS2 boot wait; pc={bns.cpu.pc:04X} "
            f"speech_tail=[{' '.join(names[-40:])}]"
        )

    if folder_initialization:
        harness.chord(FLASH_INITIALIZATION_Y_KEY)
        reach_editor_command_loop(harness)
        return

    speech_cursor = len(bns.ssi263.phoneme_log)
    harness.chord(FLASH_INITIALIZATION_Y_KEY)
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
    if bns._command_loop_write_count > 0 and bns.cpu.pc == 0xD657:
        return

    response_names = [
        phoneme.name
        for phoneme in bns.ssi263.get_phonemes(
            start=speech_cursor,
            include_pauses=False,
        )
    ]
    if bns.cpu.pc != FLASH_INITIALIZATION_PC or not is_flash_confirmation_prompt(
        response_names
    ):
        raise RuntimeError(
            f"unexpected flash confirmation wait; pc={bns.cpu.pc:04X} "
            f"response_speech=[{' '.join(response_names)}]"
        )

    harness.chord(FLASH_INITIALIZATION_Y_KEY)
    if wipeout:
        harness.run_until(
            lambda: bns._command_loop_write_count > 0 and bns.cpu.pc == 0xD657,
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
    harness.queue_serial(bytes((NAK,)))
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
    harness.queue_serial(bytes((NAK,)))
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
        bytes((CRC_REQUEST,)),
        "initial YMODEM CRC request",
    )
    harness.queue_serial(ymodem_packet(0, header, 128))
    cursor = harness.wait_for_serial(
        0,
        cursor,
        bytes((ACK, CRC_REQUEST)),
        "header ACK and data CRC request",
    )

    for block_number, offset in enumerate(range(0, len(program_data), 1_024), start=1):
        payload = program_data[offset : offset + 1_024].ljust(1_024, bytes((CPM_EOF,)))
        harness.queue_serial(ymodem_packet(block_number & 0xFF, payload, 1_024))
        cursor = harness.wait_for_serial(
            0,
            cursor,
            bytes((ACK,)),
            f"data block {block_number} ACK",
        )

    harness.queue_serial(bytes((EOT,)))
    cursor = harness.wait_for_serial(
        0,
        cursor,
        bytes((ACK, CRC_REQUEST)),
        "EOT ACK and batch CRC request",
    )
    harness.queue_serial(ymodem_packet(0, bytes(128), 128))
    harness.wait_for_serial(0, cursor, bytes((ACK,)), "empty batch header ACK")


def send_stdio_chord(
    process: BNSStdioProcess,
    chord: int,
    *,
    wait_ready: bool = True,
) -> None:
    """Deliver one exact chord and require firmware acceptance."""
    process.send_keyboard(chord=chord)
    process.wait_for_keyboard("accepted", chord=chord, timeout=60)
    if wait_ready:
        process.wait_for_keyboard("ready", timeout=60)


def reach_stdio_editor_command_loop(process: BNSStdioProcess) -> None:
    """Complete real first-boot prompts using speech and keyboard events only."""
    process.wait_for_keyboard(
        "accepted",
        chord=POWER_ON_INITIALIZE_CHORD,
        timeout=60,
    )
    responded_at = -1
    initialization_prompts = (
        FLASH_INITIALIZATION_PROMPT,
        FILE_INITIALIZATION_PROMPT,
        FOLDER_INITIALIZATION_PROMPT,
        WIPEOUT_PROMPT,
        FLASH_CONFIRMATION_PROMPT,
    )
    for _ in range(12):
        process.wait_for_keyboard("ready", timeout=60)
        names = process.speech_names
        prompt_seen = any(
            tuple(names[-len(prompt):]) == prompt
            for prompt in initialization_prompts
        )
        if not prompt_seen or len(names) == responded_at:
            return
        responded_at = len(names)
        process.send_keyboard(chord=FLASH_INITIALIZATION_Y_KEY)
        process.wait_for_keyboard(
            "accepted",
            chord=FLASH_INITIALIZATION_Y_KEY,
            timeout=60,
        )
    raise RuntimeError("BS2 initialization exceeded 12 firmware prompts")


def transfer_stdio_ymodem(
    process: BNSStdioProcess,
    cursor: int,
    program: Path,
) -> None:
    """Transfer one external program through structured ASCI0 events."""
    program_data = program.read_bytes()
    header = (
        program.name.encode("ascii")
        + b"\0"
        + str(len(program_data)).encode("ascii")
        + b"\0"
    ).ljust(128, b"\0")

    cursor = process.wait_for_serial(
        0,
        cursor,
        bytes((CRC_REQUEST,)),
        "initial YMODEM CRC request",
        timeout=60,
    )
    process.send_serial(0, ymodem_packet(0, header, 128))
    cursor = process.wait_for_serial(
        0,
        cursor,
        bytes((ACK, CRC_REQUEST)),
        "header ACK and data CRC request",
        timeout=60,
    )

    for block_number, offset in enumerate(range(0, len(program_data), 1_024), start=1):
        payload = program_data[offset : offset + 1_024].ljust(1_024, bytes((CPM_EOF,)))
        process.send_serial(
            0,
            ymodem_packet(block_number & 0xFF, payload, 1_024),
        )
        cursor = process.wait_for_serial(
            0,
            cursor,
            bytes((ACK,)),
            f"data block {block_number} ACK",
            timeout=60,
        )

    process.send_serial(0, bytes((EOT,)))
    cursor = process.wait_for_serial(
        0,
        cursor,
        bytes((ACK, CRC_REQUEST)),
        "EOT ACK and batch CRC request",
        timeout=60,
    )
    process.send_serial(0, ymodem_packet(0, bytes(128), 128))
    process.wait_for_serial(
        0,
        cursor,
        bytes((ACK,)),
        "empty batch header ACK",
        timeout=60,
    )


def receive_stdio_file(process: BNSStdioProcess, file_path: Path) -> None:
    """Receive one host file through the firmware's file-menu YMODEM path."""
    serial1_cursor = len(process.serial[1])
    serial0_cursor = len(process.serial[0])
    send_stdio_chord(process, T_CHORD, wait_ready=False)
    serial1_cursor = process.wait_for_serial(
        1,
        serial1_cursor,
        bytes((0x05,)),
        "ASCI1 disk-drive ENQ",
        timeout=60,
    )
    process.send_serial(1, bytes((NAK,)))
    serial0_cursor = process.wait_for_serial(
        0,
        serial0_cursor,
        bytes((0x05,)),
        "ASCI0 disk-drive ENQ",
        timeout=60,
    )
    process.send_serial(0, bytes((NAK,)))

    process.wait_for_keyboard("ready", timeout=60)
    send_stdio_chord(process, R_KEY)
    send_stdio_chord(process, Y_KEY, wait_ready=False)
    transfer_stdio_ymodem(process, serial0_cursor, file_path)
    process.wait_for_speech_suffix(
        FILE_COMMAND_PROMPT,
        "post-import Enter file command prompt",
        timeout=60,
    )
    process.wait_for_keyboard("ready", timeout=60)


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


def execute_selected_stdio_program(
    process: BNSStdioProcess,
    expected_cbar: int,
    speech_marker: tuple[str, ...] | None,
) -> dict[str, object]:
    """Execute the selected external program and prove native entry and speech."""
    process.arm_pc_watch(0x1000, timeout=60)
    process.send_keyboard(chord=X_CHORD)
    entry = process.wait_for_pc_watch(0x1000, timeout=60)
    if entry.get("cbar") != expected_cbar:
        raise RuntimeError(
            f"external program entered with CBAR {entry.get('cbar'):02X}; "
            f"expected {expected_cbar:02X}"
        )
    if speech_marker is not None:
        process.wait_for_speech_suffix(
            speech_marker,
            "external program speech",
            timeout=60,
        )
    return entry


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
) -> None:
    """Import and execute a program through the shipped CLI subprocess."""
    expected_cbar = expected_program_cbar(program.read_bytes())
    with BNSStdioProcess(
        rom,
        model="bs2",
        state=state,
        power_on_input=True,
    ) as process:
        process.send_keyboard(chord=POWER_ON_INITIALIZE_CHORD)
        reach_stdio_editor_command_loop(process)
        speech_start = len(process.speech_names)

        send_stdio_chord(process, O_CHORD)
        send_stdio_chord(process, F_KEY)
        process.wait_for_speech_suffix(
            FILE_COMMAND_PROMPT,
            "Enter file command prompt",
            timeout=60,
        )

        for file_path in (*resources, program):
            receive_stdio_file(process, file_path)
        send_stdio_chord(process, DOT5_CHORD)

        entry = execute_selected_stdio_program(
            process,
            expected_cbar,
            _program_speech_marker(program),
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

        send_stdio_chord(process, O_CHORD)
        send_stdio_chord(process, F_KEY)
        process.wait_for_speech_suffix(
            FILE_COMMAND_PROMPT,
            "persisted Enter file command prompt",
            timeout=60,
        )
        send_stdio_chord(process, DOT5_CHORD)
        entry = execute_selected_stdio_program(
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
    start_cycle = bns.cpu.cycle_count
    while bns.cpu.cycle_count - start_cycle < CYCLE_LIMIT:
        harness.advance()
        if bns.cpu.pc_watch_count and bns.cpu.pc_watch_cbar == expected_cbar:
            return bns.cpu.pc_watch_cycle, 0x1000, bns.cpu.pc_watch_cbar
    phonemes = bns.ssi263.get_phonemes(include_pauses=False)
    speech_tail = " ".join(phoneme.name for phoneme in phonemes[-80:])
    raise RuntimeError(
        f"external program entry not observed; pc={bns.cpu.pc:04X} "
        f"cbar={bns.cpu.cbar:02X} entry_watch={bns.cpu.pc_watch_count} "
        f"entry_cbar={bns.cpu.pc_watch_cbar:02X} "
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
        bns.cpu.watch_pc(0x07F2)

        # A real blank BS2 must be hard-initialized by holding I-chord while
        # power is applied.  Keep it held until WARM0 reaches the linked
        # COMBYT initializer, then deliver the physical key-up edge.
        bns.keyboard.press(POWER_ON_INITIALIZE_CHORD)
        harness.run_until(
            lambda: bns.cpu.pc_watch_count > 0,
            "BS2 power-on hard-reset initializer",
            context=lambda: (
                f"combyt={bns.memory.read(0x414B0):02X},"
                f"cbr={bns.cpu.cbr:02X},bbr={bns.cpu.bbr:02X},"
                f"cbar={bns.cpu.cbar:02X}"
            ),
        )
        bns.keyboard.release()

        reach_editor_command_loop(harness)
        boot_context = (
            f"loaded_COMBYT={loaded_combyt:02X},"
            f"command_COMBYT={bns.memory.read(0x414B0):02X},"
            f"initializer_hits={bns.cpu.pc_watch_count},"
            f"initializer_cycle={bns.cpu.pc_watch_cycle}"
        )
        speech_start = len(bns.ssi263.phoneme_log)

        chord_phases: list[str] = []
        serial_event_cursor = 0
        for phase, chord in (("O", O_CHORD), ("f", F_KEY)):
            harness.chord(chord)
            harness.wait_for_key()
            chord_phases.append(f"{phase}=[{serial_output.format_events(serial_event_cursor)}]")
            serial_event_cursor = len(serial_output.events)

        bns.cpu.reset_asci_debug()
        harness.chord(T_CHORD)
        t_delivered_cycle = bns.cpu.cycle_count
        chord_phases.append(f"T=[{serial_output.format_events(serial_event_cursor)}]")
        serial_event_cursor = len(serial_output.events)
        probe_context = (
            f"{boot_context},T_delivered={t_delivered_cycle},"
            f"chord_phases=[{';'.join(chord_phases)}]"
        )
        serial_cursor, probe_traces = reject_disk_probes(harness, probe_context)
        chord_phases.append(f"disk_probes=[{serial_output.format_events(serial_event_cursor)}]")
        serial_event_cursor = len(serial_output.events)

        harness.chord(R_KEY)
        harness.wait_for_key()
        chord_phases.append(f"r=[{serial_output.format_events(serial_event_cursor)}]")
        serial_event_cursor = len(serial_output.events)
        harness.chord(Y_KEY)
        harness.wait_for_speech()
        chord_phases.append(f"y=[{serial_output.format_events(serial_event_cursor)}]")
        serial_event_cursor = len(serial_output.events)
        harness.chord(E_CHORD)
        chord_phases.append(f"E=[{serial_output.format_events(serial_event_cursor)}]")
        transfer_ymodem(harness, serial_cursor, args.program)
        harness.run_until(
            lambda: bns._command_loop_write_count > 0 and bns.cpu.pc == 0xD657,
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
        bns.cpu.watch_pc(0x1000)
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
