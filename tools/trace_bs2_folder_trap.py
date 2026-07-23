"""Trace the first BS2 transition from firmware code into high RAM/data."""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

from z180 import Reg

from qns.bns import BNS

Z180_ITC = 0x34
Z180_ITC_TRAP = 0x80


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom", type=Path)
    parser.add_argument("state", type=Path)
    args = parser.parse_args()

    bns = BNS(model="bs2", stdin_device="keyboard")
    bns.load_rom(args.rom)
    bns.load_state(args.state)

    accepted_keys = 0
    original_press = bns.keyboard.press
    original_execute_instruction = bns._execute_instruction
    recent: deque[
        tuple[
            int,
            int,
            int,
            int,
            int,
            int,
            int,
            int,
            tuple[int, ...],
            tuple[int, ...],
        ]
    ] = deque(maxlen=64)

    def traced_press(raw_key: int) -> None:
        nonlocal accepted_keys
        accepted_keys += 1
        print(f"[Trap trace] delivered key {accepted_keys}: raw=0x{raw_key:02X}")
        original_press(raw_key)

    def traced_execute_instruction(*, pump_inputs: bool = True) -> int:
        if accepted_keys < 2:
            return original_execute_instruction(pump_inputs=pump_inputs)

        pc = bns.cpu.reg(Reg.PC)
        cbr = bns.cpu.io_reg_peek(0x38)
        bbr = bns.cpu.io_reg_peek(0x39)
        cbar = bns.cpu.io_reg_peek(0x3A)
        sp = bns.cpu.reg(Reg.SP)
        ix = bns.cpu.reg(Reg.IX)
        physical = bns.cpu.mmu_translate(pc)
        stack_physical = bns.cpu.mmu_translate(sp)
        fetched = tuple(
            bns.memory.read(bns.cpu.mmu_translate((pc + offset) & 0xFFFF))
            for offset in range(8)
        )
        stack_bytes = tuple(
            bns.memory.read(bns.cpu.mmu_translate((sp + offset) & 0xFFFF))
            for offset in range(16)
        )

        recent.append(
            (
                pc,
                physical,
                sp,
                ix,
                stack_physical,
                cbr,
                bbr,
                cbar,
                fetched,
                stack_bytes,
            )
        )

        if pc >= 0xC000:
            print(
                "[Trap trace] stopping at first high RAM/data PC: "
                f"PC={pc:04X} physical={physical:05X}"
            )
            print("[Trap trace] preceding instruction-boundary frames:")
            for frame in recent:
                (
                    frame_pc,
                    frame_physical,
                    frame_sp,
                    frame_ix,
                    frame_stack_physical,
                    frame_cbr,
                    frame_bbr,
                    frame_cbar,
                    frame_bytes,
                    frame_stack,
                ) = frame
                byte_text = " ".join(f"{byte:02X}" for byte in frame_bytes)
                stack_text = " ".join(f"{byte:02X}" for byte in frame_stack)
                print(
                    f"  PC={frame_pc:04X} physical={frame_physical:05X} "
                    f"SP={frame_sp:04X} IX={frame_ix:04X} "
                    f"stack_physical={frame_stack_physical:05X} "
                    f"CBR={frame_cbr:02X} BBR={frame_bbr:02X} "
                    f"CBAR={frame_cbar:02X} bytes={byte_text} stack={stack_text}"
                )
            raise KeyboardInterrupt

        itc_before = bns.cpu.io_reg_peek(Z180_ITC)
        actual = original_execute_instruction(pump_inputs=pump_inputs)

        itc_after = bns.cpu.io_reg_peek(Z180_ITC)
        if not itc_before & Z180_ITC_TRAP and itc_after & Z180_ITC_TRAP:
            trap_pc = (bns.cpu.reg(Reg.PC) - 2) & 0xFFFF
            trap_cbr = bns.cpu.io_reg_peek(0x38)
            trap_bbr = bns.cpu.io_reg_peek(0x39)
            trap_cbar = bns.cpu.io_reg_peek(0x3A)
            trap_physical = bns.cpu.mmu_translate(trap_pc)
            trap_bytes = tuple(
                bns.memory.read(bns.cpu.mmu_translate((trap_pc + offset) & 0xFFFF))
                for offset in range(8)
            )
            print(
                f"[Trap trace] ITC.TRAP set: PC={trap_pc:04X} "
                f"physical={trap_physical:05X} CBR={trap_cbr:02X} "
                f"BBR={trap_bbr:02X} CBAR={trap_cbar:02X} "
                f"HICLK={bns.high_bank_latch:02X} "
                f"bytes={' '.join(f'{byte:02X}' for byte in trap_bytes)}"
            )
            print("[Trap trace] preceding Python pre-call frames:")
            for frame in recent:
                (
                    frame_pc,
                    frame_physical,
                    frame_sp,
                    frame_ix,
                    frame_stack_physical,
                    frame_cbr,
                    frame_bbr,
                    frame_cbar,
                    frame_bytes,
                    frame_stack,
                ) = frame
                byte_text = " ".join(f"{byte:02X}" for byte in frame_bytes)
                stack_text = " ".join(f"{byte:02X}" for byte in frame_stack)
                print(
                    f"  PC={frame_pc:04X} physical={frame_physical:05X} "
                    f"SP={frame_sp:04X} IX={frame_ix:04X} "
                    f"stack_physical={frame_stack_physical:05X} "
                    f"CBR={frame_cbr:02X} BBR={frame_bbr:02X} "
                    f"CBAR={frame_cbar:02X} bytes={byte_text} stack={stack_text}"
                )
            raise KeyboardInterrupt

        return actual

    bns.keyboard.press = traced_press
    bns._execute_instruction = traced_execute_instruction
    bns.run()


if __name__ == "__main__":
    main()
