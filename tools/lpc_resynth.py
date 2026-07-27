"""Resynthesize a phoneme stream from the SSI-263 captures with coarticulation.

The AppleWin captures are 62 isolated recordings, so replaying them gives a
hard edge at every phoneme boundary - no amount of pacing or crossfading makes
a re-triggered recording continuous (see tools/render_speech.py --timing
sustain).  A real formant synthesizer has no boundary at all: its filter
parameters glide from one phoneme's targets toward the next.

The SSI-263 is a source-filter synthesizer, which is exactly what linear
prediction models, so each capture can be analysed into an all-pole filter
plus an excitation description.  Resynthesis then interpolates the *filter*
across phoneme boundaries and runs one continuous excitation through it,
which reproduces the chip's timbre while gaining the coarticulation that
recordings cannot provide.

Reflection coefficients are what gets interpolated: they stay stable under
interpolation as long as each stays inside the unit circle, which direct LPC
coefficients do not.

    uv run tools/lpc_resynth.py speech.csv out.wav
"""

from __future__ import annotations

import argparse
import csv
import wave
from pathlib import Path

import numpy as np

from qns.synth.phonemes import SAMPLE_RATE, get_phoneme_samples

ORDER = 14
FRAME_MS = 5.0


def levinson(autocorr: np.ndarray, order: int) -> tuple[np.ndarray, float]:
    """Solve for reflection coefficients and residual power (Levinson-Durbin)."""
    error = float(autocorr[0])
    reflection = np.zeros(order, dtype=np.float64)
    coeffs = np.zeros(order + 1, dtype=np.float64)
    coeffs[0] = 1.0
    if error <= 0:
        return reflection, 0.0

    for step in range(order):
        acc = autocorr[step + 1]
        for index in range(1, step + 1):
            acc += coeffs[index] * autocorr[step + 1 - index]
        k = -acc / error
        k = float(np.clip(k, -0.999, 0.999))
        reflection[step] = k

        updated = coeffs.copy()
        for index in range(1, step + 2):
            updated[index] = coeffs[index] + k * coeffs[step + 1 - index]
        coeffs = updated
        error *= 1.0 - k * k
        if error <= 0:
            break

    return reflection, max(error, 0.0)


def reflection_to_lpc(reflection: np.ndarray) -> np.ndarray:
    """Convert reflection coefficients to direct-form LPC coefficients."""
    order = len(reflection)
    coeffs = np.zeros(order + 1, dtype=np.float64)
    coeffs[0] = 1.0
    for step in range(order):
        k = reflection[step]
        updated = coeffs.copy()
        for index in range(1, step + 2):
            updated[index] = coeffs[index] + k * coeffs[step + 1 - index]
        coeffs = updated
    return coeffs


def analyse_phoneme(code: int) -> dict:
    """Analyse one capture into filter, gain, voicing and pitch."""
    index = (2 if code == 1 else code) - 2
    samples = get_phoneme_samples(index).astype(np.float64)
    steady = samples[len(samples) // 4:3 * len(samples) // 4]
    steady = steady - steady.mean()
    if len(steady) < ORDER * 2:
        steady = samples.astype(np.float64)

    windowed = steady * np.hanning(len(steady))
    full = np.correlate(windowed, windowed, "full")
    autocorr = full[len(windowed) - 1:len(windowed) + ORDER]
    reflection, residual = levinson(autocorr, ORDER)

    # Voicing and pitch from the same autocorrelation the periodicity test uses.
    centered = steady
    correlation = np.correlate(centered, centered, "full")[len(centered) - 1:]
    low = int(SAMPLE_RATE / 400)
    high = min(int(SAMPLE_RATE / 60), len(correlation) - 1)
    if high > low and correlation[0] > 0:
        period = low + int(np.argmax(correlation[low:high]))
        voicing = float(correlation[period] / correlation[0])
    else:
        period, voicing = 0, 0.0

    voiced = voicing >= 0.35
    period = period if period > 0 else int(SAMPLE_RATE / 100)

    # Excitation is taken from the capture itself, not modelled.  Inverse-
    # filtering the capture through its own LPC filter leaves the residual -
    # the chip's real excitation - so one period of it carries the true
    # spectral tilt.  A synthetic pulse has to guess that tilt, and guessing
    # wrong shows up directly as a too-dark or too-harsh voice.
    coeffs = reflection_to_lpc(reflection)
    resid = np.convolve(steady, coeffs, mode="same")

    if voiced:
        search = resid[:len(resid) - period] if len(resid) > period else resid
        anchor = int(np.argmax(np.abs(search))) if len(search) else 0
        anchor = max(0, min(anchor, max(0, len(resid) - period)))
        template = resid[anchor:anchor + period].copy()
        if len(template) < period:
            template = np.pad(template, (0, period - len(template)))
    else:
        template = resid.copy()

    rms = float(np.sqrt((template ** 2).mean())) if len(template) else 0.0
    if rms > 0:
        template = template / rms

    return {
        "reflection": reflection,
        "gain": float(np.sqrt(residual / max(1, len(windowed)))),
        "voiced": voiced,
        "period": period,
        "rms": float(np.sqrt((steady ** 2).mean())),
        "template": template,
    }


def resample_template(template: np.ndarray, length: int) -> np.ndarray:
    """Stretch or squeeze one excitation period to the current pitch period."""
    if len(template) == 0:
        return np.zeros(length, dtype=np.float64)
    if len(template) == length:
        return template
    return np.interp(
        np.linspace(0.0, len(template) - 1, length),
        np.arange(len(template)),
        template,
    )


def glottal_pulse(period: int) -> np.ndarray:
    """One glottal excitation pulse, shaped rather than a bare impulse.

    A unit impulse has energy at every frequency up to Nyquist, which reads
    as a click on each pitch period.  The chip's excitation is a shaped wave
    (see GLOTTAL_WAVE in sc01_rom.py), so a smooth asymmetric pulse - fast
    opening, slower close - is much closer and far less harsh.
    """
    width = max(2, period // 3)
    rise = max(1, width // 3)
    pulse = np.zeros(width, dtype=np.float64)
    pulse[:rise] = np.linspace(0.0, 1.0, rise, endpoint=False)
    pulse[rise:] = np.cos(np.linspace(0.0, np.pi / 2, width - rise)) ** 2
    return pulse - pulse.mean()


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
