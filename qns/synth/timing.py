"""Shared audio fitting for the SSI-263 phoneme-end lifecycle."""

from __future__ import annotations

import numpy as np


def conform_audio_to_length(samples: np.ndarray, sample_count: int) -> np.ndarray:
    """Fit modeled phoneme content to its exact scheduled sample count.

    Short content repeats its closing half at the original sample rate with
    crossfaded joins, which fills the requested span without a silent tail,
    pitch-changing resampling, or click-sized seams.  Long content is
    truncated because only its leading scheduled portion can play before the
    next phoneme.
    """
    sample_count = max(0, sample_count)
    if sample_count <= len(samples):
        return samples[:sample_count]
    if len(samples) == 0:
        return np.zeros(sample_count, dtype=samples.dtype)

    closing_samples = samples[len(samples) // 2 :]
    overlap = min(128, len(closing_samples) // 4)
    if overlap == 0:
        extension = np.resize(closing_samples, sample_count - len(samples))
        return np.concatenate((samples, extension))

    ramp = np.linspace(0.0, 1.0, overlap).astype(samples.dtype)
    conformed = samples.copy()
    while len(conformed) < sample_count:
        conformed[-overlap:] = (
            conformed[-overlap:] * (1.0 - ramp) + closing_samples[:overlap] * ramp
        )
        conformed = np.concatenate((conformed, closing_samples[overlap:]))
    return conformed[:sample_count]


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
