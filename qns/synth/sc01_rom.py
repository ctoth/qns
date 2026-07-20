"""SC-01A Votrax phoneme parameters.

Decoded from sc01a.bin ROM using tools/decode_sc01_rom.py.
These parameters control the formant synthesizer.

Parameters per phoneme:
    f1, f2, f3: Formant frequencies (4-bit, 0-15)
    f2q: Formant 2 Q/resonance (4-bit)
    va: Voice amplitude (4-bit, 0=unvoiced, 15=full)
    fa: Fricative/noise amplitude (4-bit)
    fc: F2 noise coefficient (4-bit)
    vd: Voice delay in ticks (4-bit)
    cld: Closure delay in ticks (4-bit)
    closure: Whether phoneme has silent stop (bool)
    duration: Base duration units (7-bit, 0-127)
"""

from typing import TypedDict


class PhonemeParams(TypedDict):
    """Type definition for phoneme parameters."""

    name: str
    f1: int
    f2: int
    f2q: int
    f3: int
    va: int
    fa: int
    fc: int
    vd: int
    cld: int
    closure: bool
    duration: int


# SC-01 phoneme names (matches MAME votrax.cpp)
PHONE_NAMES: tuple[str, ...] = (
    "EH3", "EH2", "EH1", "PA0", "DT",  "A1",  "A2",  "ZH",
    "AH2", "I3",  "I2",  "I1",  "M",   "N",   "B",   "V",
    "CH",  "SH",  "Z",   "AW1", "NG",  "AH1", "OO1", "OO",
    "L",   "K",   "J",   "H",   "G",   "F",   "D",   "S",
    "A",   "AY",  "Y1",  "UH3", "AH",  "P",   "O",   "I",
    "U",   "Y",   "T",   "R",   "E",   "W",   "AE",  "AE1",
    "AW2", "UH2", "UH1", "UH",  "O2",  "O1",  "IU",  "U1",
    "THV", "TH",  "ER",  "EH",  "E1",  "AW",  "PA1", "STOP",
)

