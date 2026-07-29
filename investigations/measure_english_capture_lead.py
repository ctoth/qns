"""Measure SPBUF-write lead before exact English capture boundaries."""

from __future__ import annotations

from pathlib import Path
from types import MethodType

from qns.bns import BNS

ROM = Path("roms/bns2000/BS2ENG.BNS")
STATE = Path("flash.bin")
MAX_CYCLES = 100_000_000


def main() -> None:
    captures: list[tuple[str, int, tuple[int, ...]]] = []
    buffer_write_cycles: list[int] = []
    capture_cycle = 0

    def capture_english(text: str) -> None:
        captures.append((text, capture_cycle, tuple(buffer_write_cycles)))
        buffer_write_cycles.clear()

    bns = BNS(
        model="bs2",
        core="direct",
        stdin_device=None,
        pc_disk_dir=Path("."),
        english_callback=capture_english,
    )
    bns.load_rom(ROM)
    if STATE.exists():
        bns.load_state(STATE)
    else:
        print(f"State absent; using initialized RAM without saving: {STATE}")

    boundary = bns._english_boundary
    assert boundary is not None
    buffer_page_offset = boundary.spbuf & 0xFFF

    original_observe_write = bns._observe_write

    def observe_write(
        _self: BNS,
        addr: int,
        value: int,
        *,
        pc: int,
        cycle: int,
    ) -> None:
        offset = addr & 0xFFF
        if buffer_page_offset <= offset < buffer_page_offset + 0x100:
            buffer_write_cycles.append(cycle)
        original_observe_write(addr, value, pc=pc, cycle=cycle)

    bns._observe_write = MethodType(observe_write, bns)

    original_capture_boundary = bns._capture_english_boundary

    def capture_boundary(_self: BNS, discovered_boundary) -> None:
        nonlocal capture_cycle
        capture_cycle = bns.cpu.cycle_count()
        original_capture_boundary(discovered_boundary)

    bns._capture_english_boundary = MethodType(capture_boundary, bns)
    bns.run(max_cycles=MAX_CYCLES)

    print(f"Valid English captures: {len(captures)}")
    for text, cycle, writes in captures:
        first_write = min(writes) if writes else None
        last_write = max(writes) if writes else None
        print(f"text={text!r}")
        print(f"capture_cycle={cycle}")
        print(f"buffer_writes={len(writes)}")
        print(f"first_write_cycle={first_write}")
        print(f"last_write_cycle={last_write}")
        print(
            "first_write_lead="
            f"{cycle - first_write if first_write is not None else None}"
        )
        print(
            "last_write_lead="
            f"{cycle - last_write if last_write is not None else None}"
        )


if __name__ == "__main__":
    main()
