"""Render a traced SSI-263 phoneme stream to a WAV file.

Takes the CSV written by ``qns.bns --trace-speech`` and reconstructs the
audio offline, so listening to a boot does not require a working host
audio device (or a real-time emulation run).

Every phoneme event carries the CPU cycle count at which the firmware
wrote it, so events are placed on the output timeline by that timestamp
rather than concatenated back to back.  Each phoneme is rendered for
exactly the span until the next event, which is the duration the
firmware's own INT1 schedule gave it - not a duration this renderer
invents.

    uv run tools/render_speech.py speech.csv boot.wav
"""

from __future__ import annotations

import argparse
import csv
import wave
from pathlib import Path

import numpy as np

from qns.ssi263 import playback_length_samples
from qns.synth.formant import FormantSynth
from qns.synth.phonemes import SAMPLE_RATE
from qns.synth.sc02_to_sc01 import SC02_TO_SC01
from qns.synth.ssi263_pcm import SSI263PCMSynth

# Z180 clock the profiles run the machine at; the trace's cycle column is
# in these units.
CPU_CLOCK_HZ = 12_288_000


def _sc01_inflection(inflection: int) -> int:
    """Map the 12-bit SSI-263 inflection (2048 = neutral) to SC-01 pitch."""
    if inflection > 3072:
        return 3
    if inflection > 2560:
        return 2
    if inflection > 1536:
        return 1
    return 0


def load_events(path: Path) -> list[dict[str, int]]:
    """Read the --trace-speech CSV into integer-valued event records."""
    with open(path, encoding="ascii", newline="") as handle:
        rows = list(csv.DictReader(handle))
    events = []
    for row in rows:
        events.append({
            key: int(value)
            for key, value in row.items()
            if key != "name"
        })
    return events


def chip_duration_cycles(
    phoneme: int,
    rate: int,
    playback_duration: int,
) -> int:
    """Current emulator duration for one traced phoneme, in CPU cycles.

    Uses the same capture-length, rate, and latched duration model that
    :mod:`qns.ssi263` uses to schedule phoneme completion.
    """
    samples = playback_length_samples(phoneme, playback_duration, rate)
    return int(samples * CPU_CLOCK_HZ / SAMPLE_RATE)


