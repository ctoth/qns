"""LPC resynthesis backend tests.

Run with: uv run pytest tests/test_lpc_backend.py -v
"""

import numpy as np

from qns.synth import SSI263LPCSynth, SSI263PCMSynth
from qns.synth.lpc import SAMPLE_RATE, LPCStream

# A mix of voiced phonemes and a fricative (0x2D), so the sequence exercises
# boundaries where the excitation switches between pulses and noise as well
# as ones where it stays voiced throughout.
MIXED_SEQUENCE = (0x2D, 0x0A, 0x2F, 0x0C, 0x2D, 0x1A, 0x0A, 0x2F)
WINDOW = 110  # 5 ms, the same frame the synthesis works in


def _envelope(samples: np.ndarray) -> np.ndarray:
    """Short-window RMS, which is what "choppy" is audible as."""
    count = len(samples) // WINDOW
    return np.sqrt((samples[: count * WINDOW].reshape(count, WINDOW) ** 2).mean(axis=1))


def _join_ratio(pieces: list[np.ndarray]) -> float:
    """How much of the normal level survives at the phoneme boundaries."""
    output = np.concatenate(pieces)
    joins = np.cumsum([len(piece) for piece in pieces])[:-1]
    envelope = _envelope(output)
    overall = float(np.median(envelope[envelope > 0]))
    dips = [envelope[max(0, join // WINDOW - 1) : join // WINDOW + 2].min() for join in joins]
    return float(np.median(dips)) / overall


def _render(backend) -> list[np.ndarray]:
    return [backend.get_phoneme_audio(code, 15, 0) for code in MIXED_SEQUENCE]


def test_lpc_holds_level_through_phoneme_boundaries():
    """A pitch pulse spanning a boundary keeps its energy.

    The excitation is built per phoneme but a glottal period is longer than
    one synthesis frame, so a pulse starting near the end of a phoneme runs
    past it.  Dropping that overhang cost amplitude at every join - the exact
    choppiness this backend exists to remove - so the level at the joins is
    the thing worth asserting.
    """
    ratio = _join_ratio(_render(SSI263LPCSynth(audio_enabled=False)))

    assert ratio > 0.5, f"level collapses at phoneme joins: {ratio:.0%} of normal"


def test_lpc_is_less_choppy_than_replayed_captures():
    """The whole point: fewer holes at the boundaries than isolated captures.

    The PCM backend replays one recording per phoneme, each with its own
    fade in and out, so its joins dip toward silence.  LPC runs a continuous
    excitation through a gliding filter and should not.
    """
    lpc = _join_ratio(_render(SSI263LPCSynth(audio_enabled=False)))
    pcm = _join_ratio(_render(SSI263PCMSynth(audio_enabled=False)))

    assert lpc > pcm, f"lpc joins {lpc:.0%} are no better than pcm joins {pcm:.0%}"


def test_lpc_matches_the_chips_own_phoneme_duration():
    """Audio has to last as long as the chip holds the phoneme.

    The chip schedules the next phoneme from its duration model.  A backend
    producing a different length would drift against the emulated clock,
    which is heard as the audio queue draining mid-utterance.
    """
    from qns.ssi263 import playback_length_samples

    backend = SSI263LPCSynth(audio_enabled=False)
    for duration in range(4):
        rendered = backend.get_phoneme_audio(0x2D, 15, duration)
        assert len(rendered) == playback_length_samples(0x2D, duration)


def test_lpc_uses_rate_dependent_playback_length():
    from qns.ssi263 import playback_length_samples

    slow_backend = SSI263LPCSynth(audio_enabled=False)
    fast_backend = SSI263LPCSynth(audio_enabled=False)
    slow = slow_backend.get_phoneme_audio(0x2D, 15, duration=0, rate=0)
    fast = fast_backend.get_phoneme_audio(0x2D, 15, duration=0, rate=15)

    assert len(slow) == playback_length_samples(0x2D, duration=0, rate=0)
    assert len(fast) == playback_length_samples(0x2D, duration=0, rate=15)
    assert len(slow) > len(fast)


def test_lpc_stream_reset_restores_a_fresh_voice():
    """reset() has to clear every piece of carried state, not just some.

    Filter history, pitch phase and the excitation tail all persist between
    phonemes by design; if reset leaves any of them behind, an utterance
    would start differently depending on what preceded it.
    """
    stream = LPCStream()
    first = stream.render(0x2D, 2000)

    stream.render(0x0A, 2000)
    stream.reset()
    again = stream.render(0x2D, 2000)

    assert np.array_equal(first, again)


def test_lpc_pause_exposes_full_modeled_silence_for_end_lifecycle():
    """A pause offers modeled zeros for the chip to truncate at its end."""
    from qns.ssi263 import playback_length_samples

    backend = SSI263LPCSynth(audio_enabled=False)
    backend.get_phoneme_audio(0x2D, 15, 0)
    pause = backend.get_phoneme_audio(0x00, 15, 0)

    assert len(pause) == playback_length_samples(0x00, 0)
    assert not np.any(pause)


def test_lpc_pause_matches_the_pcm_backend():
    """Capture backends expose identical modeled silence to end_phoneme."""
    lpc = SSI263LPCSynth(audio_enabled=False).get_phoneme_audio(0x00, 15, 3)
    pcm = SSI263PCMSynth(audio_enabled=False).get_phoneme_audio(0x00, 15, 3)

    assert len(lpc) == len(pcm)


def test_lpc_amplitude_zero_mutes_the_phoneme():
    """A commanded amplitude of zero is a mute, not a filter ring-out."""
    backend = SSI263LPCSynth(audio_enabled=False)
    loud = backend.get_phoneme_audio(0x2D, 15, 0)
    muted = backend.get_phoneme_audio(0x2D, 0, 0)

    assert float(np.abs(loud).max()) > 1e-4
    assert float(np.abs(muted).max()) < 1e-4


def test_lpc_produces_audio_at_the_capture_sample_rate():
    """The backend has to agree with the player it feeds."""
    backend = SSI263LPCSynth(audio_enabled=False)

    assert backend.sample_rate == SAMPLE_RATE
