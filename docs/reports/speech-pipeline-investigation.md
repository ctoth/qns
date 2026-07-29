# Speech pipeline investigation

Why the emulator produced no intelligible speech, what was actually broken,
and what remains. Every claim below was measured; where something is
unverified it says so.

## Summary

The firmware's own text-to-speech was never broken. It emits correct phoneme
codes within ~0.23 s of emulated boot. Everything downstream of it was wrong,
in four independent places:

| Defect | Effect | Status |
|---|---|---|
| AppleWin phoneme index table halved | every phoneme read the wrong audio | fixed |
| SC-01 ROM parameters bit-reversed | formant synthesizer had scrambled targets | fixed |
| SSI-263 pacing model wrong in 4 ways | phonemes written 82 µs apart | fixed |
| Formant model run at the output rate | every formant detuned to ~55% | fixed |
| Speech settings never initialised | amplitude 0, and wrong rate/pitch | fixed |
| Sleeping CPU deadlocked the run loop | looked like ~1000x too slow | fixed |
| Speech-power timeout threshold unset | chip silenced mid-word, every 50 ms | fixed |

## What the firmware actually does

`--speech english` snoops the firmware's pre-translation buffer (SPBUF,
capture site discovered from the image's MFULL3 signature). `--trace-speech`
records the resulting phoneme writes. On `roms/bspeng.bns`:

```
B R A E L   EH N   S P E K   R EH D E1 E   HF EH L P   W UH1 N   P A E1 D J
Braille     'n     Speak     ready         help        one       page
```

Text-to-phoneme conversion happens in ROM, on the emulated Z180. QNS does not
and should not implement it. The SSI-263 emulation only has to receive codes.

## Register ground truth

From `--trace-io`, the complete set of writes the firmware makes to the chip
(base port 0xC0) during boot:

```
port=C0  0xC0 x49  (mode 3, phoneme 0 = pause) + phoneme codes with mode bits 00
port=C1  0x00 x45
port=C2  0x08 x44   -> rate 0, I11 set -> inflection 2048 (neutral)
port=C3  0x50 x44,  0x70 x3,  0x80 x3
port=C4  0xE0 x44   -> filter 224
```

The firmware never *reads* the chip. Zero reads in the entire trace, so it is
paced by INT1, not by polling.

Register variation across 116 events: `rate` is 0 throughout, `inflection` is
2048 (three exceptions at 0), `filter_freq` is 224 (three at 255). There is no
varispeed control in use here, which is why a fixed-rate resampler suffices
(contrast doubletalk-pc, where the `nF` command retunes the DAC clock over
9883..11060 Hz and a real rate conversion is mandatory).

## Fixed: AppleWin phoneme index table (commit 3108c4e)

`tools/extract_phonemes.py` halved every offset and length, commented
"Convert byte offsets to sample indices (divide by 2)". They were already
sample units: AppleWin indexes `g_nPhonemeData` (a `short[]`) with `nOffset`
directly, and the 62 lengths sum to exactly 156566 - the array's declared
element count.

Consequence: every phoneme was fetched from half its true offset with half
its true length, landing part-way through some earlier phoneme. Because the
bank is roughly ordered by the phoneme table, halved offsets land in the vowel
region, so speech came out as an "a o e u" drone. The *sample data* was always
complete; only the index table was wrong, describing the first 78283 of 156566
samples.

Fixing this is what first produced recognizable words.

## Fixed: SC-01 ROM bit order (commit 3b52947)

`tools/decode_sc01_rom.py`'s `bitswap()` read fields LSB-first. MAME's
`util::bitswap()`, which `votrax.cpp` applies to this exact ROM, reads
MSB-first. Every 4-bit field (f1, f2, f3, f2q, va, fa, fc, vd, cld) and the
7-bit duration in `qns/synth/sc01_rom.py` was therefore bit-reversed.

The phonetics decide it:

