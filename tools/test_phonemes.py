#!/usr/bin/env python
"""Phoneme diagnostic tool.

Test SSI-263 phoneme playback to identify audio issues.

Usage:
    uv run python tools/test_phonemes.py --list           # List all phonemes
    uv run python tools/test_phonemes.py --play 0x01      # Play phoneme 0x01 (E)
    uv run python tools/test_phonemes.py --play-all       # Play all phonemes
    uv run python tools/test_phonemes.py --word hello     # Try to say "hello"
    uv run python tools/test_phonemes.py --dump 0x01      # Dump phoneme to WAV
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from qns.synth import SSI263Synth
from qns.ssi263 import PHONEMES


def list_phonemes():
    """Print all phonemes with their codes and names."""
    print("SSI-263 Phonemes (64 total):")
    print("-" * 50)
    print(f"{'Code':>6}  {'Name':<6}  {'Example':<12}")
    print("-" * 50)
    for code in range(64):
        info = PHONEMES.get(code, ("?", "unknown", ""))
        name, example, _ = info  # Skip IPA (encoding issues on Windows)
        print(f"0x{code:02X}    {name:<6}  {example:<12}")


def play_phoneme(synth: SSI263Synth, code: int, wait: bool = True):
    """Play a single phoneme and optionally wait."""
    from qns.synth.sc02_to_sc01 import SC02_TO_SC01

    info = PHONEMES.get(code, ("?", "unknown", ""))
    name, example, _ = info

    # Show mapping info (SSI-263 -> SC-01 -> data index)
    if code == 0:
        data_info = "silence"
    else:
        sc01 = SC02_TO_SC01[code & 0x3F]
        data_info = f"SC01[0x{sc01:02X}]"

    print(f"Playing 0x{code:02X} {name} ({example}) -> {data_info}")

    # Reset to known good standalone settings
    synth.amplitude = 15     # Full volume
    synth.inflection = 2048  # Neutral pitch

    synth.speak_phoneme(code)

    if wait:
        synth.wait_until_done()
        time.sleep(0.1)  # Small gap between phonemes


def play_all_phonemes(synth: SSI263Synth):
    """Play all 64 phonemes in sequence."""
    print("Playing all phonemes (0x00-0x3F)...")
    print("Press Ctrl+C to stop")
    print()

    for code in range(64):
        try:
            play_phoneme(synth, code, wait=True)
        except KeyboardInterrupt:
            print("\nStopped by user")
            break


def play_raw_sample(synth: SSI263Synth, index: int):
    """Play raw sample data by index to identify sample order."""
    from qns.synth.phonemes import PHONEME_INFO, get_phoneme_samples
    import numpy as np

    if index < 0 or index >= len(PHONEME_INFO):
        print(f"Invalid index {index}. Must be 0-{len(PHONEME_INFO)-1}")
        return

    print(f"Playing raw data[{index}]...")
    samples = get_phoneme_samples(index)

    # Convert to float32 and play
    samples_float = (samples / 32768.0).astype(np.float32)
    synth._player.play(samples_float)
    synth.wait_until_done()
    time.sleep(0.1)


def play_word(synth: SSI263Synth, word: str):
    """Try to speak a word using phoneme sequences."""
    # Simple word-to-phoneme mapping for testing
    WORDS = {
        "hello": [0x2C, 0x01, 0x20, 0x14],  # HF, E, L, O
        "test": [0x28, 0x06, 0x30, 0x28],   # T, EH, S, T
        "one": [0x23, 0x16, 0x38],          # W, O2, N
        "two": [0x28, 0x18],                # T, U
        "three": [0x36, 0x1D, 0x01],        # TH, R, E
        "yes": [0x03, 0x06, 0x30],          # Y, EH, S
        "no": [0x38, 0x14],                 # N, O
        "bee": [0x24, 0x01],                # B, E
        "cat": [0x29, 0x0C, 0x28],          # K, A2, T
        "dog": [0x25, 0x0D, 0x26],          # D, AW, G (using KV)
    }

    word_lower = word.lower()
    if word_lower not in WORDS:
        print(f"Unknown word: {word}")
        print(f"Available: {', '.join(sorted(WORDS.keys()))}")
        return

    phonemes = WORDS[word_lower]
    print(f"Speaking '{word}' using phonemes: {[f'0x{p:02X}' for p in phonemes]}")

    for code in phonemes:
        play_phoneme(synth, code, wait=True)


def dump_phoneme(synth: SSI263Synth, code: int, output_path: str | None = None):
    """Dump phoneme audio to WAV file."""
    import wave

    info = PHONEMES.get(code, ("?", "unknown", ""))
    name, example, _ = info

    if output_path is None:
        output_path = f"phoneme_0x{code:02X}_{name}.wav"

    # Get raw samples
    samples = synth.get_phoneme_audio(phoneme=code, amplitude=15, inflection=2048)

    # Convert to int16
    samples_int16 = (samples * 32767).astype(np.int16)

    # Write WAV
    with wave.open(output_path, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # 16-bit
        wav.setframerate(synth.sample_rate)
        wav.writeframes(samples_int16.tobytes())

    print(f"Dumped 0x{code:02X} {name} ({example}) to {output_path}")
    print(f"  Samples: {len(samples)}, Duration: {len(samples)/synth.sample_rate:.3f}s")


def parse_phoneme_code(value: str) -> int:
    """Parse phoneme code from hex or decimal string."""
    try:
        if value.startswith('0x') or value.startswith('0X'):
            return int(value, 16)
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid phoneme code: {value}")


def main():
    parser = argparse.ArgumentParser(
        description="SSI-263 phoneme diagnostic tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true",
                       help="List all phonemes")
    group.add_argument("--play", type=parse_phoneme_code, metavar="CODE",
                       help="Play a single phoneme (hex, e.g., 0x01)")
    group.add_argument("--play-all", action="store_true",
                       help="Play all phonemes in sequence")
    group.add_argument("--word", type=str, metavar="WORD",
                       help="Try to speak a word")
    group.add_argument("--dump", type=parse_phoneme_code, metavar="CODE",
                       help="Dump phoneme to WAV file")
    group.add_argument("--dump-all", action="store_true",
                       help="Dump all phonemes to WAV files")
    group.add_argument("--raw", type=int, metavar="INDEX",
                       help="Play raw sample data by index (0-61) to identify sample order")

    parser.add_argument("--output", "-o", type=str, metavar="FILE",
                        help="Output file for --dump")

    args = parser.parse_args()

    if args.list:
        list_phonemes()
        return

    # All other commands need the synth
    synth = SSI263Synth(audio_enabled=not (args.dump or args.dump_all))

    if args.dump:
        dump_phoneme(synth, args.dump, args.output)
        return

    if args.dump_all:
        Path("phoneme_dumps").mkdir(exist_ok=True)
        for code in range(64):
            info = PHONEMES.get(code, ("?", "unknown", ""))
            name = info[0]
            output = f"phoneme_dumps/0x{code:02X}_{name}.wav"
            dump_phoneme(synth, code, output)
        print(f"\nDumped all phonemes to phoneme_dumps/")
        return

    # Audio playback commands
    synth.start()
    try:
        if args.play is not None:
            play_phoneme(synth, args.play, wait=True)
        elif args.play_all:
            play_all_phonemes(synth)
        elif args.word:
            play_word(synth, args.word)
        elif args.raw is not None:
            play_raw_sample(synth, args.raw)
    finally:
        time.sleep(0.5)  # Let audio finish
        synth.stop()


if __name__ == "__main__":
    main()
