"""Offline backend trace renderer regressions."""

from __future__ import annotations

import numpy as np

from qns.ssi263 import playback_length_samples
from qns.synth import SSI263PCMSynth
from tools.render_backend import render_row


def _row(*, rate: int | None = 9, cycle: int = 0) -> dict[str, str]:
    row = {
        "cycle": str(cycle),
        "code": "8",
        "duration_mode": "0",
        "inflection": "2048",
        "articulation": "5",
        "amplitude": "15",
        "filter_freq": "241",
        "playback_duration": "0",
    }
    if rate is not None:
        row["rate"] = str(rate)
    return row


def test_render_row_honors_explicit_rate_nine() -> None:
    backend = SSI263PCMSynth(audio_enabled=False)

    samples = render_row(backend, _row(rate=9), "pcm")

    assert len(samples) == playback_length_samples(8, duration=0, rate=9)


def test_legacy_trace_uses_rate_eight_and_warns_once(capsys) -> None:
    from tools.render_backend import render_rows

    rows = [_row(rate=None, cycle=0), _row(rate=None, cycle=12_288)]
    backend = SSI263PCMSynth(audio_enabled=False)

    samples = render_rows(backend, rows, "pcm")

    assert np.any(samples)
    stderr = capsys.readouterr().err
    assert len(stderr.splitlines()) == 1
    assert "rate" in stderr
    assert "8" in stderr


def test_lpc_track_row_length_honors_rate_and_legacy_fallback(capsys) -> None:
    from tools.lpc_track_experiment import playback_samples_for_row

    assert playback_samples_for_row(_row(rate=9)) == playback_length_samples(
        8,
        duration=0,
        rate=9,
    )
    assert playback_samples_for_row(_row(rate=None)) == playback_length_samples(
        8,
        duration=0,
        rate=8,
    )
    assert "rate" in capsys.readouterr().err