| phoneme | shipped F2 | corrected F2 |
|---|---|---|
| AH (low back, "mop") | 12 | 3 |
| A (front, "day") | 13 | 11 |

A low back vowel must have low F2 and a front vowel high F2; the shipped table
gave them nearly identical values, which is impossible. Corrected, `L` becomes
F2=2/F3=15 (textbook lateral) and `S` becomes va=0/fa=15 (voiceless
fricative).

Regenerating normally needs `sc01a.bin`, which is proprietary and not in the
repo. The decode is invertible, so `tools/encode_sc01_rom.py` rebuilds the
512-byte image from the decoded table. **Verified round-trip**: encode with
the old convention, decode with the corrected one, and every field of all 64
phonemes equals the bit-reverse of the shipped value. Bits 44-55 and 62-63 are
read by nothing and are emitted as zero, so the image is functionally
equivalent rather than byte-identical.

That reconstructed image is also what lets a native MAME-derived core run here
as a conformance oracle without the real dump.

## Fixed: SSI-263 pacing (commit 46924b5)

The firmware was writing phonemes ~82 µs apart - the whole greeting in about
1.5 ms of emulated time. Four separate defects, all checked against AppleWin's
`SSI263.cpp`:

1. **`irq_enabled` recomputed per write.** The top two DURPHON bits are a
   *mode selector*, not a duration: `0xC0/0x80/0x40` select modes, `0x00` means
   "disables A/!R output only; does not change previous A/!R response". Mode
   and interrupt-enable latch at CTL H->L (`SetDeviceModeAndInts()`). The
   firmware selects mode 3, drops CTL, then writes phonemes with mode bits
   `00` - so recomputing from each write deleted the handshake pacing the
   whole utterance.
2. **Status polarity inverted.** `read()` returned `0x80` while *speaking*. On
   the chip, bit 7 (A/!R) goes high when a phoneme *completes*, and is set even
   when interrupts are disabled; writes to registers 0-2 or standby clear it.
3. **Duration came from a debug logger.** `_calc_phoneme_duration_cycles()`
   used `(((16-rate)*4096)/1023)*(4-dur)`, which lives inside `SSI_Output()`
   under `#if LOG_SSI263B` - an estimate for a log line, not playback timing.
   It produced 256 ms phonemes, ~4x too long. A phoneme lasts as long as its
   waveform takes to play out.
4. **Playback speed ignored the duration mode.** It selects decimation (1,
   4/3, 2, 4 - `SSI263.cpp:617`), and frame timing mode forces it to 3
   regardless of the bits written (`SSI263.cpp:613`).

Measured on the boot phrase: B->R went from 1,006 cycles to 564,809 (46 ms),
R->A to 1,476,884 (120 ms). Note the firmware's timing *varies*, so it is
worth capturing a full utterance at the corrected pacing (a 60M-cycle run;
see throughput below).

## Fixed: formant clock (commit 4fbab79)

`_sclock`/`_cclock` were derived from the output sample rate (22050/11025)
instead of the hardware's 40 kHz/20 kHz. `_cclock` is a term in k0/k1/k2 of
every filter builder - F1, F2, F3, F4, noise shaper, final lowpass - so every
formant sat at ~55% of its correct frequency. Spectral centroid moved
1049 Hz -> 2028 Hz.

`_chip_update()` also ran every generated sample; the state machine ticks at
`_cclock`, half the sample clock (MAME: `if (m_sample_count & 1) chip_update()`).
Per-phoneme normalization was replaced with a clamp, as MAME does - scaling
every phoneme to the same peak destroyed relative loudness of vowels against
fricatives.

## Fixed: the speech settings were never initialised

The firmware wrote `0x50` to port C3 - CTL=0, articulation 5, **amplitude 0** -
so both backends multiplied to silence and every listening test needed
`--force-amplitude 15`.

None of the three hypotheses this section used to list was right. The BNS
source settles it. `BSPMON.ASM::ISSET`:

```asm
ISSET:  LD A,(VOLUME)      ; VOLUME: DS 1 ;SPEECH VOLUME (0-15)
        OR 050H            ; CTL=0, articulation 5
        OUT (SSI263+3),A
```

The decode was always correct - amplitude is the low nibble, exactly AppleWin's
masks, and there is no BNS-specific `D6:D3` split. The firmware wrote `0x50`
because it read `VOLUME` as 0.

**It was never only amplitude.** ISSET applies four settings, and all four read
zero, so every render before this was also at the wrong rate and pitch:

| register | was | decoded | now |
|---|---|---|---|
| C3 `VOLUME OR 50h` | `0x50` | volume 0 | `0x58` |
| C2 `RATE<<4 OR 08h` | `0x08` | rate 0 | `0x98` |
| C1 `INFL` | `0x00` | inflection 0 | `0x80` |
| C4 `PITCH OR E0h` | `0xE0` | filter freq 0 | `0xF1` |

These live in the monitor's uninitialised `DS` scratch area. No shipped code
path gives them a value: `BSSPEECH.ASM::ISINIT` would, but it is dead code -
searching the linked image for `CALL` to its address finds nothing. A field
unit carries them in battery-backed RAM, set once through
`BSSERIAL.ASM::EHVOL`/`EHPITC`/`EHTONE`. Starting RAM at zero therefore made
the firmware *correctly* speak silence.

`qns.loader.find_speech_parameters` recovers the cells by signature, anchored
on ISSET's `OR 50h`, and `BNS._seed_retained_speech_settings` seeds them at
load - not in `reset`, because surviving a reset is exactly the property that
makes the real hardware work.

Two things the addresses have to get right, both of which failed first:

1. **They are physical.** They carry the same `CBR=34` common-area offset
   `find_input_boundary` applies. Logical `0xD5FD` is physical `0x415FD`;
   writing the logical address puts the byte in the ROM image copy, where
   nothing reads it, and the seed reports success.
2. **Each setting is held twice.** ISSET reads a working cell (`RATE`, `INFL`)
   that the firmware rebuilds per utterance from a retained shadow (`NRATE`,
   `NINFL`), applying for inflection the markers `BRL.ASM::INTON` inserts.
   Seed only the working cell and it is overwritten partway through boot -
   rate collapsed back to 0 at cycle 3,235,311, just past where the first
   check looked. Seed only the shadow and the setting is wrong until the
   first rebuild. Both are seeded.

### Choosing values

`BSAPI.H` and `BNSAPI.H` document the ranges and agree exactly:

```
Volume 0..15    Pitch 1..32    Rate 1..16    Frequency 0..255
```

Defaults are the midpoint of each: **volume 8, rate 9, pitch 17, frequency
128**, overridable with `--volume/--rate/--pitch/--frequency`. This is a
deliberate neutral choice, not a recovered default - nothing in the firmware
records what a unit shipped with. The only nearby hints agree loosely: dead
`ISINIT` used volume 6, and the ROM's own zero-argument fallback for rate is 10.

### The names cross three ways

Worth stating once, because every layer disagrees:

| firmware variable | chip register | API name |
|---|---|---|
| `VOLUME` | C3 amplitude | Volume |
| `RATE` | C2 rate | Rate |
| `INFL` | C1 inflection | **Frequency** |
| `PITCH` | C4 filter frequency | **Pitch** |

`SpeechParameters` names its fields for the chip register - the one
unambiguous sense - while the CLI flags follow the API, so `--pitch` sets
filter frequency and `--frequency` sets inflection.

## Fixed: the throughput wall was a deadlock

There was never a thousandfold gap. The "~10-15k cycles/s" figure recorded
here was two artefacts: several emulator runs competing for one core, and -
mostly - a run loop that made **no progress at all**.

