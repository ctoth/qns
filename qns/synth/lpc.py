"""Linear-prediction model of the SSI-263 captures, and a streaming voice.

The AppleWin captures are 62 isolated recordings, so replaying them gives a
hard edge at every phoneme boundary - no amount of pacing or crossfading makes
a re-triggered recording continuous.  A real formant synthesizer has no
boundary at all: its filter parameters glide from one phoneme's targets toward
the next.

The SSI-263 is a source-filter synthesizer, which is exactly what linear
prediction models, so each capture can be analysed into an all-pole filter
plus an excitation description.  Resynthesis then interpolates the *filter*
across phoneme boundaries and runs one continuous excitation through it,
which reproduces the chip's timbre while gaining the coarticulation that
recordings cannot provide.

Reflection coefficients are what gets interpolated: they stay stable under
interpolation as long as each stays inside the unit circle, which direct LPC
coefficients do not.

:class:`LPCStream` is the real-time form.  It differs from the offline
renderer in `tools/lpc_resynth.py` in one deliberate way: the offline pass
knows the whole phoneme sequence, so it straddles each boundary, easing out of
one phoneme and into the next.  A live chip hands over one phoneme at a time
with no lookahead, so the stream instead glides from the *previous* phoneme's
targets into the current one across the head of each phoneme.  Both keep the
filter continuous, which is what removes the edge; only the placement of the
transition differs, and the head-glide costs no added latency and needs no
end-of-utterance flush.
"""

from __future__ import annotations

import numpy as np

from .phonemes import SAMPLE_RATE, get_phoneme_samples

ORDER = 14
FRAME_MS = 5.0