def _periodicity(samples: np.ndarray, sample_rate: int) -> tuple[int, float]:
    """Pitch period of a capture's steady portion, and how periodic it is.

    Strength is the normalized autocorrelation at that lag: ~0.8 for voiced
    phonemes, under ~0.3 for fricatives, which have no pitch at all.
    Looping a fricative at a "period" imposes an audible tone on noise.
    """
    middle = samples[len(samples) // 4:3 * len(samples) // 4]
    if len(middle) < 8:
        return 0, 0.0
    centered = middle - middle.mean()
    correlation = np.correlate(centered, centered, "full")[len(middle) - 1:]
    low = int(sample_rate / 400)
    high = min(int(sample_rate / 60), len(correlation) - 1)
    if high <= low or correlation[0] <= 0:
        return 0, 0.0
    period = low + int(np.argmax(correlation[low:high]))
    return period, float(correlation[period] / correlation[0])


def _find_period(samples: np.ndarray, sample_rate: int) -> int:
    """Pitch period of a capture's steady portion, in samples."""
    middle = samples[len(samples) // 4:3 * len(samples) // 4]
    if len(middle) < 8:
        return 0
    centered = middle - middle.mean()
    correlation = np.correlate(centered, centered, "full")[len(middle) - 1:]
    low = int(sample_rate / 400)
    high = min(int(sample_rate / 60), len(correlation) - 1)
    if high <= low:
        return 0
    return _periodicity(samples, sample_rate)[0]


def _granular_sustain(
    samples: np.ndarray,
    target_samples: int,
    sample_rate: int,
) -> np.ndarray:
    """Sustain a noise phoneme without imposing a pitch on it.

    Fricatives have no period to loop, so grains are drawn from random
    offsets in the steady region and crossfaded.  A fixed seed keeps the
    output reproducible.
    """
    grain = max(8, int(0.020 * sample_rate))
    fade = max(2, grain // 4)
    region = samples[len(samples) // 8:]
    if len(region) <= grain:
        return samples[:target_samples]

    rng = np.random.default_rng(0)
    ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    output = np.zeros(target_samples + grain, dtype=np.float32)
    position = 0
    while position < target_samples:
        start = int(rng.integers(0, len(region) - grain))
        piece = region[start:start + grain].copy()
        piece[:fade] *= ramp
        piece[-fade:] *= ramp[::-1]
        output[position:position + grain] += piece
        position += grain - fade
    return output[:target_samples]


def is_transient(samples: np.ndarray, sample_rate: int) -> bool:
    """Whether a capture is a stop burst rather than a sustainable sound."""
    return len(samples) < int(0.055 * sample_rate)


def sustain_phoneme(
    samples: np.ndarray,
    target_samples: int,
    sample_rate: int,
) -> np.ndarray:
    """Hold a phoneme for target_samples without pitch or timbre change.

    The AppleWin captures are single isolated utterances, each with its own
    onset and decay, so replaying one to sustain a sound gives ~30% amplitude
    pulsing plus a phase glitch at every repeat (a capture is not a whole
    number of pitch periods).  Instead: keep the natural onset, then loop the
    steady middle on exact pitch-period boundaries, which is continuous.

    Stops and other short transients are returned untouched - looping a burst
    would turn it into a tone.
    """
    if target_samples <= 0 or len(samples) == 0:
        return samples
    if is_transient(samples, sample_rate) or target_samples <= len(samples):
        return samples[:target_samples]

    period, strength = _periodicity(samples, sample_rate)
    if strength < 0.35:
        return _granular_sustain(samples, target_samples, sample_rate)
    if period <= 0:
        return samples[:target_samples]

    onset_end = (len(samples) // 4 // period) * period
    if onset_end <= 0:
        onset_end = period
    loop_periods = max(1, min(4, (len(samples) // 2) // period))
    loop = samples[onset_end:onset_end + period * loop_periods]
    if len(loop) == 0:
        return samples[:target_samples]

    pieces = [samples[:onset_end]]
    length = onset_end
    while length < target_samples:
        pieces.append(loop)
        length += len(loop)
    return np.concatenate(pieces)[:target_samples]


def render(
    events: list[dict[str, int]],
    sample_rate: int,
    backend: str,
    tail_seconds: float,
    timing: str,
    force_amplitude: int | None,
    phoneme_ms: float | None = None,
    overlap_ms: float = 0.0,
    force_duration_mode: int | None = None,
) -> np.ndarray:
    """Place every phoneme on a timeline and mix it down.

    With ``timing="trace"`` events land at the cycle the firmware wrote
    them.  With ``timing="chip"`` each phoneme instead occupies the span
    its own duration/rate registers call for, laid end to end.
    """
    if not events:
        return np.zeros(0, dtype=np.float32)

    def playback_duration_of(event: dict[str, int]) -> int:
        if force_duration_mode is not None:
            return force_duration_mode
        return event.get("playback_duration", event["duration_mode"])

    if timing in ("natural", "sustain"):
        # Each phoneme lasts exactly as long as its own source says: the
        # SC-01 ROM's duration for the formant path, the capture's length
        # for the PCM path.  Nothing is stretched to fill a slot, so stops
        # stay short instead of sustaining like vowels.
        formant = FormantSynth(sample_rate=sample_rate) if backend == "formant" else None
        pcm = SSI263PCMSynth(audio_enabled=False) if backend == "pcm" else None
        pieces = []
        transients: list[bool] = []
        for event in events:
            amplitude = (
                event["amplitude"] if force_amplitude is None else force_amplitude
            )
            if formant is not None:
                piece = formant.synthesize_phoneme(
                    phoneme=SC02_TO_SC01[event["code"] & 0x3F],
                    inflection=_sc01_inflection(event["inflection"]),
                )
                piece = piece * (max(0, min(15, amplitude)) / 15.0)
            else:
                piece = pcm.get_phoneme_audio(
                    event["code"],
                    amplitude,
                    playback_duration_of(event),
                    event["rate"],
                )
            if timing == "sustain":
                target = int((phoneme_ms or 90.0) * sample_rate / 1000)
                piece = sustain_phoneme(piece, target, sample_rate)
                transients.append(is_transient(piece, sample_rate))
            elif phoneme_ms is not None:
                # Truncate, do not resample: the chip cuts a phoneme short
                # when the next one arrives, which shortens it without
                # touching its pitch.  Decimating would raise pitch too.
                limit = int(phoneme_ms * sample_rate / 1000)
                if 0 < limit < len(piece):
                    piece = piece[:limit].copy()
                    edge = min(len(piece), max(1, sample_rate // 500))
                    piece[-edge:] *= np.linspace(1.0, 0.0, edge, dtype=np.float32)
            pieces.append(piece)
        if not pieces:
            return np.zeros(0, dtype=np.float32)

        if timing == "sustain":
            # Splice sustained phonemes over about one pitch period so the
            # joint neither dips to silence nor swallows a stop: transients
            # are butt-joined, keeping their burst intact.
            output = pieces[0]
            for index, piece in enumerate(pieces[1:], start=1):
                if transients[index] or transients[index - 1]:
                    output = np.concatenate([output, piece])
                    continue
                span = min(len(output), len(piece), int(0.006 * sample_rate))
                if span <= 1:
                    output = np.concatenate([output, piece])
                    continue
                fade = np.linspace(1.0, 0.0, span, dtype=np.float32)
                joint = output[-span:] * fade + piece[:span] * (1.0 - fade)
                output = np.concatenate([output[:-span], joint, piece[span:]])
            return output

        if not overlap_ms:
            return np.concatenate(pieces)

        # Each capture is an isolated phoneme with its own onset and decay, so
        # butting them together dips to near-silence at every joint.  The real
        # chip never returns to silence mid-word; overlapping the decay of one
        # phoneme into the onset of the next approximates that.
        overlap = int(overlap_ms * sample_rate / 1000)
        output = pieces[0]
        for piece in pieces[1:]:
            span = min(overlap, len(output), len(piece))
            if span <= 0:
                output = np.concatenate([output, piece])
                continue
            fade = np.linspace(1.0, 0.0, span, dtype=np.float32)
            joint = output[-span:] * fade + piece[:span] * (1.0 - fade)
            output = np.concatenate([output[:-span], joint, piece[span:]])
        return output

    first_cycle = events[0]["cycle"]

    if timing == "chip":
        cycles: list[int] = []
        running = first_cycle
        for event in events:
            cycles.append(running)
            if phoneme_ms is not None:
                running += int(phoneme_ms * CPU_CLOCK_HZ / 1000)
            else:
                running += chip_duration_cycles(
                    event["code"],
                    event["rate"],
                    playback_duration_of(event),
                )
        for event, cycle in zip(events, cycles):
            event["cycle"] = cycle

    def sample_index(cycle: int) -> int:
        return int((cycle - first_cycle) * sample_rate / CPU_CLOCK_HZ)

    total = sample_index(events[-1]["cycle"]) + int(tail_seconds * sample_rate)
    output = np.zeros(total + 1, dtype=np.float32)

    formant = FormantSynth(sample_rate=sample_rate) if backend == "formant" else None
    pcm = SSI263PCMSynth(audio_enabled=False) if backend == "pcm" else None

    for index, event in enumerate(events):
        start = sample_index(event["cycle"])
        if index + 1 < len(events):
            span = sample_index(events[index + 1]["cycle"]) - start
        else:
            span = int(tail_seconds * sample_rate)
        if span <= 0:
            continue

        amplitude = (
            event["amplitude"] if force_amplitude is None else force_amplitude
        )

        if formant is not None:
            samples = formant.synthesize_phoneme(
                phoneme=SC02_TO_SC01[event["code"] & 0x3F],
                duration_override=span / sample_rate,
                inflection=_sc01_inflection(event["inflection"]),
            )
            gain = max(0, min(15, amplitude)) / 15.0
            samples = samples * gain
        else:
            samples = pcm.get_phoneme_audio(
                event["code"],
                amplitude,
                playback_duration_of(event),
                event["rate"],
            )

        length = min(len(samples), len(output) - start)
        if length > 0:
            output[start:start + length] += samples[:length]

    return output


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    """Write float samples as a mono 16-bit PCM WAV."""
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak > 0:
        samples = samples / peak * 0.89
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="CSV from --trace-speech")
    parser.add_argument("output", type=Path, help="WAV file to write")
    parser.add_argument(
        "--synth",
        choices=("formant", "pcm"),
        default="formant",
        help="Audio backend to render with (default: formant)",
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=22050,
        help="Output sample rate in Hz (default: 22050)",
    )
    parser.add_argument(
        "--tail",
        type=float,
        default=0.25,
        help="Seconds of rendering to allow the final phoneme (default: 0.25)",
    )
    parser.add_argument(
        "--skip-pauses",
        action="store_true",
        help="Drop pause (code 0) events instead of rendering their silence",
    )
    parser.add_argument(
        "--timing",
        choices=("chip", "trace", "natural", "sustain"),
        default="chip",
        help=(
            "Pace phonemes by their own duration/rate registers (chip), by "
            "the cycle the firmware wrote them (trace), or back to back at "
            "each phoneme's own natural length (natural), or held for "
            "--phoneme-ms by looping the steady middle (sustain; "
            "default: chip)"
        ),
    )
    parser.add_argument(
        "--force-amplitude",
        type=int,
        metavar="N",
        help="Override the traced amplitude with N (0-15) for every event",
    )
    parser.add_argument(
        "--force-duration-mode",
        type=int,
        metavar="N",
        help=(
            "Override the traced duration mode with N (0-3), which selects "
            "how fast the PCM capture is played out"
        ),
    )
    parser.add_argument(
        "--overlap-ms",
        type=float,
        default=0.0,
        metavar="MS",
        help=(
            "With --timing natural, crossfade consecutive phonemes over MS "
            "milliseconds so joints do not dip to silence"
        ),
    )
    parser.add_argument(
        "--phoneme-ms",
        type=float,
        metavar="MS",
        help=(
            "With --timing chip, give every phoneme MS milliseconds instead "
            "of the duration its registers ask for"
        ),
    )
    args = parser.parse_args()

    events = load_events(args.trace)
    if args.skip_pauses:
        events = [event for event in events if event["code"] != 0]
    samples = render(
        events,
        args.rate,
        args.synth,
        args.tail,
        args.timing,
        args.force_amplitude,
        args.phoneme_ms,
        args.overlap_ms,
        args.force_duration_mode,
    )
    write_wav(args.output, samples, args.rate)

    seconds = len(samples) / args.rate if args.rate else 0.0
    print(
        f"Rendered {len(events)} events to {args.output} "
        f"({seconds:.2f}s at {args.rate} Hz, {args.synth})"
    )


if __name__ == "__main__":
    main()
