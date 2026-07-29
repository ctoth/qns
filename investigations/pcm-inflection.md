# Investigation: PCM Inflection

## Facts (verified)

- `SSI263` decodes the complete 12-bit inflection value into
  `SSI263State.inflection`.
- `SSI263State` now reports whether the latched mode selected transitioned
  inflection, and `SSI263PCMSynth.play()` receives both that mode and the
  complete inflection value.
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
| Physical listening of `2a3b364` | Segment resampling plus length restoration preserves the intended timbre | The user reports that it sounds like the frequency setting shifts and that the original hardware definitely did not do that. The implementation resampled the entire waveform, moving formants together with glottal pitch | Passing pitch/length/callback tests as audible proof; whole-waveform resampling as a valid pitch transform | Revert the slice and require spectral-envelope/formant preservation |
| Git reconciliation | The audibly rejected source slice should remain | Commit `6f2fa30` reverts `2a3b364` in full; no rejected PCM transform remains in production | Keeping a technically green but behaviorally wrong slice | Begin a new test-first formant-preserving attempt |
| Isolated pitch-synchronous transform | Intact waveform grains can change glottal pulse spacing without moving the spectral envelope | A 1.15 PSOLA target kept exact sample length, measured a 1.10-1.20 autocorrelation pitch ratio, and retained greater than 0.95 LPC-envelope correlation | Whole-capture resampling being necessary for pitch movement | Pitch-synchronous overlap-add as the candidate mechanism |
| Transition integration regressions | The chip's five/eight-frame targets can drive PSOLA without imposing pitch on noise | Transitioned mode reached PCM; the high target increased measured pitch below the rejected flat ratio while retaining greater than 0.95 LPC-envelope correlation; phoneme 52 remained sample-exact | Dropping the latched mode; treating every capture as voiced | Keep the candidate for real callback and physical-listening gates |
| Focused SSI-263/PCM suite | Transition state breaks existing chip or PCM behavior | 26 passed in 0.63 seconds | Known focused regressions | Proceed to the exact startup command |
| Exact startup command with fresh callback log | Pitch-synchronous processing reintroduces the earlier inserted-silence failure | The command reached the prompt; 88 enqueues contained 30 speech chunks and 2.982993 queued seconds over a 3.416053-second enqueue span; the 2.969330-second callback span had zero internal silent callbacks | Callback starvation or inserted callback silence as a regression in this candidate | Proceed to full gates, then physical listening |
| Full automated gates | The candidate breaks behavior outside the focused SSI-263 surface or violates repository checks | 356 passed and 8 skipped in 17.18 seconds; Ruff and `git diff --check` passed | Known repository regressions and lint/whitespace failures | Commit the isolated candidate for physical listening |

## Current Best Theory

Two independently necessary failures are proven. Fresh QNS RAM leaves
`_VIFLAG` off even though source initialization defines 1 as its default, so
firmware suppresses the marker-driven C1 writes. Enabling the flag exposes
normal 3072 and raised 3288 snapshots; PCM previously dropped those snapshots.
The rejected transform moved the entire capture spectrum because it resampled
the waveform. Pitch-synchronous overlap-add instead changes glottal pulse
spacing while reusing intact capture grains; automated measurements preserve
the formant envelope, but only physical listening can establish that it
matches the original behavior.

## Open Questions

- What inflection value was used to record the fixed AppleWin captures?
- Does the pitch-synchronous candidate sound like pitch movement rather than a
  frequency/filter-setting change on the user's actual output device?

## Next Action

Commit the isolated candidate, then present the exact startup command for
physical listening.
