# Investigation: PCM Inflection

## Facts (verified)

- `SSI263` decodes the complete 12-bit inflection value into
  `SSI263State.inflection`.
- Before this slice, `SSI263PCMSynth.play()` dropped that value and forwarded
  only phoneme, amplitude, duration, and rate.
- The SC-02 datasheet defines pitch as
  `XCK / (8 * (4096 - inflection))`; higher inflection therefore means higher
  pitch, and the mapping is not linear.
- The AppleWin source bank contains one fixed capture per phoneme at an
  undocumented inflection. Absolute chip pitch cannot be recovered from those
  captures without an anchor.
- Commit `6bcf5cb` deliberately changes rate without resampling the captures,
  so adding inflection must not re-couple pitch and duration.
- A deleted earlier resampling attempt assumed 2048 was neutral and was
  disabled because real firmware values made the voice far too low.

## Theories (plausible)

1. The startup phrase contains useful per-phoneme inflection variation, but PCM
   drops it. A pitch-preserving-duration transform relative to the phrase's
   normal firmware value will restore punctuation contours.
2. The firmware does not vary inflection across the startup question; its weak
   contour comes from another register or from the capture sequence.
3. The firmware varies inflection, but fixed independent captures cannot
   tolerate enough pitch shift to make the contour audible without artifacts.

## Tests Run

| Test | Hypothesis | Result | Rules Out | Supports |
|------|------------|--------|-----------|----------|
| Exact BS2 startup trace | 1 vs 2 | 88 events; the three reset events used 0, then all 85 initialized events used inflection 3072, including the complete question | A per-phoneme raw-inflection contour being merely dropped by PCM | 2, or missing chip transition state |
| DOPITCH `_VIFLAG` causal trace | Missing fresh-state enable flag | The exact ROM links `_VIFLAG` at logical `DA05` / physical `41A05`; flag 0 produced only 3072, while flag 1 produced 62 normal events at 3072 and 20 raised events at 3288 | The phrase lacking firmware intonation markers; transitioned mode being the first missing mechanism | Fresh-state flag seeding, followed by PCM use of the resulting snapshots |
| Production fresh-state trace | ROM-derived flag seeding restores firmware contour events | The unmodified exact startup command reported `Voice inflection enabled @ 0x41A05` and produced 62 events at 3072 plus 20 at 3288 | Diagnostic-only flag behavior | Keep the firmware-default slice |
| PCM transform design | Relative datasheet mapping can preserve normal timbre and exact timing | Normal firmware inflection is proven at 3072; documented frequency is proportional to `1 / (4096 - I)`, making 3288/3072 a 1.267x rise and 2856/3072 a 0.826x fall | Treating 2048 as neutral; linear mapping; varispeed duration changes | Anchor 3072 at identity, transform voiced captures, then restore the exact pre-transform length |
| First PCM transform | Resample by the documented ratio, then restore length with the existing pitch-preserving rate path | Length, normal identity, rate invariance, and `play()` wiring passed; the real capture's strongest low FFT component moved from 274 Hz to 299 Hz for the requested lower setting | This implementation as proven pitch lowering | Compare autocorrelation period against FFT harmonic selection before keeping or rejecting |
| Fundamental-period measurement | The FFT failure is harmonic-peak swapping, not reversed pitch | Autocorrelation measured 90.37 Hz normal, 74.75 Hz lower (0.827x), and 114.84 Hz higher (1.271x), matching predicted 0.826x/1.267x ratios at identical frame counts | The transform moving fundamental pitch in the wrong direction | Keep the transform; use period rather than strongest harmonic in its regression |
| Transitioned-mode field decode | The complete 12-bit value is an immediate-frequency value | The datasheet scan says transitioned mode uses I10:I6 as a target and I5:I3 as its rate. Firmware 3072 decodes to target 16/rate 0; 3288 decodes to target 19/rate 3, with unchanged immediate bits | Applying the immediate-frequency formula to all 12 bits; a flat whole-phoneme 1.267x retune | Model a gradual target transition and verify the rate scale before changing PCM |
| User-authorized rate mapping | The extracted five-frame mapping may be used despite its unavailable scan | The user explicitly authorized using it; rate 3 maps to five frames and rate 0 to eight | The missing scan as a blocker to implementation | Encode those exact frame counts in the PCM regression |
| Transitioned PCM focused gate | A stateful target ramp can preserve length and reduce the pitch jump | The latched mode and five/eight-frame target regressions failed before production changes, then passed; all SSI-263 and PCM tests pass, 25 total. The rendered high phoneme changes fundamental pitch by less than the rejected 1.267x flat retune at identical length, and an unvoiced capture remains byte-for-byte identical | A flat full-register retune; a stateless per-phoneme restart; pitch movement on unvoiced captures | Run the exact command and inspect callback continuity plus real captured audio |
| Exact-command callback continuity | The target-ramp DSP may starve Windows playback | The clean log has 88 enqueues, 30 speech chunks, 2.983 seconds queued, a 3.415-second enqueue span, a 2.971-second callback span, and zero internal silent callbacks. An earlier log's internal silence was caused only by a Ctrl-C control enqueue 15.7 seconds after speech completed | The target-ramp DSP as a source of startup choppiness; the contaminated post-symptom event as causal evidence | Run the full automated gate, then require physical listening |

## Current Best Theory

Two independently necessary failures are proven. Fresh QNS RAM leaves
`_VIFLAG` off even though source initialization defines 1 as its default, so
firmware suppresses the marker-driven C1 writes. Enabling the flag exposes
normal 3072 and raised 3288 snapshots, which the old PCM path still dropped.
The first PCM attempt decoded those transitioned-mode snapshots as immediate
frequency values. That is wrong: the raised value requests a gradual move from
target level 16 toward target level 19 at rate 3.
The corrected PCM backend now carries the chip's latched inflection mode and
current target level across phonemes, divides each voiced phoneme into its
hardware frame count, and moves toward the new target over `8 - rate` frames.
It advances the transition through unvoiced and pause frames without imposing
pitch on their samples.

## Open Questions

- What inflection value was used to record the fixed AppleWin captures?

## Next Action

The full gate passed with 355 tests and 8 skips. Run Ruff, audit and commit the
kept source slice, then ask the user to rerun the exact command as the physical
listening oracle.
