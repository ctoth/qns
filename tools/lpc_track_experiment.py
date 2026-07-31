"""EXPERIMENT: time-varying LPC, one filter track per capture.

Not a backend, and not wired to --audio.  This is the unfinished idea from
docs/reports/lpc-backend-investigation.md, kept runnable so it does not have
to be rediscovered.

The shipped `lpc` backend models a phoneme as ONE steady filter plus a
description of its excitation.  That is true of a vowel and false of a stop,
which is a closure followed by a burst - so the burst is replaced by
stationary noise at the same average level, and /p/ goes missing.

This analyses the whole capture frame by frame instead, and inverse-filters
it through its own time-varying filter.  The residual that falls out is
exact: running it back through the same filter reconstructs the capture
sample for sample.  So the voice is the capture's - stop bursts included -
and the only deliberate deviation is gliding the filter across phoneme
boundaries, which is what isolated recordings cannot do.

No voicing test, no pulse template, no noise generator: the residual already
carries whatever the chip did, burst or buzz or hiss.  That deletes the
three mechanisms where the shipped model misclassifies stops.

    uv run tools/lpc_track_experiment.py greeting.csv out/track.wav
    uv run tools/lpc_track_experiment.py greeting.csv out/track.wav --measure

Known incomplete: the frame time-scaling does not align when a phoneme's
length is not a whole number of frames, which leaves a small reconstruction
error (S 0.000, AH 0.067, P 0.082, K 0.159 relative RMS).  That is
arithmetic, not model error, and is the first thing to fix if this is taken
further.
"""

from __future__ import annotations

import argparse
import csv
import wave
from pathlib import Path

import numpy as np

from qns.ssi263 import PHONEMES, playback_length_samples
from qns.synth import SSI263PCMSynth
from qns.synth.lpc import ORDER, SAMPLE_RATE, levinson, reflection_to_lpc
from qns.synth.phonemes import get_phoneme_samples

FRAME = 110  # 5 ms
STOPS = (0x24, 0x25, 0x27, 0x28, 0x29)  # B D P T K

_tracks: dict[int, list[dict]] = {}


def phoneme_track(code: int) -> list[dict]:
    """Analyse one capture into frames carrying an exact residual."""
    code &= 0x3F
    if code in _tracks:
        return _tracks[code]

    index = (2 if code == 1 else code) - 2
    samples = get_phoneme_samples(index).astype(np.float64)

    frames = []
    for start in range(0, max(1, len(samples)), FRAME):
        stop = min(start + FRAME, len(samples))
        if stop <= start:
            break
        # Analyse on a wider window than the frame, so a short frame still
        # yields a stable filter, but keep the frame itself as the segment.
        low = max(0, start - FRAME)
        high = min(len(samples), stop + FRAME)
        window = samples[low:high]
        window = window - window.mean()
        if len(window) < ORDER * 2:
            window = np.pad(window, (0, ORDER * 2 - len(window)))
        windowed = window * np.hanning(len(window))
        full = np.correlate(windowed, windowed, "full")
        autocorr = full[len(windowed) - 1 : len(windowed) + ORDER]
        reflection, _ = levinson(autocorr, ORDER)
        frames.append(
            {
                "reflection": reflection,
                "taps": reflection_to_lpc(reflection)[1:],
                "span": (start, stop),
            }
        )

    # One inverse-filtering pass across the whole capture, carrying history,
    # so the residual is exactly what reproduces the capture on the way back.
    history = np.zeros(ORDER, dtype=np.float64)
    for frame in frames:
        start, stop = frame["span"]
        residual = np.zeros(stop - start, dtype=np.float64)
        taps = frame["taps"]
        for offset in range(start, stop):
            value = samples[offset]
            residual[offset - start] = value + float(taps @ history)
            history[1:] = history[:-1]
            history[0] = value
        frame["residual"] = residual

    _tracks[code] = frames
    return frames


def _stretch(values: np.ndarray, length: int) -> np.ndarray:
    if len(values) == length:
        return values
    if len(values) == 0:
        return np.zeros(length)
    return np.interp(
        np.linspace(0.0, len(values) - 1, length),
        np.arange(len(values)),
        values,
    )


