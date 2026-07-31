"""Shared audio fitting for the SSI-263 phoneme-end lifecycle."""

from __future__ import annotations

import numpy as np


def conform_audio_to_length(samples: np.ndarray, sample_count: int) -> np.ndarray:
    """Fit modeled phoneme content to its exact scheduled sample count.

    Short content is stretched across the requested span so conformance does
    not create a silent tail.  Long content is truncated because only its
    leading scheduled portion can play before the next phoneme.
    """
    sample_count = max(0, sample_count)
    if sample_count <= len(samples):
        return samples[:sample_count]
    if len(samples) == 0:
        return np.zeros(sample_count, dtype=samples.dtype)
    if len(samples) == 1:
        return np.full(sample_count, samples[0], dtype=samples.dtype)

    source_positions = np.arange(len(samples))
    target_positions = np.linspace(0.0, len(samples) - 1, sample_count)
    return np.interp(target_positions, source_positions, samples).astype(
        samples.dtype,
        copy=False,
    )


def fit_audio_to_elapsed(samples: np.ndarray, elapsed_samples: int) -> np.ndarray:
    """Return exactly the audio span for elapsed emulated speech time.

    Superseded phonemes lose their unplayed tail.  A phoneme held longer
    than the available modeled content retains that content and fills the
    remaining emulated time with silence.
    """
    elapsed_samples = max(0, elapsed_samples)
    if elapsed_samples <= len(samples):
        return samples[:elapsed_samples]
    return np.pad(samples, (0, elapsed_samples - len(samples)))
