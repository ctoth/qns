"""Trace the BS2 status-menu wait and bq2010 transaction."""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path

from qns.bns import BNS

CYCLE_LIMIT = 30_000_000
EXPECTED_COMMANDS = [0x03, 0x05, 0x01]
EXPECTED_SPEECH_SUFFIX = [
    0x23, 0x19, 0x38,  # one
    0x01, 0x2C, 0x18, 0x38, 0x25, 0x1D, 0x0B, 0x25,  # hundred
    0x27, 0x1C, 0x30, 0x0A, 0x38, 0x28,  # percent
    0x38, 0x0E, 0x28,  # not
    0x28, 0x32, 0x0E, 0x1C, 0x25, 0x31, 0x07, 0x38, 0x26,  # charging
]


def physical_address(logical: int, cbr: int, bbr: int, cbar: int) -> int:
    """Apply the Z180 core's 4 KiB-page MMU mapping."""
    page = logical >> 12
    physical_page = page
    if page >= (cbar & 0x0F):
        physical_page += cbr if page >= (cbar >> 4) else bbr
    return ((physical_page << 12) & 0xFFFFF) | (logical & 0x0FFF)


def run_until(bns: BNS, predicate: Callable[[], bool]) -> None:
    """Advance all timed devices until the predicate becomes true."""
    start_cycle = bns.cpu.cycle_count
    while not predicate():
        if bns.cpu.cycle_count - start_cycle >= CYCLE_LIMIT:
            commands = " ".join(f"{value:02X}" for value in bns.gas_gauge.command_log)
            raise RuntimeError(
                f"condition not reached within {CYCLE_LIMIT:,} cycles; "
                f"cycle={bns.cpu.cycle_count} pc={bns.cpu.pc:04X} commands=[{commands}]"
            )
        bns.cpu.run(1_000)
        cycle = bns.cpu.cycle_count
        bns.ssi263.set_cycle_count(cycle)
        bns.ssi263.check_pending_irq(cycle)


def deliver_chord(bns: BNS, chord: int) -> None:
    """Deliver one raw chord through both acknowledged keyboard edges."""
    bns.keyboard.press(chord)
    run_until(bns, lambda: not bns.keyboard.latched)
    bns.keyboard.release()
    run_until(bns, lambda: not bns.keyboard.latched)


def run_until_stable_key_wait(bns: BNS) -> None:
    """Reach a halted wait that remains after all pending speech work runs."""
    start_cycle = bns.cpu.cycle_count
    while bns.cpu.cycle_count - start_cycle < CYCLE_LIMIT:
        bns.cpu.run(1_000)
        cycle = bns.cpu.cycle_count
        bns.ssi263.set_cycle_count(cycle)
        bns.ssi263.check_pending_irq(cycle)
        if bns.ssi263._pending_irq_cycle is not None or not bns.cpu.halted:
            continue

        candidate_pc = bns.cpu.pc
        candidate_phonemes = len(bns.ssi263.phoneme_log)
        bns.cpu.run(1_000)
        cycle = bns.cpu.cycle_count
        bns.ssi263.set_cycle_count(cycle)
        bns.ssi263.check_pending_irq(cycle)
        if (
            bns.ssi263._pending_irq_cycle is None
            and bns.cpu.halted
            and bns.cpu.pc == candidate_pc
            and len(bns.ssi263.phoneme_log) == candidate_phonemes
        ):
            return
    raise RuntimeError(f"stable key wait not reached within {CYCLE_LIMIT:,} cycles")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom", type=Path)
    parser.add_argument("state", type=Path)
    args = parser.parse_args()

    captured_output = io.StringIO()
    with redirect_stdout(captured_output):
        bns = BNS(model="bs2")
        bns.load_rom(args.rom)
        bns.load_state(args.state)
        phonemes: list[tuple[int, str]] = []
        bns.ssi263.set_phoneme_callback(lambda code, name: phonemes.append((code, name)))

        run_until(
            bns,
            lambda: bns._bsp_command_loop_ready and bns.cpu.pc == 0xD657,
        )
        phonemes.clear()
        print(
            f"post-boot gauge: high={int(bns.gas_gauge._line_high)} "
            f"awaiting_break={int(bns.gas_gauge._awaiting_break)} "
            f"break={bns.gas_gauge._break_cycles} bits={bns.gas_gauge._command_bits}",
            file=sys.stderr,
        )
        bns.gas_gauge.command_log.clear()
        gauge_edges: list[tuple[int, bool]] = []
        original_write_line = bns.gas_gauge.write_line

        def trace_gauge_line(high: bool, cycle: int) -> None:
            gauge_edges.append((cycle, high))
            original_write_line(high, cycle)

        bns.gas_gauge.write_line = trace_gauge_line
        deliver_chord(bns, 0x4C)
        run_until_stable_key_wait(bns)
        menu_wait_cycle = bns.cpu.cycle_count
        menu_wait_pc = bns.cpu.pc
        mapped_pc = physical_address(
            menu_wait_pc,
            bns.cpu.cbr,
            bns.cpu.bbr,
            bns.cpu.cbar,
        )
        nearby = bytes(bns.memory.read((mapped_pc + offset) & 0xFFFFF) for offset in range(-8, 8))
        print(
            f"candidate wait: cycle={menu_wait_cycle} pc={menu_wait_pc:04X} "
            f"physical={mapped_pc:05X} phonemes={len(phonemes)} "
            f"bytes={nearby.hex(' ')}",
            file=sys.stderr,
        )

        deliver_chord(bns, 0x29)
        try:
            run_until(bns, lambda: len(bns.gas_gauge.command_log) >= len(EXPECTED_COMMANDS))
        except RuntimeError:
            print(
                "gauge edges:",
                " ".join(f"{cycle}:{int(high)}" for cycle, high in gauge_edges[:40]),
                file=sys.stderr,
            )
            raise
        run_until_stable_key_wait(bns)

        if bns.gas_gauge.command_log != EXPECTED_COMMANDS:
            raise RuntimeError(f"unexpected bq2010 commands: {bns.gas_gauge.command_log}")
        non_pause_codes = [code for code, _ in phonemes if code]
        if non_pause_codes[-len(EXPECTED_SPEECH_SUFFIX):] != EXPECTED_SPEECH_SUFFIX:
            raise RuntimeError(
                "battery speech does not end with 'one hundred percent not charging'"
            )

    print(f"menu wait: cycle={menu_wait_cycle} pc={menu_wait_pc:04X}")
    print("commands:", " ".join(f"{value:02X}" for value in bns.gas_gauge.command_log))
    print("phoneme codes:", " ".join(f"{code:02X}" for code, _ in phonemes))
    print("phoneme names:", " ".join(name for _, name in phonemes))


if __name__ == "__main__":
    main()
