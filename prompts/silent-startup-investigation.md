# BNS Silent Startup Investigation

## Current Status

The emulator now boots the BNS firmware successfully:
- CPU executes without crashing
- Memory/RAM works correctly (~265K writes during boot)
- Keyboard interrupt (INT2) is wired up
- SSI-263 receives phoneme writes

**The Problem:** All ROM variants take the "silent startup" path and never speak.

## What's Been Fixed

1. **CPU Segfault** - Added `cpu_reset_z180()` in CFFI wrapper to initialize MMU
2. **ROM Format** - BNS files are update packages; firmware extracted from offset 0x3000
3. **Memory** - Removed duplicate MMU translation (z180emu handles it internally)
4. **Keyboard** - Added INT2 interrupt support with keyclr port (0x20)

## The Silent Startup Mystery

In `C:\Users\Q\src\bns\bsp\BS.ASM` lines 2169-2173:
```asm
LD A,(ONFLG)    ;SEE IF WE SHOULD SAY ANYTHING.
CP 1            ;IS FLAG SET?
jr z,..silent
cp 2            ; both are silent startup commands
JR NZ,NOCFG6    ;NO, NORMAL STARTUP (speaks "Braille 'n Speak ready")
..silent:       ;SKIPS speech, just chirps
```

If ONFLG is 0, it should fall through to NOCFG6 and speak the boot message.
ONFLG is set to 0 at line 1657: `XOR A; LD (ONFLG),A`

But something causes silent mode in ALL tested ROMs:
- bspeng.bns (Braille 'n Speak Plus)
- bl2eng.bns (Braille Lite 2000)
- bs2eng.bns (BNS 2)
- bsleng.bns (Braille Lite)
- tnseng.tns (Type 'n Speak) - uses different SSI-263 port 0x90

## Investigation Areas

### 1. ONFLG Value
Where ONFLG gets set (BS.ASM):
- Line 1657: Reset to 0 (normal)
- Line 1865: Set if space bar (0xA9) detected
- Line 2079: Set if bit 6 (space key) is held
- Line 2091: Silent with macro
- Line 3016: Another set point

**Task:** Trace what value ONFLG has when the check at line 2169 happens.

### 2. Unregistered Ports
During boot, we see reads from:
- 0x40 (keyboard) - returns 0x00 (correct)
- 0x6F (RTC offset?) - returns 0xFF (unregistered, might be wrong)

Port 0x6F is likely RTC (CKPORT=0x60 + offset 15). Returning 0xFF might cause issues.

### 3. Status Checks
The firmware might check hardware status that we're not emulating:
- Battery status
- Power control
- RTC validity
- EEPROM/flash configuration

### 4. Different Hardware Variants
The ROMs are compiled for specific hardware:
- BSPLUS: Keyboard 0x40, SSI-263 0xC0
- B_LITE_40: Keyboard 0xB0, SSI-263 0x90
- TNS: QWERTY keyboard at 0xD0

The TNS ROM outputs only 1 pause phoneme because SSI-263 is at 0x90 not 0xC0.

## Test Commands

```bash
# Run emulator (currently only outputs pauses)
uv run python -m qns.bns --audio roms/NFB99/BSPENG/bspeng.bns

# Quick test of boot behavior
uv run python -c "
from qns.bns import BNS
bns = BNS(audio=False)
bns.load_rom('roms/NFB99/BSPENG/bspeng.bns')
bns.reset()
bns.cpu.run(10_000_000)
print('PC:', hex(bns.cpu.pc))
print('Phonemes:', len(bns.ssi263.phoneme_log))
non_pause = [p for p in bns.ssi263.phoneme_log if p > 0]
print('Non-pause:', len(non_pause))
"
```

## Key Files

```
qns/bns.py           - Main emulator, ROM loading, I/O setup
qns/io.py            - Keyboard with INT2, keyclr, display
qns/memory.py        - Physical address handling
qns/ssi263.py        - SSI-263 register emulation
qns/cpu.py           - Z180 wrapper (CFFI)
tools/build_ffi.py   - CFFI wrapper with debug counters

C:\Users\Q\src\bns\bsp\BS.ASM         - Main BNS source
C:\Users\Q\src\bns\bsp\LIB\BSPORTS.LIB - Port definitions
C:\Users\Q\src\bns\EMULATION_REPORT.md - Hardware documentation
```

## What SSI-263 Receives During Boot

```
CtrlAmp writes (all with amp=0, meaning volume=0):
  0x80: CTL=1 (standby)
  0x70: CTL=0, art=7 (wake with articulation)
  0x50: CTL=0, art=5

Phoneme writes:
  0xC0: mode=3, phoneme=0x00 (pause with transitioned inflection)
  0x00: mode=0, phoneme=0x00 (pause, IRQ disabled)
```

This is just initialization - the SETSP speech routine never gets called with actual text.

## Investigation Progress (2024-01-10)

### Root Cause Identified: Memory Layout Was Wrong

**The Problem:** The 262KB ROM file was being loaded entirely, occupying physical addresses 0x00000-0x3FE00. Variables like ONFLG at logical 0xD468 mapped to physical 0xD468, which was ROM (read-only). Writes silently failed.

**The Fix (Partial):** Modified `memory.py` to use correct BNS physical memory layout:
- Physical 0x00000-0x0FFFF: ROM (64KB, first bank only)
- Physical 0x10000+: RAM (512KB)

**Result:** Now getting 41K+ writes during boot (was 0 before). But still only pause phonemes.

### Key Technical Findings

1. **z180emu handles MMU internally** - Our I/O handlers for ports 0x38-0x3A never get called. z180emu intercepts MMU register writes and updates its internal translation table.

2. **MMU Configuration** - The firmware sets:
   - CBR = 0x32 (implied from write addresses going to 0x41000+)
   - CBAR = 0xFE (Bank starts at 0xE000, Common1 at 0xF000)
   - This maps Common Area 1 (0xF000-0xFFFF) to physical 0x41000-0x41FFF

3. **Write Address Pattern:**
   - All writes go to physical 0x41000-0x90FFF (RAM region)
   - Most writes (41K) concentrated in 0x41000-0x41FFF
   - No writes to 0x00000-0x0FFFF (ROM) - correct behavior now

4. **ONFLG Mystery Remains:**
   - ONFLG at logical 0xD468 is in page 13 (Common Area 0)
   - With current MMU, pages 0-13 map 1:1 (no offset)
   - Physical 0xD468 is in ROM, so writes would fail
   - But we see no writes attempting 0xD468 region at all
   - The firmware might be using different MMU settings when initializing ONFLG

### What Still Needs Investigation

1. **Why doesn't ONFLG get written?** The XOR A; LD (ONFLG),A at line 1657 should write 0, but we never see writes to 0xD000-0xE000.

2. **MMU State During Init** - The MMU is configured BEFORE ONFLG init. Need to trace exact MMU state at that moment.

3. **Possible Banked Code** - The 262KB firmware has 4 banks. Maybe init code is in a different bank that we're not loading?

## Suggested Next Steps

1. ~~Add RTC emulation~~ - Not the root cause
2. **Trace MMU state changes** - Log when CBR/BBR/CBAR change
3. **Add debug CLI commands** - `--trace-mmu`, `--trace-writes <addr>`, `--breakpoint <addr>`
4. **Check if init code is in bank 0** - Compare code at offset 0 vs other banks
5. **Add ONFLG watchpoint** - Alert when logical 0xD468 is accessed

## Success Criteria

- Hear "Braille 'n Speak ready" on boot
- See non-zero phonemes in SSI-263 log
- Understand why silent startup was triggered
