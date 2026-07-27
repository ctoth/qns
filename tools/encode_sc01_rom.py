"""Reconstruct an SC-01A phone ROM image from decoded parameters.

The SC-01A mask ROM dump is proprietary and not in this repository, but its
contents are - decoded, in qns/synth/sc01_rom.py.  The decode is lossless for
every field the synthesizer reads, so the 512-byte image can be rebuilt from
it.  That image is what a native MAME-derived core (rusty_tts's retrochip)
needs to run as a conformance oracle for qns/synth/formant.py.

Bits 44-55 and 62-63 of each entry are not read by the decoder and are
emitted as zero, so the result is functionally equivalent to the original
dump rather than byte-identical to it.

    uv run tools/encode_sc01_rom.py sc01a.bin
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qns.synth.sc01_rom import PHONEME_PARAMS  # noqa: E402

# Bit positions each field occupies, listed exactly as the decoder lists
# them.  Placement below inverts the ORIGINAL decoder's LSB-first reading
# (result bit i came from the first-listed position onwards), which is what
# reproduces the real ROM's bytes from the shipped table.  Note that reading
# is done MSB-first by MAME - that mismatch is the bug this reconstruction
# exists to undo, so do not "simplify" the placement to match MAME here.
FIELD_BITS: dict[str, tuple[int, ...]] = {
    "f1": (0, 7, 14, 21),
    "va": (1, 8, 15, 22),
    "f2": (2, 9, 16, 23),
    "fc": (3, 10, 17, 24),
    "f2q": (4, 11, 18, 25),
    "f3": (5, 12, 19, 26),
    "fa": (6, 13, 20, 27),
    "cld": (34, 32, 30, 28),
    "vd": (35, 33, 31, 29),
    "duration": (37, 38, 39, 40, 41, 42, 43),
}

# duration is stored inverted in the ROM
INVERTED_FIELDS = frozenset({"duration"})


def place(value: int, positions: tuple[int, ...], invert: bool) -> int:
    """Scatter a right-aligned field across positions, LSB first.

    Inverse of the shipped table's decode: value bit i went to positions[i].
    """
    width = len(positions)
    if invert:
        value = ~value & ((1 << width) - 1)
    result = 0
    for index, position in enumerate(positions):
        if (value >> index) & 1:
            result |= 1 << position
    return result


def encode_entry(code: int, params: dict) -> int:
    """Build one 64-bit ROM entry for a phoneme."""
    value = (code & 0x3F) << 56
    for field, positions in FIELD_BITS.items():
        value |= place(int(params[field]), positions, field in INVERTED_FIELDS)
    if params["closure"]:
        value |= 1 << 36
    return value


def build_rom() -> bytes:
    """Build the whole 512-byte image, one 8-byte entry per phoneme."""
    image = bytearray()
    for code in range(64):
        image += struct.pack("<Q", encode_entry(code, PHONEME_PARAMS[code]))
    return bytes(image)


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sc01a.bin")
    image = build_rom()
    output.write_bytes(image)
    print(f"Wrote {len(image)} bytes to {output}")


if __name__ == "__main__":
    main()
