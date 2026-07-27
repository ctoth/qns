# QNS - Q's Note Speak Emulator

Emulator for the Blazie Engineering BNS (Braille 'N Speak) family of devices.

## Current Status

**Z180 CPU boots successfully.** Firmware runs, memory works, keyboard interrupt functional.

**The firmware speaks, at real settings.** Its own text-to-speech emits correct
phoneme codes ~0.23s into emulated boot ("Braille 'n Speak ready, help, one
page"), and the SSI-263 now receives a real volume, rate, inflection and filter
frequency. Speech is still an *offline* workflow - trace the phoneme stream,
render it to a WAV - because of one remaining blocker described in
`docs/reports/speech-pipeline-investigation.md`:

- Throughput is ~10-15k cycles/s. Correct phoneme pacing costs ~120ms of
  emulated time each, so live `--audio` is ~1000x too slow.

The old "amplitude 0" blocker is **resolved**, and was not a decode bug. The
four speech settings live in RAM that no shipped code path initialises - a real
unit retains them on battery - so a machine booting RAM at zero made the
firmware correctly write silence, at the wrong rate and pitch too. `qns.loader`
discovers the cells and `BNS` seeds them at load; `--force-amplitude` is no
longer needed. Override with `--volume/--rate/--pitch/--frequency` (names follow
`BSAPI.H`, so `--pitch` is filter frequency and `--frequency` is inflection).

```bash
# Trace the phoneme stream (streams to CSV as it runs)
uv run -m qns.bns --cycles 6000000 --trace-speech speech.csv roms/bspeng.bns

# Render it offline and listen (paplay works under WSLg)
uv run tools/lpc_resynth.py speech.csv out.wav && paplay out.wav

# SSI-263 synth works standalone
uv run pytest tests/test_synth.py::test_synth_speaks_phoneme -v -s
```

## Project Structure

```
qns/
├── qns/
│   ├── synth/                # SSI-263 audio backends
│   │   ├── __init__.py       # Exports SSI263Synth, SSI263PCMSynth, FormantSynth
│   │   ├── phonemes.py       # AppleWin captures: 62 phonemes @ 22050 Hz
│   │   ├── ssi263_pcm.py     # PCM-capture backend (default)
│   │   ├── ssi263_synth.py   # Formant-synthesis backend
│   │   ├── formant.py        # SC-01 formant model (from MAME votrax)
│   │   ├── sc01_rom.py       # Decoded SC-01A ROM parameters
│   │   ├── sc02_to_sc01.py   # SSI-263 -> SC-01 phoneme mapping
│   │   └── player.py         # sounddevice real-time audio
│   ├── devices/              # Peripherals: bus, keyboards, displays,
│   │                         # rtc, clock_pic, gas_gauge, watchdog
│   ├── _z180_cffi.*.pyd      # Legacy benchmark extension (optional)
│   ├── cpu.py                # Legacy CFFI benchmark subject
│   ├── ssi263.py             # SSI-263 chip: register decode, phoneme
│   │                         # capture, INT1; SpeechBackend protocol
│   ├── memory.py             # Memory + Z180 MMU (physical addressing)
│   ├── profiles.py           # Per-model hardware profiles (all 6 models)
│   ├── loader.py             # Firmware extraction (boundary discovery)
│   ├── input_driver.py       # Stdin chord tables + press/release driver
│   ├── stdio.py              # JSONL structured I/O events
│   ├── cli.py                # argparse CLI (python -m qns.bns)
│   └── bns.py                # Main emulator machine
├── tools/
│   ├── build_ffi.py          # Legacy benchmark build script
│   ├── extract_phonemes.py   # Extract phonemes from AppleWin
│   ├── decode_sc01_rom.py    # Regenerates qns/synth/sc01_rom.py
│   ├── extract_firmware.py   # Package -> .bin extraction (uses qns.loader)
│   └── rom_analyzer.py       # ROM bank/structure analysis
├── tests/                    # pytest suite (uv run pytest tests/)
├── roms/NFB99/               # ROM images (update packages)
└── prompts/
    ├── handoff.md                    # General handoff
    ├── z180-investigation.md         # Z180 research (RESOLVED)
    └── silent-startup-investigation.md # Current issue
```

## Related Resources

- **z-core**: `https://github.com/ctoth/z-core` - production Z180 core and Python binding
- **z180emu**: `C:\Users\Q\src\z180emu\` - legacy CFFI benchmark core
- **BNS source**: `C:\Users\David\Dropbox\Daiverd and Q\bns\` - Original Blazie
  source. `bsp/` holds the firmware: `BSSPEECH.ASM` and `BSPMON.ASM` (ISSET,
  the SSI-263 driver), `BSSERIAL.ASM` (Echo parameter handlers), `BRL.ASM`
  (text to phonemes), `LIB/BSPORTS.LIB` (port map), `include/BSAPI.H` and
  `include/BNSAPI.H` (documented speech-parameter ranges).
- **Technical report**: `C:\Users\David\Dropbox\Daiverd and Q\bns\EMULATION_REPORT.md`
- **AppleWin SSI-263**: `C:\Users\Q\src\AppleWin\source\SSI263.cpp`

## Hardware Target

- **CPU**: Z180 (HD64180) @ 12.288 MHz
- **Speech**: SSI-263 phoneme synthesizer (64 phonemes)
- **Display**: Braille cells
- **Input**: 8-dot Braille keyboard with INT2 interrupt

## Commands

```bash
# Refresh the pinned z-core dependency
uv sync

# Build the optional legacy CFFI benchmark after changes to build_ffi.py
uv run tools/build_ffi.py

# Run synth tests
uv run pytest tests/test_synth.py -v

# Manual audio test (hear phoneme)
uv run pytest tests/test_synth.py::test_synth_speaks_phoneme -v -s

# Run emulator with audio - NEEDS ~40M CYCLES TO HEAR SPEECH
uv run -m qns.bns --audio --cycles 40000000 roms/bspeng.bns

# Quick test (5M cycles) - only shows pauses during boot
uv run -m qns.bns --audio --cycles 5000000 roms/bspeng.bns
```

**IMPORTANT**: The emulator needs approximately 40 million cycles before the firmware
starts producing actual speech phonemes. Running with fewer cycles will only show
pause phonemes (0x00) during the boot sequence.

## What Works

1. **Z180 CPU** - Executes firmware without crashing
   - MMU properly initialized via cpu_reset_z180()
   - ~265K memory writes during boot
   - Keyboard interrupt (INT2) wired to CPU

2. **ROM Loading** (`qns/loader.py`) - Extracts firmware from update packages
   - BNS files are update programs, not raw firmware
   - The image boundary is discovered from the package's own length/CRC
     metadata (0x3000 classic, 0x7000/0x8000 Millennium)

3. **SSI-263 Synthesizer** - Two selectable audio backends (`--synth`)
   - `pcm` (default): AppleWin phoneme captures
   - `formant`: SC-01 formant synthesis ported from MAME's Votrax,
     with the SC-02 to SC-01 mapping from the datasheet
     (see `docs/sc02-phoneme-mapping.md` and `datasheet.pdf`)
   - The chip (`qns/ssi263.py`) owns register decode and pushes decoded
     `SSI263State` snapshots to a backend via `set_synth()`

4. **Memory System** - Physical addressing works
   - z-core owns the 512 KiB RAM hot path and Z180 MMU translation
   - qns callbacks own only the optional high flash aperture and external I/O
   - native write-watch events preserve QNS observers without RAM callbacks

## What's Not Working

1. **Live audio output** - see `docs/reports/speech-pipeline-investigation.md`
   - Firmware writes amplitude 0; both backends scale by `amplitude/15`
   - Emulation throughput is ~1000x short of real-time speech
   - (The old "silent startup" theory was wrong - the firmware speaks fine.
     `prompts/silent-startup-investigation.md` records that resolution.)

2. **Fluency depends on the backend, by construction**
   - `pcm`: correct SSI-263 timbre, but 62 isolated recordings, so choppy
   - `formant`: continuous, but SC-01 - the wrong chip's voice
   - `tools/lpc_resynth.py`: correct timbre and continuous, not yet a backend

3. **Missing Peripherals**
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
uv run -m qns.bns --help
uv run -m qns.bns --cycles N --stats rom.bns
uv run -m qns.bns --trace-writes 0xADDR rom.bns
uv run -m qns.bns --trace-io rom.bns
```

When adding tools, consider:
- What question am I trying to answer?
- What visibility do I lack?
- Can z-core expose the missing native state directly?
- Can the CLI filter/format output better?
