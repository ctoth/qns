# Investigation: PCM Inflection

## Facts (verified)

- `SSI263` decodes the complete 12-bit inflection value into
  `SSI263State.inflection`.
- `SSI263PCMSynth.play()` currently drops that value and forwards only
  phoneme, amplitude, duration, and rate.
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

## Current Best Theory

Two independently necessary failures are proven. Fresh QNS RAM leaves
`_VIFLAG` off even though source initialization defines 1 as its default, so
firmware suppresses the marker-driven C1 writes. Enabling the flag exposes
normal 3072 and raised 3288 snapshots, but PCM still drops those snapshots.

## Open Questions

- What inflection value was used to record the fixed AppleWin captures?
- Can PCM move dominant voiced frequency in the documented direction while
  preserving the existing playback length exactly?

## Next Action

Commit ROM-derived `_VIFLAG` seeding after its 352-passed, 8-skipped full
suite, passing Ruff gate, clean diff audit, and exact production trace. Then
begin the separate PCM transform.
