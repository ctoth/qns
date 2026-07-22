# Task: Load All 4 ROM Banks (256KB) Instead of Just Bank 0

## Context

ROOT CAUSE FOUND for silent startup! The "Braille 'n Speak ready" message (TALK09) is in ROM Bank 3 at offset 0xEC2D, but we only load Bank 0 (first 64KB).

The firmware uses Z180 MMU bank switching (via CBR register) to access different ROM banks:
- Bank 0: 0x00000-0x0FFFF - Code
- Bank 1: 0x10000-0x1FFFF
- Bank 2: 0x20000-0x2FFFF
- Bank 3: 0x30000-0x3FFFF - Contains speech messages

When SETSP tries to read TALK09, it switches CBR to access Bank 3, but since we only loaded Bank 0, it reads 0xFF (uninitialized memory) and speech fails.

## Objective

Fix ROM loading to load all 256KB (4 banks) instead of truncating to 64KB.

## Files to Read
- `qns/memory.py` - Memory class, see `rom` and `load_rom()`
- `qns/bns.py` - BNS class, see `load_rom()` method
- `tools/extract_firmware.py` - Firmware extraction tool

## Files to Modify
- `qns/memory.py` - Increase ROM size to 256KB
- `qns/bns.py` - Remove the 64KB truncation in `load_rom()`
- `tools/extract_firmware.py` - Extract full firmware, not just bank 0

## Implementation

### qns/memory.py
Change ROM size from 64KB to 256KB:
```python
def __init__(self, ram_size: int = 512 * 1024, rom_size: int = 256 * 1024):
```

### qns/bns.py
In `load_rom()`, remove the truncation that limits to 64KB. The code currently says:
```python
if len(data) > 0x10000:
    print(f"  Truncating to 64KB ROM (from {len(data)} bytes)")
    data = data[:0x10000]
```
Remove this - let all banks load.

### tools/extract_firmware.py
Change to extract full firmware (256KB) instead of just bank 0:
```python
# Take full firmware, pad to 256KB if needed
firmware = firmware[:256*1024]  # max 256KB
if len(firmware) < 256*1024:
    firmware = firmware + b'\xff' * (256*1024 - len(firmware))
```

## Test Command
```bash
# First extract full firmware
uv run python tools/extract_firmware.py roms/NFB99/BSPENG/bspeng.bns -o roms/extracted/bspeng_full.bin

# Run emulator and look for non-pause phonemes
uv run python -m qns.bns --cycles 20000000 roms/extracted/bspeng_full.bin 2>&1 | grep SSI263 | head -30
```

Expected: Should see phonemes OTHER than 0x00 (pause) - actual speech phonemes.

## Output
Write findings/status to `./reports/load-all-rom-banks-report.md`

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
