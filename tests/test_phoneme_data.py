"""Semantic authority for the compact AppleWin SSI-263 capture archive."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from tools.extract_phonemes import (
    DEFAULT_HEADERS,
    extract_phoneme_data,
    extract_phoneme_info,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PATH = REPO_ROOT / "qns" / "synth" / "phonemes.npz"
LOADER_PATH = REPO_ROOT / "qns" / "synth" / "phonemes.py"
EXPECTED_SEMANTIC_SHA256 = "1c417cae9bd0d6d599858bbdf9e865e8941df1655b1d34614e9a32b9773189ac"


def _semantic_checksum(
    sample_rate: int,
    info: np.ndarray,
    data: np.ndarray,
) -> str:
    digest = hashlib.sha256()
    digest.update(np.asarray(sample_rate, dtype="<u4").tobytes())
    digest.update(np.asarray(info, dtype="<u4").tobytes())
    digest.update(np.asarray(data, dtype="<i2").tobytes())
    return digest.hexdigest()


def test_compact_archive_preserves_every_capture_and_metadata_field() -> None:
    from qns.synth.phonemes import PHONEME_DATA, PHONEME_INFO, SAMPLE_RATE

    assert ARCHIVE_PATH.is_file()
    with np.load(ARCHIVE_PATH, allow_pickle=False) as archive:
        archived_rate = int(archive["sample_rate"])
        archived_info = archive["phoneme_info"]
        archived_data = archive["phoneme_data"]

        assert archived_rate == SAMPLE_RATE == 22_050
        assert archived_info.dtype == np.dtype("<u4")
        assert archived_data.dtype == np.dtype("<i2")
        assert archived_info.shape == (62, 2)
        assert archived_data.shape == (156_566,)
        assert np.array_equal(archived_info, np.asarray(PHONEME_INFO))
        assert np.array_equal(archived_data, PHONEME_DATA)
        assert (
            _semantic_checksum(archived_rate, archived_info, archived_data)
            == EXPECTED_SEMANTIC_SHA256
        )

    assert ARCHIVE_PATH.stat().st_size < 512 * 1024
    assert LOADER_PATH.stat().st_size < 8 * 1024


def test_regeneration_semantically_matches_shipped_archive() -> None:
    header = next((candidate for candidate in DEFAULT_HEADERS if candidate.is_file()), None)
    if header is None:
        pytest.skip("AppleWin SSI263Phonemes.h authority is absent")

    text = header.read_text(encoding="utf-8")
    regenerated_info = np.asarray(extract_phoneme_info(text), dtype="<u4")
    regenerated_data = np.asarray(extract_phoneme_data(text), dtype="<i2")

    with np.load(ARCHIVE_PATH, allow_pickle=False) as archive:
        assert int(archive["sample_rate"]) == 22_050
        assert np.array_equal(archive["phoneme_info"], regenerated_info)
        assert np.array_equal(archive["phoneme_data"], regenerated_data)
