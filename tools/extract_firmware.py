"""Extract firmware from BNS update packages to raw .bin images."""

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).parent.parent))

from qns.loader import load_firmware

BANK_SIZE = 0x10000  # 64KB
FULL_ROM_SIZE = 4 * BANK_SIZE  # 256KB


@click.command()
@click.argument('bns_file', type=click.Path(exists=True, path_type=Path))
@click.option('--output', '-o', type=click.Path(path_type=Path),
              help='Output path (default: roms/extracted/<name>.bin)')
def extract(bns_file: Path, output: Path | None):
    """Extract firmware from a BNS update package."""
    image = load_firmware(bns_file)
    if image.kind != "package":
        click.echo(f"Error: {bns_file} is not a BNS update package")
        return

    click.echo(f"Package: {bns_file.name}")
    click.echo(f"  Total size: {image.package_size:,} bytes")
    click.echo(f"  Firmware offset: 0x{image.image_offset:04X}")
    click.echo(f"  Firmware size: {len(image.data):,} bytes")

    # Pad to the full 256KB (4 banks) ROM image the emulator maps
    full_rom = image.data[:FULL_ROM_SIZE]
    if len(full_rom) < FULL_ROM_SIZE:
        full_rom = full_rom + b'\xff' * (FULL_ROM_SIZE - len(full_rom))

    num_banks = (len(image.data) + BANK_SIZE - 1) // BANK_SIZE
    click.echo(f"  Banks in firmware: {num_banks}")

    if output is None:
        output_dir = Path('roms/extracted')
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{bns_file.stem}_full.bin"

    output.write_bytes(full_rom)
    click.echo(f"  Extracted full ROM to: {output}")
    click.echo(f"  Output size: {len(full_rom):,} bytes (4 banks)")


if __name__ == '__main__':
    extract()
