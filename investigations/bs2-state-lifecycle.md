# Investigation: BS2 state lifecycle

## Facts (verified)

- The exact BS2ENG verifier loads `roms/NFB99/BS2ENG/bs2eng.bns` and `C:/Users/Q/AppData/Local/Temp/qns-bs2-file-lifecycle-20260718.state`.
- After loading that state and reaching the editor command loop, physical `COMBYT` at `0x414B0` is `0x00`.
- The ROM cold initializer at PC `0x07F2` is not executed on this startup path; its watch count and cycle remain zero.
- O-chord followed by lowercase `f` is accepted far enough to start the disk-probe sequence.
- ASCI1 sends ENQ, accepts host NAK, raises its receive interrupt, and drains the byte in firmware.
- The firmware then writes ENQ to ASCI0 TDR at cycle `17806526`, PC `0x22E4`, while ASCI0 `CNTLA=0x01` has transmitter enable clear. The byte cannot shift.
- The shared-harness refactor preserves this exact cycle, PC, state, and causal trace.
- A QNS state file contains complete RAM, shadow-written bitmap, and flash bytes; it contains no CPU execution snapshot.
- In the exact lifecycle state, bitmap byte `0x82A6` is `0x00`, so physical `COMBYT` address `0x414B0` was never marked written. Its raw RAM byte at file offset `0x514C0` is also `0x00`.

## Theories (plausible)

1. The preserved state was captured at the wrong lifecycle point. It resumes a warm-start path with cold-start-owned RAM fields unset; a correctly initialized state would contain the required `COMBYT` value and permit ASCI0 transmission.
2. `BNS.save_state()` / `BNS.load_state()` omit or incorrectly restore reset, MMU, RAM, or peripheral state needed to make a saved command-loop state self-consistent. The file may have been valid when captured but becomes inconsistent after reload.
3. The ROM deliberately expects a reset transition after state/ROM loading. The verifier currently resumes directly, so it selects a warm path without executing the initialization required after host construction.

## Tests Run

| Test | Hypothesis | Result | Rules Out | Supports |
|------|------------|--------|-----------|----------|
| Exact external-program verifier after harness cleanup | Refactor changed the lifecycle behavior | Same ASCI1 success and ASCI0 TE-disabled failure at the same cycle and PC | Harness refactor regression | Pre-existing lifecycle defect |
| Inspect state serializer and exact `COMBYT` bitmap/raw bytes | State serialization omitted a written `COMBYT` value | Serializer restores all bytes and metadata; `COMBYT` is unwritten and raw zero in the file | Explicitly persisted zero; CPU-snapshot loss | Inconsistent warm/cold lifecycle state |
| Run exact verifier with a newly created blank state | Blank and preserved states select the same broken path | Blank state reaches the 100,000,000-cycle boot bound at PC `0x1BDA`; preserved state reaches command loop and fails at ASCI0 in about seven seconds | One universal reset path | State-dependent lifecycle branch |
| Run exact verifier with a pristine one-instruction state | The previous blank-state result represents cold startup | A state saved after only reset-vector `DI` also reaches PC `0x1BDA`, with zero `0x07F2` hits and MMU `34/1E/C6` | Prior million-cycle save as cause; preserved image causing initializer skip | A genuine cold-start stall before editor readiness |
| Capture retained speech at pristine PC `0x1BDA` | Cold startup is blocked on a missing device transition | CPU is halted after speaking `Initialize flash system. Enter Y or N.` | Hardware/interrupt stall | Required first-boot keyboard dialogue |
| Recognize the exact prompt and send acknowledged lowercase `y` (`0x3D`) | The first-boot dialogue accepts the same lowercase key used by later menus | Firmware returns to halted PC `0x1BDA` after the next 100,000,000-cycle bound | Lowercase response | Response rejection or initialization failure |
| Send authoritative uppercase `Y` chord (`0x7D`) | The uppercase prompt label identifies the required case-sensitive chord | Firmware again returns to halted PC `0x1BDA` with zero initializer hits and MMU `34/1E/C6` | Simple case mismatch | Response rejection or initialization failure after acknowledged input |

## Current Best Theory

Pristine flash correctly enters a firmware initialization dialogue and waits at halted PC `0x1BDA` for `Y` or `N`, but neither acknowledged lowercase `y` nor authoritative uppercase `Y` crosses the dialogue. The current evidence does not distinguish firmware response rejection, flash initialization failure, or a deliberate repeated prompt. The preserved image bypasses the dialogue because its flash is already initialized, but it contains a separate downstream inconsistency: `COMBYT` was never written on that restart path.

## Open Questions

- Does the dialogue reject both raw responses, or does flash initialization fail and return to the same prompt?
- What speech does firmware produce after the acknowledged uppercase `Y`, before it returns to PC `0x1BDA`?
- Can a correct initialized path write logical `COMBYT=0x64` and complete BS2ENG import/execution without patching state bytes?

## Next Action

Restore the prematurely reverted verifier/test slice, retain the speech cursor before uppercase `Y`, and inspect the exact post-response speech at the next stable key wait. Use that evidence to distinguish response rejection from flash-initialization failure while staying on the same first-boot target.
