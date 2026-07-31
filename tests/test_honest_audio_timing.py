"""Regressions for honest SSI-263 phoneme-end and trace timing."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from qns.ssi263 import SSI263, SSI263State, playback_length_samples
from qns.synth import SSI263LPCSynth, SSI263PCMSynth, SSI263Synth
from qns.synth.phonemes import SAMPLE_RATE

FIXTURES = Path(__file__).with_name("fixtures")


def _state(
    phoneme: int,
    *,
    duration: int = 0,
    rate: int = 8,
    amplitude: int = 15,
) -> SSI263State:
    return SSI263State(
        phoneme=phoneme,
        duration=duration,
        inflection=2048,
        rate=rate,
        articulation=5,
        amplitude=amplitude,
        filter_freq=0xF1,
        playback_duration=duration,
    )


class _Player:
    def __init__(self) -> None:
        self.pieces: list[np.ndarray] = []

    def play(self, samples: np.ndarray) -> None:
        self.pieces.append(samples)

    def realtime_lead_seconds(self) -> float:
        return 0.0


def test_chip_ends_superseded_phoneme_at_exact_elapsed_sample_count() -> None:
    player = _Player()
    backend = SSI263PCMSynth(audio_enabled=False)
    backend._player = player
    chip = SSI263(clock=SAMPLE_RATE)
    chip.set_synth(backend)
    chip.write(chip.base_port + chip.REG_DURPHON, 0xC8)
    chip.write(chip.base_port + chip.REG_CTRLAMP, 0x0F)

    chip.set_cycle_count(500)
    chip.write(chip.base_port + chip.REG_DURPHON, 0xC9)

    assert len(player.pieces) == 1
    assert len(player.pieces[0]) == 500


@pytest.mark.parametrize(
    "backend",
    [
        pytest.param(SSI263PCMSynth(audio_enabled=False), id="pcm"),
        pytest.param(SSI263LPCSynth(audio_enabled=False), id="lpc"),
        pytest.param(SSI263Synth(audio_enabled=False), id="formant"),
    ],
)
def test_completed_silence_queues_full_modeled_zeros(backend) -> None:
    player = _Player()
    backend._player = player
    expected = playback_length_samples(0, duration=0, rate=9)
    chip = SSI263(clock=SAMPLE_RATE)
    chip.set_synth(backend)
    chip.write(chip.base_port + chip.REG_DURPHON, 0x00)
    chip.write(chip.base_port + chip.REG_RATEINF, 9 << 4)
    chip.write(chip.base_port + chip.REG_CTRLAMP, 0x0F)

    chip.check_pending_irq(expected)

    assert len(player.pieces) == 1
    assert len(player.pieces[0]) == expected
    assert not np.any(player.pieces[0])


def test_non_silence_end_preserves_content_and_requested_sample_count() -> None:
    backend = SSI263PCMSynth(audio_enabled=False)
    player = _Player()
    backend._player = player
    state = _state(0x08, duration=0, rate=8)
    modeled = backend.get_phoneme_audio(
        state.phoneme,
        state.amplitude,
        state.playback_duration,
        state.rate,
        state.inflection,
        state.transitioned_inflection,
    )

    backend.play(state)
    backend.end_phoneme(500)

    assert len(player.pieces[0]) == 500
    np.testing.assert_array_equal(player.pieces[0], modeled[:500])


def test_pause_heavy_player_lead_never_jumps_to_prime_mid_utterance() -> None:
    from qns.synth.player import AudioPlayer

    player = AudioPlayer(sample_rate=1_000, blocksize=100, prime_ms=250)
    backend = SSI263PCMSynth(audio_enabled=False)
    backend._player = player
    output = np.empty((100, 1), dtype=np.float32)

    backend.play(_state(0x08))
    backend.end_phoneme(100)
    for _ in range(5):
        player._audio_callback(output, 100, None, None)
        backend.play(_state(0))
        backend.end_phoneme(100)
        assert player.realtime_lead_seconds() < 0.25


def _silent_spans(samples: np.ndarray) -> list[int]:
    silent = np.abs(samples) <= 1e-8
    changes = np.flatnonzero(np.diff(np.pad(silent.astype(np.int8), (1, 1))))
    return [
        int(stop - start)
        for start, stop in changes.reshape(-1, 2)
        if start > 0 and stop < len(samples)
    ]


def test_trace_renderer_preserves_cycle_span_and_internal_gaps() -> None:
    from tools.render_backend import CPU_CLOCK_HZ, render_rows

    with (FIXTURES / "greeting_trace.csv").open(encoding="ascii", newline="") as handle:
        rows = list(csv.DictReader(handle))

    backend = SSI263PCMSynth(audio_enabled=False)
    samples = render_rows(backend, rows, "pcm")
    expected = int((int(rows[-1]["cycle"]) - int(rows[0]["cycle"])) * SAMPLE_RATE / CPU_CLOCK_HZ)

    assert abs(len(samples) - expected) <= 2048
    assert sum(span >= int(0.09 * SAMPLE_RATE) for span in _silent_spans(samples)) >= 4
