"""Offline speech renderer timing tests."""

import numpy as np

from qns.ssi263 import playback_length_samples
from qns.synth.phonemes import SAMPLE_RATE
from qns.synth.ssi263_pcm import SSI263PCMSynth
from tools.render_speech import CPU_CLOCK_HZ, chip_duration_cycles, render


def _event(cycle: int) -> dict[str, int]:
    return {
        "cycle": cycle,
        "code": 0x02,
        "duration_mode": 3,
        "rate": 8,
        "inflection": 2048,
        "articulation": 5,
        "amplitude": 15,
        "filter_freq": 0xF1,
        "playback_duration": 0,
    }


def test_chip_duration_uses_shared_phoneme_rate_and_playback_mode() -> None:
    expected_samples = playback_length_samples(0x02, duration=0, rate=8)

    assert chip_duration_cycles(0x02, rate=8, playback_duration=0) == int(
        expected_samples * CPU_CLOCK_HZ / SAMPLE_RATE
    )


def test_chip_timing_uses_traced_playback_duration() -> None:
    events = [_event(0), _event(1)]

    render(
        events,
        sample_rate=SAMPLE_RATE,
        backend="pcm",
        tail_seconds=0.01,
        timing="chip",
        force_amplitude=None,
    )

    assert events[1]["cycle"] == chip_duration_cycles(
        events[0]["code"],
        events[0]["rate"],
        events[0]["playback_duration"],
    )


def test_trace_timing_caps_pcm_at_the_next_event(monkeypatch) -> None:
    def identifiable_audio(
        _synth,
        phoneme,
        _amplitude,
        _duration,
        _rate,
    ):
        return np.full(10, phoneme, dtype=np.float32)

    monkeypatch.setattr(
        SSI263PCMSynth,
        "get_phoneme_audio",
        identifiable_audio,
    )
    sample_rate = 1_000
    cycle_span = 2 * CPU_CLOCK_HZ // sample_rate
    first = _event(0)
    first["code"] = 1
    second = _event(cycle_span)
    second["code"] = 2

    output = render(
        [first, second],
        sample_rate=sample_rate,
        backend="pcm",
        tail_seconds=0.005,
        timing="trace",
        force_amplitude=None,
    )

    np.testing.assert_array_equal(output[:2], np.ones(2))
    np.testing.assert_array_equal(output[2:-1], np.full(len(output) - 3, 2))
    assert output[-1] == 0
