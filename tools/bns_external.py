"""Inspect and build Blazie external-program BNS files."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

HEADER_SIZE = 0x0E
BASE_ADDRESS = 0x1000
ENTRY_ADDRESS = 0x100E
IDENTIFIER = b"BNS\0"
ENTRY_JUMP = bytes((0x18, 0x0C))
END_MARKER = 0xAA
MINIMUM_STACK = 0x1000
REQUIRED_SYMBOLS = (
    "__bns_entry",
    "__bns_code_end",
    "__bns_end_marker",
    "__bns_stack_top",
)
MAP_SYMBOL = re.compile(r"^(\S+)\s*=\s*\$([0-9a-fA-F]+)\s*(?:;.*)?$")


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


def parse_link_symbols(map_text: str) -> dict[str, int]:
    """Read the required public symbols from a z88dk-z80asm map."""
    symbols: dict[str, int] = {}
    for line in map_text.splitlines():
        match = MAP_SYMBOL.fullmatch(line.strip())
        if match is None or match.group(1) not in REQUIRED_SYMBOLS:
            continue
        name = match.group(1)
        if name in symbols:
            raise ValueError(f"link map defines {name} more than once")
        symbols[name] = int(match.group(2), 16)

    missing = [name for name in REQUIRED_SYMBOLS if name not in symbols]
    if missing:
        raise ValueError(f"link map is missing required symbols: {', '.join(missing)}")
    return symbols


def pack_external_program(raw_image: bytes, map_text: str) -> bytes:
    """Finalize a linked raw image using its public link-map symbols."""
    if len(raw_image) < HEADER_SIZE + 1:
        raise ValueError("raw image is shorter than the 14-byte header and end marker")
    if raw_image[:2] != ENTRY_JUMP:
        raise ValueError("raw image does not jump from offset 0x00 to 0x0e")
    if raw_image[2:6] != IDENTIFIER:
        raise ValueError("raw image identifier is not BNS\\0")

    symbols = parse_link_symbols(map_text)
    entry = symbols["__bns_entry"]
    code_end = symbols["__bns_code_end"]
    end_marker = symbols["__bns_end_marker"]
    stack = symbols["__bns_stack_top"]

    if entry != ENTRY_ADDRESS:
        raise ValueError(f"__bns_entry is 0x{entry:04x}, not 0x{ENTRY_ADDRESS:04x}")
    if code_end <= entry:
        raise ValueError("__bns_code_end must follow __bns_entry")
    if end_marker < code_end:
        raise ValueError("__bns_end_marker must not precede __bns_code_end")
    if not MINIMUM_STACK <= stack <= 0xFFFF:
        raise ValueError(f"__bns_stack_top 0x{stack:x} is outside 0x1000..0xffff")

    entry_offset = entry - BASE_ADDRESS
    code_end_offset = code_end - BASE_ADDRESS
    marker_offset = end_marker - BASE_ADDRESS
    if marker_offset != len(raw_image) - 1:
        raise ValueError(
            f"__bns_end_marker maps to file offset 0x{marker_offset:x}, "
            f"not final offset 0x{len(raw_image) - 1:x}"
        )
    if raw_image[marker_offset] != END_MARKER:
        raise ValueError("__bns_end_marker does not identify a 0xaa byte")

    code_size = code_end - entry
    program_length = end_marker - entry
    if code_size > 0xFFFF or program_length > 0xFFFF:
        raise ValueError("linked program does not fit 16-bit header fields")

    output = bytearray(raw_image)
    output[6:8] = code_size.to_bytes(2, "little")
    output[8:10] = program_length.to_bytes(2, "little")
    output[10:12] = program_crc(raw_image[entry_offset:code_end_offset]).to_bytes(2, "little")
    output[12:14] = stack.to_bytes(2, "little")

    result = bytes(output)
    info = inspect_external_program(result)
    expected = ExternalProgramInfo(
        file_size=len(raw_image),
        code_size=code_size,
        program_length=program_length,
        crc=int.from_bytes(output[10:12], "little"),
        stack=stack,
    )
    if info != expected:
        raise ValueError(f"reinspection produced {info!r}, expected {expected!r}")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Run the external-program command-line tool."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect", help="validate an external-program BNS")
    inspect_parser.add_argument("program", type=Path)
    pack_parser = subparsers.add_parser("pack", help="finalize a linked external-program image")
    pack_parser.add_argument("image", type=Path, help="linked raw binary")
    pack_parser.add_argument("map", type=Path, help="z88dk-z80asm link map")
    pack_parser.add_argument("output", type=Path, help="output external-program BNS")
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

    if args.command == "pack":
        try:
            program = pack_external_program(args.image.read_bytes(), args.map.read_text())
            args.output.write_bytes(program)
        except (OSError, UnicodeError, ValueError) as error:
            parser.exit(1, f"{error}\n")
        return 0

    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
