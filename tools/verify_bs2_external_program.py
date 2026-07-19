"""Import and execute a BS2 external program through the real firmware path."""

from __future__ import annotations

import argparse
import io
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path

from qns.bns import BNS

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


def advance(bns: BNS, cycles: int = 1_000) -> None:
    """Advance the CPU and the timed SSI-263 device together."""
    bns.cpu.run(cycles)
    current_cycle = bns.cpu.cycle_count
    bns.ssi263.set_cycle_count(current_cycle)
    bns.ssi263.check_pending_irq(current_cycle)


def run_until(bns: BNS, predicate: Callable[[], bool], description: str) -> None:
    """Run until a condition is true or the bounded verifier fails."""
    start_cycle = bns.cpu.cycle_count
    while not predicate():
        if bns.cpu.cycle_count - start_cycle >= CYCLE_LIMIT:
            raise RuntimeError(
                f"{description} not reached within {CYCLE_LIMIT:,} cycles; "
                f"cycle={bns.cpu.cycle_count} pc={bns.cpu.pc:04X}"
            )
        advance(bns)


def deliver_chord(bns: BNS, chord: int) -> None:
    """Deliver one raw chord through acknowledged key-down and key-up edges."""
    bns.keyboard.press(chord)
    run_until(bns, lambda: not bns.keyboard.latched, f"key-down acknowledgment for {chord:02X}")
    bns.keyboard.release()
    run_until(bns, lambda: not bns.keyboard.latched, f"key-up acknowledgment for {chord:02X}")


def run_until_stable_key_wait(bns: BNS) -> None:
    """Wait until firmware is halted with no pending speech work."""
    start_cycle = bns.cpu.cycle_count
    while bns.cpu.cycle_count - start_cycle < CYCLE_LIMIT:
        advance(bns)
        if bns.ssi263._pending_irq_cycle is not None or not bns.cpu.halted:
            continue

        candidate_pc = bns.cpu.pc
        candidate_phonemes = len(bns.ssi263.phoneme_log)
        advance(bns)
        if (
            bns.ssi263._pending_irq_cycle is None
            and bns.cpu.halted
            and bns.cpu.pc == candidate_pc
            and len(bns.ssi263.phoneme_log) == candidate_phonemes
        ):
            return
    raise RuntimeError(f"stable key wait not reached within {CYCLE_LIMIT:,} cycles")


def run_until_speech_idle(bns: BNS) -> None:
    """Wait for a prompt to finish even when its key loop does not HALT."""
    start_cycle = bns.cpu.cycle_count
    while bns.cpu.cycle_count - start_cycle < CYCLE_LIMIT:
        advance(bns)
        if bns.ssi263._pending_irq_cycle is not None:
            continue

        candidate_phonemes = len(bns.ssi263.phoneme_log)
        advance(bns, 100_000)
        if (
            bns.ssi263._pending_irq_cycle is None
            and len(bns.ssi263.phoneme_log) == candidate_phonemes
        ):
            return
    raise RuntimeError(f"speech did not settle within {CYCLE_LIMIT:,} cycles")


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


def queue_serial(bns: BNS, data: bytes) -> None:
    """Make host bytes available to the selected ASCI receive callback."""
    for byte in data:
        bns._serial_input_queue.put(byte)


def format_asci_state(bns: BNS, channel: int) -> str:
    """Format one side-effect-free native ASCI diagnostic snapshot."""
    state = bns.cpu.asci_debug_state(channel)
    return (
        f"asci{channel}=stat:{state['status']:02X},bits:{state['rx_bits_remaining']},"
        f"fifo:{state['rx_fifo_depth']},irq:{int(state['irq_pending'])},"
        f"div:{state['brg_divisor']},frame:{state['frame_bits']}"
    )