class TrackStream:
    """Play a phoneme's own frame track, gliding only across boundaries."""

    def __init__(self, transition_ms: float = 35.0) -> None:
        self.transition_ms = transition_ms
        self._history = np.zeros(ORDER, dtype=np.float64)
        self._previous: np.ndarray | None = None

    def render(self, code: int, samples: int, amplitude: int = 15) -> np.ndarray:
        if samples <= 0:
            return np.zeros(0, dtype=np.float32)
        gain = max(0, min(15, amplitude)) / 15.0
        if code & 0x3F == 0 or gain == 0.0:
            # Pause is a no-op between phonemes; see the pause finding in the
            # report.  Continuity is deliberately preserved across it.
            return np.zeros(1, dtype=np.float32)

        track = phoneme_track(code)
        glide = max(1, int(self.transition_ms * SAMPLE_RATE / 1000))
        output = np.zeros(samples, dtype=np.float64)
        history = self._history

        count = max(1, int(round(samples / FRAME)))
        written = 0
        for index in range(count):
            start = written
            stop = samples if index == count - 1 else min(samples, start + FRAME)
            if stop <= start:
                break
            position = index * (len(track) - 1) / max(1, count - 1)
            source = track[int(np.floor(position))]
            excitation = _stretch(source["residual"], stop - start) * gain

            reflection = source["reflection"]
            if self._previous is not None and start < glide:
                blend = min(1.0, (start + (stop - start) / 2) / glide)
                reflection = (1 - blend) * self._previous + blend * reflection
            taps = reflection_to_lpc(np.clip(reflection, -0.999, 0.999))[1:]

            for offset in range(stop - start):
                value = excitation[offset] - float(taps @ history)
                history[1:] = history[:-1]
                history[0] = value
                output[start + offset] = value
            written = stop

        self._previous = track[-1]["reflection"]
        return (output / 32768.0).astype(np.float32)


def measure() -> None:
    """Report the two numbers that made this look worth finishing."""
    print("Reconstruction error against the raw capture (glide off):")
    for code in (0x27, 0x29, 0x0E, 0x30):
        raw = get_phoneme_samples(code - 2).astype(np.float64) / 32768.0
        got = TrackStream(transition_ms=0).render(code, len(raw), 15)
        error = float(np.sqrt(((got - raw) ** 2).mean()) / np.sqrt((raw**2).mean()))
        print(f"  {PHONEMES[code][0]:5} relative RMS error {error:8.5f}")

    print("\nPeak level of each stop, isolated:")
    pcm = SSI263PCMSynth(audio_enabled=False)
    print(f"  {'stop':6} {'pcm':>7} {'track':>7}")
    for code in STOPS:
        want = float(np.abs(pcm.get_phoneme_audio(code, 15, 0)).max())
        got = float(np.abs(TrackStream().render(code, playback_length_samples(code, 0), 15)).max())
        print(f"  {PHONEMES[code][0]:6} {want:7.3f} {got:7.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="CSV from --trace-speech")
    parser.add_argument("output", type=Path, help="WAV file to write")
    parser.add_argument("--transition-ms", type=float, default=35.0)
    parser.add_argument(
        "--measure",
        action="store_true",
        help="Also report reconstruction error and stop-burst levels",
    )
    args = parser.parse_args()

    with open(args.trace, encoding="ascii", newline="") as handle:
        rows = list(csv.DictReader(handle))

    stream = TrackStream(transition_ms=args.transition_ms)
    samples = np.concatenate(
        [
            stream.render(
                int(row["code"]) & 0x3F,
                playback_length_samples(
                    int(row["code"]),
                    int(row.get("playback_duration") or row["duration_mode"]),
                ),
                int(row["amplitude"]),
            )
            for row in rows
        ]
    )

    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(args.output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    print(f"Rendered {len(rows)} phonemes to {args.output} ({len(samples) / SAMPLE_RATE:.2f}s)")

    if args.measure:
        print()
        measure()


if __name__ == "__main__":
    main()
