# SSI-263 phoneme review handoff

## Scope

Read-only review (2026-07-18, second pass): what phoneme assets/parameters are missing, which approach is valid, what work makes SSI-263 speech authentic. This file is the review's own notes artifact — no project source has been edited.

## Verified this pass (with citations)

1. Dirty diff replaces the AppleWin PCM playback path with SC-01 formant synthesis: `qns/synth/ssi263_synth.py` now calls `FormantSynth.synthesize_phoneme(sc01_phoneme, sc01_inflection)` after translating via `SC02_TO_SC01`; 12-bit inflection is collapsed to 2 bits; rate/filter-freq DSP dropped; amplitude applied as linear scale.
2. `qns/synth/sc01_rom.py` params are decoded from `sc01a.bin` (512 bytes, sha1 1d6da90b1807a01b5e186ef08476119a862b5e6d) by `tools/decode_sc01_rom.py` using MAME votrax.cpp bitswap logic. This is SC-01 data, not SSI-263 data.
3. `SC02_TO_SC01` (qns/synth/sc02_to_sc01.py) is hand-authored nearest-name matching; collapses R/R1/R2→R, L/L1/LF/LB→L, maps HVC/HFC/HN→PA0 silence. Documented in docs/sc02-phoneme-mapping.md.
4. Tests (tests/test_synth.py) still assert the OLD PCM path: PHONEME_DATA len 156566, 62 phonemes, dsp.apply_filter/time_stretch/pitch_shift. The dirty diff removed those from the runtime path, so tests test dead code; get_phoneme_audio tests exercise new formant path only incidentally.
5. AppleWin (C:\Users\Q\src\AppleWin\source\SSI263.cpp): 62 PCM samples @22050 Hz (SSI263Phonemes.h g_nPhonemeInfo[62], offsets match qns/synth/phonemes.py exactly, e.g. first entry 0xA60 bytes = 1328 int16). Phoneme 1 missing → mapped to 2 (line 360). Amplitude = linear ARTAMP scale; filterFreq only used as ==0xFF silence gate (line 621-624); DUR implemented as sample-skip/average (lines 629-666). No inflection, no articulation, no filter-frequency synthesis. So AppleWin PCM = fixed-inflection captures with amplitude+duration hacks.
6. Datasheet page_01.png (read visually): SC-02 has five cascaded programmable lowpass filter sections, glottal or pseudo-random excitation, linear transition between phoneme targets governed by articulation TR2-TR0, rate R3-R0 scales all transitions, inflection I11-I0 = 7 octaves pitch (Inflection Freq = XCK/(8×(4096-I))), Filter Freq = XCK/(2×(256-FF)) sets switched-cap filter clock (vocal tract length). None of this survives either the PCM path or the SC-01-translation path.
7. Die images (Temp\qns-ssi263-review): full die 7000×5803 (JPEG + map PNG), suspected-rom.png crop is 1800×1600 and shows a large regular array. Its identity and bit-level readability are not established from this single intact top-layer optical image; programming may depend on layers obscured by metal.

## Assessment so far (inference, to be finalized)

- SC-01 formant path CANNOT be SSI-263-authentic: different phoneme inventory (64 vs 64 but different sounds), different parameter ROM, no articulation/rate/12-bit-inflection/filter-freq model. It is a "different chip that talks."
- AppleWin PCM samples are genuine-sounding SSI-263 captures at ONE register setting; usable as reference/fallback and for A/B validation, not for authentic register-driven synthesis.
- Authentic path requires: SSI-263 parameter ROM (extract from die or capture-and-fit) + a transition/filter model per datasheet.

## Completed second pass (2026-07-18)

- Datasheet page_02.png phoneme chart verified visually: matches new PHONEMES table in qns/ssi263.py and docs/sc02-phoneme-mapping.md exactly (00 PA … 3F LB/LUBE). Also verified: duration formulas (Frame = 4096×(16−R)/XCK, Phoneme = Frame×(4−D)), amplitude A3-A0 with per-phoneme preset amplitudes, CTL power-down, XCK 800–1000 kHz nominal.
- Die photo: full mosaic 7000×5803 (Visual6502, © 2011, 1mm scale bar). `suspected-rom.png` (1800×1600 crop) shows a regular grid, but the image alone does not establish that it is ROM, that visible features encode bits, or that raw extraction is feasible. Layer identity, decoder/addressing order, and bit-to-parameter semantics remain unknown.
- AppleWin provenance: help/acknowledgements.html credits "Greg Hedger: SSI263 phoneme samples" (verified by grep). Local git history truncated at repo-restructure commit d591dd00 — capture metadata/register settings NOT recoverable locally.
- qns/ssi263.py: INT1 scheduling uses datasheet duration formula assuming XCK≈1.023 MHz; register plumbing (5 regs, modes) present.

