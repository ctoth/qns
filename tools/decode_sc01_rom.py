#!/usr/bin/env python
"""Decode SC-01/SC-01A Votrax ROM to extract phoneme parameters.

The ROM contains 64 8-byte entries with formant synthesis parameters.
Based on MAME's votrax.cpp decoding logic.
"""

import struct
import sys
from pathlib import Path

# SC-01 phoneme names (from MAME votrax.cpp)
PHONE_NAMES = [
    "EH3", "EH2", "EH1", "PA0", "DT",  "A1",  "A2",  "ZH",
    "AH2", "I3",  "I2",  "I1",  "M",   "N",   "B",   "V",
    "CH",  "SH",  "Z",   "AW1", "NG",  "AH1", "OO1", "OO",
    "L",   "K",   "J",   "H",   "G",   "F",   "D",   "S",
    "A",   "AY",  "Y1",  "UH3", "AH",  "P",   "O",   "I",
    "U",   "Y",   "T",   "R",   "E",   "W",   "AE",  "AE1",
    "AW2", "UH2", "UH1", "UH",  "O2",  "O1",  "IU",  "U1",
    "THV", "TH",  "ER",  "EH",  "E1",  "AW",  "PA1", "STOP",
]


def bitswap(val: int, *bits: int) -> int:
    """Extract bits from val at specified positions, LSB first."""
    result = 0
    for i, bit in enumerate(bits):
        if val & (1 << bit):
            result |= (1 << i)
    return result


def decode_phoneme(data: bytes) -> dict:
    """Decode an 8-byte phoneme entry from the ROM.

    Returns dict with all parameters.
    """
    # ROM is stored little-endian as 64-bit value
    val = struct.unpack('<Q', data)[0]

    # Extract phoneme ID from bits 61:56
    phone_id = (val >> 56) & 0x3F

    # Extract parameters using MAME's bitswap patterns
    # These are 4-bit values extracted from scattered bits
    f1  = bitswap(val, 0, 7, 14, 21)      # Formant 1 frequency
    va  = bitswap(val, 1, 8, 15, 22)      # Voice amplitude
    f2  = bitswap(val, 2, 9, 16, 23)      # Formant 2 frequency (5 bits actually)
    fc  = bitswap(val, 3, 10, 17, 24)     # F2 noise coefficient
    f2q = bitswap(val, 4, 11, 18, 25)     # Formant 2 Q
    f3  = bitswap(val, 5, 12, 19, 26)     # Formant 3 frequency
    fa  = bitswap(val, 6, 13, 20, 27)     # Noise (fricative) amplitude

    # Closure and voice delays have inverted bit order
    cld = bitswap(val, 34, 32, 30, 28)    # Closure delay in ticks
    vd  = bitswap(val, 35, 33, 31, 29)    # Voice delay in ticks

    # Single bit for closure
    closure = bool(val & (1 << 36))

    # Duration is 7 bits, inverted
    duration = bitswap(~val, 37, 38, 39, 40, 41, 42, 43)

    return {
        'id': phone_id,
        'name': PHONE_NAMES[phone_id] if phone_id < 64 else '?',
        'f1': f1,
        'f2': f2,
        'f2q': f2q,
        'f3': f3,
        'va': va,      # voice amplitude
        'fa': fa,      # noise amplitude
        'fc': fc,      # f2 noise coefficient
        'vd': vd,      # voice delay
        'cld': cld,    # closure delay
        'closure': closure,
        'duration': duration,
    }


def decode_rom(rom_path: Path) -> list[dict]:
    """Decode entire SC-01 ROM file."""
    data = rom_path.read_bytes()
    if len(data) != 512:
        raise ValueError(f"Expected 512 bytes, got {len(data)}")

    phonemes = []
    for i in range(64):
        entry = data[i*8:(i+1)*8]
        phoneme = decode_phoneme(entry)
        phonemes.append(phoneme)

    # Sort by phoneme ID
    phonemes.sort(key=lambda p: p['id'])
    return phonemes


def main():
    rom_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sc01a.bin")

    if not rom_path.exists():
        print(f"ROM file not found: {rom_path}")
        sys.exit(1)

    phonemes = decode_rom(rom_path)

    print(f"Decoded {len(phonemes)} phonemes from {rom_path.name}")
    print()
    print(
        f"{'ID':>4} {'Name':<5} {'F1':>3} {'F2':>3} {'F2Q':>3} "
        f"{'F3':>3} {'VA':>3} {'FA':>3} {'FC':>3} {'VD':>3} "
        f"{'CLD':>3} {'CL':>3} {'DUR':>4}"
    )
    print("-" * 60)

    for p in phonemes:
        print(f"0x{p['id']:02X} {p['name']:<5} {p['f1']:3} {p['f2']:3} {p['f2q']:3} {p['f3']:3} "
              f"{p['va']:3} {p['fa']:3} {p['fc']:3} {p['vd']:3} {p['cld']:3} "
              f"{'Y' if p['closure'] else 'N':>3} {p['duration']:4}")

    # Generate Python dict for embedding
    print("\n\n# Python phoneme data for embedding:")
    print("PHONEME_PARAMS = {")
    for p in phonemes:
        print(f"    0x{p['id']:02X}: {{"
              f"'name': {p['name']!r}, "
              f"'f1': {p['f1']}, 'f2': {p['f2']}, 'f2q': {p['f2q']}, 'f3': {p['f3']}, "
              f"'va': {p['va']}, 'fa': {p['fa']}, 'fc': {p['fc']}, "
              f"'vd': {p['vd']}, 'cld': {p['cld']}, "
              f"'closure': {p['closure']}, 'duration': {p['duration']}}},")
    print("}")


if __name__ == "__main__":
    main()
