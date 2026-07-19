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

## Current Best Theory

Theory 1 now has the strongest evidence. The state selects a startup path that skips the cold initializer even though required shadow workspace `COMBYT` was never written. Theory 2's CPU-snapshot premise is ruled out because QNS state files intentionally contain only nonvolatile memory, and their RAM/bitmap restoration is byte-exact. Theory 3 remains possible only if the emulator's reset or hardware-memory model differs from the real BS2 lifecycle.

## Open Questions

- Which ROM condition selects the cold initializer at PC `0x07F2` versus the observed warm path?
- Which state byte or flash condition makes the current image satisfy that branch?
- Does a genuinely blank state reach `0x07F2`, write `COMBYT=0x64`, and configure ASCI0 correctly?

## Next Action

Rerun only the blank-state verifier with the new timeout context. Use its initializer hit count/cycle and final MMU registers to determine whether PC `0x07F2` ran before the boot path stalled.
