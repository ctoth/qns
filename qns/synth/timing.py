"""Shared audio fitting for the SSI-263 phoneme-end lifecycle."""

from __future__ import annotations

import numpy as np


def _seamless_loop(samples: np.ndarray) -> tuple[np.ndarray, float]:
    """Return a cyclic copy whose joins stay within the source's native steps."""
    if len(samples) < 2:
        return samples.copy(), 0.0

    source = samples.astype(np.float64)
    native_max = float(np.abs(np.diff(source)).max())
    boundary = float(source[-1])
    tolerance = native_max * 1e-6 + 1e-12

    for overlap in range(1, len(samples)):
        ramp = (np.arange(overlap, dtype=np.float64) + 1.0) / (overlap + 1.0)
        loop = samples.copy()
        loop[:overlap] = (boundary * (1.0 - ramp) + source[:overlap] * ramp).astype(samples.dtype)
        joined = np.concatenate(([boundary], loop.astype(np.float64)))
        if float(np.abs(np.diff(joined)).max()) <= native_max + tolerance:
            return loop, native_max

    return samples.copy(), native_max


def _energy_matched_extension(samples: np.ndarray, sample_count: int) -> np.ndarray:
    """Select a seam-safe cyclic window with the source's average energy."""
    loop, native_max = _seamless_loop(samples)
    loop_length = len(loop)
    cycles, remainder = divmod(sample_count, loop_length)

    squared = loop.astype(np.float64) ** 2
    base_energy = cycles * float(squared.sum())
    if remainder:
        doubled = np.concatenate((squared, squared))
        prefix = np.concatenate(([0.0], np.cumsum(doubled)))
        offsets = np.arange(loop_length)
        energies = base_energy + prefix[offsets + remainder] - prefix[offsets]
    else:
        energies = np.full(loop_length, base_energy)

    tolerance = native_max * 1e-6 + 1e-12
    valid_offsets = np.flatnonzero(
        np.abs(loop.astype(np.float64) - float(samples[-1])) <= native_max + tolerance
    )
    target_energy = float(np.mean(samples.astype(np.float64) ** 2)) * sample_count
    offset = int(valid_offsets[np.argmin(np.abs(energies[valid_offsets] - target_energy))])
    indices = (offset + np.arange(sample_count)) % loop_length
    return loop[indices]


def conform_audio_to_length(samples: np.ndarray, sample_count: int) -> np.ndarray:
    """Fit modeled phoneme content to its exact scheduled sample count.

    Short content keeps the original samples intact, then selects an
    energy-matched cyclic window from a seam-safe copy at the original sample
    rate.  This fills the requested span without a silent tail, amplitude
    scaling, pitch-changing resampling, clipping, or click-sized seams.  Long
    content is truncated because only its leading scheduled portion can play
    before the next phoneme.
    """
    sample_count = max(0, sample_count)
    if sample_count <= len(samples):
        return samples[:sample_count]
    if len(samples) == 0:
        return np.zeros(sample_count, dtype=samples.dtype)
    extension = _energy_matched_extension(samples, sample_count - len(samples))
    return np.concatenate((samples, extension))


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
