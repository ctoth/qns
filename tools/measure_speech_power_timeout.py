"""Measure firmware speech-power idle timing against exact z-core events."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from qns.bns import BNS
from qns.clock import HD64180_PHI_HZ


@dataclass(frozen=True)
class Measurement:
    """One live-ROM speech-power timeout measurement."""

    last_phoneme_cycle: int
    power_off_cycle: int
    clock_hz: int

    @property
    def elapsed_cycles(self) -> int:
        return self.power_off_cycle - self.last_phoneme_cycle

    @property
    def elapsed_seconds(self) -> float:
        return self.elapsed_cycles / self.clock_hz


class SpeechPowerProbe(BNS):
    """BNS variant retaining exact I/O events needed by the experiment."""

    def __init__(self, *, clock: int = HD64180_PHI_HZ) -> None:
        super().__init__(clock=clock, core="direct", model="bsp")
        self.last_phoneme_cycle: int | None = None
        self.power_off_cycle: int | None = None
        self.power_events: list[tuple[int, int, int]] = []
        self.ssi263.set_phoneme_callback(self._record_phoneme)

    def _record_phoneme(self, _code: int, _name: str) -> None:
        self.last_phoneme_cycle = self.ssi263.current_cycle

    def _process_memory_events(self) -> None:
        """Retain exact power events while preserving QNS event processing."""
        for event in self.cpu.drain_events():
            if event["kind"] == "mem_write":
                self._observe_write(
                    event["phys"],
                    event["value"],
                    pc=event["pc"],
                    cycle=event["cycle"],
                )
            elif event["kind"] == "io_write":
                port = event["port"] & 0xFF
                if self.ssi263.base_port <= port < self.ssi263.base_port + 5:
                    self.ssi263.confirm_write_cycle(port, event["value"], event["cycle"])
                if port == self.PORT_SPEECH_POWER:
                    self.power_events.append((event["cycle"], event["pc"], event["value"]))
                    if (
                        self.last_phoneme_cycle is not None
                        and not (event["value"] & 0x01)
                        and self.power_off_cycle is None
                    ):
                        self.power_off_cycle = event["cycle"]
                        self._stdio_stop_requested.set()
        if self.cpu.events_lost():
            raise RuntimeError("z-core events were lost; timing measurement is invalid")


def measure_speech_power_timeout(
    rom: Path,
    *,
    clock_hz: int = HD64180_PHI_HZ,
    max_cycles: int = 250_000_000,
) -> tuple[Measurement, list[tuple[int, int, int]]]:
    """Boot one BSP ROM and measure its post-speech power-latch timeout."""
    machine = SpeechPowerProbe(clock=clock_hz)
    machine.load_rom(rom)
    machine.run(max_cycles=max_cycles)
    if machine.last_phoneme_cycle is None:
        raise RuntimeError(f"{rom}: firmware produced no phonemes")
    if machine.power_off_cycle is None:
        raise RuntimeError(f"{rom}: speech power did not turn off within {max_cycles} cycles")
    return (
        Measurement(machine.last_phoneme_cycle, machine.power_off_cycle, clock_hz),
        machine.power_events,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--clock-hz", type=int, default=HD64180_PHI_HZ)
    parser.add_argument("--max-cycles", type=int, default=250_000_000)
    args = parser.parse_args()

    measurement, power_events = measure_speech_power_timeout(
        args.rom,
        clock_hz=args.clock_hz,
        max_cycles=args.max_cycles,
    )
    print(f"ROM: {args.rom}")
    for cycle, pc, value in power_events:
        print(f"power cycle={cycle} pc={pc:04X} value={value:02X}")
    print(f"last phoneme cycle: {measurement.last_phoneme_cycle}")
    print(f"power off cycle: {measurement.power_off_cycle}")
    print(f"elapsed cycles: {measurement.elapsed_cycles}")
    print(f"configured phi Hz: {measurement.clock_hz}")
    print(f"elapsed seconds: {measurement.elapsed_seconds:.9f}")


if __name__ == "__main__":
    main()
