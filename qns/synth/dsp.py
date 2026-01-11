"""SSI-263 DSP Processing Functions.

Pure functions for audio processing:
- Amplitude scaling
- Filter (resonance)
- Time stretching (duration modes)
- Pitch shifting (inflection)
"""

import numpy as np


def apply_amplitude(samples: np.ndarray, amplitude: int) -> np.ndarray:
    """Scale sample amplitude.

    Args:
        samples: Input samples (int16)
        amplitude: 4-bit amplitude (0-15), 15 = full volume

    Returns:
        Scaled samples (int16)
    """
    if amplitude == 0:
        return np.zeros(len(samples), dtype=np.int16)
    if amplitude == 15:
        return samples.copy()

    # Linear scaling
    scale = amplitude / 15.0
    return (samples * scale).astype(np.int16)


def apply_filter(samples: np.ndarray, filter_freq: int) -> np.ndarray:
    """Apply resonance filter.

    Args:
        samples: Input samples (int16)
        filter_freq: 8-bit filter value (0-255), 0xFF = silence

    Returns:
        Filtered samples (int16)
    """
    if filter_freq == 0xFF:
        return np.zeros(len(samples), dtype=np.int16)

    # For now, pass through unchanged (filter implementation TBD)
    # Could implement a simple low-pass IIR filter here
    return samples.copy()


def time_stretch(samples: np.ndarray, rate: int, duration: int) -> np.ndarray:
    """Adjust playback duration via sample averaging.

    From AppleWin SSI263.cpp:
    - DUR=0: no averaging (1 sample)
    - DUR=1: no averaging with skip (faster)
    - DUR=2: average 2 samples
    - DUR=3: average 4 samples

    Args:
        samples: Input samples (int16)
        rate: 4-bit rate (0-15), not used yet
        duration: 2-bit duration mode (0-3)

    Returns:
        Time-stretched samples (int16)
    """
    if duration == 0 or duration == 1:
        # No averaging
        return samples.copy()

    # Averaging mode
    avg_count = 2 if duration == 2 else 4

    # Calculate output length
    out_len = len(samples) // avg_count
    if out_len == 0:
        return samples.copy()

    # Average samples
    result = np.zeros(out_len, dtype=np.int32)
    for i in range(avg_count):
        result += samples[i : i + out_len * avg_count : avg_count].astype(np.int32)
    result = (result // avg_count).astype(np.int16)

    return result


def pitch_shift(samples: np.ndarray, inflection: int) -> np.ndarray:
    """Shift pitch via resampling.

    Args:
        samples: Input samples (int16)
        inflection: 12-bit inflection value (0-4095)
            2048 = neutral (no pitch change)
            Higher = higher pitch (fewer samples)
            Lower = lower pitch (more samples)

    Returns:
        Pitch-shifted samples (int16)
    """
    # Calculate pitch ratio
    # Inflection 2048 = neutral, range approximately 0.5x to 2.0x
    ratio = 1.0 + (inflection - 2048) / 4096.0

    if abs(ratio - 1.0) < 0.01:
        # Close enough to neutral, no change
        return samples.copy()

    # Resample using linear interpolation
    old_len = len(samples)
    new_len = int(old_len / ratio)
    if new_len < 1:
        new_len = 1

    # Create new sample positions
    old_indices = np.linspace(0, old_len - 1, new_len)

    # Interpolate
    result = np.interp(old_indices, np.arange(old_len), samples.astype(np.float64))

    return result.astype(np.int16)
