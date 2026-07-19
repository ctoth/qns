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
| Capture speech after acknowledged uppercase `Y` | Flash initialization emits a distinct failure message before returning to the prompt | Firmware speaks the complete identical `Initialize flash system. Enter Y or N.` sequence and returns to PC `0x1BDA` | Distinct spoken failure path | Prompt loop before or after a silent initialization failure |
| Read `ASKSURE` and linked English `BRLYES` | The prompt accepts uppercase ASCII `Y` | Both `GETKEY` reads compare directly to `BRLYES=0x3D`, the lowercase `y` raw chord | Uppercase response; single-response workflow | Two prompt-paced lowercase `y` confirmations |
| Match confirmation speech and send the second lowercase `y` | Both confirmations enter `flashInit` | Firmware leaves the prompt loop and runs until the following 100,000,000-cycle stable-key bound expires | Keyboard/prompt rejection | Downstream flash-initialization failure or long-running loop |
| Add causal state to the post-confirmation stable-key timeout | Firmware remains inside flash initialization | At the bound, PC is the editor command loop `0xD657`, speech IRQ is clear, and 311 phonemes have completed; only `halted=0` prevents `wait_for_key()` success | Flash polling loop or missing device transition | Verifier uses the wrong post-initialization predicate |
| Use the exact editor predicate after the second confirmation | First boot can reach the external-program scenario | Pristine state crosses flash initialization, O/f/T, and ASCI1 ENQ/NAK, then reaches the same ASCI0 TE-disabled failure with `COMBYT=00` and no `0x07F2` hit | Flash initialization as current blocker; stale preserved state as sole cause | Shared startup/serial initialization defect downstream of editor readiness |

## Current Best Theory

Pristine flash correctly enters `ASKSURE`, accepts both lowercase `y` raw chords (`BRLYES=0x3D`), reaches the exact editor predicate, and continues through O/f/T and the complete ASCI1 probe response. It then reproduces the original ASCI0 failure: `COMBYT=00`, no PC `0x07F2` initializer hit, and ENQ stuck in TDR with TE disabled. First-boot flash initialization is solved; the remaining root cause is a shared startup/serial initialization defect, not the preserved state.

## Open Questions

- Why does the real linked BS2 startup path never execute PC `0x07F2` or otherwise initialize `COMBYT` before `DTRON` uses it?
- Is PC `0x07F2` part of a different model/configuration path, making the prior source assumption invalid for BS2ENG?
- Can a correct initialized path write logical `COMBYT=0x64` and complete BS2ENG import/execution without patching state bytes?

## Next Action

Commit the kept first-boot verifier slice. Then recover the actual linked startup path that should initialize ASCI0/`COMBYT` in BS2ENG before changing emulator or firmware-facing behavior.
