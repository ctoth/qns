"""ROM bank analyzer for BNS firmware files.

Analyzes .bns update packages containing 4 x 64KB ROM banks.
"""

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).parent.parent))

from qns.loader import load_firmware as _load_firmware_image

BANK_SIZE = 0x10000  # 64KB per bank


def load_firmware(path: Path) -> bytes:
    """Load firmware bytes from a .bns update package or raw file."""
    return _load_firmware_image(path).data


def get_banks(firmware: bytes) -> list[bytes]:
    """Split firmware into 64KB banks."""
    banks = []
    for i in range(0, len(firmware), BANK_SIZE):
        bank = firmware[i:i + BANK_SIZE]
        if len(bank) > 0:
            # Pad to full size if needed
            if len(bank) < BANK_SIZE:
                bank = bank + b'\xff' * (BANK_SIZE - len(bank))
            banks.append(bank)
    return banks


def format_hex_bytes(data: bytes, max_bytes: int = 16) -> str:
    """Format bytes as hex string."""
    return ' '.join(f'{b:02X}' for b in data[:max_bytes])


def is_printable_ascii(byte: int) -> bool:
    """Check if byte is printable ASCII."""
    return 0x20 <= byte <= 0x7E


def format_ascii(data: bytes) -> str:
    """Format bytes as ASCII, replacing non-printable with dots."""
    return ''.join(chr(b) if is_printable_ascii(b) else '.' for b in data)


@click.group()
def cli():
    """ROM bank analyzer for BNS firmware files.

    Analyzes .bns update packages containing 4 x 64KB ROM banks.
    """
    pass


@cli.command()
@click.argument('rom_file', type=click.Path(exists=True, path_type=Path))
def info(rom_file: Path):
    """Show ROM structure and bank information.

    Displays file size, number of banks, headers, and entry points.
    """
    image = _load_firmware_image(rom_file)
    firmware = image.data
    click.echo(f"File: {rom_file}")
    click.echo(f"Raw file size: {image.package_size:,} bytes")

    if image.kind == "package":
        click.echo("Format: BNS update package")
        click.echo(
            f"  Header bytes: {format_hex_bytes(rom_file.read_bytes()[:16])}"
        )
        click.echo(f"  Firmware offset: 0x{image.image_offset:04X}")
        click.echo(f"  Firmware size: {len(firmware):,} bytes")
    else:
        click.echo("Format: Raw firmware")

    banks = get_banks(firmware)
    click.echo(f"\nBanks: {len(banks)} x 64KB")

    for i, bank in enumerate(banks):
        click.echo(f"\n--- Bank {i} (offset 0x{i * BANK_SIZE:05X}) ---")
        click.echo(f"  First 16 bytes: {format_hex_bytes(bank[:16])}")
        click.echo(f"  ASCII:          {format_ascii(bank[:16])}")

        # Entry point detection - handle DI (F3) prefix
        first = bank[0]
        second = bank[1] if len(bank) > 1 else 0

        if first == 0xF3:  # DI instruction
            click.echo(f"  Starts with: DI (disable interrupts)")
            if second == 0xC3:  # JP opcode after DI
                addr = bank[2] | (bank[3] << 8)
                click.echo(f"  Entry: DI; JP 0x{addr:04X}")
            elif second == 0x18:  # JR opcode after DI
                offset = bank[2]
                entry = 3 + offset
                click.echo(f"  Entry: DI; JR +{offset} -> 0x{entry:04X}")
        elif first == 0x18:  # JR opcode
            offset = bank[1]
            entry = 2 + offset
            click.echo(f"  Entry: JR +{offset} -> 0x{entry:04X}")
            click.echo(f"  At entry point: {format_hex_bytes(bank[entry:entry+16])}")
        elif first == 0xC3:  # JP opcode
            addr = bank[1] | (bank[2] << 8)
            click.echo(f"  Entry: JP 0x{addr:04X}")
        else:
            click.echo(f"  Entry: Unknown (first byte 0x{first:02X})")

        # Check for magic strings
        magic = bank[2:6]
        if magic.isalpha() or magic in [b'BNS\x00', b'BNSP']:
            click.echo(f"  Magic: {magic!r}")


