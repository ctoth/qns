"""SSI-263 phoneme captures loaded from the generated compact archive."""

from pathlib import Path

import numpy as np

_ARCHIVE = Path(__file__).with_name("phonemes.npz")

with np.load(_ARCHIVE, allow_pickle=False) as _archive:
    SAMPLE_RATE = int(_archive["sample_rate"])
    _phoneme_info = _archive["phoneme_info"].copy()
    PHONEME_DATA = _archive["phoneme_data"].copy()

if _phoneme_info.shape != (62, 2) or _phoneme_info.dtype != np.dtype("<u4"):
    raise ValueError(f"invalid phoneme metadata in {_ARCHIVE}")
if PHONEME_DATA.shape != (156_566,) or PHONEME_DATA.dtype != np.dtype("<i2"):
    raise ValueError(f"invalid phoneme sample data in {_ARCHIVE}")

PHONEME_INFO: list[tuple[int, int]] = [
    (int(offset), int(length)) for offset, length in _phoneme_info
]
del _phoneme_info


def get_phoneme_samples(phoneme_index: int) -> np.ndarray:
    """Return the signed 16-bit samples for one phoneme capture."""
    if not 0 <= phoneme_index < len(PHONEME_INFO):
        raise ValueError(f"Invalid phoneme index {phoneme_index}, must be 0-61")

    offset, length = PHONEME_INFO[phoneme_index]
    return PHONEME_DATA[offset : offset + length]
