"""Trace the BS2 status-menu wait and bq2010 transaction."""

from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

from z180 import Reg

from tools.bs2_harness import BS2Harness

CYCLE_LIMIT = 30_000_000
EXPECTED_COMMANDS = [0x03, 0x05, 0x01]
EXPECTED_SPEECH_SUFFIX = [
    0x23,
    0x19,
    0x38,  # one
    0x01,
    0x2C,
    0x18,
    0x38,
    0x25,
    0x1D,
    0x0B,
    0x25,  # hundred
    0x27,
    0x1C,
    0x30,
    0x0A,
    0x38,
    0x28,  # percent
    0x38,
    0x0E,
    0x28,  # not
    0x28,
    0x32,
    0x0E,
    0x1C,
    0x25,
    0x31,
    0x07,
    0x38,
    0x26,  # charging
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom", type=Path)
    parser.add_argument("state", type=Path)
    args = parser.parse_args()

    captured_output = io.StringIO()
    with redirect_stdout(captured_output):
        harness = BS2Harness(args.rom, args.state, cycle_limit=CYCLE_LIMIT)
        bns = harness.bns

        harness.run_until(
            lambda: (
                bns._command_loop_write_count > 0
                and bns.cpu.reg(Reg.PC) == 0xD657
            ),
            "BS2 editor command loop",
        )
        speech_start = len(bns.ssi263.phoneme_log)
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
        harness.chord(0x4C)
        harness.wait_for_key()
        menu_wait_cycle = bns.cpu.cycle_count()
        menu_wait_pc = bns.cpu.reg(Reg.PC)
        mapped_pc = bns.cpu.mmu_translate(menu_wait_pc)
        nearby = bytes(bns.memory.read((mapped_pc + offset) & 0xFFFFF) for offset in range(-8, 8))
        print(
            f"candidate wait: cycle={menu_wait_cycle} pc={menu_wait_pc:04X} "
            f"physical={mapped_pc:05X} "
            f"phonemes={len(bns.ssi263.phoneme_log) - speech_start} "
            f"bytes={nearby.hex(' ')}",
            file=sys.stderr,
        )

        harness.chord(0x29)
        try:
            harness.run_until(
                lambda: len(bns.gas_gauge.command_log) >= len(EXPECTED_COMMANDS),
                "bq2010 command sequence",
                context=lambda: (
                    "commands=["
                    + " ".join(f"{value:02X}" for value in bns.gas_gauge.command_log)
                    + "]"
                ),
            )
        except RuntimeError:
            print(
                "gauge edges:",
                " ".join(f"{cycle}:{int(high)}" for cycle, high in gauge_edges[:40]),
                file=sys.stderr,
            )
            raise
        harness.wait_for_key()

        if bns.gas_gauge.command_log != EXPECTED_COMMANDS:
            raise RuntimeError(f"unexpected bq2010 commands: {bns.gas_gauge.command_log}")
        phonemes = bns.ssi263.get_phonemes(start=speech_start)
        non_pause_codes = [phoneme.code for phoneme in phonemes if phoneme.code]
        if non_pause_codes[-len(EXPECTED_SPEECH_SUFFIX) :] != EXPECTED_SPEECH_SUFFIX:
            raise RuntimeError(
                "battery speech does not end with 'one hundred percent not charging'"
            )

    print(f"menu wait: cycle={menu_wait_cycle} pc={menu_wait_pc:04X}")
    print("commands:", " ".join(f"{value:02X}" for value in bns.gas_gauge.command_log))
    print("phoneme codes:", " ".join(f"{phoneme.code:02X}" for phoneme in phonemes))
    print("phoneme names:", " ".join(phoneme.name for phoneme in phonemes))


if __name__ == "__main__":
    main()
