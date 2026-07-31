"""Tests for the fixed-capture SSI-263 audio backend."""

import numpy as np

from qns.bns import BNS
from qns.ssi263 import SSI263, SSI263State, playback_length_samples
from qns.synth.lpc import ORDER, levinson, reflection_to_lpc
from qns.synth.phonemes import get_phoneme_samples
from qns.synth.ssi263_pcm import SSI263PCMSynth


def _dominant_voiced_frequency(samples: np.ndarray) -> float:
    """Return the strongest low-frequency component of a voiced capture."""
    windowed = samples * np.hanning(len(samples))
    spectrum = np.abs(np.fft.rfft(windowed))
    frequencies = np.fft.rfftfreq(len(samples), 1 / 22050)
    voiced = (frequencies >= 70) & (frequencies <= 350)
    return float(frequencies[voiced][np.argmax(spectrum[voiced])])


def _autocorrelation_voiced_frequency(samples: np.ndarray) -> float:
    """Return the fundamental implied by the strongest voiced period."""
    middle = samples[len(samples) // 4 : 3 * len(samples) // 4]
    centered = middle - middle.mean()
    correlation = np.correlate(centered, centered, "full")[len(middle) - 1 :]
    low = int(22050 / 400)
    high = min(int(22050 / 60), len(correlation) - 1)
    period = low + int(np.argmax(correlation[low:high]))
    return 22050 / period


def _lpc_spectral_envelope(samples: np.ndarray) -> np.ndarray:
    """Return a normalized formant envelope independent of pitch harmonics."""
    middle = samples[len(samples) // 4 : 3 * len(samples) // 4]
    centered = middle - middle.mean()
    windowed = centered * np.hanning(len(centered))
    full = np.correlate(windowed, windowed, "full")
    autocorrelation = full[len(windowed) - 1 : len(windowed) + ORDER]
    reflection, _ = levinson(autocorrelation, ORDER)
    coefficients = reflection_to_lpc(reflection)

    frequencies = np.linspace(0.0, np.pi, 1025)
    powers = np.arange(len(coefficients))
    response = np.exp(-1j * np.outer(frequencies, powers)) @ coefficients
    envelope = -np.log(np.maximum(np.abs(response), 1e-12))
    speech_band = envelope[28:326]
    return (speech_band - speech_band.mean()) / speech_band.std()


def test_pcm_backend_uses_captured_ssi263_samples() -> None:
    synth = SSI263PCMSynth(audio_enabled=False)

    actual = synth.get_phoneme_audio(2, amplitude=15)
    expected = get_phoneme_samples(0).astype(np.float32) / 32768.0

    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(
        synth.get_phoneme_audio(1, amplitude=15),
        expected,
    )


def test_pcm_backend_honors_zero_amplitude() -> None:
    synth = SSI263PCMSynth(audio_enabled=False)

    assert np.any(synth.get_phoneme_audio(2, amplitude=15))
    assert not np.any(synth.get_phoneme_audio(2, amplitude=0))
    assert not np.any(synth.get_phoneme_audio(0, amplitude=15))


def test_pcm_backend_uses_rate_dependent_playback_length() -> None:
    synth = SSI263PCMSynth(audio_enabled=False)

    slow = synth.get_phoneme_audio(2, amplitude=15, rate=0)
    fast = synth.get_phoneme_audio(2, amplitude=15, rate=15)

    assert len(slow) == playback_length_samples(2, duration=0, rate=0)
    assert len(fast) == playback_length_samples(2, duration=0, rate=15)
    assert len(slow) > len(fast)


def test_pcm_rate_changes_duration_without_changing_pitch() -> None:
    synth = SSI263PCMSynth(audio_enabled=False)

    captured = synth.get_phoneme_audio(2, amplitude=15, rate=8)
    captured_pitch = _dominant_voiced_frequency(captured)
    for rate in (0, 9):
        changed = synth.get_phoneme_audio(2, amplitude=15, rate=rate)
        changed_pitch = _dominant_voiced_frequency(changed)
        assert abs(changed_pitch - captured_pitch) / captured_pitch < 0.03


def test_pcm_pitch_shift_preserves_formant_envelope_and_length() -> None:
    synth = SSI263PCMSynth(audio_enabled=False)
    captured = synth.get_phoneme_audio(2)

    shifted = synth._pitch_shift_psola(captured, 1.15)

    assert len(shifted) == len(captured)
    pitch_ratio = _autocorrelation_voiced_frequency(shifted) / _autocorrelation_voiced_frequency(
        captured
    )
    assert 1.10 < pitch_ratio < 1.20
    envelope_similarity = np.corrcoef(
        _lpc_spectral_envelope(captured),
        _lpc_spectral_envelope(shifted),
    )[0, 1]
    assert envelope_similarity > 0.95


def test_pcm_transition_changes_pitch_without_moving_formants() -> None:
    played: list[np.ndarray] = []

    class Player:
        def play(self, samples: np.ndarray) -> None:
            played.append(samples)

    def state(
        phoneme: int,
        duration: int,
        inflection: int,
    ) -> SSI263State:
        return SSI263State(
            phoneme=phoneme,
            duration=duration,
            inflection=inflection,
            rate=8,
            articulation=5,
            amplitude=15,
            filter_freq=17,
            playback_duration=duration,
            transitioned_inflection=True,
        )

    synth = SSI263PCMSynth(audio_enabled=False)
    synth._player = Player()
    normal = synth.get_phoneme_audio(2)

    synth.play(state(0, 3, 3288))
    assert synth._current_inflection_level == 16.6
    synth.play(state(2, 0, 3288))

    transitioned = played[-1]
    assert synth._current_inflection_level == 19.0
    assert len(transitioned) == len(normal)
    pitch_ratio = _autocorrelation_voiced_frequency(
        transitioned
    ) / _autocorrelation_voiced_frequency(normal)
    assert 1.0 < pitch_ratio < (1024 / 808)
    envelope_similarity = np.corrcoef(
        _lpc_spectral_envelope(normal),
        _lpc_spectral_envelope(transitioned),
    )[0, 1]
    assert envelope_similarity > 0.95

    synth.play(state(2, 0, 3072))
    assert synth._current_inflection_level == 17.5
    synth.play(state(2, 0, 3072))
    assert synth._current_inflection_level == 16.0


def test_pcm_inflection_does_not_impose_pitch_on_unvoiced_capture() -> None:
    synth = SSI263PCMSynth(audio_enabled=False)

    normal = synth.get_phoneme_audio(52)
    transitioned = synth.get_phoneme_audio(
        52,
        inflection=3288,
        transitioned_inflection=True,
    )

    np.testing.assert_array_equal(transitioned, normal)


def test_chip_drives_pcm_backend_on_wake_and_active_phoneme_write() -> None:
    chip = SSI263()
    synth = SSI263PCMSynth(audio_enabled=False)
    chip.set_synth(synth)
    played: list[int] = []
    synth.set_phoneme_callback(played.append)

    chip.write(chip.base_port + chip.REG_DURPHON, 0xC2)
    assert played == []

    chip.write(chip.base_port + chip.REG_CTRLAMP, 0x0F)
    chip.write(chip.base_port + chip.REG_DURPHON, 0xC3)

    assert played == [2, 3]


def test_bns_audio_selects_pcm_backend_by_default() -> None:
    bns = BNS(audio=True)

    assert isinstance(bns.synth, SSI263PCMSynth)
    assert bns.ssi263._synth is bns.synth
