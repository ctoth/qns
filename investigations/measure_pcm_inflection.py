"""Locate the firmware voice-inflection flag and trace its startup effect."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from qns.bns import BNS
from qns.loader import find_voice_inflection_flag, load_firmware
from qns.ssi263 import SSI263State

ROM = Path("roms/bns2000/BS2ENG.BNS")
MAX_CYCLES = 100_000_000
COMMON_CBR = 0x34

def trace_with_flag(flag: int, physical_flag: int) -> tuple[SSI263State, ...]:
    """Run the fresh startup with one explicit _VIFLAG value."""
    states: list[SSI263State] = []

    class CaptureBackend:
        def play(self, state: SSI263State) -> None:
            states.append(state)

        def realtime_lead_seconds(self) -> float:
            return 0.0

    bns = BNS(
        model="bs2",
        core="direct",
        pc_disk_dir=Path("."),
        english_callback=lambda text: print(f"english={text!r}"),
    )
    bns.load_rom(ROM)
    bns.memory.write(physical_flag, flag)
    bns.ssi263.set_synth(CaptureBackend())
    bns.run(max_cycles=MAX_CYCLES)
    return tuple(states)


def main() -> None:
    firmware = load_firmware(ROM).data
    physical_flag = find_voice_inflection_flag(firmware)
    if physical_flag is None:
        raise RuntimeError("DOPITCH voice-inflection flag not found")
    logical_flag = physical_flag - (COMMON_CBR << 12)
    print(f"logical_voice_inflection_flag=0x{logical_flag:04X}")
    print(f"physical_voice_inflection_flag=0x{physical_flag:05X}")
    for flag in (0, 1):
        states = trace_with_flag(flag, physical_flag)
        initialized = [state for state in states if state.amplitude > 0]
        inflections = dict(sorted(Counter(
            state.inflection for state in initialized
        ).items()))
        print(
            f"flag={flag},events={len(states)},"
            f"inflections={inflections}"
        )


if __name__ == "__main__":
    main()
