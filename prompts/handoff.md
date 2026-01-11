# QNS Emulator Handoff

## Project Location

`C:\Users\Q\code\qns`

## What This Is

QNS (Q's Note Speak) is an emulator for the Blazie Engineering BNS (Braille 'N Speak) family of devices - portable note-takers for the blind from the 1990s. These devices use:

- **Z180 (HD64180) CPU** @ 12.288 MHz
- **SSI-263 phoneme speech synthesizer** (64 phonemes)
- **8-dot Braille keyboard** for input
- **Braille display cells** for output

## Current State (2025-01-10)

### Working

1. **Z180 CPU** - Boots and runs firmware
   - `qns/cpu.py` - CFFI bindings to z180emu
   - CPU executes ~41K memory writes during boot
   - MMU translation handled internally by z180emu

2. **SSI-263 Speech Synthesizer** - Complete standalone module
   - `qns/synth/` - Real PCM audio from AppleWin phoneme samples
   - 62 phonemes, DSP: amplitude, filter, pitch shift, time stretch
   - 20 tests (17 automated, 3 manual)

3. **Memory Subsystem** - `qns/memory.py`
   - Physical layout: ROM at 0x00000-0x0FFFF (64KB), RAM at 0x10000+ (512KB)
   - z180emu handles MMU translation internally

4. **I/O Bus** - `qns/io.py`
   - Keyboard with INT2, keyclr, display, watchdog

5. **CLI with debug options** - `qns/bns.py`
   ```bash
   uv run python -m qns.bns --help
   uv run python -m qns.bns --cycles 1000000 --stats rom.bns
   uv run python -m qns.bns --trace-writes 0xD468 rom.bns
   ```

### The Problem: Silent Startup

**The emulator boots but doesn't speak.** All ROM variants take the "silent startup" path - SSI-263 only receives pause phonemes.

See `prompts/silent-startup-investigation.md` for full details.

#### What We Know

1. **ONFLG controls speech** - BS.ASM lines 2169-2173:
   - ONFLG=0 → normal startup (speaks "Braille 'n Speak ready")
   - ONFLG=1 or 2 → silent startup (just chirps)

2. **ONFLG is at logical 0xD468** (found via ROM pattern search)

3. **Memory layout was wrong (FIXED)** - ROM was 262KB, occupying physical 0-0x3FE00. Fixed to 64KB ROM at physical 0-0xFFFF.

4. **Writes now work** - 41K+ writes during boot, all going to 0x41000+ (RAM)

5. **But ONFLG region has no writes** - No writes to physical 0xD000-0xE000 observed

#### The Mystery

Logical 0xD468 is in page 13 (Common Area 0). With the MMU settings (CBAR=0xFE), pages 0-13 map 1:1 to physical addresses. So logical 0xD468 → physical 0xD468, which is in ROM!

Either:
- The init code never runs (wrong ROM bank?)
- ONFLG is at a different address than we think
- The MMU settings are different during init

## Key Files

```
qns/
├── qns/
│   ├── synth/           # SSI-263 audio synthesis (working)
│   ├── ssi263.py        # SSI-263 register emulation
│   ├── cpu.py           # Z180 CFFI wrapper
│   ├── memory.py        # Physical memory (ROM 0-64KB, RAM 64KB+)
│   ├── io.py            # I/O bus, keyboard, display
│   └── bns.py           # Main emulator with CLI
├── tools/
│   ├── build_ffi.py     # CFFI build script
│   └── extract_phonemes.py
├── tests/
│   └── test_synth.py    # 20 tests
├── roms/NFB99/          # ROM images (update packages)
└── prompts/
    ├── handoff.md       # This file
    └── silent-startup-investigation.md  # Detailed investigation notes
```

## External Resources

- **z180emu**: `C:\Users\Q\src\z180emu\` - Z180 CPU emulator (C)
- **BNS source**: `C:\Users\Q\src\bns\bsp\BS.ASM` - Original firmware source
- **Technical report**: `C:\Users\Q\src\bns\EMULATION_REPORT.md`

## Next Steps

1. **Why no writes to 0xD000-0xE000?**
   - The `XOR A; LD (ONFLG),A` at BS.ASM line 1657 should write 0 to ONFLG
   - Add tracing to detect any writes to that region

2. **Check ROM bank structure**
   - The 262KB firmware has 4 banks × 64KB
   - We only load bank 0 - is the init code there?
   - Compare code between banks

3. **Trace early MMU state**
   - z180emu handles MMU internally; we can't easily see its state
   - May need to modify z180emu to log MMU changes

4. **Add logical address tracing**
   - Current `--trace-writes` traces physical addresses
   - Need to trace logical 0xD468 before MMU translation

## Commands

```bash
cd C:\Users\Q\code\qns

# Build CFFI extension (after z180emu changes)
uv run python tools/build_ffi.py

# Run emulator with stats
uv run python -m qns.bns --cycles 1000000 --stats roms/NFB99/BSPENG/bspeng.bns

# Trace I/O operations
uv run python -m qns.bns --trace-io --cycles 100000 roms/NFB99/BSPENG/bspeng.bns

# Run synth tests
uv run pytest tests/test_synth.py -v

# Manual audio test (hear a phoneme)
uv run pytest tests/test_synth.py::test_synth_speaks_phoneme -v -s
```

## Success Criteria

- Hear "Braille 'n Speak ready" on boot
- See non-zero phonemes in SSI-263 log
- Understand why ONFLG was not being initialized to 0