The firmware ends every phoneme by calling a RAM-resident `SLP; RET` stub at
`0xD654` and sleeping until the SSI-263 completes it. A sleeping Z180 advances
no cycles, so `cpu.run()` returned 0, `cycles_run` stopped increasing, and
`check_pending_irq` was called forever with a frozen cycle count. The
scheduled completion could never be reached and the CPU never woke. A 40M-cycle
capture did not run slowly; it died at ~6.2M cycles and span for eight minutes.

`BNS.run` now advances emulated time to the next scheduled device event when
the core reports no progress, so sleeping costs one iteration rather than a
million. Where nothing is scheduled, time still passes: the Z180's own timers
wake the background task, and asleep is not dead.

Measured without contention:

| path | cycles/s | vs real time (12.288M) |
|---|---|---|
| per-instruction stepping | ~4-5.7M | too slow |
| `cpu.run` over a whole budget | ~32M | 2.6x headroom |

`--audio` holds emulated time to wall-clock time and speaks the greeting in
the 3.6 s the hardware takes.

## Open: command responses lag real time

The greeting keeps up because the CPU sleeps between phonemes and pacing
dominates. While the firmware is actually working we manage ~6.9M cycles/s,
so the audio queue drains between phonemes and a command response is gappier
than the greeting.

The cause is the per-instruction path, which delivering a chord still needs:
`_observe_input_boundary` watches for the PC reaching `keyboard_wait_pc`, and
Python sees every instruction to do it. Stepping is now paid only while a
keystroke is in flight rather than whenever a keyboard is attached, which took
this from 4.4M to 6.9M cycles/s - audible, but not enough.

The remaining move is to put that observation on z-core's native PC watch
(`WatchKind`, `pc_watch_hits()`, already used by `--watch-pc`), which would let
chord delivery run on the fast path. One correctness question to settle first:
the observer currently reads `keyboard_queue_count` at the instant of the hit,
and a native watch reports a count rather than that instantaneous read.

## The three synthesis approaches

The BNS uses an **SSI-263 (SC-02)**. No true SC-02 synthesis model exists
publicly - MAME's `ssi263hle.cpp` is high-level emulation that remaps SC-02
phonemes onto the SC-01 phoneme set, which is exactly what
`qns/synth/sc02_to_sc01.py` does. So the options are:

| approach | voice | fluency |
|---|---|---|
| PCM captures (`--synth pcm`) | correct chip | choppy - 62 isolated recordings |
| SC-01 formant (`--synth formant`) | wrong chip | fluent - continuous state |
| LPC resynthesis (`tools/lpc_resynth.py`) | derived from correct chip | continuous |

The PCM backend **cannot** produce fluent speech by construction: it re-triggers
recordings that each have their own attack and decay. Measured on the `A`
capture, tiling it gives a `71 -> 100 -> 97 -> 94 -> 83`% amplitude envelope
(~30% pulsing at 8.3 Hz) plus a phase discontinuity at each join, because the
capture is 10.88 pitch periods long. Crossfading reduces the dip but swallows
stop consonants; decimating shortens phonemes but raises pitch (it is
varispeed).

LPC resynthesis is the way out: analyse each capture into an all-pole filter
plus its own excitation residual, interpolate *reflection* coefficients across
boundaries (stable under interpolation, unlike direct-form coefficients), and
run one continuous excitation through the gliding filter.

Using the **captured residual** rather than a synthetic glottal pulse is what
matches timbre. Measured spectral centroid, capture playback as reference:

| | centroid |
|---|---|
| capture playback (reference) | 2325 Hz |
| synthetic smooth glottal pulse | 817 Hz (muffled) |
| captured residual | 1947 Hz |

A bare unit impulse is the opposite failure - energy flat to Nyquist, audible
as a click per pitch period.

## Listening results

Judged by ear by the project owner, same phoneme stream throughout:

- PCM with corrected index table: intelligible, correct pitch and speed,
  chopped between phonemes.
