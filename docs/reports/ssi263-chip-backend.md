# SSI-263 register-level chip backend

`--audio chip` drives Tamas Geczy's register-level SSI-263 model
([tgeczy/ssi263-speech](https://github.com/tgeczy/ssi263-speech), MIT, the
`ssi263speech` 0.9.1 wheel) with the firmware's own register writes, each at
its exact CPU cycle.  This report records how its timing was checked, how
QNS's speech defaults were matched to a real unit, and what is still open.

## Using it

```bash
uv run -m qns.bns --audio chip roms/bspeng.bns                     # live
uv run -m qns.bns --cycles 26000000 --input none \
    --audio-wav out.wav roms/bspeng.bns                            # offline, full speed
```

A BNS 2000 stops at first-boot prompts; answer them once and keep the
result with `--state FILE` (loaded at start, saved on exit).

## Design

- `qns.ssi263.SSI263` still owns register decode, A/R and INT1.  A backend
  with `write_register(register, value, cycle)` and `advance_to(cycle)` (the
  `RegisterBackend` protocol) also receives every raw bus write.  Deferred
  native I/O writes reach it through `confirm_write_cycle`, at z-core's exact
  event cycle.
- `qns/synth/ssi263_chip.py` renders the engine up to each write's cycle, then
  writes.  Emulated time is a whole-sample count from the first write, so
  rounding never drifts: 22050 samples per emulated second, exactly.
- The wheel's parameter struct (194 doubles) is checked for size and for
  known defaults before anything is changed, so a different engine version
  fails loudly instead of being misconfigured.

## Timing audit (user asked: "don't trust that they've gotten the timings exactly right")

The SSI-263A data sheet (scanned; render with `gswin64c`) gives:

- frame = 4096 (16 - R) / XCK; phoneme = frame (4 - D); mode 1 is one frame
  per phoneme; mode 0 disables A/R
- F0 = XCK / (8 (4096 - I)); filter clock = XCK / (2 (256 - FF))
- XCK = 1 MHz: measured on Braille Lite pitch within ±3 cents, and now
  consistent with a real BNS 2000 (below)

Findings:

1. **The engine's A/R matches the data sheet**, within a constant 30-44 us
   output latency, across modes, rates and durations.
   `tests/test_ssi263_chip.py` holds both QNS and the engine to the formula
   within 100 us.
2. **One deviation: `release_lookahead`** (on by default and tagged GUESS
   in its own notes) raises A/R 1.75 frames early before T, P or K, and holds
   the host's writes.  That is not data-sheet behaviour, and it would deliver
   INT1 to the firmware tens of ms early.  QNS switches it off.  By ear it was
   also the stranger-sounding option.
3. **QNS's own A/R was the bigger error.**  It used AppleWin capture lengths,
   which ran vowels about 8% short and stops about 3x short.  It now uses the
   data-sheet duration for every phoneme code.  The firmware has no speech
   timing of its own (SAYIT/SSIWT just wait on A/R), so the chip's timing is
   the device's timing.

## Matching a real BNS 2000

Reference: `Braille N Speak 2000 Full Help File.mp3` (not committed), 46
minutes of a real unit reading its help file.  It is an open-air microphone
recording of the built-in speaker, so it is trusted for pitch and timing only,
never for spectra or levels.

| Setting     | Old seed | Now (factory) | Evidence |
|-------------|----------|---------------|----------|
| Inflection  | 128      | 69            | greeting F0 81.4 Hz in the recording = inflection 69 at XCK 1 MHz; 128 gave 122 Hz |
| Rate        | 9        | 11            | envelope correlation with the recording: rate 11 0.80; rates 9, 10, 12 and 13 all at or below 0.20 |
| Filter      | 17       | 7             | 7 gives the data sheet's typical ~20 kHz filter clock; 17 gave 33 kHz; preferred by ear |
| Volume      | 8        | 6             | firmware reset value; a speaker recording cannot measure it |

These are the firmware's own warm-reset values.  QNS now seeds the retained
speech RAM with them (`qns.loader.RETAINED_SPEECH_DEFAULTS`).

## Live-audio bug found on the way: INT1 held for a whole budget

Live `--audio chip` was unintelligible while offline WAVs were clear.  The
cause was in QNS, not the chip.  Device IRQ lines reach z-core only between
core calls, so when the speech ISR acknowledged A/R by loading a phoneme,
INT1 stayed asserted until the budget ended.  The ISR re-entered and loaded
the next phonemes back to back, each cutting off the last.  Real-time
budgets are 6144 cycles (offline ones are 1000), enough for four or five
loads, and 23 of the greeting's 28 phonemes were cut short.

The fix in `BNS._execute_budget` steps per instruction while INT1 is up, a
few hundred ISR cycles per phoneme, and ends each budget at the active
phoneme's end.  Real-time and offline runs now load phonemes at identical
cycles.  `test_speech_isr_loads_one_phoneme_per_ar_request` covers both
budget sizes.  This affected every backend in real time, not just the chip.

## Open: "ehwon" for "one"

After a pause, "one" sounds like "ehwon".  In the engine, the formants keep
gliding toward PA's targets (F2 about 1600 Hz) during the pause.  When W
loads, its amplitude rises about 6x faster than the formants glide, so the
first ~50 ms sound like "eh".  Two variants, rendered through the engine's
reference Python chip, both sounded better by ear and alike:

- B: a phoneme loaded onto silence lands its formants at once
- C: PA leaves the formants where they were

The shipped C core applies a rule like B only in mode 1 at rate 15.  Whether
the real chip behaves like A (as shipped), B or C is unmeasured.  The BNS 2000
greeting cannot settle it, because the real unit says "nine" there.  Next
step: find a W, R, L or Y word straight after a pause in the recording and
compare its onset, then either report upstream or carry a patched build.
