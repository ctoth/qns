# QNS - Q's Note Speak Emulator

Emulator for the Blazie Engineering BNS (Braille 'N Speak) family of devices.

## Current Status

**SSI-263 synthesizer complete and working standalone.** Generates real PCM audio from phoneme data.

**Z180 CPU segfaults** - needs investigation. ROM format also unclear.

```bash
# SSI-263 synth works standalone
uv run pytest tests/test_synth.py::test_synth_speaks_phoneme -v -s  # Hear audio

# Emulator crashes
uv run python -m qns.bns --audio roms/NFB99/BSPENG/bspeng.bns  # Segfault
```

## Project Structure

```
qns/
├── qns/
│   ├── synth/                # NEW - SSI-263 audio synthesis
│   │   ├── __init__.py       # Exports SSI263Synth, SSI263State
│   │   ├── phonemes.py       # 62 phonemes, 156K samples @ 22050 Hz
│   │   ├── dsp.py            # Amplitude, filter, pitch, time stretch
│   │   ├── player.py         # sounddevice real-time audio
│   │   └── ssi263_synth.py   # Main synthesizer class
│   ├── _z180_cffi.*.pyd      # Z180 native extension (SEGFAULTS)
│   ├── cpu.py                # Z180 wrapper (CFFI bindings)
│   ├── ssi263.py             # SSI-263 register emulation
│   ├── memory.py             # Memory + Z180 MMU banking
│   ├── io.py                 # I/O port handlers
│   └── bns.py                # Main emulator
├── tools/
│   ├── build_ffi.py          # CFFI build script
│   └── extract_phonemes.py   # Extract phonemes from AppleWin
├── tests/
│   └── test_synth.py         # 20 tests (17 auto, 3 manual)
├── roms/NFB99/               # ROM images (may need unpacking?)
└── prompts/
    ├── handoff.md            # General handoff
    └── z180-investigation.md # Z180/ROM research task
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
- **Input**: 8-dot Braille keyboard

## Commands

```bash
# Build CFFI extension
uv run python tools/build_ffi.py

# Run synth tests (working)
uv run pytest tests/test_synth.py -v

# Manual audio test
uv run pytest tests/test_synth.py::test_synth_speaks_phoneme -v -s

# Run emulator (currently segfaults)
uv run python -m qns.bns --audio roms/NFB99/BSPENG/bspeng.bns
```

## What Works

1. **SSI-263 Synthesizer** - Complete standalone module
   - Real PCM audio from AppleWin phoneme samples
   - DSP: amplitude, filter, pitch shift, time stretch
   - sounddevice real-time playback
   - Integration with SSI263 chip via `set_synth()`

## What's Broken

1. **Z180 CPU** - Segfaults when running ROM
   - See `prompts/z180-investigation.md` for research task

2. **ROM format** - May need unpacking
   - NFB99 ROMs might be updater programs, not raw firmware
