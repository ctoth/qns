"""Trace why a queued chord does or does not reach the firmware.

`ChordInputDriver` only starts a chord once the firmware looks ready, and
only completes one once the firmware's input buffer echoes it back.  Each
of those gates is invisible from outside, so this reports every phase
change together with the epochs and buffer bytes the driver consults.

    uv run investigations/chord_delivery_trace.py [chord] [cycles]
"""

from __future__ import annotations

import sys
from pathlib import Path

from qns.bns import BNS
from qns.input_driver import ChordInputDriver

ROM = Path("roms/bspeng.bns")


def main() -> None:
    chord = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x55
    max_cycles = int(sys.argv[2], 0) if len(sys.argv) > 2 else 400_000_000
    delay = int(sys.argv[3], 0) if len(sys.argv) > 3 else 80_000_000

    original_init = ChordInputDriver.__init__
    original_tick = ChordInputDriver.tick
    state = {"phase": "<none>", "ticks": 0, "reported": 0, "seeded": False}

    def seeded_init(self, bns) -> None:
        original_init(self, bns)

    def traced_tick(self) -> None:
        # Hold the chord back until the greeting has finished; a chord
        # delivered mid-utterance is swallowed by the speaking firmware.
        if not state["seeded"] and self._bns.stats.get("cycles", 0) >= delay:
            state["seeded"] = True
            self.queue.put(chord)
            print(
                f"seeded chord {chord:02X} at cycles={self._bns.stats.get('cycles', 0)}", flush=True
            )
        original_tick(self)
        state["ticks"] += 1
        boundary = self._bns._input_boundary
        phase = self._phase or "<idle>"
        if phase == state["phase"]:
            return
        state["phase"] = phase
        state["reported"] += 1
        print(
            f"tick={state['ticks']} phase={phase} "
            f"cycles={self._bns.stats.get('cycles', 0)} "
            f"ready={self._bns._keyboard_ready_epoch} "
            f"accept={self._bns._keyboard_accept_epoch} "
            f"queue={self._bns._keyboard_queue_epoch} "
            f"consume={self._bns._keyboard_consume_epoch} "
            f"queue_count={self._bns.memory.read(boundary.keyboard_queue_count)} "
            f"input_buffer={self._bns.memory.read(boundary.keyboard_input_buffer):02X}",
            flush=True,
        )

    ChordInputDriver.__init__ = seeded_init
    ChordInputDriver.tick = traced_tick

    def say(text: str) -> None:
        print(f"speech={text!r}", flush=True)

    bns = BNS(core="direct", stdin_device="keyboard", english_callback=say)
    bns.load_rom(ROM)
    bns.run(max_cycles=max_cycles)

    print(f"total_ticks={state['ticks']} phase_changes={state['reported']}")
    print(f"final_ready_epoch={bns._keyboard_ready_epoch}")
    print(f"final_consume_epoch={bns._keyboard_consume_epoch}")
    print(f"steps_required={bns._requires_instruction_steps()}")


if __name__ == "__main__":
    main()
