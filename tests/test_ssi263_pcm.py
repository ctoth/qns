"""Tests for the fixed-capture SSI-263 audio backend."""

import numpy as np

from qns.bns import BNS
from qns.synth.phonemes import get_phoneme_samples
from qns.synth.ssi263_pcm import SSI263PCMState, SSI263PCMSynth


def test_pcm_state_matches_chip_reset() -> None:
    state = SSI263PCMState()

    assert state.phoneme == 0
    assert state.duration == 3
    assert state.inflection == 0
    assert state.rate == 0
    assert state.amplitude == 0
    assert state.filter_freq == 0xFF
    assert state.control is True


def test_pcm_backend_mirrors_all_register_fields() -> None:
    synth = SSI263PCMSynth(audio_enabled=False)

    synth.write_durphon(0x85)
    synth.write_inflect(0xA5)
    synth.write_rateinf(0xB3)
    synth.write_ctrlamp(0x6C)
    synth.write_filter(0x42)

    assert synth.state.phoneme == 5
    assert synth.state.duration == 2
    assert synth.state.inflection == 0x52B
    assert synth.state.rate == 0x0B
    assert synth.state.control is False
    assert synth.state.articulation == 6
    assert synth.state.amplitude == 12
    assert synth.state.filter_freq == 0x42


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


def test_pcm_backend_plays_on_wake_and_active_phoneme_write() -> None:
    synth = SSI263PCMSynth(audio_enabled=False)
    played: list[int] = []
    synth.set_phoneme_callback(played.append)

    synth.write_durphon(0xC2)
    assert played == []

    synth.write_ctrlamp(0x0F)
    synth.write_durphon(0xC3)

    assert played == [2, 3]


def test_bns_audio_selects_pcm_backend_directly() -> None:
    bns = BNS(audio=True)

    assert isinstance(bns.synth, SSI263PCMSynth)
    assert bns.ssi263._synth is bns.synth
