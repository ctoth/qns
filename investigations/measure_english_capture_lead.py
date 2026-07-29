"""Measure SPBUF-write lead before exact English capture boundaries."""

from __future__ import annotations

from pathlib import Path
from types import MethodType

from qns.bns import BNS
from qns.paths import resolve_state_path

ROM = Path("roms/bns2000/BS2ENG.BNS")
STATE = resolve_state_path("flash.bin")
MAX_CYCLES = 100_000_000
BufferWrite = tuple[int, int, int, int]


def print_writes(label: str, writes: tuple[BufferWrite, ...]) -> None:
    print(f"{label}_count={len(writes)}")
    print(f"{label}_writer_pcs={sorted({pc for _, pc, _, _ in writes})}")
    for writer_pc in sorted({pc for _, pc, _, _ in writes}):
        writer_events = [
            (cycle, addr & 0xFFF, value)
            for cycle, pc, addr, value in writes
            if pc == writer_pc
        ]
        print(f"{label}_writer_{writer_pc:04X}={writer_events}")
    for cycle, pc, addr, value in writes[:12]:
        print(
            f"{label}_event="
            f"cycle:{cycle},pc:{pc:04X},offset:{addr & 0xFFF:03X},value:{value:02X}"
        )


def main() -> None:
    captures: list[tuple[str, int, tuple[BufferWrite, ...]]] = []
    buffer_writes: list[BufferWrite] = []
    capture_cycle = 0

    def capture_english(text: str) -> None:
        captures.append((text, capture_cycle, tuple(buffer_writes)))
        buffer_writes.clear()
        if len(captures) == 1:
            assert bns._input_driver is not None
            bns._input_driver.queue.put("n")

    bns = BNS(
        model="bs2",
        core="direct",
        stdin_device="jsonl",
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
            buffer_writes.append((cycle, pc, addr, value))
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
        write_cycles = [write[0] for write in writes]
        first_write = min(write_cycles) if write_cycles else None
        last_write = max(write_cycles) if write_cycles else None
        print(f"text={text!r}")
        print(f"capture_cycle={cycle}")
        print_writes("pre_capture", writes)
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
    print_writes("post_capture", tuple(buffer_writes))
    post_capture_cycles = [write[0] for write in buffer_writes]
    print(
        "first_post_capture_write_cycle="
        f"{min(post_capture_cycles) if post_capture_cycles else None}"
    )
    print(f"english_capture_armed={bns._english_capture_armed}")


if __name__ == "__main__":
    main()
