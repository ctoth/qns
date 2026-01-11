# Load All 4 ROM Banks (256KB) - Completion Report

## Task Summary

**Objective**: Fix ROM loading to load all 256KB (4 banks) instead of truncating to 64KB.

**Status**: COMPLETE - All 4 ROM banks now load correctly.

## Changes Made

### 1. qns/memory.py

Changed default ROM size from 64KB to 256KB:

```python
# Before
def __init__(self, ram_size: int = 512 * 1024, rom_size: int = 64 * 1024):

# After
def __init__(self, ram_size: int = 512 * 1024, rom_size: int = 256 * 1024):
```

### 2. qns/bns.py

**Removed 64KB truncation** - now accepts up to 256KB:

```python
# Before
if len(data) > 0x10000:
    print(f"  Truncating to 64KB ROM (from {len(data)} bytes)")
    data = data[:0x10000]

# After
if len(data) > 256 * 1024:
    print(f"  Limiting to 256KB ROM (from {len(data)} bytes)")
    data = data[:256 * 1024]
```

**Updated .bin file detection** to accept both 64KB and 256KB:

```python
# Before
if path.suffix.lower() == '.bin' and len(data) == 0x10000:

# After
if path.suffix.lower() == '.bin' and len(data) in (0x10000, 0x40000):
```

### 3. tools/extract_firmware.py

Changed to extract full 256KB instead of just bank 0:

```python
# Before: Extracted only bank 0 (64KB)
bank0 = firmware[:BANK_SIZE]

# After: Extracts all 4 banks (256KB)
FULL_ROM_SIZE = 4 * BANK_SIZE  # 256KB
full_rom = firmware[:FULL_ROM_SIZE]
```

Also changed default output filename from `<name>.bin` to `<name>_full.bin`.

## Verification Results

### Firmware Extraction

```
Package: bspeng.bns
  Total size: 274,174 bytes
  Firmware offset: 0x3000
  Firmware size: 261,886 bytes
  Banks in firmware: 4
  Extracted full ROM to: roms/extracted/bspeng_full.bin
  Output size: 262,144 bytes (4 banks)
```

### Memory Loading Verification

```
ROM size in memory: 262144 bytes

Bank 0 (0x00000-0x0FFFF): first 16 bytes: f3c32f03ff434f505952494748542031
Bank 1 (0x10000-0x1FFFF): first 16 bytes: 21bbd9e5cdfcaad1225ed7dd7efab728
Bank 2 (0x20000-0x2FFFF): first 16 bytes: b72814dd6efbdd66fc11060019e57edd
Bank 3 (0x30000-0x3FFFF): first 16 bytes: 21faffcd283fdd6e04dd6605dd75fcdd

TALK09 at 0x3EC2D in memory: 537065616b20726561647900656e64206f662066
                              ^-- "Speak ready\0end of f..."

Testing memory.read() for bank 3:
  read(0x30000) = 0x21
  read(0x3EC2D) = 0x53  <-- 'S' from "Speak ready"
  read(0x3FFFF) = 0xFF
```

All 4 ROM banks are now loaded and accessible:
- Bank 0 (0x00000-0x0FFFF): Code
- Bank 1 (0x10000-0x1FFFF): Data
- Bank 2 (0x20000-0x2FFFF): Data
- Bank 3 (0x30000-0x3FFFF): Speech messages (including TALK09 "Speak ready")

## Current Speech Status

After loading all 4 ROM banks, the emulator still outputs only pause phonemes (0x00). This indicates that while the ROM data is now accessible, the firmware is still taking a path that doesn't reach the speech routines.

The "silent startup" issue is **not** caused by missing ROM banks. The root cause lies elsewhere - likely in:
1. The ONFLG flag check at BS.ASM:2169
2. Missing peripheral emulation (RTC, status ports)
3. Other initialization conditions not being met

## Files Modified

| File | Change |
|------|--------|
| `qns/memory.py` | ROM size 64KB -> 256KB |
| `qns/bns.py` | Remove 64KB truncation, accept 256KB .bin files |
| `tools/extract_firmware.py` | Extract full 256KB, output as `*_full.bin` |

## Test Commands

```bash
# Extract full firmware
uv run python tools/extract_firmware.py roms/NFB99/BSPENG/bspeng.bns

# Run emulator with full ROM
uv run python -m qns.bns --cycles 20000000 roms/extracted/bspeng_full.bin

# Verify ROM loading
uv run python -c "
from qns.bns import BNS
bns = BNS()
bns.load_rom('roms/extracted/bspeng_full.bin')
print(f'ROM size: {len(bns.memory.rom)} bytes')
print(f'Bank 3 accessible: {bns.memory.read(0x3EC2D):02X}')  # Should be 0x53 ('S')
"
```

## Conclusion

The ROM loading is now working correctly. All 256KB (4 banks) are loaded and accessible via the Z180 MMU. The TALK09 speech message at 0x3EC2D in Bank 3 is present and readable.

The continued "silent startup" issue requires investigation in other areas of the emulator, not ROM loading.