def wait_for_firmware_receive(bns: BNS, channel: int, description: str) -> str:
    """Trace one host byte through callback, frame, IRQ, and firmware ISR drain."""
    start_cycle = bns.cpu.cycle_count
    configured = bns.cpu.asci_debug_state(channel)
    frame_cycle_bound = (
        16 * int(configured["brg_divisor"]) * (int(configured["frame_bits"]) + 2)
    )
    trace_cycle_limit = max(100_000, frame_cycle_bound)
    events: list[str] = []
    callback_seen = False
    shift_seen = False
    frame_seen = False
    irq_seen = False

    while bns.cpu.cycle_count - start_cycle < trace_cycle_limit:
        state = bns.cpu.asci_debug_state(channel)
        cycle = bns.cpu.cycle_count
        pc = bns.cpu.pc

        if not callback_seen and bns._serial_input_queue.empty():
            callback_seen = True
            events.append(f"callback@{cycle}/pc={pc:04X}")
        if callback_seen and not shift_seen and state["rx_bits_remaining"]:
            shift_seen = True
            events.append(
                f"shift@{cycle}/pc={pc:04X}/bits={state['rx_bits_remaining']}"
            )
        if shift_seen and not frame_seen and (
            state["status"] & 0x80 or state["rx_fifo_depth"]
        ):
            frame_seen = True
            events.append(
                f"frame@{cycle}/pc={pc:04X}/fifo={state['rx_fifo_depth']}"
            )
        if frame_seen and not irq_seen and state["irq_pending"]:
            irq_seen = True
            events.append(f"irq@{cycle}/pc={pc:04X}")
        if frame_seen and not (state["status"] & 0x80) and not state["rx_fifo_depth"]:
            events.append(f"drain@{cycle}/pc={pc:04X}")
            return f"{description}:" + ",".join(events)

        advance(bns, 1)

    raise RuntimeError(
        f"{description} did not cross the firmware receive path within "
        f"{trace_cycle_limit:,} cycles; events={','.join(events)} "
        f"{format_asci_state(bns, channel)} pc={bns.cpu.pc:04X}"
    )


def wait_for_serial(
    bns: BNS,
    output: io.BytesIO,
    cursor: int,
    expected: bytes,
    description: str,
    context: str = "",
) -> int:
    """Wait for an exact protocol response and return the new output cursor."""
    start_cycle = bns.cpu.cycle_count
    while bns.cpu.cycle_count - start_cycle < CYCLE_LIMIT:
        data = output.getvalue()
        offset = data.find(expected, cursor)
        if offset >= 0:
            return offset + len(expected)
        advance(bns)
    tail = output.getvalue()[cursor:]
    phonemes = bns.ssi263.get_phonemes(include_pauses=False)
    speech_tail = " ".join(phoneme.name for phoneme in phonemes[-80:])
    raise RuntimeError(
        f"{description} not received within {CYCLE_LIMIT:,} cycles; "
        f"pc={bns.cpu.pc:04X} cbr={bns.cpu.cbr:02X} bbr={bns.cpu.bbr:02X} "
        f"cbar={bns.cpu.cbar:02X} serial_tail={tail[-32:].hex(' ')} "
        f"{format_asci_state(bns, 0)} {format_asci_state(bns, 1)} "
        f"context=[{context}] speech_tail=[{speech_tail}]"
    )


def reject_disk_probes(bns: BNS, output: io.BytesIO) -> tuple[int, list[str]]:
    """Reject the firmware's channel-1/channel-0 disk-drive probes."""
    traces: list[str] = []
    cursor = wait_for_serial(bns, output, 0, bytes((0x05,)), "ASCI1 disk-drive ENQ")
    queue_serial(bns, bytes((NAK,)))
    traces.append(wait_for_firmware_receive(bns, 1, "ASCI1 NAK"))

    bns.stdin_device = "serial0"
    bns.serial_output_channel = 0
    cursor = wait_for_serial(
        bns,
        output,
        cursor,
        bytes((0x05,)),
        "ASCI0 disk-drive ENQ",
        context="; ".join(traces),
    )
    queue_serial(bns, bytes((NAK,)))
    traces.append(wait_for_firmware_receive(bns, 0, "ASCI0 NAK"))
    return cursor, traces


