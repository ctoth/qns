"""Extract compact phoneme samples from AppleWin ``SSI263Phonemes.h``.

The generated NPZ is a release artifact tracked in the repository. Its
semantic contents are pinned by tests; ZIP container bytes are not.

Usage:
    uv run python tools/extract_phonemes.py [path/to/SSI263Phonemes.h]
"""

import re
import sys
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22_050
DEFAULT_HEADERS = (
    Path.home() / "src" / "AppleWin" / "source" / "SSI263Phonemes.h",
    Path(r"C:\Users\Q\src\AppleWin\source\SSI263Phonemes.h"),
)
OUTPUT_FILE = Path(__file__).parent.parent / "qns" / "synth" / "phonemes.npz"


def find_header() -> Path:
    """Locate AppleWin's SSI263Phonemes.h, or explain how to get it."""
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    for candidate in DEFAULT_HEADERS:
        if candidate.exists():
            return candidate
    raise SystemExit(
        "AppleWin's SSI263Phonemes.h not found. Pass its path, or clone it:\n"
        "  git clone --depth 1 https://github.com/AppleWin/AppleWin ~/src/AppleWin"
    )


def extract_phoneme_info(text: str) -> list[tuple[int, int]]:
    """Parse g_nPhonemeInfo into (offset_samples, length_samples) pairs."""
    match = re.search(r"g_nPhonemeInfo\[62\]\s*=\s*\{([^;]+)\};", text, re.DOTALL)
    if not match:
        raise ValueError("Could not find g_nPhonemeInfo")

    pairs = re.findall(
        r"\{(0x[0-9A-Fa-f]+),(0x[0-9A-Fa-f]+)\}",
        match.group(1),
    )
    info = [(int(offset, 16), int(length, 16)) for offset, length in pairs]

    if len(info) != 62:
        raise ValueError(f"expected 62 phonemes, found {len(info)}")
    total = info[-1][0] + info[-1][1]
    lengths_total = sum(length for _, length in info)
    if total != lengths_total:
        raise ValueError(
            f"phoneme table is not contiguous: spans {total} samples but "
            f"lengths sum to {lengths_total}"
        )
    return info


def extract_phoneme_data(text: str) -> list[int]:
    """Parse g_nPhonemeData into signed 16-bit samples."""
    match = re.search(r"g_nPhonemeData\[156566\]\s*=\s*\{([^;]+)\};", text, re.DOTALL)
    if not match:
        raise ValueError("Could not find g_nPhonemeData")

    values = re.findall(r"0x([0-9A-Fa-f]+)", match.group(1))
    samples = []
    for value in values:
        unsigned = int(value, 16)
        samples.append(unsigned if unsigned < 32768 else unsigned - 65536)

    if len(samples) != 156_566:
        raise ValueError(f"expected 156566 samples, found {len(samples)}")
    return samples


def write_archive(
    output: Path,
    info: list[tuple[int, int]],
    data: list[int],
) -> None:
    """Write the compact, typed phoneme archive."""
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        sample_rate=np.asarray(SAMPLE_RATE, dtype="<u4"),
        phoneme_info=np.asarray(info, dtype="<u4"),
        phoneme_data=np.asarray(data, dtype="<i2"),
    )


def main() -> None:
    header = find_header()
    print(f"Reading {header}...")
    text = header.read_text(encoding="utf-8")

    info = extract_phoneme_info(text)
    data = extract_phoneme_data(text)
    write_archive(OUTPUT_FILE, info, data)

    print(f"Wrote {OUTPUT_FILE}")
    print(f"  Phonemes: {len(info)}")
    print(f"  Samples: {len(data)}")
    print(f"  Sample rate: {SAMPLE_RATE} Hz")


if __name__ == "__main__":
    main()
