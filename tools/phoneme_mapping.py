#!/usr/bin/env python
"""SSI-263 to SC-01 phoneme mapping analyzer.

Shows how SSI-263 phonemes map to SC-01 phonemes and highlights potential issues.

Usage:
    uv run python tools/phoneme_mapping.py
    uv run python tools/phoneme_mapping.py --compare 0x01
    uv run python tools/phoneme_mapping.py --mismatches
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from qns.ssi263 import PHONEMES as SSI263_PHONEMES
from qns.synth.sc02_to_sc01 import SC02_TO_SC01
from qns.synth.sc01_rom import PHONE_NAMES as SC01_NAMES


def get_ssi263_info(code: int) -> tuple[str, str]:
    """Get SSI-263 phoneme name and example."""
    info = SSI263_PHONEMES.get(code, ("?", "unknown", ""))
    return info[0], info[1]


def get_sc01_name(code: int) -> str:
    """Get SC-01 phoneme name."""
    if 0 <= code < len(SC01_NAMES):
        return SC01_NAMES[code]
    return "?"


def print_full_mapping():
    """Print the complete SSI-263 to SC-01 mapping table."""
    print("SSI-263 to SC-01 Phoneme Mapping")
    print("=" * 80)
    print()
    print(f"{'SSI-263':^30} | {'SC-01':^30} | Notes")
    print(f"{'Code':<6} {'Name':<6} {'Example':<15} | {'Code':<6} {'Name':<10} | ")
    print("-" * 80)

    for ssi_code in range(64):
        ssi_name, ssi_example = get_ssi263_info(ssi_code)
        sc01_code = SC02_TO_SC01[ssi_code]
        sc01_name = get_sc01_name(sc01_code)

        # Check for obvious mismatches
        notes = ""
        if ssi_name == "PA" and sc01_name != "PA0" and sc01_name != "PA1":
            notes = "PAUSE?"
        elif ssi_name.upper() != sc01_name.upper() and ssi_name[0] == sc01_name[0]:
            notes = "similar"
        elif ssi_name.upper() != sc01_name.upper():
            notes = "DIFFERENT!"

        print(f"0x{ssi_code:02X}   {ssi_name:<6} {ssi_example:<15} | 0x{sc01_code:02X}   {sc01_name:<10} | {notes}")


def analyze_mismatches():
    """Find and report potential phoneme mismatches."""
    print("Potential Phoneme Mismatches")
    print("=" * 60)
    print()

    mismatches = []
    for ssi_code in range(64):
        ssi_name, ssi_example = get_ssi263_info(ssi_code)
        sc01_code = SC02_TO_SC01[ssi_code]
        sc01_name = get_sc01_name(sc01_code)

        # Skip pauses
        if ssi_name in ("PA", "PA1", "STOP"):
            continue

        # Check if first letter matches (rough heuristic)
        ssi_first = ssi_name[0].upper() if ssi_name else "?"
        sc01_first = sc01_name[0].upper() if sc01_name else "?"

        if ssi_first != sc01_first:
            mismatches.append((ssi_code, ssi_name, ssi_example, sc01_code, sc01_name))

    if mismatches:
        print(f"Found {len(mismatches)} potential mismatches (first letter differs):")
        print()
        for ssi_code, ssi_name, ssi_example, sc01_code, sc01_name in mismatches:
            print(f"  SSI-263 0x{ssi_code:02X} {ssi_name} ({ssi_example})")
            print(f"      -> SC-01 0x{sc01_code:02X} {sc01_name}")
            print()
    else:
        print("No obvious mismatches found (but mapping may still be wrong!)")


def compare_phoneme(code: int):
    """Show detailed comparison for a single phoneme."""
    ssi_name, ssi_example = get_ssi263_info(code)
    sc01_code = SC02_TO_SC01[code]
    sc01_name = get_sc01_name(sc01_code)

    print(f"Phoneme Comparison: SSI-263 0x{code:02X}")
    print("=" * 50)
    print()
    print(f"SSI-263 Phoneme:")
    print(f"  Code:    0x{code:02X}")
    print(f"  Name:    {ssi_name}")
    print(f"  Example: {ssi_example}")
    print()
    print(f"Mapped to SC-01 Phoneme:")
    print(f"  Code:    0x{sc01_code:02X}")
    print(f"  Name:    {sc01_name}")
    print()

    # Show other SC-01 phonemes that might be better matches
    print("Other SC-01 phonemes with similar names:")
    for i, name in enumerate(SC01_NAMES):
        if ssi_name[0].upper() == name[0].upper():
            marker = " <-- CURRENT" if i == sc01_code else ""
            print(f"  0x{i:02X} {name}{marker}")


def main():
    parser = argparse.ArgumentParser(description="SSI-263 to SC-01 phoneme mapping analyzer")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--compare", "-c", type=lambda x: int(x, 0), metavar="CODE",
                       help="Compare a specific phoneme (e.g., 0x01)")
    group.add_argument("--mismatches", "-m", action="store_true",
                       help="Show potential mismatches")

    args = parser.parse_args()

    if args.compare is not None:
        compare_phoneme(args.compare)
    elif args.mismatches:
        analyze_mismatches()
    else:
        print_full_mapping()
        print()
        print("NOTE: This is the corrected SC-02 datasheet mapping from")
        print("      qns/synth/sc02_to_sc01.py; see docs/sc02-phoneme-mapping.md.")


if __name__ == "__main__":
    main()