# The analysis works in the captures' own int16 units, so the resynthesized
# output lands at that scale too.  Dividing by the int16 range therefore puts
# this backend at the same loudness as the PCM backend, which scales the raw
# captures the same way - rather than at some level tuned by ear that would
# make switching backends a volume change.
OUTPUT_SCALE = 1.0 / 32768.0


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
    steady = samples[len(samples) // 4 : 3 * len(samples) // 4]
    steady = steady - steady.mean()
    if len(steady) < ORDER * 2:
        steady = samples.astype(np.float64)

    windowed = steady * np.hanning(len(steady))
    full = np.correlate(windowed, windowed, "full")
    autocorr = full[len(windowed) - 1 : len(windowed) + ORDER]
    reflection, residual = levinson(autocorr, ORDER)

    # Voicing and pitch from the same autocorrelation the periodicity test uses.
    centered = steady
    correlation = np.correlate(centered, centered, "full")[len(centered) - 1 :]
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
        search = resid[: len(resid) - period] if len(resid) > period else resid
        anchor = int(np.argmax(np.abs(search))) if len(search) else 0
        anchor = max(0, min(anchor, max(0, len(resid) - period)))
        template = resid[anchor : anchor + period].copy()
        if len(template) < period:
            template = np.pad(template, (0, period - len(template)))
    else:
        template = resid.copy()

    rms = float(np.sqrt((template**2).mean())) if len(template) else 0.0
    if rms > 0:
        template = template / rms

    return {
        "reflection": reflection,
        "gain": float(np.sqrt(residual / max(1, len(windowed)))),
        "voiced": voiced,
        "period": period,
        "rms": float(np.sqrt((steady**2).mean())),
        "template": template,
    }


_analysis_cache: dict[int, dict] = {}


def phoneme_params(code: int) -> dict:
    """Analyse a phoneme once and reuse it for every later occurrence.

    All 62 captures analyse in about 40 ms together, so this exists to keep
    the cost off the audio path rather than because it is expensive.
    """
    code &= 0x3F
    if code not in _analysis_cache:
        _analysis_cache[code] = analyse_phoneme(code)
    return _analysis_cache[code]


def warm_analysis_cache() -> None:
    """Analyse every capture up front, so no phoneme pays for it live."""
    for code in range(2, 64):
        phoneme_params(code)


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


class LPCStream:
    """Synthesize a phoneme at a time while staying continuous across them.

    Three pieces of state have to survive between calls or the boundary comes
    straight back: the all-pole filter's own history, the pitch phase (so a
    period is not restarted mid-cycle), and the previous phoneme's targets
    (so the filter has somewhere to glide *from*).
    """

    def __init__(
        self,
        transition_ms: float = 35.0,
        pitch_scale: float = 1.0,
    ) -> None:
        self.transition_ms = transition_ms
        self.pitch_scale = pitch_scale
        self._frame_len = int(FRAME_MS * SAMPLE_RATE / 1000)
        self._history = np.zeros(ORDER, dtype=np.float64)
        self._previous: dict | None = None
        # Samples until the next glottal pulse, measured from the start of
        # the next buffer.  Carrying this is what keeps pitch phase unbroken.
        self._next_pulse = 0
        # A pitch pulse starting near the end of a phoneme runs past it - a
        # period at 60 Hz is over 350 samples.  Carrying phase alone would
        # still truncate that pulse's energy, putting an amplitude dip at
        # every boundary, so its tail is carried too.
        self._tail = np.zeros(0, dtype=np.float64)
        self._seed = 0
        self._rng = np.random.default_rng(self._seed)

    def reset(self) -> None:
        """Forget all continuity, as at the start of a fresh utterance.

        The noise source is reseeded along with the rest: fricatives draw
        from it, so leaving it advanced would make an utterance depend on
        whatever was spoken before it.
        """
        self._history[:] = 0.0
        self._previous = None
        self._next_pulse = 0
        self._tail = np.zeros(0, dtype=np.float64)
        self._rng = np.random.default_rng(self._seed)

    def render(self, code: int, samples: int, amplitude: int = 15) -> np.ndarray:
        """Render one phoneme as `samples` float32 samples at SAMPLE_RATE.

        `samples` comes from the chip's own duration model, so the audio
        produced here lasts exactly as long as the chip will hold the
        phoneme before asking for the next one.
        """
        if samples <= 0:
            return np.zeros(0, dtype=np.float32)

        gain_scale = max(0, min(15, amplitude)) / 15.0
        if gain_scale == 0.0:
            return np.zeros(samples, dtype=np.float32)
        if code & 0x3F == 0:
            return self._render_silence(samples)

        target = phoneme_params(code)
        source = self._previous if self._previous is not None else target
        excitation = self._excite(source, target, samples, gain_scale)
        output = self._filter(source, target, excitation, samples)
        self._previous = target
        return (output * OUTPUT_SCALE).astype(np.float32)

    def _blend_track(self, samples: int) -> list[tuple[int, int, float]]:
        """Split the buffer into frames, each with its glide position 0..1."""
        glide = max(1, int(self.transition_ms * SAMPLE_RATE / 1000))
        track = []
        start = 0
        while start < samples:
            length = min(self._frame_len, samples - start)
            middle = start + length / 2.0
            blend = 1.0 if self._previous is None else min(1.0, middle / glide)
            track.append((start, length, blend))
            start += length
        return track

    def _excite(
        self,
        source: dict,
        target: dict,
        samples: int,
        gain_scale: float,
    ) -> np.ndarray:
        """Build the excitation for one phoneme, keeping pitch phase intact.

        Gain is carried by the excitation, which is what LPC's residual power
        means - normalizing the OUTPUT per frame would flatten every phoneme
        to the same loudness and put a step at each frame boundary.
        """
        # Headroom past the end so a pulse starting inside this buffer can
        # finish; whatever lands beyond `samples` is carried into the next
        # call rather than dropped.  The lowest pitch the analysis reports is
        # 60 Hz, so one period never exceeds this.
        headroom = int(SAMPLE_RATE / 50)
        excitation = np.zeros(samples + headroom, dtype=np.float64)
        carried = min(len(self._tail), len(excitation))
        excitation[:carried] += self._tail[:carried]
        next_pulse = self._next_pulse

        for start, length, blend in self._blend_track(samples):
            gain = ((1 - blend) * source["gain"] + blend * target["gain"]) * gain_scale
            voiced = source["voiced"] if blend < 0.5 else target["voiced"]
            period = int(
                round(
                    ((1 - blend) * source["period"] + blend * target["period"])
                    / max(0.05, self.pitch_scale)
                )
            )
            period = max(2, period)

            if voiced:
                # Blend the two phonemes' own residual periods through the
                # glide, so the excitation's character crosses over with the
                # filter rather than switching under it.
                pulse = resample_template(source["template"], period)
                if blend > 0 and target["voiced"]:
                    pulse = (1 - blend) * pulse + blend * resample_template(
                        target["template"], period
                    )
                pulse = pulse * gain
                while next_pulse < start + length:
                    if next_pulse >= 0:
                        end = min(next_pulse + len(pulse), len(excitation))
                        excitation[next_pulse:end] += pulse[: end - next_pulse]
                    next_pulse += period
            else:
                # Fricative residual is noise; draw randomly from the captured
                # residual rather than from a Gaussian, keeping its spectrum.
                template = source["template"] if blend < 0.5 else target["template"]
                if len(template) > length:
                    offset = int(self._rng.integers(0, len(template) - length))
                    noise = template[offset : offset + length]
                else:
                    noise = self._rng.normal(0.0, 1.0, length)
                excitation[start : start + length] += noise * gain
                next_pulse = start + length

        self._next_pulse = max(0, next_pulse - samples)
        self._tail = excitation[samples:].copy()
        return excitation

    def _filter(
        self,
        source: dict,
        target: dict,
        excitation: np.ndarray,
        samples: int,
    ) -> np.ndarray:
        """Run the excitation through the gliding all-pole filter."""
        output = np.zeros(samples, dtype=np.float64)
        history = self._history
        for start, length, blend in self._blend_track(samples):
            reflection = (1 - blend) * source["reflection"] + blend * target["reflection"]
            taps = reflection_to_lpc(np.clip(reflection, -0.999, 0.999))[1:]
            for offset in range(start, start + length):
                value = excitation[offset] - float(taps @ history)
                history[1:] = history[:-1]
                history[0] = value
                output[offset] = value
        return output

    def _render_silence(self, samples: int) -> np.ndarray:
        """Let the filter ring out into a pause instead of cutting to zero."""
        history = self._history
        taps = np.zeros(ORDER, dtype=np.float64)
        if self._previous is not None:
            taps = reflection_to_lpc(np.clip(self._previous["reflection"], -0.999, 0.999))[1:]
        output = np.zeros(samples, dtype=np.float64)
        for offset in range(samples):
            value = -float(taps @ history)
            history[1:] = history[:-1]
            history[0] = value
            output[offset] = value
        # A pause ends the utterance's excitation: a pulse tail held over it
        # would re-enter at the head of the next phoneme, a whole pause late.
        self._next_pulse = 0
        self._tail = np.zeros(0, dtype=np.float64)
        return (output * OUTPUT_SCALE).astype(np.float32)
