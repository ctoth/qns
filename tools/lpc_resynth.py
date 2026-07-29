"""Resynthesize a phoneme stream from the SSI-263 captures with coarticulation.

The model itself - analysis, reflection coefficients, excitation templates -
lives in :mod:`qns.synth.lpc`, which the live ``--audio lpc`` backend shares.
This tool is the offline renderer: it has the whole phoneme sequence in hand,
so unlike the live stream it can straddle each boundary, easing out of one
phoneme and into the next rather than gliding into each phoneme's head.

    uv run tools/lpc_resynth.py speech.csv out.wav
"""

from __future__ import annotations

import argparse
import csv
import wave
from pathlib import Path

import numpy as np

from qns.synth.lpc import (
    FRAME_MS,
    ORDER,
    SAMPLE_RATE,
    analyse_phoneme,
    reflection_to_lpc,
    resample_template,
)


def synthesize(
    sequence: list[dict],
    phoneme_ms: float,
    transition_ms: float,
    pitch_scale: float = 1.0,
) -> np.ndarray:
    """Run one continuous excitation through a gliding filter."""
    frame_len = int(FRAME_MS * SAMPLE_RATE / 1000)
    frames_per_phoneme = max(1, int(phoneme_ms / FRAME_MS))
    glide = max(1, int(transition_ms / FRAME_MS))

    # Build a per-frame parameter track, easing between phoneme targets.
    track: list[dict] = []
    for position, params in enumerate(sequence):
        for frame in range(frames_per_phoneme):
            blend = 0.0
            target = params
            if position + 1 < len(sequence):
                remaining = frames_per_phoneme - frame
                if remaining <= glide:
                    blend = (glide - remaining + 1) / (2.0 * glide)
                    target = sequence[position + 1]
            track.append({"from": params, "to": target, "blend": blend})

    total = len(track) * frame_len
    output = np.zeros(total, dtype=np.float64)
    history = np.zeros(ORDER, dtype=np.float64)
    rng = np.random.default_rng(0)

    # Excitation is built across the whole utterance first, so the pitch phase
    # is continuous and no per-frame rescaling can introduce an edge.  Gain is
    # carried by the excitation, which is what LPC's residual power means -
    # normalizing the OUTPUT per frame would flatten every phoneme to the same
    # loudness and put a step at each frame boundary.
    excitation = np.zeros(total + frame_len, dtype=np.float64)
    next_pulse = 0
    for position, frame in enumerate(track):
        source, target, blend = frame["from"], frame["to"], frame["blend"]
        gain = (1 - blend) * source["gain"] + blend * target["gain"]
        voiced = source["voiced"] if blend < 0.5 else target["voiced"]
        period = int(round(
            ((1 - blend) * source["period"] + blend * target["period"])
            / max(0.05, pitch_scale)
        ))
        period = max(2, period)
        start = position * frame_len

        if voiced:
            # Blend the two phonemes' own residual periods through the glide,
            # so the excitation's character crosses over with the filter.
            pulse = resample_template(source["template"], period)
            if blend > 0 and target["voiced"]:
                pulse = (1 - blend) * pulse + blend * resample_template(
                    target["template"], period
                )
            pulse = pulse * gain
            while next_pulse < start + frame_len:
                end = min(next_pulse + len(pulse), len(excitation))
                excitation[next_pulse:end] += pulse[:end - next_pulse]
                next_pulse += period
        else:
            # Fricative residual is noise; draw randomly from the captured
            # residual rather than from a Gaussian, keeping its spectrum.
            template = source["template"] if blend < 0.5 else target["template"]
            if len(template) > frame_len:
                offset = int(rng.integers(0, len(template) - frame_len))
                noise = template[offset:offset + frame_len]
            else:
                noise = rng.normal(0.0, 1.0, frame_len)
            excitation[start:start + frame_len] += noise * gain
            next_pulse = start + frame_len

    for position, frame in enumerate(track):
        source, target, blend = frame["from"], frame["to"], frame["blend"]
        reflection = (1 - blend) * source["reflection"] + blend * target["reflection"]
        coeffs = reflection_to_lpc(np.clip(reflection, -0.999, 0.999))
        taps = coeffs[1:]
        start = position * frame_len
        for offset in range(frame_len):
            value = excitation[start + offset] - float(taps @ history)
            history[1:] = history[:-1]
            history[0] = value
            output[start + offset] = value

    return output.astype(np.float32)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="CSV from --trace-speech")
    parser.add_argument("output", type=Path, help="WAV file to write")
    parser.add_argument("--phoneme-ms", type=float, default=110.0)
    parser.add_argument("--transition-ms", type=float, default=35.0)
    parser.add_argument(
        "--pitch-scale",
        type=float,
        default=1.0,
        help=(
            "Multiply pitch relative to the captures' own measured pitch "
            "(~91 Hz); below 1.0 lowers the voice"
        ),
    )
    args = parser.parse_args()

    with open(args.trace, encoding="ascii", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if int(row["code"]) != 0]

    cache: dict[int, dict] = {}
    sequence = []
    for row in rows:
        code = int(row["code"]) & 0x3F
        if code not in cache:
            cache[code] = analyse_phoneme(code)
        sequence.append(cache[code])

    samples = synthesize(
        sequence, args.phoneme_ms, args.transition_ms, args.pitch_scale
    )
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak > 0:
        samples = samples / peak * 0.89
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(args.output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())

    print(
        f"Resynthesized {len(sequence)} phonemes to {args.output} "
        f"({len(samples) / SAMPLE_RATE:.2f}s, LPC order {ORDER})"
    )


if __name__ == "__main__":
    main()