@cli.command('compare-banks')
@click.argument('rom_file', type=click.Path(exists=True, path_type=Path))
def compare_banks(rom_file: Path):
    """Compare all banks for similarities and differences.

    Shows percentage similarity and identifies differing regions.
    """
    firmware = load_firmware(rom_file)
    banks = get_banks(firmware)

    if len(banks) < 2:
        click.echo(f"Only {len(banks)} bank(s) found, nothing to compare.")
        return

    click.echo(f"Comparing {len(banks)} banks:\n")

    # Compare each pair of banks
    for i in range(len(banks)):
        for j in range(i + 1, len(banks)):
            bank_a = banks[i]
            bank_b = banks[j]

            # Count matching bytes
            matches = sum(1 for a, b in zip(bank_a, bank_b) if a == b)
            total = len(bank_a)
            pct = (matches / total) * 100

            click.echo(f"Bank {i} vs Bank {j}: {pct:.1f}% identical ({matches:,}/{total:,} bytes)")

            if pct == 100.0:
                click.echo("  -> Banks are IDENTICAL")
            elif pct > 99.0:
                click.echo("  -> Banks are nearly identical")
            elif pct > 90.0:
                click.echo("  -> Banks share most code")
            elif pct < 50.0:
                click.echo("  -> Banks are significantly different")

            # Find differing regions
            if pct < 100.0:
                diff_regions = []
                in_diff = False
                start = 0

                for k in range(total):
                    if bank_a[k] != bank_b[k]:
                        if not in_diff:
                            in_diff = True
                            start = k
                    else:
                        if in_diff:
                            in_diff = False
                            diff_regions.append((start, k))

                if in_diff:
                    diff_regions.append((start, total))

                # Show first few differing regions
                click.echo(f"  Differing regions: {len(diff_regions)}")
                for start, end in diff_regions[:5]:
                    size = end - start
                    click.echo(f"    0x{start:04X}-0x{end:04X} ({size:,} bytes)")

                if len(diff_regions) > 5:
                    click.echo(f"    ... and {len(diff_regions) - 5} more regions")

            click.echo()


@cli.command('find-pattern')
@click.argument('rom_file', type=click.Path(exists=True, path_type=Path))
@click.argument('pattern')
@click.option('--context', '-c', default=8, help='Context bytes to show before/after match')
@click.option('--limit', '-l', default=20, help='Maximum matches to show (0 for all)')
def find_pattern(rom_file: Path, pattern: str, context: int, limit: int):
    """Search for hex pattern across all banks.

    PATTERN is a hex string like "AF 32" (spaces optional).

    Example: find-pattern rom.bns "AF 32" (finds XOR A; LD (nn),A)
    """
    # Parse hex pattern
    pattern = pattern.replace(' ', '')
    if len(pattern) % 2 != 0:
        click.echo(f"Error: Invalid hex pattern (odd length): {pattern}")
        return

    try:
        search_bytes = bytes.fromhex(pattern)
    except ValueError as e:
        click.echo(f"Error: Invalid hex pattern: {e}")
        return

    click.echo(f"Searching for: {format_hex_bytes(search_bytes, 32)}")
    click.echo(f"Pattern length: {len(search_bytes)} bytes\n")

    firmware = load_firmware(rom_file)
    banks = get_banks(firmware)

    total_matches = 0
    shown_matches = 0

    for bank_num, bank in enumerate(banks):
        # Find all occurrences
        offset = 0
        while True:
            pos = bank.find(search_bytes, offset)
            if pos == -1:
                break

            total_matches += 1

            # Check if we should display this match
            if limit == 0 or shown_matches < limit:
                # Get context
                ctx_start = max(0, pos - context)
                ctx_end = min(len(bank), pos + len(search_bytes) + context)

                before = bank[ctx_start:pos]
                matched = bank[pos:pos + len(search_bytes)]
                after = bank[pos + len(search_bytes):ctx_end]

                click.echo(f"Bank {bank_num}, offset 0x{pos:04X}:")
                click.echo(f"  {format_hex_bytes(before)} [{format_hex_bytes(matched)}] {format_hex_bytes(after)}")

                # If pattern starts with AF 32 (XOR A; LD (nn),A), decode the address
                if len(search_bytes) >= 2 and search_bytes[0] == 0xAF and search_bytes[1] == 0x32:
                    if pos + 4 <= len(bank):
                        addr = bank[pos + 2] | (bank[pos + 3] << 8)
                        click.echo(f"  -> XOR A; LD (0x{addr:04X}),A  ; clears address 0x{addr:04X}")

                shown_matches += 1

            offset = pos + 1

    click.echo(f"\nTotal matches: {total_matches}")
    if limit > 0 and shown_matches < total_matches:
        click.echo(f"(showing {shown_matches} of {total_matches} matches, use --limit 0 for all)")