- SC-01 formant, native MAME core: fluent, recognizably Votrax - the wrong
  chip's voice. "page" renders as "pe age" because `E1` is a transitional
  glide given a full syllable's length from the SC-01 ROM.
- LPC with captured residual: most fluent so far, timbre close to the PCM
  reference.

All of the above were rendered with `--force-amplitude 15` and, unknowingly,
at rate 0 and filter frequency 0. They should be re-judged now that the
firmware supplies real settings - traces no longer need any forcing.

## Tools added

```bash
# Stream every phoneme event with cycle count and full register state
uv run -m qns.bns --cycles N --trace-speech speech.csv rom.bns

# Render a trace offline - no host audio device, no real-time run
uv run tools/render_speech.py speech.csv out.wav --synth pcm|formant \
    --timing chip|trace|natural|sustain [--phoneme-ms MS] [--overlap-ms MS] \
    [--force-amplitude N] [--force-duration-mode N] [--skip-pauses]

# LPC resynthesis with coarticulation
uv run tools/lpc_resynth.py speech.csv out.wav [--phoneme-ms MS] \
    [--transition-ms MS] [--pitch-scale S]

# Rebuild a functional SC-01 ROM image from the decoded table
uv run tools/encode_sc01_rom.py sc01a.bin
```

Audio plays straight out of WSL with `paplay out.wav` (WSLg PulseAudio).

## Using the native core as an oracle

rusty_tts (`/mnt/c/Users/David/src/rusty_tts`) vendors MAME's Votrax SC-01 as
a standalone CLI. It builds here directly:

```bash
g++ -Wall -O2 -std=c++17 -o retrochip native/retrochip/main.cpp \
    native/retrochip/{tms5220,sp0256,votrax,tms5110,s14001a}.cpp
uv run tools/encode_sc01_rom.py sc01a.bin
./retrochip --chip votrax --rom sc01a.bin < codes.bin > out.raw   # s16le, 40kHz
```

Feed it SC-01 codes (SC-02 codes mapped through `SC02_TO_SC01`) to compare
against `qns/synth/formant.py` sample-by-sample. Known remaining divergences
of our port from MAME, not yet fixed:

- filter commit condition: MAME uses `(pitch & 0xf9) == 0x08` (pitch in
  {0x08, 0x0A, 0x0C, 0x0E}); ours uses `8 <= pitch < 12`.
- noise LFSR input: ours adds a `filt_fa > 0` gate MAME does not have.

`qns/synth/sc02_to_sc01.py` is hand-built from the datasheet and has never
been validated against anything.

## Test baseline

**20 tests fail on clean master** and are unrelated to this work - verified by
running the same set in a detached worktree at `HEAD`:

- `tests/test_bns_external.py` (13) - needs the external toolchain/downloads
- `tests/test_cpu.py` (7) - legacy CFFI extension is not built on Linux

Everything else passes: 274 passed, 9 skipped, with all 33 SSI-263 and synth
tests green.

## External references used

- AppleWin: `git clone --depth 1 https://github.com/AppleWin/AppleWin` -
  `source/SSI263.cpp` is the authority for register semantics and phoneme
  playback.
- rusty_tts `native/retrochip/votrax.{h,cpp}` - MAME SC-01 core, BSD-3-Clause.
- doubletalk-pc `notes/audio-resampling.md` - the reference write-up on
  reconstructing a chip's output onto a fixed sample grid, and on measuring
  whether a source rate is actually constant before assuming it.

## Suggested next steps

1. Put `keyboard_wait_pc` observation on z-core's native PC watch, so chord
   delivery stops forcing the per-instruction path and command responses hold
   real time like the greeting does.
2. Make `SpeechBackend` streaming rather than one buffer per phoneme. The
   present interface asks for "audio for this phoneme" and gets a finished
   buffer; that boundary is where continuity dies, and LPC needs a continuous
   pull.
3. Validate `sc02_to_sc01.py` and the remaining formant divergences against
   the native core.
