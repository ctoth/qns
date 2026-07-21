"""Inspect and build Blazie external-program BNS files."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

HEADER_SIZE = 0x0E
ENTRY_ADDRESS = 0x100E
IDENTIFIER = b"BNS\0"
ENTRY_JUMP = bytes((0x18, 0x0C))
END_MARKER = 0xAA
MINIMUM_STACK = 0x1000


@dataclass(frozen=True)
class ExternalProgramInfo:
    """Validated fields from an external-program header."""

    file_size: int
    code_size: int
    program_length: int
    crc: int
    stack: int


def program_crc(code: bytes) -> int:
    """Return the firmware's external-program CRC for *code*."""
    crc = 0
    for byte in code:
        carry = crc & 0x8000
        crc = (crc << 1) & 0xFFFF
        crc = (crc & 0xFF00) | ((crc + byte) & 0xFF)
        if carry:
            crc ^= 0xA097
    return crc


def inspect_external_program(data: bytes) -> ExternalProgramInfo:
    """Validate *data* as a portable Blazie external program."""
    if len(data) < HEADER_SIZE + 1:
        raise ValueError("file is shorter than the 14-byte header and end marker")
    if data[:2] != ENTRY_JUMP:
        raise ValueError("entry instruction is not JR from offset 0x00 to 0x0e")
    if data[2:6] != IDENTIFIER:
        raise ValueError("identifier is not BNS\\0; firmware-update packages are not programs")

    code_size = int.from_bytes(data[6:8], "little")
    program_length = int.from_bytes(data[8:10], "little")
    expected_crc = int.from_bytes(data[10:12], "little")
    stack = int.from_bytes(data[12:14], "little")

    if len(data) != program_length + HEADER_SIZE + 1:
        raise ValueError(
            f"file size {len(data)} does not equal program_length + 15 "
            f"({program_length + HEADER_SIZE + 1})"
        )
    if code_size == 0:
        raise ValueError("code_size must be nonzero")
    if code_size > program_length:
        raise ValueError(f"code_size {code_size} exceeds program_length {program_length}")
    if data[-1] != END_MARKER:
        raise ValueError(f"final byte is 0x{data[-1]:02x}, not the 0xaa end marker")
    if stack < MINIMUM_STACK:
        raise ValueError(f"stack 0x{stack:04x} is below logical address 0x1000")

    code = data[HEADER_SIZE : HEADER_SIZE + code_size]
    actual_crc = program_crc(code)
    if actual_crc != expected_crc:
        raise ValueError(
            f"code CRC is 0x{actual_crc:04x}, header requires 0x{expected_crc:04x}"
        )

    return ExternalProgramInfo(
        file_size=len(data),
        code_size=code_size,
        program_length=program_length,
        crc=expected_crc,
        stack=stack,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the external-program command-line tool."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect", help="validate an external-program BNS")
    inspect_parser.add_argument("program", type=Path)
    args = parser.parse_args(argv)

    if args.command == "inspect":
        try:
            info = inspect_external_program(args.program.read_bytes())
        except (OSError, ValueError) as error:
            parser.exit(1, f"{args.program}: {error}\n")
        print(f"file_size={info.file_size}")
        print(f"code_size=0x{info.code_size:04x}")
        print(f"program_length=0x{info.program_length:04x}")
        print(f"crc=0x{info.crc:04x}")
        print(f"stack=0x{info.stack:04x}")
        return 0

    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
