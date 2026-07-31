"""Find masked byte patterns in raw firmware or BNS update packages."""

from __future__ import annotations

import argparse
from pathlib import Path

from qns.loader import load_firmware

BANK_SIZE = 0x10000


def parse_pattern(text: str) -> tuple[int | None, ...]:
    """Parse space-separated hexadecimal bytes, using ?? as a wildcard."""
    tokens = text.split()
    if not tokens:
        raise ValueError("pattern is empty")
    pattern: list[int | None] = []
    for token in tokens:
        if token == "??":
            pattern.append(None)
            continue
        if len(token) != 2:
            raise ValueError(f"invalid pattern byte: {token!r}")
        try:
            pattern.append(int(token, 16))
        except ValueError as error:
            raise ValueError(f"invalid pattern byte: {token!r}") from error
    return tuple(pattern)


def find_pattern(data: bytes, pattern: tuple[int | None, ...]) -> list[int]:
    """Return every offset where fixed pattern bytes match the input."""
    if not pattern:
        raise ValueError("pattern is empty")
    limit = len(data) - len(pattern) + 1
    return [
        offset
        for offset in range(max(0, limit))
        if all(
            expected is None or data[offset + index] == expected
            for index, expected in enumerate(pattern)
        )
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom", type=Path)
    parser.add_argument("pattern", help="hex bytes separated by spaces; ?? matches any byte")
    args = parser.parse_args()

    image = load_firmware(args.rom)
    firmware = image.data
    file_base = image.image_offset or 0
    pattern = parse_pattern(args.pattern)
    matches = find_pattern(firmware, pattern)
    for offset in matches:
        bank, address = divmod(offset, BANK_SIZE)
        matched = firmware[offset : offset + len(pattern)].hex(" ").upper()
        print(
            f"file=0x{file_base + offset:06X} firmware=0x{offset:06X} "
            f"bank={bank} address=0x{address:04X} bytes={matched}"
        )
    if not matches:
        raise SystemExit("pattern not found")


if __name__ == "__main__":
    main()