def transfer_ymodem(bns: BNS, output: io.BytesIO, cursor: int, program: Path) -> None:
    """Send one file and an empty batch terminator to the firmware receiver."""
    program_data = program.read_bytes()
    header = program.name.encode("ascii") + b"\0" + str(len(program_data)).encode("ascii") + b"\0"
    header = header.ljust(128, b"\0")

    cursor = wait_for_serial(
        bns,
        output,
        cursor,
        bytes((CRC_REQUEST,)),
        "initial YMODEM CRC request",
    )
    queue_serial(bns, ymodem_packet(0, header, 128))
    cursor = wait_for_serial(
        bns,
        output,
        cursor,
        bytes((ACK, CRC_REQUEST)),
        "header ACK and data CRC request",
    )

    for block_number, offset in enumerate(range(0, len(program_data), 1_024), start=1):
        payload = program_data[offset:offset + 1_024].ljust(1_024, bytes((CPM_EOF,)))
        queue_serial(bns, ymodem_packet(block_number & 0xFF, payload, 1_024))
        cursor = wait_for_serial(
            bns,
            output,
            cursor,
            bytes((ACK,)),
            f"data block {block_number} ACK",
        )

    queue_serial(bns, bytes((EOT,)))
    cursor = wait_for_serial(
        bns,
        output,
        cursor,
        bytes((ACK, CRC_REQUEST)),
        "EOT ACK and batch CRC request",
    )
    queue_serial(bns, ymodem_packet(0, bytes(128), 128))
    wait_for_serial(bns, output, cursor, bytes((ACK,)), "empty batch header ACK")


def run_until_program_entry(bns: BNS) -> tuple[int, int]:
    """Require the external-program launcher MMU and real entry point."""
    start_cycle = bns.cpu.cycle_count
    while bns.cpu.cycle_count - start_cycle < CYCLE_LIMIT:
        advance(bns, 1)
        if bns.cpu.cbar == 0x11 and bns.cpu.pc in (0x1000, 0x100E):
            return bns.cpu.cycle_count, bns.cpu.pc
    raise RuntimeError(
        f"external program entry not observed; pc={bns.cpu.pc:04X} "
        f"cbar={bns.cpu.cbar:02X}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom", type=Path)
    parser.add_argument("state", type=Path)
    parser.add_argument("program", type=Path)
    args = parser.parse_args()

    with redirect_stdout(io.StringIO()):
        serial_output = io.BytesIO()
        bns = BNS(
            model="bs2",
            stdin_device="serial1",
            serial_output=serial_output,
            serial_output_channel=1,
        )
        bns.load_rom(args.rom)
        bns.load_state(args.state)

        run_until(
            bns,
            lambda: bns._bsp_command_loop_ready and bns.cpu.pc == 0xD657,
            "BS2 editor command loop",
        )
        speech_start = len(bns.ssi263.phoneme_log)

        for chord in (O_CHORD, F_KEY, T_CHORD, R_KEY):
            deliver_chord(bns, chord)
            run_until_stable_key_wait(bns)
        deliver_chord(bns, Y_KEY)
        run_until_speech_idle(bns)
        deliver_chord(bns, E_CHORD)

        serial_cursor, probe_traces = reject_disk_probes(bns, serial_output)
        transfer_ymodem(bns, serial_output, serial_cursor, args.program)
        run_until_stable_key_wait(bns)

        deliver_chord(bns, X_CHORD)
        entry_cycle, entry_pc = run_until_program_entry(bns)

    phonemes = bns.ssi263.get_phonemes(start=speech_start, include_pauses=False)
    print(f"imported: {args.program.name} ({args.program.stat().st_size} bytes)")
    print(f"entry: cycle={entry_cycle} pc={entry_pc:04X} cbar=11")
    for trace in probe_traces:
        print(f"serial: {trace}")
    print("phonemes:", " ".join(phoneme.name for phoneme in phonemes))


if __name__ == "__main__":
    main()
