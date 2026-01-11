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

1. **SSI-263 Speech Synthesizer** - COMPLETE
   - `qns/synth/` - Standalone module generating real PCM audio
   - 62 phonemes extracted from AppleWin (156K samples @ 22050 Hz)
   - DSP: amplitude, filter, pitch shift, time stretch
   - Real-time audio via sounddevice
   - 20 tests (17 automated, 3 manual)

   ```bash
   # Hear actual phoneme audio
   uv run pytest tests/test_synth.py::test_synth_speaks_phoneme -v -s
   ```

2. **SSI-263 Register Emulation** - `qns/ssi263.py`
   - Hardware-accurate register handling
   - Integration with synth via `set_synth()`

3. **Memory Subsystem** - `qns/memory.py`
   - 512KB RAM, ROM overlay
   - Z180 MMU banking (CBR/BBR/CBAR)

4. **I/O Bus** - `qns/io.py`
   - Keyboard, display, speech handlers

### Broken

1. **Z180 CPU** - SEGFAULTS
   - See `prompts/z180-investigation.md` for research task
   - Either z180emu C library has issues, or CFFI bindings are wrong

2. **ROM Format** - UNCLEAR
   - ROMs in `roms/NFB99/` might be updater programs, not raw firmware
   - May need unpacking/extraction

## Key Files

```
qns/
├── qns/
│   ├── synth/           # SSI-263 audio (WORKING)
│   ├── ssi263.py        # SSI-263 registers (WORKING)
│   ├── cpu.py           # Z180 wrapper (BROKEN - segfaults)
│   ├── memory.py        # Memory subsystem
│   ├── io.py            # I/O bus
│   └── bns.py           # Main emulator
├── tools/
│   ├── build_ffi.py     # CFFI build script
│   └── extract_phonemes.py
├── tests/
│   └── test_synth.py    # 20 tests
└── roms/NFB99/          # ROM images (format unclear)
```

## External Dependencies

- **z180emu**: `C:\Users\Q\src\z180emu` - Z180 CPU emulator in C
- **BNS source**: `C:\Users\Q\src\bns\` - Original Blazie source (ASM)
- **Technical report**: `C:\Users\Q\src\bns\EMULATION_REPORT.md`
- **AppleWin SSI-263**: `C:\Users\Q\src\AppleWin\source\SSI263.cpp`

## Next Priority

**Fix the Z180 CPU / ROM format issue.** See `prompts/z180-investigation.md`.

Once the CPU works:
- Audio will work via `--audio` flag
- Keyboard input needed (map PC keys to Braille dots)
- Serial I/O for file transfer

## Build Commands

```bash
cd C:\Users\Q\code\qns

# Build CFFI extension
uv run python tools/build_ffi.py

# Run synth tests (WORKING)
uv run pytest tests/test_synth.py -v

# Manual audio test (WORKING)
uv run pytest tests/test_synth.py::test_synth_speaks_phoneme -v -s

# Run emulator (BROKEN - segfaults)
uv run python -m qns.bns --audio roms/NFB99/BSPENG/bspeng.bns
```

## Gotchas

- Always use `uv run` for Python commands
- z180emu's `z180.c` #includes other .c files - don't compile separately
- z80common.h has tentative `int VERBOSE;` - must provide definition before include
