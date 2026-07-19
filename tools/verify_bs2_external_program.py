"""Import and execute a BS2 external program through the real firmware path."""

from __future__ import annotations

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path

from tools.bs2_harness import BS2Harness

CYCLE_LIMIT = 100_000_000

O_CHORD = 0x55
F_KEY = 0x0B
T_CHORD = 0x5E
R_KEY = 0x17
Y_KEY = 0x3D
E_CHORD = 0x51
X_CHORD = 0x6D

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


def is_flash_confirmation_prompt(names: list[str]) -> bool:
    """Return whether speech ends with the exact destructive-action confirmation."""
    prompt_size = len(FLASH_CONFIRMATION_PROMPT)
    return tuple(names[-prompt_size:]) == FLASH_CONFIRMATION_PROMPT


def reach_editor_command_loop(harness: BS2Harness) -> None:
    """Complete the real first-boot dialogue and reach the editor key loop."""
    bns = harness.bns
    harness.wait_for_key()
    if bns._bsp_command_loop_ready and bns.cpu.pc == 0xD657:
        return

    names = [
        phoneme.name
        for phoneme in bns.ssi263.get_phonemes(include_pauses=False)
    ]
    if bns.cpu.pc != FLASH_INITIALIZATION_PC or not is_flash_initialization_prompt(names):
        raise RuntimeError(
            f"unexpected BS2 boot wait; pc={bns.cpu.pc:04X} "
            f"speech_tail=[{' '.join(names[-40:])}]"
        )

    speech_cursor = len(bns.ssi263.phoneme_log)
    harness.chord(FLASH_INITIALIZATION_Y_KEY)
    harness.wait_for_key()
    if bns._bsp_command_loop_ready and bns.cpu.pc == 0xD657:
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

    speech_cursor = len(bns.ssi263.phoneme_log)
    harness.chord(FLASH_INITIALIZATION_Y_KEY)
    harness.run_until(
        lambda: bns._bsp_command_loop_ready and bns.cpu.pc == 0xD657,
        "BS2 editor command loop after flash initialization",
        context=lambda: (
            f"initializer_hits={bns.cpu.pc_watch_count},"
            f"initializer_cycle={bns.cpu.pc_watch_cycle},"
            f"cbr={bns.cpu.cbr:02X},bbr={bns.cpu.bbr:02X},"
            f"cbar={bns.cpu.cbar:02X} response_speech=["
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


def run_until_program_entry(harness: BS2Harness) -> tuple[int, int]:
    """Require the external-program launcher MMU and real entry point."""
    bns = harness.bns
    start_cycle = bns.cpu.cycle_count
    while bns.cpu.cycle_count - start_cycle < CYCLE_LIMIT:
        harness.advance(1)
        if bns.cpu.cbar == 0x11 and bns.cpu.pc in (0x1000, 0x100E):
            return bns.cpu.cycle_count, bns.cpu.pc
    raise RuntimeError(
        f"external program entry not observed; pc={bns.cpu.pc:04X} cbar={bns.cpu.cbar:02X}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom", type=Path)
    parser.add_argument("state", type=Path)
    parser.add_argument("program", type=Path)
    args = parser.parse_args()

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
        harness.wait_for_key()

        harness.chord(X_CHORD)
        entry_cycle, entry_pc = run_until_program_entry(harness)

    phonemes = bns.ssi263.get_phonemes(start=speech_start, include_pauses=False)
    print(f"imported: {args.program.name} ({args.program.stat().st_size} bytes)")
    print(f"entry: cycle={entry_cycle} pc={entry_pc:04X} cbar=11")
    for trace in probe_traces:
        print(f"serial: {trace}")
    print("phonemes:", " ".join(phoneme.name for phoneme in phonemes))


if __name__ == "__main__":
    main()
