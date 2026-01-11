# Z180 CPU & ROM Format Investigation

## The Problem

The QNS emulator segfaults when trying to run ROM code:

```bash
uv run python -m qns.bns roms/NFB99/BSPENG/bspeng.bns
# Segmentation fault
```

## What Needs Investigation

### 1. Z180 CPU Emulator (z180emu)

**Location:** `C:\Users\Q\src\z180emu\`

The CFFI extension wraps this C library. Questions:

- Is z180emu actually correct/complete?
- Are the CFFI bindings in `tools/build_ffi.py` correct?
- Is the memory callback setup correct?
- What's causing the segfault? (Bad memory access? Bad opcode?)

**Key files:**
- `C:\Users\Q\src\z180emu\z180.c` - Main CPU implementation
- `C:\Users\Q\src\z180emu\z180.h` - API
- `C:\Users\Q\code\qns\tools\build_ffi.py` - CFFI wrapper
- `C:\Users\Q\code\qns\qns\cpu.py` - Python interface

### 2. ROM Format

**The ROMs in `roms/NFB99/` might not be raw firmware.**

The directory is named "NFB99" which suggests these are from the National Federation of the Blind 1999 distribution. These might be:

- **Updater programs** - Executables that update the device, containing the real firmware packed inside
- **Compressed/encrypted** - The actual ROM might need extraction
- **Wrong format entirely** - Maybe not Z180 code at all

**Evidence:**
- The handoff mentioned these are "update programs you executed to update your machine"
- A raw ROM would probably just start executing, but we get a segfault

### 3. BNS Source Code

**Location:** `C:\Users\Q\src\bns\`

This contains the original Blazie Engineering source code in assembly. Research needed:

- How was the ROM built from source?
- What's the ROM layout? (header format, entry point, etc.)
- What tools were used to assemble it?
- Can we build a ROM from source to test with?

**Key files to examine:**
- `C:\Users\Q\src\bns\bsp\` - BSPLUS source
- `C:\Users\Q\src\bns\EMULATION_REPORT.md` - Technical notes
- Any Makefiles, build scripts, or documentation

### 4. ROM Header Analysis

The current code expects:
```
Offset 0-1: JR instruction (0x18 0xNN = jump over header)
Offset 2-5: "BNS\0" magic
Offset 6+:  Code
```

But is this correct? Need to:
- Hexdump the ROM files
- Compare with what the source code says
- Check if there's a different header format for updater vs firmware

## Research Tasks

1. **Hexdump ROMs** - Look at actual bytes, find patterns
2. **Read BNS source** - Understand ROM layout from source
3. **Check EMULATION_REPORT.md** - Previous research notes
4. **Debug z180emu** - Add tracing to find where it crashes
5. **Try building from source** - If toolchain exists

## Files to Read First

```
C:\Users\Q\src\bns\EMULATION_REPORT.md     # Previous research
C:\Users\Q\src\bns\bsp\*.asm               # Original source
C:\Users\Q\code\qns\tools\build_ffi.py     # CFFI wrapper
C:\Users\Q\code\qns\qns\cpu.py             # Z180 Python interface
C:\Users\Q\src\z180emu\z180.c              # CPU emulator
```

## Debugging Approach

1. Add verbose logging to `cpu.py` for every instruction
2. Catch the segfault with a debugger (gdb on the Python process)
3. Find what memory address or instruction causes the crash
4. Work backwards to understand why

## Success Criteria

- Understand why the CPU segfaults
- Determine if ROMs need unpacking
- Either fix the CPU or extract the correct ROM format
- Get the emulator to execute at least a few instructions without crashing

## Notes

- The SSI-263 synthesizer is complete and working standalone
- Once the CPU works, audio should "just work" via `--audio` flag
- The synth test `test_synth_speaks_phoneme` proves audio output works
