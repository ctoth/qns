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
- Ordinary power-up writes ASCI0 `CNTLA0=0x64` directly, but the cold-reset `WARM0` path is the linked code at PC `0x07F2` that also persists `COMBYT=0x64`.
- The documented and linked cold-reset gesture is I-chord `0x4A` held at power-on. Holding it until PC `0x07F2` executes enters the complete file, flash, folder, and file-area initialization workflow without patching state bytes.
- Linked keyboard ISR entry clears the hardware latch before it accepts a chord. Firmware-level key-down acceptance writes the held chord to logical `_IIB=0xF27D` (physical `0x4327D`); key-up acceptance clears `_IIB` while buffering the chord.
- With that two-phase firmware handshake, both ASCI disk probes and the complete YMODEM import succeed. The firmware returns to its editor loop at PC `0xD657` after the transfer.

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
| Hold documented I-chord through linked PC `0x07F2` | A real cold reset owns persistent serial initialization | Firmware executes `WARM0`, writes `COMBYT=0x64`, and enters the documented destructive initialization dialogue | Emulator-side `COMBYT` patch; ASCI implementation defect | Missing power-on lifecycle input |
| Complete file/flash/folder/wipeout prompts with latch-only chords | Hardware latch clear means the firmware accepted each chord | The first wipeout `y` is dropped with no confirmation speech because `ONFLG='i'` and the ISR has not reached its key-up queue path | Prompt mismatch; wrong yes chord | Keyboard handshake ends too early |
| Hold and release against physical `_IIB` transitions | `_IIB` is the firmware acceptance boundary | All cold-reset prompts cross; ASCI1 and ASCI0 probes complete; YMODEM imports the program and returns to PC `0xD657` | Serial initialization defect; YMODEM transport defect | Linked firmware-level chord handshake |
| Send bare X-chord after transfer returns to PC `0xD657` | Transfer leaves the firmware inside the file manager | Firmware waits at PC `0x1BDA` and never switches to external `CBAR=0x11` | External launcher/MMU as the immediate failure | Transfer returned to editor; file manager must be re-entered |
| Re-enter O/f, select with C5, and require PC `0x1000` under `CBAR=0x11` | Every external program enters under the launcher's temporary validation map | Native watch records one PC `0x1000` hit with `CBAR=0x81`, followed by BSNAME's own speech | Import, selection, or execution failure | The fixed `0x11` entry-map premise is wrong for smaller programs |
| Derive entry CBAR from BSNAME's header using `_execute_program` | The captured `0x81` is the program-size-specific final map | Header length `0x6205` plus `0x1fff` is `0x8204`; firmware masks to `0x80`, sets bank base page 1, and jumps with `CBAR=0x81` | Arbitrary PC `0x1000` collision | Source-defined external-program execution |
| Rerun the pristine lifecycle/import/launch gate with the header-derived map | The complete supplied-ROM path is now exact | Exit `0`; imports 25,108 bytes, reports cycle `344424483`, PC `0x1000`, `CBAR=0x81`, and retains BSNAME's own speech | Remaining lifecycle, serial, filesystem, or launcher defect | Root lifecycle and external-program path confirmed |

## Current Best Theory

Confirmed. The original ASCI0 failure was caused by an incomplete lifecycle, not the serial device: flash-only initialization left persistent `COMBYT` unset because the documented power-on I-chord cold reset never ran. The linked cold-reset path initializes `COMBYT`, and the linked `_IIB` handshake makes keyboard delivery reliable enough to complete the full dialogue, both serial probes, YMODEM import, file selection, and BSNAME execution at its source-derived PC/MMU entry state.

## Open Questions

- How should the product stdio keyboard path expose the source-defined power-on I-chord and wait for firmware-level chord acceptance instead of hardware-latch clearing?

## Next Action

Run the full repository gate and commit this confirmed lifecycle/import/entry slice. Then inspect the product stdio keyboard scheduler against the now-proven power-on and `_IIB` acceptance requirements before making a separate product slice.
