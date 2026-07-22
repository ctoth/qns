# Task: Create Firmware Extraction Tool

## Context

The BNS emulator currently extracts firmware from .bns update packages on every startup. This is wasteful - we should extract once and save to a known location.

.bns files are update packages with firmware at offset 0x3000. The firmware itself is up to 256KB (4 x 64KB banks), but we only need the first 64KB bank for emulation.

## Objective

Create a CLI tool `tools/extract_firmware.py` that:
1. Reads a .bns update package
2. Extracts firmware from offset 0x3000
3. Saves the first 64KB bank to `roms/extracted/<name>.bin`
4. Prints info about what was extracted

## Files to Read
- `qns/bns.py` - see `load_rom()` method for current extraction logic (lines 148-178)
- `tools/rom_analyzer.py` - for click CLI patterns

## Files to Create
- `tools/extract_firmware.py` - new extraction tool

## Implementation

```python
"""Extract firmware from BNS update packages."""

import click
from pathlib import Path

IMAGE_OFFSET = 0x3000
BANK_SIZE = 0x10000  # 64KB

@click.command()
@click.argument('bns_file', type=click.Path(exists=True, path_type=Path))
@click.option('--output', '-o', type=click.Path(path_type=Path),
              help='Output path (default: roms/extracted/<name>.bin)')
def extract(bns_file: Path, output: Path | None):
    """Extract firmware from BNS update package."""
    data = bns_file.read_bytes()

    # Check for BNS package format
    if len(data) < 5 or data[2:5] != b'BNS':
        click.echo(f"Error: {bns_file} is not a BNS update package")
        return

    # Extract firmware
    firmware = data[IMAGE_OFFSET:]
    click.echo(f"Package: {bns_file.name}")
    click.echo(f"  Total size: {len(data):,} bytes")
    click.echo(f"  Firmware offset: 0x{IMAGE_OFFSET:04X}")
    click.echo(f"  Firmware size: {len(firmware):,} bytes")

    # Take first 64KB bank
    bank0 = firmware[:BANK_SIZE]
    if len(bank0) < BANK_SIZE:
        bank0 = bank0 + b'\xff' * (BANK_SIZE - len(bank0))

    # Determine output path
    if output is None:
        output_dir = Path('roms/extracted')
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{bns_file.stem}.bin"

    output.write_bytes(bank0)
    click.echo(f"  Extracted bank 0 to: {output}")
    click.echo(f"  Output size: {len(bank0):,} bytes")

if __name__ == '__main__':
    extract()
```

Also update `qns/bns.py` `load_rom()` to detect already-extracted .bin files and skip extraction.

## Test Command
```bash
uv run python tools/extract_firmware.py roms/NFB99/BSPENG/bspeng.bns
ls -la roms/extracted/
uv run python -m qns.bns --cycles 1000000 roms/extracted/bspeng.bin 2>&1 | tail -5
```

## Output
Write findings/status to `./reports/extract-firmware-tool-report.md`

## CRITICAL: File Modified Error Workaround

If Edit/Write fails with "file unexpectedly modified":
1. Read the file again with Read tool
2. Retry the Edit
3. Try path formats: `./relative`, `C:/forward/slashes`, `C:\back\slashes`
4. NEVER use cat, sed, echo - always Read/Edit/Write
5. If all formats fail, STOP and report

## CRITICAL: Parallel Swarm Awareness

You may be running alongside other agents in parallel.
- NEVER use git restore, git checkout, git reset, git clean
- If you mess up a file beyond repair: STOP, write what happened to your report, exit
