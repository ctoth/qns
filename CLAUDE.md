# QNS - Q's Note Speak Emulator

Emulator for the Blazie Engineering BNS (Braille 'N Speak) family of devices.

## Current Status

**Z180 CPU boots successfully.** Firmware runs, memory works, keyboard interrupt functional.

**The firmware speaks, at real settings.** Its own text-to-speech emits correct
phoneme codes ~0.23s into emulated boot ("Braille 'n Speak ready, help, one
page"), and the SSI-263 now receives a real volume, rate, inflection and filter
frequency. **`--audio` speaks live, in real time** - the greeting takes the
3.6 s the hardware takes - and the device answers the keyboard.

```bash
uv run -m qns.bns --audio roms/bspeng.bns          # speaks, then type at it
uv run -m qns.bns --audio lpc roms/bspeng.bns      # pcm (default), lpc, or formant
uv run -m qns.bns --audio --input 6-key roms/bspeng.bns   # fdsjkl = dots 1-6
```

To compare the backends by ear without a working sound device, or without
waiting out a real-time boot each time, render a trace through the very
backend `--audio` uses:

```bash
uv run -m qns.bns --cycles 60000000 --input none \
    --trace-speech greeting.csv roms/bspeng.bns
uv run tools/render_backend.py greeting.csv out/lpc.wav --backend lpc
paplay out/lpc.wav
```

**Do not combine `--audio` with `--speech`/`--speech-stream english`.** Those
set an english callback, and any callback needing instruction boundaries drops
the core to the per-instruction path at ~4-5M cycles/s - below the 12.288M
real time needs - so speech develops audible gaps. Watch the text or listen to
the audio, not both, until observation moves onto z-core's native PC watch.

Both blockers named in earlier notes are resolved, and neither was what it
looked like. The "~1000x too slow" throughput wall was a **deadlock**: the
firmware sleeps in a RAM-resident `SLP; RET` stub between phonemes, a sleeping
core advances no cycles, so the scheduled wake was never reached and the loop
span forever. Measured without contention the core runs 4-32M cycles/s against
the 12.288M real time needs. See `docs/reports/speech-pipeline-investigation.md`.

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
│   │   ├── lpc.py            # LPC analysis + LPCStream continuous voice
│   │   ├── ssi263_lpc.py     # LPC-resynthesis backend
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
│   ├── keysource.py          # Key transitions: win32-input-mode decode,
│   │                         # ReadConsoleInput, Ctrl-C recognition
│   ├── sixkey.py             # Six-key layouts + chord assembly
│   ├── stdio.py              # JSONL structured I/O events
│   ├── cli.py                # argparse CLI (python -m qns.bns)
│   └── bns.py                # Main emulator machine
├── tools/
│   ├── build_ffi.py          # Legacy benchmark build script
│   ├── extract_phonemes.py   # Extract phonemes from AppleWin
│   ├── decode_sc01_rom.py    # Regenerates qns/synth/sc01_rom.py
│   ├── extract_firmware.py   # Package -> .bin extraction (uses qns.loader)
│   ├── probe_terminal_keys.py # What key info a terminal can deliver
│   ├── render_backend.py     # Trace -> WAV through a live --audio backend
│   ├── lpc_track_experiment.py # Unfinished time-varying LPC (not a backend)
│   └── rom_analyzer.py       # ROM bank/structure analysis
├── tests/                    # pytest suite (uv run pytest tests/)
├── roms/NFB99/               # ROM images (update packages)
└── prompts/
    ├── handoff.md                    # General handoff
    ├── z180-investigation.md         # Z180 research (RESOLVED)
    └── silent-startup-investigation.md # Silent startup (RESOLVED)
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

3. **SSI-263 Synthesizer** - Three selectable audio backends (`--audio BACKEND`)
   - `pcm` (default): AppleWin phoneme captures
   - `lpc`: those same captures analysed into an all-pole filter plus
     excitation (`qns/synth/lpc.py`) and resynthesized through one
     continuous, gliding filter - the chip's timbre without the boundaries
   - `formant`: SC-01 formant synthesis ported from MAME's Votrax,
     with the SC-02 to SC-01 mapping from the datasheet
     (see `docs/sc02-phoneme-mapping.md` and `datasheet.pdf`)
   - The chip (`qns/ssi263.py`) owns register decode and pushes decoded
     `SSI263State` snapshots to a backend via `set_synth()`
   - Every backend renders each phoneme for exactly
     `qns.ssi263.playback_length_samples()`, the same duration model the
     chip schedules its completion interrupt from, so audio cannot drift
     against the emulated clock

4. **Six-key Braille entry** (`--input 6-key`, `--input 6-key-dvorak`)
   - `fdsjkl` are dots 1-6, `ueohtn` on Dvorak; space and Alt both give
     the space bit, so `space`+`f` is the dot-1 chord
   - Backspace, Escape, Enter, the arrows, PgUp/PgDn and
     Ctrl+Home/End/Left/Right stand in for their chords
   - F4 exits, F5 restarts with the same command line, Ctrl-C exits
   - A chord must be assembled host-side: `BrailleKeyboard.press` latches
     a whole dot bitmask and the firmware ISR reads that port once, so the
     firmware never sees an individual key transition.  The assembled byte
     goes onto `ChordInputDriver`'s queue, which already took chord ints
   - That needs key *releases*, which a plain pty does not carry.  Windows
     Terminal's win32-input-mode does - after `CSI ? 9001 h` it forwards
     the whole Win32 `KEY_EVENT_RECORD` - and `ReadConsoleInput` gives the
     same fields natively, so one assembler serves WSL and Windows.  Run
     `uv run tools/probe_terminal_keys.py` to see what a terminal supports;
     ones that report no releases fall back to ending a chord on a gap in
     arrival times, and redirected input ends it at a line break
   - On those terminals the named keys arrive as escape sequences, which
     `VTKeyDecoder` reads before any character reaches the chord tables -
     `ESC [ D` ends in the dot-3 key, so an undecoded Left would spell a
     cell.  Escape shares its first byte with every sequence, so it is
     settled by the same quiet interval that ends a chord
   - The six-key devices are in `CHORD_STDIN_DEVICES` so
     `_requires_instruction_steps` still pays for boundary observation only
     while a chord is in flight.  Pinning the core to the per-instruction
     path costs the ~6x that real-time speech cannot afford

5. **Memory System** - Physical addressing works
   - z-core owns the 512 KiB RAM hot path and Z180 MMU translation
   - qns callbacks own only the optional high flash aperture and external I/O
   - native write-watch events preserve QNS observers without RAM callbacks

## What's Not Working

1. **Command responses are gappier than the greeting**
   - The greeting holds real time because the CPU sleeps between phonemes;
     while the firmware is working we manage ~6.9M cycles/s against the
     12.288M real time needs, so the audio queue drains between phonemes
   - Delivering a chord still needs the per-instruction path.  Moving
     `keyboard_wait_pc` observation onto z-core's native PC watch should
     reach the fast path's ~32M cycles/s and close the gaps

2. **Fluency depends on the backend, by construction**
   - `pcm`: correct SSI-263 timbre, but 62 isolated recordings, so choppy
   - `formant`: continuous, but SC-01 - the wrong chip's voice
   - `lpc`: continuous, and now a live backend, but it loses stop
     consonants - a 41 ms burst becomes stationary noise at the same
     average level, so /p/ and /k/ measure 5-10x below `pcm`'s peak.
     Unlike the offline `tools/lpc_resynth.py` it has no lookahead, so it
     glides into each phoneme's head rather than straddling the boundary
   - **By ear, `pcm` is still the most accurate.**  The underlying
     choppiness is neither backend's fault: the captures were recorded as
     isolated utterances and 82% of them decay to 34% of their middle
     level in their final 10%, which modulates amplitude at the phoneme
     rate.  Filter gliding does not touch it and makes it worse
   - `tools/lpc_track_experiment.py` is the unfinished idea that matches
     `pcm`'s stop bursts exactly.  See
     `docs/reports/lpc-backend-investigation.md` for the measurements, the
     four theories that were refuted, and what to do next

3. **A chord delivered during the greeting is silently lost**
   - `ChordInputDriver`'s ready gate opens around 37M cycles, part way
     through the boot greeting.  A chord delivered while the firmware is
     still speaking is accepted into its input buffer - `input_buffer`
     reads the chord back - and then cleared without
     `keyboard_queue_count` ever going non-zero.  The driver waits in its
     `queued` phase forever and the command is gone
   - This predates six-key input and affects every mode: `printf 'O' |
     ... --input keyboard` loses its chord the same way.  Interactive use
     is unaffected because a person waits for the greeting; scripted use
     is not, which makes the input layer look broken when it is not
   - Deliver after ~80M cycles.  `investigations/chord_delivery_trace.py`
     prints every driver phase change with the epochs and buffer bytes it
     consults, which is how this was located

4. **Missing Peripherals**
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
