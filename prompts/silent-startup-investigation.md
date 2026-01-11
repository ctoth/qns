# BNS Silent Startup Investigation

## RESOLVED - 2026-01-10

**Speech is working!** The emulator outputs "Braille 'n Speak ready" phonemes after ~15 million cycles.

### Root Cause
The issue was **not** that speech wasn't working - it was that we weren't running enough cycles. The boot initialization takes ~10-15M cycles before actual speech phonemes are output. During this time:
1. Pause phonemes (0xC0) are sent for chip initialization/warmup
2. Text-to-speech conversion happens in the background
3. Finally, real phonemes are sent to SSI-263

### Evidence
Running with 30M cycles shows the phonemes for "Braille 'n Speak ready":
```
B-R-EH2-E-L-A-N-S-P-E-K-R-A-D-E1-E
   Braille     n     Speak    Ready
```

### All Fixes Applied
1. **Shadow RAM** - Writes go to RAM even at ROM addresses (memory.py)
2. **MMU State Exposure** - CBR/BBR/CBAR visible via CFFI (build_ffi.py, cpu.py)
3. **INT1 Timing Fix** - Removed immediate INT1 trigger that broke boot (ssi263.py)
4. **Phoneme Duration** - Calculated from registers, INT1 fires after duration (ssi263.py)
5. **256KB ROM Loading** - All 4 banks loaded instead of just bank 0 (memory.py, bns.py)
6. **CTL H→L Transition** - Phoneme spoken when chip comes out of standby (ssi263.py)

### Key Insights
- ONFLG=0x00 means "speak" (not silent) - firmware takes speech path
- _SPMAIN (C code) does text-to-phoneme conversion
- Phonemes with mode=0 (bits 7:6=00) have IRQ disabled
- INT1 chain: phoneme output → duration wait → INT1 → SSIINT → next phoneme

### Debug Commands

```bash
# Full boot with speech (needs ~15-30M cycles)
uv run python -m qns.bns --cycles 30000000 roms/extracted/bspeng_full.bin

# See non-pause phonemes
uv run python -m qns.bns --cycles 30000000 roms/extracted/bspeng_full.bin 2>&1 | grep SSI263 | grep -v 0x00

# With audio (if synth working)
uv run python -m qns.bns --audio --cycles 50000000 roms/extracted/bspeng_full.bin
```

### Files Modified
- `qns/memory.py` - 256KB ROM support
- `qns/bns.py` - Removed 64KB truncation, 256KB .bin detection
- `qns/ssi263.py` - CTL H→L transition, duration timing
- `tools/extract_firmware.py` - Full 256KB extraction

### Next Steps
- Enable audio synthesis with `--audio` flag
- Optimize cycle count for reasonable startup time
- Consider adding progress indicator during boot

## The Speech Chain (How It Works)

1. **SETSP** reads message from ROM Bank 3, copies to SPBUF
2. **_SPMAIN** (C function) converts text to phonemes
3. **SPON** powers on SSI-263
4. First phoneme output with CTL=0, INT1 enabled
5. **INT1** fires when phoneme completes (based on duration timing)
6. **SSIINT** (ISR) gets next phoneme from buffer, outputs to SSI-263, re-enables INT1
7. Repeat until buffer empty

## Key Code Locations

```
BS.ASM:2169-2173     - ONFLG check (0=speak, 1/2=silent)
BS.ASM:2231-2233     - SETSP call with TALK09 message
BSSPEECH.ASM:619     - _SPMAIN call (TTS conversion)
BSSPEECH.ASM:731-734 - First phoneme output
BS.ASM:3872-3951     - SSIINT (INT1 ISR)
BS.ASM:4162          - Phoneme output in ISR
BS.ASM:4193-4195     - INT1 re-enable in ISR
```