## Verdict (final)

The SC-01 translation/formant path cannot be SSI-263-authentic (wrong chip's ROM, collapsed phoneme inventory, 12-bit→2-bit inflection, no articulation/rate/filter-freq model). AppleWin PCM is credited as SSI-263 audio at one fixed, undocumented register setting — valid reference/playback material, invalid as register-driven synthesis. The central missing asset for exact synthesis is the SSI-263 internal parameter ROM or an equivalent black-box characterization. The available die image may help locate candidate arrays but does not yet prove readable bits. Tests are stale because they assert the removed PCM/DSP path. Independent review captured; final user report still pending.

## Live firmware trace and assembly follow-up

- A 5,000,000-cycle timing baseline completed in 1.09 seconds. The exact existing CLI command was then run for 40,000,000 cycles with `--trace-io`; it completed in 8.0 seconds at PC `0x3A3C` and produced non-pause speech phonemes.
- During the observed speech sequences, voice-control writes were repeatedly fixed at `C1=00`, `C2=08`, `C3=50`, `C4=E0`. The `C0` duration/phoneme byte varied (examples include `24`, `1D`, `08`, `01`, `A5`, `C1`, `6C`, `59`).
- That trace is **not a valid speech capture profile**. Original `BSSPEECH.ASM` explains the ordering: `ISINIT` sets `VOLUME=6`; `ISSET` writes `VOLUME | 0x50` (normally `0x56`); but the TNS first-power-on path then deliberately overwrites C3 with `0x50` before a delay. The observed fixed controls and phonemes are therefore a muted startup/stabilization sequence, not demonstrated user speech.
- `C3=0x50` decodes per the datasheet as CTL=0, articulation=5, amplitude=0. QNS currently forces amplitude 0 to 15 in `SSI263Synth._play_current_phoneme`, causing that deliberately muted startup sequence to become audible. That workaround is semantically wrong and explains why the trace looked like speech.
- The current CLI only boots/runs the firmware; it exposes no stdin, keyboard, or scripted-input option. `BrailleKeyboard.press()` exists internally, but the CLI never invokes it. A real speaking-state trace requires an explicit driver/harness or real-hardware capture; creating one was outside this read-only review.
- Original BNS assembly contains explicit high/normal/low inflection marker bytes (`0x3E`, `0x3D`, `0x3C`) inserted into phoneme buffers, writes normal amplitude `0x56`, varies inflection for intonation, and has chirp paths with distinct filter/rate/inflection/amplitude settings. Authentic BNS output therefore cannot be reduced to one fixed-control sample bank.

## Targeted test result

- `uv run pytest tests/test_synth.py -m "not manual"`: 17 selected, 16 passed, 1 failed, 3 deselected. Failure: `test_time_stretch_duration_modes` expected duration 3 to shorten a four-sample input but received four samples. More importantly, most selected tests still exercise the legacy PCM/DSP modules rather than the dirty runtime formant path, so the 16 passes are not an authority for the replacement design.

## User correction: BNS is not a hardware oracle

- There is no physical BNS available for capture.
- Even if a physical BNS were available, its user interface cannot command arbitrary individual SSI-263 phonemes, so it cannot produce the required 64-phoneme characterization corpus.
- Driving the emulated BNS keyboard can help test firmware integration, but emulator register traces are not ground truth for phoneme audio and must not be substituted for a hardware oracle.
- Direct arbitrary-phoneme capture would require access to a bare SSI-263/SC-02 in a purpose-built electrical fixture that drives its registers directly. If no such chip access exists, the remaining exact-recovery route is internal-ROM/die reverse engineering; AppleWin's fixed, undocumented sample bank can only support an explicitly approximate backend.
