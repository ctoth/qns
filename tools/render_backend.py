"""Render a traced phoneme stream through a live --audio backend, offline.

`--audio` can only be judged on a machine with working sound, and only in
real time.  This replays a `--trace-speech` CSV through the very backend
`--audio BACKEND` would use, writing a WAV instead of opening a stream - so
the three backends can be compared by ear, on any machine, as many times as
it takes.

    uv run -m qns.bns --cycles 60000000 --input none \\
        --trace-speech greeting.csv roms/bspeng.bns
    uv run tools/render_backend.py greeting.csv lpc.wav --backend lpc

Each phoneme is rendered for exactly the length the chip holds it, so the
result runs the same length as the live audio rather than being paced by
however fast the emulator happened to run.

Traces made before the rate column was added remain supported.  They use
the capture-neutral SSI-263 rate 8 and emit one warning on stderr.
"""

from __future__ import annotations

import argparse
import csv
import sys
import wave
from pathlib import Path

import numpy as np

from qns.ssi263 import playback_length_samples
from qns.synth import SSI263LPCSynth, SSI263PCMSynth, SSI263Synth
from qns.synth.phonemes import SAMPLE_RATE
from qns.synth.timing import fit_audio_to_elapsed

BACKENDS = {"pcm": SSI263PCMSynth, "lpc": SSI263LPCSynth, "formant": SSI263Synth}
CPU_CLOCK_HZ = 12_288_000


def _duration(row: dict) -> int:
    return int(row.get("playback_duration") or row["duration_mode"])


def _rate(row: dict) -> int:
    return int(row.get("rate") or 8)


def render_row(backend, row: dict, name: str) -> np.ndarray:
    """Render one traced phoneme event through the backend.

    The three backends take their third argument from different registers -
    the capture-based ones are governed by the duration mode, the formant
    model by inflection - so each is handed what it actually uses.
    """
    code = int(row["code"]) & 0x3F
    amplitude = int(row["amplitude"])
    duration = _duration(row)
    rate = _rate(row)
    if name == "formant":
        audio = backend.get_phoneme_audio(code, amplitude, int(row["inflection"]))
    else:
        audio = backend.get_phoneme_audio(code, amplitude, duration, rate)

    return fit_audio_to_elapsed(
        audio,
        playback_length_samples(code, duration, rate),
    )


def render_rows(
    backend,
    rows: list[dict],
    name: str,
    *,
    cpu_clock: int = CPU_CLOCK_HZ,
) -> np.ndarray:
    """Render events for their measured trace-cycle spans.

    The last trace row marks the end of the measurable span.  Every earlier
    phoneme is truncated or zero-padded to the next event's cycle, exactly as
    the live chip's ``end_phoneme`` event treats supersession.
    """
    if not rows:
        return np.zeros(0, dtype=np.float32)
    if any(not row.get("rate") for row in rows):
        print(
            "warning: legacy trace has no rate column; using SSI-263 rate 8",
            file=sys.stderr,
        )
    if len(rows) == 1:
        return render_row(backend, rows[0], name)

    pieces = []
    origin_cycle = int(rows[0]["cycle"])
    for row, next_row in zip(rows, rows[1:]):
        start_sample = int((int(row["cycle"]) - origin_cycle) * SAMPLE_RATE / cpu_clock)
        end_sample = int((int(next_row["cycle"]) - origin_cycle) * SAMPLE_RATE / cpu_clock)
        elapsed_samples = max(0, end_sample - start_sample)
        pieces.append(
            fit_audio_to_elapsed(
                render_row(backend, row, name),
                elapsed_samples,
            )
        )
    return np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="CSV from --trace-speech")
    parser.add_argument("output", type=Path, help="WAV file to write")
    parser.add_argument(
        "--backend",
        choices=tuple(BACKENDS),
        default="lpc",
        help="Which --audio backend to render with (default: lpc)",
    )
    parser.add_argument(
        "--drop-pauses",
        action="store_true",
        help=(
            "Leave out pause events.  They are most of the stream - the "
            "greeting is 88 pauses around 28 phonemes - so dropping them "
            "no longer previews what --audio plays; useful only for "
            "listening to the phonemes alone"
        ),
    )
    args = parser.parse_args()

    with open(args.trace, encoding="ascii", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if args.drop_pauses:
        rows = [row for row in rows if int(row["code"]) != 0]

    backend = BACKENDS[args.backend](audio_enabled=False)
    if args.drop_pauses:
        if any(not row.get("rate") for row in rows):
            print(
                "warning: legacy trace has no rate column; using SSI-263 rate 8",
                file=sys.stderr,
            )
        pieces = [render_row(backend, row, args.backend) for row in rows]
        samples = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)
    else:
        samples = render_rows(backend, rows, args.backend)

    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak > 1.0:
        print(f"warning: peak {peak:.2f} exceeds full scale; clipping")
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(args.output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())

    print(
        f"Rendered {len(rows)} phonemes through {args.backend} to "
        f"{args.output} ({len(samples) / SAMPLE_RATE:.2f}s, peak {peak:.2f})"
    )


if __name__ == "__main__":
    main()