# Phoneme parameters decoded from SC-01A ROM
# Keys are SC-01 phoneme codes (0x00-0x3F)
PHONEME_PARAMS: dict[int, PhonemeParams] = {
    0x00: {'name': 'EH3', 'f1': 9, 'f2': 1, 'f2q': 0, 'f3': 13, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 14, 'closure': False, 'duration': 100},
    0x01: {'name': 'EH2', 'f1': 9, 'f2': 1, 'f2q': 0, 'f3': 13, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 14, 'closure': False, 'duration': 116},
    0x02: {'name': 'EH1', 'f1': 9, 'f2': 1, 'f2q': 0, 'f3': 13, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 6, 'closure': False, 'duration': 50},
    0x03: {'name': 'PA0', 'f1': 14, 'f2': 9, 'f2q': 0, 'f3': 3, 'va': 0, 'fa': 0, 'fc': 0, 'vd': 12, 'cld': 12, 'closure': False, 'duration': 120},
    0x04: {'name': 'DT', 'f1': 2, 'f2': 6, 'f2q': 0, 'f3': 3, 'va': 0, 'fa': 1, 'fc': 15, 'vd': 11, 'cld': 6, 'closure': True, 'duration': 120},
    0x05: {'name': 'A1', 'f1': 6, 'f2': 13, 'f2q': 0, 'f3': 13, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 6, 'closure': False, 'duration': 116},
    0x06: {'name': 'A2', 'f1': 6, 'f2': 13, 'f2q': 0, 'f3': 13, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 10, 'closure': False, 'duration': 66},
    0x07: {'name': 'ZH', 'f1': 4, 'f2': 13, 'f2q': 8, 'f3': 7, 'va': 8, 'fa': 1, 'fc': 15, 'vd': 14, 'cld': 14, 'closure': False, 'duration': 92},
    0x08: {'name': 'AH2', 'f1': 15, 'f2': 12, 'f2q': 0, 'f3': 13, 'va': 9, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 6, 'closure': False, 'duration': 116},
    0x09: {'name': 'I3', 'f1': 10, 'f2': 5, 'f2q': 0, 'f3': 3, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 2, 'closure': False, 'duration': 36},
    0x0A: {'name': 'I2', 'f1': 10, 'f2': 5, 'f2q': 0, 'f3': 3, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 10, 'closure': False, 'duration': 44},
    0x0B: {'name': 'I1', 'f1': 10, 'f2': 5, 'f2q': 0, 'f3': 3, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 10, 'closure': False, 'duration': 50},
    0x0C: {'name': 'M', 'f1': 8, 'f2': 12, 'f2q': 15, 'f3': 9, 'va': 5, 'fa': 0, 'fc': 0, 'vd': 10, 'cld': 6, 'closure': False, 'duration': 66},
    0x0D: {'name': 'N', 'f1': 8, 'f2': 1, 'f2q': 15, 'f3': 11, 'va': 3, 'fa': 0, 'fc': 0, 'vd': 12, 'cld': 6, 'closure': False, 'duration': 44},
    0x0E: {'name': 'B', 'f1': 8, 'f2': 12, 'f2q': 0, 'f3': 3, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 6, 'cld': 10, 'closure': True, 'duration': 116},
    0x0F: {'name': 'V', 'f1': 4, 'f2': 12, 'f2q': 8, 'f3': 9, 'va': 8, 'fa': 6, 'fc': 15, 'vd': 14, 'cld': 14, 'closure': False, 'duration': 116},
    0x10: {'name': 'CH', 'f1': 4, 'f2': 13, 'f2q': 8, 'f3': 7, 'va': 0, 'fa': 9, 'fc': 15, 'vd': 14, 'cld': 14, 'closure': False, 'duration': 116},
    0x11: {'name': 'SH', 'f1': 4, 'f2': 13, 'f2q': 8, 'f3': 7, 'va': 0, 'fa': 9, 'fc': 15, 'vd': 14, 'cld': 12, 'closure': False, 'duration': 50},
    0x12: {'name': 'Z', 'f1': 4, 'f2': 12, 'f2q': 2, 'f3': 11, 'va': 8, 'fa': 13, 'fc': 0, 'vd': 6, 'cld': 10, 'closure': False, 'duration': 116},
    0x13: {'name': 'AW1', 'f1': 11, 'f2': 4, 'f2q': 0, 'f3': 5, 'va': 13, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 12, 'closure': False, 'duration': 58},
    0x14: {'name': 'NG', 'f1': 4, 'f2': 3, 'f2q': 3, 'f3': 13, 'va': 3, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 12, 'closure': False, 'duration': 50},
    0x15: {'name': 'AH1', 'f1': 15, 'f2': 12, 'f2q': 0, 'f3': 13, 'va': 9, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 2, 'closure': False, 'duration': 58},
    0x16: {'name': 'OO1', 'f1': 1, 'f2': 4, 'f2q': 0, 'f3': 5, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 10, 'closure': False, 'duration': 66},
    0x17: {'name': 'OO', 'f1': 1, 'f2': 4, 'f2q': 0, 'f3': 5, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 2, 'closure': False, 'duration': 46},
    0x18: {'name': 'L', 'f1': 6, 'f2': 4, 'f2q': 0, 'f3': 15, 'va': 5, 'fa': 0, 'fc': 0, 'vd': 12, 'cld': 14, 'closure': False, 'duration': 66},
    0x19: {'name': 'K', 'f1': 12, 'f2': 5, 'f2q': 0, 'f3': 1, 'va': 0, 'fa': 2, 'fc': 15, 'vd': 2, 'cld': 8, 'closure': True, 'duration': 44},
    0x1A: {'name': 'J', 'f1': 8, 'f2': 5, 'f2q': 8, 'f3': 7, 'va': 8, 'fa': 14, 'fc': 15, 'vd': 5, 'cld': 12, 'closure': False, 'duration': 120},
    0x1B: {'name': 'H', 'f1': 10, 'f2': 1, 'f2q': 0, 'f3': 9, 'va': 0, 'fa': 8, 'fc': 15, 'vd': 14, 'cld': 12, 'closure': False, 'duration': 116},
    0x1C: {'name': 'G', 'f1': 4, 'f2': 5, 'f2q': 0, 'f3': 1, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 14, 'cld': 6, 'closure': True, 'duration': 116},
    0x1D: {'name': 'F', 'f1': 2, 'f2': 12, 'f2q': 2, 'f3': 9, 'va': 0, 'fa': 2, 'fc': 15, 'vd': 10, 'cld': 4, 'closure': False, 'duration': 66},
    0x1E: {'name': 'D', 'f1': 8, 'f2': 9, 'f2q': 0, 'f3': 7, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 1, 'cld': 1, 'closure': True, 'duration': 36},
    0x1F: {'name': 'S', 'f1': 2, 'f2': 14, 'f2q': 0, 'f3': 3, 'va': 0, 'fa': 15, 'fc': 0, 'vd': 1, 'cld': 4, 'closure': False, 'duration': 92},
    0x20: {'name': 'A', 'f1': 6, 'f2': 13, 'f2q': 0, 'f3': 13, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 2, 'closure': False, 'duration': 46},
    0x21: {'name': 'AY', 'f1': 12, 'f2': 7, 'f2q': 0, 'f3': 7, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 14, 'closure': False, 'duration': 84},
    0x22: {'name': 'Y1', 'f1': 8, 'f2': 11, 'f2q': 0, 'f3': 11, 'va': 1, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 6, 'closure': False, 'duration': 44},
    0x23: {'name': 'UH3', 'f1': 3, 'f2': 12, 'f2q': 0, 'f3': 13, 'va': 7, 'fa': 0, 'fc': 0, 'vd': 2, 'cld': 14, 'closure': False, 'duration': 120},
    0x24: {'name': 'AH', 'f1': 15, 'f2': 12, 'f2q': 0, 'f3': 13, 'va': 9, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 2, 'closure': False, 'duration': 25},
    0x25: {'name': 'P', 'f1': 2, 'f2': 4, 'f2q': 8, 'f3': 1, 'va': 0, 'fa': 6, 'fc': 15, 'vd': 10, 'cld': 4, 'closure': True, 'duration': 66},
    0x26: {'name': 'O', 'f1': 14, 'f2': 8, 'f2q': 0, 'f3': 13, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 2, 'closure': False, 'duration': 46},
    0x27: {'name': 'I', 'f1': 10, 'f2': 5, 'f2q': 0, 'f3': 3, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 2, 'closure': False, 'duration': 46},
    0x28: {'name': 'U', 'f1': 12, 'f2': 8, 'f2q': 0, 'f3': 5, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 2, 'closure': False, 'duration': 46},
    0x29: {'name': 'Y', 'f1': 4, 'f2': 7, 'f2q': 0, 'f3': 11, 'va': 3, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 6, 'closure': False, 'duration': 66},
    0x2A: {'name': 'T', 'f1': 2, 'f2': 6, 'f2q': 0, 'f3': 3, 'va': 0, 'fa': 15, 'fc': 0, 'vd': 14, 'cld': 4, 'closure': True, 'duration': 116},
    0x2B: {'name': 'R', 'f1': 6, 'f2': 2, 'f2q': 0, 'f3': 12, 'va': 3, 'fa': 0, 'fc': 0, 'vd': 2, 'cld': 14, 'closure': False, 'duration': 92},
    0x2C: {'name': 'E', 'f1': 4, 'f2': 7, 'f2q': 0, 'f3': 7, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 12, 'closure': False, 'duration': 46},
    0x2D: {'name': 'W', 'f1': 12, 'f2': 0, 'f2q': 0, 'f3': 9, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 2, 'cld': 9, 'closure': False, 'duration': 44},
    0x2E: {'name': 'AE', 'f1': 11, 'f2': 9, 'f2q': 0, 'f3': 13, 'va': 13, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 12, 'closure': False, 'duration': 46},
    0x2F: {'name': 'AE1', 'f1': 11, 'f2': 9, 'f2q': 0, 'f3': 13, 'va': 13, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 12, 'closure': False, 'duration': 66},
    0x30: {'name': 'AW2', 'f1': 11, 'f2': 4, 'f2q': 0, 'f3': 5, 'va': 13, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 6, 'closure': False, 'duration': 92},
    0x31: {'name': 'UH2', 'f1': 3, 'f2': 12, 'f2q': 0, 'f3': 13, 'va': 7, 'fa': 0, 'fc': 0, 'vd': 2, 'cld': 14, 'closure': False, 'duration': 116},
    0x32: {'name': 'UH1', 'f1': 3, 'f2': 12, 'f2q': 0, 'f3': 13, 'va': 7, 'fa': 0, 'fc': 0, 'vd': 12, 'cld': 6, 'closure': False, 'duration': 66},
    0x33: {'name': 'UH', 'f1': 3, 'f2': 12, 'f2q': 0, 'f3': 13, 'va': 7, 'fa': 0, 'fc': 0, 'vd': 12, 'cld': 10, 'closure': False, 'duration': 46},
    0x34: {'name': 'O2', 'f1': 14, 'f2': 8, 'f2q': 0, 'f3': 13, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 10, 'closure': False, 'duration': 44},
    0x35: {'name': 'O1', 'f1': 14, 'f2': 8, 'f2q': 0, 'f3': 5, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 2, 'closure': False, 'duration': 50},
    0x36: {'name': 'IU', 'f1': 10, 'f2': 2, 'f2q': 0, 'f3': 1, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 2, 'cld': 9, 'closure': False, 'duration': 100},
    0x37: {'name': 'U1', 'f1': 12, 'f2': 8, 'f2q': 0, 'f3': 5, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 10, 'closure': False, 'duration': 92},
    0x38: {'name': 'THV', 'f1': 12, 'f2': 14, 'f2q': 0, 'f3': 3, 'va': 8, 'fa': 8, 'fc': 0, 'vd': 6, 'cld': 2, 'closure': False, 'duration': 44},
    0x39: {'name': 'TH', 'f1': 10, 'f2': 1, 'f2q': 0, 'f3': 5, 'va': 0, 'fa': 12, 'fc': 0, 'vd': 1, 'cld': 8, 'closure': False, 'duration': 116},
    0x3A: {'name': 'ER', 'f1': 6, 'f2': 2, 'f2q': 0, 'f3': 12, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 2, 'closure': False, 'duration': 58},
    0x3B: {'name': 'EH', 'f1': 9, 'f2': 1, 'f2q': 0, 'f3': 13, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 10, 'closure': False, 'duration': 46},
    0x3C: {'name': 'E1', 'f1': 4, 'f2': 7, 'f2q': 0, 'f3': 7, 'va': 15, 'fa': 0, 'fc': 0, 'vd': 4, 'cld': 10, 'closure': False, 'duration': 50},
    0x3D: {'name': 'AW', 'f1': 11, 'f2': 4, 'f2q': 0, 'f3': 5, 'va': 13, 'fa': 0, 'fc': 0, 'vd': 12, 'cld': 10, 'closure': False, 'duration': 25},
    0x3E: {'name': 'PA1', 'f1': 14, 'f2': 9, 'f2q': 0, 'f3': 3, 'va': 0, 'fa': 0, 'fc': 0, 'vd': 2, 'cld': 2, 'closure': False, 'duration': 46},
    0x3F: {'name': 'STOP', 'f1': 14, 'f2': 9, 'f2q': 2, 'f3': 3, 'va': 0, 'fa': 0, 'fc': 0, 'vd': 8, 'cld': 8, 'closure': True, 'duration': 120},
}

# Pause phonemes (formants freeze during these)
PAUSE_PHONES: frozenset[int] = frozenset({0x03, 0x3E})  # PA0, PA1

# Glottal wave shape (from MAME votrax.cpp)
# Represents the voice source impulse, normalized to 0-1 range
GLOTTAL_WAVE: tuple[float, ...] = (
    0.0,      # Index 0: mid-value
    -4 / 7,   # Index 1: 0V baseline
    7 / 7,    # Index 2: rising edge
    6 / 7,    # Index 3
    5 / 7,    # Index 4
    4 / 7,    # Index 5
    3 / 7,    # Index 6
    2 / 7,    # Index 7
    1 / 7,    # Index 8: tail
    # Index 9+: return to 0
)
