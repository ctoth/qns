"""Tests for the fixed-capture SSI-263 audio backend."""

import numpy as np

from qns.bns import BNS
from qns.ssi263 import SSI263
from qns.synth.phonemes import get_phoneme_samples
from qns.synth.ssi263_pcm import SSI263PCMSynth


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
