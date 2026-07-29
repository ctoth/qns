"""Tests for the fixed-capture SSI-263 audio backend."""

import numpy as np

from qns.bns import BNS
from qns.ssi263 import SSI263, playback_length_samples
from qns.synth.phonemes import get_phoneme_samples
from qns.synth.ssi263_pcm import SSI263PCMSynth


def _dominant_voiced_frequency(samples: np.ndarray) -> float:
    """Return the strongest low-frequency component of a voiced capture."""
    windowed = samples * np.hanning(len(samples))
    spectrum = np.abs(np.fft.rfft(windowed))
    frequencies = np.fft.rfftfreq(len(samples), 1 / 22050)
    voiced = (frequencies >= 70) & (frequencies <= 350)
    return float(frequencies[voiced][np.argmax(spectrum[voiced])])


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
