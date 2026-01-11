# QNS - Q's Note Speak Emulator

Emulator for the Blazie Engineering BNS (Braille 'N Speak) family of devices.

## Current Status

**Z180 CPU boots successfully.** Firmware runs, memory works, keyboard interrupt functional.

**Silent startup mystery.** All ROMs take silent path - SSI-263 only receives pause phonemes.

```bash
# Run emulator (boots but doesn't speak)
uv run python -m qns.bns --audio roms/NFB99/BSPENG/bspeng.bns

# SSI-263 synth works standalone
uv run pytest tests/test_synth.py::test_synth_speaks_phoneme -v -s
```

## Project Structure

```
qns/
├── qns/
│   ├── synth/                # SSI-263 audio synthesis (working)
│   │   ├── __init__.py       # Exports SSI263Synth, SSI263State
│   │   ├── phonemes.py       # 62 phonemes, 156K samples @ 22050 Hz
│   │   ├── dsp.py            # Amplitude, filter, pitch, time stretch
│   │   ├── player.py         # sounddevice real-time audio
│   │   └── ssi263_synth.py   # Main synthesizer class
│   ├── _z180_cffi.*.pyd      # Z180 native extension (working)
│   ├── cpu.py                # Z180 wrapper (CFFI bindings)
│   ├── ssi263.py             # SSI-263 register emulation
│   ├── memory.py             # Memory + Z180 MMU (physical addressing)
│   ├── io.py                 # I/O: keyboard w/INT2, display, keyclr
│   └── bns.py                # Main emulator
├── tools/
│   ├── build_ffi.py          # CFFI build script (with debug counters)
│   └── extract_phonemes.py   # Extract phonemes from AppleWin
├── tests/
│   └── test_synth.py         # 20 tests (17 auto, 3 manual)
├── roms/NFB99/               # ROM images (update packages)
└── prompts/
    ├── handoff.md                    # General handoff
    ├── z180-investigation.md         # Z180 research (RESOLVED)
    └── silent-startup-investigation.md # Current issue
```

## Related Resources

- **z180emu**: `C:\Users\Q\src\z180emu\` - Z180 CPU emulator (C)
- **BNS source**: `C:\Users\Q\src\bns\` - Original Blazie source (ASM)
- **Technical report**: `C:\Users\Q\src\bns\EMULATION_REPORT.md`
- **AppleWin SSI-263**: `C:\Users\Q\src\AppleWin\source\SSI263.cpp`

## Hardware Target

- **CPU**: Z180 (HD64180) @ 12.288 MHz
- **Speech**: SSI-263 phoneme synthesizer (64 phonemes)
- **Display**: Braille cells
- **Input**: 8-dot Braille keyboard with INT2 interrupt

## Commands

```bash
# Build CFFI extension (required after changes to build_ffi.py)
uv run python tools/build_ffi.py

# Run synth tests
uv run pytest tests/test_synth.py -v

# Manual audio test (hear phoneme)
uv run pytest tests/test_synth.py::test_synth_speaks_phoneme -v -s

# Run emulator (boots, outputs pauses, enters main loop)
uv run python -m qns.bns --audio roms/NFB99/BSPENG/bspeng.bns
```

## What Works

1. **Z180 CPU** - Executes firmware without crashing
   - MMU properly initialized via cpu_reset_z180()
   - ~265K memory writes during boot
   - Keyboard interrupt (INT2) wired to CPU

2. **ROM Loading** - Extracts firmware from update packages
   - BNS files are update programs, not raw firmware
   - Firmware at offset 0x3000 in .bns files

3. **SSI-263 Synthesizer** - Complete standalone module
   - Real PCM audio from AppleWin phoneme samples
   - DSP: amplitude, filter, pitch shift, time stretch
   - Integration with SSI263 chip via `set_synth()`

4. **Memory System** - Physical addressing works
   - z180emu handles MMU translation internally
   - Memory callbacks receive physical addresses

## What's Not Working

1. **Speech Output** - Firmware takes "silent startup" path
   - ONFLG flag check at BS.ASM:2169 causes skip
   - See `prompts/silent-startup-investigation.md`

2. **Missing Peripherals**
   - RTC (0x60-0x6F) - returns 0xFF
   - Status ports may need proper emulation

## Development Principle: Tooling First

**This project lives and dies on tooling.**

1. **Always use project tooling** - CLI tools in `qns/bns.py` and `tools/`
2. **If tooling doesn't exist, build it first** - Spec what you need, dispatch subagent to implement, then use it
3. **Expand the CLI** - Add click commands for any repeated debugging task
4. **Invest in visibility** - Every mystery is a missing debug tool

Current CLI (`qns/bns.py`):
```bash
uv run python -m qns.bns --help
uv run python -m qns.bns --cycles N --stats rom.bns
uv run python -m qns.bns --trace-writes 0xADDR rom.bns
uv run python -m qns.bns --trace-io rom.bns
```

When adding tools, consider:
- What question am I trying to answer?
- What visibility do I lack?
- Can z180emu expose more state? (modify C, rebuild CFFI)
- Can the CLI filter/format output better?
