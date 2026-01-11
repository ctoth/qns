# Extract Firmware Tool Report

## Task Summary

Created a CLI tool to extract firmware from BNS update packages and updated the emulator to load pre-extracted files directly.

## Files Created

### `tools/extract_firmware.py`

A click-based CLI tool that:
- Reads .bns update packages
- Validates the BNS header (bytes 2-5 must be 'BNS')
- Extracts firmware from offset 0x3000
- Saves the first 64KB bank to `roms/extracted/<name>.bin`
- Pads to 64KB if firmware is smaller
- Prints extraction statistics

```bash
# Usage
uv run python tools/extract_firmware.py roms/NFB99/BSPENG/bspeng.bns

# With custom output path
uv run python tools/extract_firmware.py roms/NFB99/BSPENG/bspeng.bns -o custom.bin
```

## Files Modified

### `qns/bns.py` - `load_rom()` method

Updated to detect and handle three formats:

1. **Pre-extracted .bin files** (new) - Detects files with `.bin` extension that are exactly 64KB. Loads directly without extraction overhead.

2. **BNS update packages** (existing) - Detects via 'BNS' magic at bytes 2-5. Extracts firmware from offset 0x3000.

3. **Raw firmware** (existing) - Truncates to 64KB if larger.

## Test Results

### Extraction Test

```
$ uv run python tools/extract_firmware.py roms/NFB99/BSPENG/bspeng.bns
Package: bspeng.bns
  Total size: 274,174 bytes
  Firmware offset: 0x3000
  Firmware size: 261,886 bytes
  Extracted bank 0 to: roms\extracted\bspeng.bin
  Output size: 65,536 bytes
```

### Emulator with Pre-extracted File

```
$ uv run python -m qns.bns --cycles 1000000 roms/extracted/bspeng.bin
Loading pre-extracted firmware: bspeng.bin
Loaded ROM: bspeng.bin (65536 bytes at physical 0x00000)
Starting BNS emulation...
Memory: 65536 ROM, 524288 RAM
MMU: CBR=00 BBR=00 CBAR=F0
[SSI263] Phoneme: 0x00 PA (pause) duration=64ms
[SSI263] Phoneme: 0x00 PA (pause) duration=256ms
[Speech] Phonemes: [0, 0]
Executed 1,000,000 cycles
Final PC: 0A33
```

The emulator now:
- Detects the `.bin` file as pre-extracted
- Loads directly without parsing as a BNS package
- Produces identical output to loading from the .bns file

## Output Files

```
roms/extracted/
  bspeng.bin    65,536 bytes    (first 64KB bank)
```

## Benefits

1. **Faster startup** - No extraction overhead when using pre-extracted files
2. **Simpler workflow** - Extract once, run many times
3. **Easier debugging** - Can hex-edit the .bin file directly
4. **Clearer code path** - Explicit format detection in load_rom()