@cli.command('find-string')
@click.argument('rom_file', type=click.Path(exists=True, path_type=Path))
@click.argument('search_string')
@click.option('--context', '-c', default=16, help='Context bytes to show before/after match')
@click.option('--case-sensitive', '-s', is_flag=True, help='Case-sensitive search')
@click.option('--limit', '-l', default=20, help='Maximum matches to show (0 for all)')
def find_string(rom_file: Path, search_string: str, context: int, case_sensitive: bool, limit: int):
    """Search for ASCII string across all banks.

    Case-insensitive by default. Shows bank, offset, and surrounding context.
    """
    firmware = load_firmware(rom_file)
    banks = get_banks(firmware)

    search_bytes = search_string.encode('ascii')
    search_lower = search_string.lower()
    if not case_sensitive:
        click.echo(f"Searching for (case-insensitive): '{search_string}'")
    else:
        click.echo(f"Searching for (case-sensitive): '{search_string}'")

    click.echo()

    total_matches = 0
    shown_matches = 0

    for bank_num, bank in enumerate(banks):
        # For case-insensitive, convert bank to lowercase for searching
        if case_sensitive:
            search_in = bank
            search_for = search_bytes
        else:
            # Create lowercase version for searching
            search_in = bytes(b if not (0x41 <= b <= 0x5A) else b + 0x20 for b in bank)
            search_for = search_lower.encode('ascii')

        offset = 0
        while True:
            pos = search_in.find(search_for, offset)
            if pos == -1:
                break

            total_matches += 1

            # Check if we should display this match
            if limit == 0 or shown_matches < limit:
                # Get context from original bank
                ctx_start = max(0, pos - context)
                ctx_end = min(len(bank), pos + len(search_bytes) + context)

                context_bytes = bank[ctx_start:ctx_end]
                match_offset_in_ctx = pos - ctx_start

                click.echo(f"Bank {bank_num}, offset 0x{pos:04X}:")
                click.echo(f"  Hex: {format_hex_bytes(context_bytes, 48)}")
                click.echo(f"  ASCII: {format_ascii(context_bytes)}")

                # Highlight match position
                marker = ' ' * match_offset_in_ctx + '^' * len(search_string)
                click.echo(f"         {marker}")

                shown_matches += 1

            offset = pos + 1

    click.echo(f"\nTotal matches: {total_matches}")
    if limit > 0 and shown_matches < total_matches:
        click.echo(f"(showing {shown_matches} of {total_matches} matches, use --limit 0 for all)")


@cli.command('dump-bank')
@click.argument('rom_file', type=click.Path(exists=True, path_type=Path))
@click.argument('bank_num', type=int)
@click.argument('output_file', type=click.Path(path_type=Path))
def dump_bank(rom_file: Path, bank_num: int, output_file: Path):
    """Extract a single bank to a file.

    BANK_NUM is 0-3 for the four 64KB banks.
    """
    firmware = load_firmware(rom_file)
    banks = get_banks(firmware)

    if bank_num < 0 or bank_num >= len(banks):
        click.echo(f"Error: Bank {bank_num} does not exist. Available: 0-{len(banks)-1}")
        return

    bank = banks[bank_num]
    output_file.write_bytes(bank)

    click.echo(f"Extracted bank {bank_num} to {output_file}")
    click.echo(f"  Size: {len(bank):,} bytes (0x{len(bank):X})")
    click.echo(f"  First 16 bytes: {format_hex_bytes(bank[:16])}")


@cli.command('disasm')
@click.argument('rom_file', type=click.Path(exists=True, path_type=Path))
@click.argument('bank_num', type=int)
@click.argument('offset', type=str)
@click.option('--count', '-n', default=16, help='Number of bytes to show')
def disasm(rom_file: Path, bank_num: int, offset: str, count: int):
    """Show raw bytes at offset (hex dump, not actual disassembly).

    OFFSET can be hex (0x1234) or decimal.
    """
    firmware = load_firmware(rom_file)
    banks = get_banks(firmware)

    if bank_num < 0 or bank_num >= len(banks):
        click.echo(f"Error: Bank {bank_num} does not exist. Available: 0-{len(banks)-1}")
        return

    # Parse offset
    try:
        if offset.startswith('0x') or offset.startswith('0X'):
            off = int(offset, 16)
        else:
            off = int(offset)
    except ValueError:
        click.echo(f"Error: Invalid offset: {offset}")
        return

    bank = banks[bank_num]
    if off >= len(bank):
        click.echo(f"Error: Offset 0x{off:04X} beyond bank size 0x{len(bank):04X}")
        return

    data = bank[off:off + count]
    click.echo(f"Bank {bank_num}, offset 0x{off:04X}:")
    click.echo(f"  Hex:   {format_hex_bytes(data, count)}")
    click.echo(f"  ASCII: {format_ascii(data)}")


if __name__ == '__main__':
    cli()
