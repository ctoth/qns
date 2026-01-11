"""Extract phoneme samples from AppleWin SSI263Phonemes.h.

Reads the AppleWin header file and generates qns/synth/phonemes.py
with numpy arrays for phoneme data.

Usage:
    uv run python tools/extract_phonemes.py
"""

import re
from pathlib import Path

APPLEWIN_HEADER = Path(r"C:\Users\Q\src\AppleWin\source\SSI263Phonemes.h")
OUTPUT_FILE = Path(__file__).parent.parent / "qns" / "synth" / "phonemes.py"


def extract_phoneme_info(text: str) -> list[tuple[int, int]]:
    """Parse g_nPhonemeInfo array - returns (offset_samples, length_samples) pairs."""
    # Find the array content between { and };
    match = re.search(r"g_nPhonemeInfo\[62\]\s*=\s*\{([^;]+)\};", text, re.DOTALL)
    if not match:
        raise ValueError("Could not find g_nPhonemeInfo")

    content = match.group(1)
    # Parse {offset,length} pairs
    pairs = re.findall(r"\{(0x[0-9A-Fa-f]+),(0x[0-9A-Fa-f]+)\}", content)

    # Convert byte offsets to sample indices (divide by 2)
    return [(int(offset, 16) // 2, int(length, 16) // 2) for offset, length in pairs]


def extract_phoneme_data(text: str) -> list[int]:
    """Parse g_nPhonemeData array - returns signed 16-bit samples."""
    # Find the array content
    match = re.search(r"g_nPhonemeData\[156566\]\s*=\s*\{([^;]+)\};", text, re.DOTALL)
    if not match:
        raise ValueError("Could not find g_nPhonemeData")

    content = match.group(1)
    # Parse hex values
    values = re.findall(r"0x([0-9A-Fa-f]+)", content)

    # Convert unsigned 16-bit to signed
    samples = []
    for v in values:
        unsigned = int(v, 16)
        signed = unsigned if unsigned < 32768 else unsigned - 65536
        samples.append(signed)

    return samples


def generate_phonemes_py(info: list[tuple[int, int]], data: list[int]) -> str:
    """Generate the phonemes.py module content."""
    lines = [
        '"""SSI-263 Phoneme Sample Data.',
        "",
        "Auto-generated from AppleWin SSI263Phonemes.h",
        "Do not edit manually - regenerate with tools/extract_phonemes.py",
        '"""',
        "",
        "import numpy as np",
        "",
        "# Sample rate for all phoneme data",
        "SAMPLE_RATE = 22050",
        "",
        "# Phoneme info: (offset_in_samples, length_in_samples)",
        f"# {len(info)} phonemes total",
        "PHONEME_INFO: list[tuple[int, int]] = [",
    ]

    for offset, length in info:
        lines.append(f"    ({offset}, {length}),")

    lines.append("]")
    lines.append("")

    # For the data, we'll use a more compact representation
    lines.append(f"# Raw 16-bit signed samples ({len(data)} total)")
    lines.append("# Stored as numpy array for efficient slicing")
    lines.append("_PHONEME_DATA_RAW = (")

    # Write data in chunks of 16 values per line for readability
    chunk_size = 16
    for i in range(0, len(data), chunk_size):
        chunk = data[i : i + chunk_size]
        line = "    " + ",".join(str(v) for v in chunk) + ","
        lines.append(line)

    lines.append(")")
    lines.append("")
    lines.append("PHONEME_DATA = np.array(_PHONEME_DATA_RAW, dtype=np.int16)")
    lines.append("")
    lines.append("")
    lines.append("def get_phoneme_samples(phoneme_index: int) -> np.ndarray:")
    lines.append('    """Get samples for a specific phoneme.')
    lines.append("")
    lines.append("    Args:")
    lines.append("        phoneme_index: Phoneme index (0-61)")
    lines.append("")
    lines.append("    Returns:")
    lines.append("        numpy array of signed 16-bit samples")
    lines.append('    """')
    lines.append("    if not 0 <= phoneme_index < len(PHONEME_INFO):")
    lines.append(
        f'        raise ValueError(f"Invalid phoneme index {{phoneme_index}}, must be 0-{len(info) - 1}")'
    )
    lines.append("")
    lines.append("    offset, length = PHONEME_INFO[phoneme_index]")
    lines.append("    return PHONEME_DATA[offset : offset + length]")
    lines.append("")

    return "\n".join(lines)


def main():
    print(f"Reading {APPLEWIN_HEADER}...")
    text = APPLEWIN_HEADER.read_text()

    print("Extracting phoneme info...")
    info = extract_phoneme_info(text)
    print(f"  Found {len(info)} phonemes")

    print("Extracting phoneme data...")
    data = extract_phoneme_data(text)
    print(f"  Found {len(data)} samples")

    print(f"Generating {OUTPUT_FILE}...")
    content = generate_phonemes_py(info, data)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(content)

    print("Done!")
    print(f"  Phonemes: {len(info)}")
    print(f"  Samples: {len(data)}")
    print(f"  Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
