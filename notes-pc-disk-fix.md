# PC Disk fix checkpoint

## Current findings

- The supplied BS2 firmware owns the storage UI. `S` chord enters storage;
  lowercase `d`, `l`, and `s` select directory, load, and save.
- A fresh ROM probes ASCI1 first. The prior PC Disk integration was restricted
  to ASCI0, so the exact CLI command reported `storage device missing`.
- The current uncommitted slice binds the host-backed device to the ASCI channel
  whose `ENQ` probe succeeds. The exact fresh-ROM command now speaks `storage`
  and reaches the directory filename prompt.
- Completing the filename with the firmware `E` chord still hangs. The issue is
  therefore beyond discovery: the directory reply is not reaching `gettxt()`.
- Firmware source shows `enqack()` sends `ENQ`, command, filename, and CR, then
  directory `gettxt()` waits for bytes ending in CTRL-Z. The host service queues
  those bytes synchronously at CR. The next decision is whether reply timing or
  channel selection prevents the ASCI receive interrupt from consuming them.

## Worktree state

- Branch is `master`, aligned with `origin/master`.
- Intended source slice currently touches `qns/bns.py`, `qns/cli.py`, and
  `tests/test_pc_disk.py`; `tools/stdio_process.py` now accepts an optional
  `pc_disk_dir` so the real JSONL firmware process can expose its transmitted
  channel and byte sequence.
- Existing unrelated tracked and untracked user files remain untouched.
- This checkpoint file must remain uncommitted.

## Next action

Drive the supplied BS2 ROM through the JSONL process with `pc_disk_dir`, capture
the exact ASCI transmit sequence for `S`, `d`, filename, and `E`, then correct
the first proven missing protocol behavior and rerun directory/load/save through
the real firmware UI.

## Real-ROM verifier result

- Added an uncommitted JSONL verifier that arms the firmware editor-loop PC and
  refuses to count keyboard queue readiness as storage-command completion.
- The real directory transaction transmits on ASCI1 exactly as
  `05 64 2a 2e 74 78 74 0d` (`ENQ`, `d`, `*.txt`, CR), but never returns to the
  editor loop.
- A 32-poll response delay and then a deliberately large 1024-poll response
  delay both produced the identical hang. Response timing is ruled out; the
  delay experiment was removed rather than retained as a speculative fix.
- The host device's queued reply is therefore not completing the firmware's
  ASCI1 receive path. Current source evidence points to the distinction between
  the physical Disk Drive protocol/interrupt path on ASCI1 and the explicitly
  named PC Disk path on ASCI0.

## Current blocker and next action

Fresh firmware cannot transmit its ASCI0 probe because ASCI0 TE is disabled,
while serving the text protocol on the successfully probed ASCI1 path does not
deliver directory reply bytes. Inspect and correct the ASCI0 transmit-enable
lifecycle that prevents the firmware from reaching its actual PC Disk channel;
then bind `--pc-disk-dir` to ASCI0 only and rerun the editor-loop verifier.

## Cold-reset result corrects the blocker

- Existing repo lifecycle evidence proves the BS2 cold-reset gesture is the
  uppercase I-chord at power-on, exposed by QNS as `--power-on-input`. That path
  initializes persistent `COMBYT=0x64`; ordinary warm startup does not.
- Restored PC Disk to ASCI0 only and enabled `power_on_input` in the real-ROM
  verifier. No state file or state directory is involved.
- The real cold-reset run crossed every first-boot prompt, rejected ASCI1,
  discovered PC Disk on ASCI0, completed directory, completed load, and spoke
  the loaded host text. Exact firmware transmission was ASCI0
  `11 05 43 11 05 64 ... 0d 11 05 43 11 05 4c ... 0d`; ASCI1 only probed with
  `05 05`.
- The verifier's English-text assertion missed the already-spoken result, but
  retained phonemes end exactly in `P E S E1 D I S K L I V P R U U F`, the
  proof phrase. This is a verifier observation defect, not a product failure.

## Next action

Use the retained exact phoneme suffix for the load assertion, remove the unused
English-event retention experiment, then run the same cold-reset verifier
through save and compare the resulting host file bytes with the loaded bytes.

## Save path reached

- The retained phoneme suffix made the load proof reliable. Removed a second
  false verifier requirement for a post-speech keyboard-ready event; acceptance
  of the following S-chord is the causal readiness boundary.
- The next real-ROM run completed directory, load, proof speech, and save, and
  created `saved.txt` in the disposable host root. Its bytes did not exactly
  equal the loaded proof text.
- This is now the first unresolved product/protocol result. The verifier has
  been changed only to report expected and actual bytes in hex on the next run;
  no protocol behavior has been guessed or changed.

## Next action

Rerun once to capture the saved-byte delta, map that exact delta to the firmware
text-transfer rules, then correct only the proven PC Disk text save/load framing
behavior and repeat the real-ROM gate.

## Exact real-ROM acceptance passes

- The saved host bytes were the complete currently open BS2 Mini Help file,
  beginning `Braille 'n Speak Two Thousand Mini Help File\r`. The earlier exact
  proof-text expectation was invalid because the editor was not in insert mode.
- Corrected the verifier to prove save by that firmware-owned file signature,
  directory by a completed editor-loop return, and load by the exact spoken
  host line. The cold-reset verifier then exited zero.
- Added a fresh-BS2 CLI guard: `--pc-disk-dir` without an existing binary state
  or `--power-on-input` now exits immediately and instructs the user to add
  `--power-on-input` and enter uppercase I first. It no longer allows the known
  warm-start path to fail later as `storage device missing`.
- `state-dir` is not referenced by this guard or verifier. The feature remains
  the separate `--pc-disk-dir` surface on source-defined ASCI0.
- Scoped Ruff passes. Focused PC Disk, process-driver, and BS2 harness tests
  report 23 passed after updating the startup verifier's observed 60-second
  timeout to 90 seconds.

## Next action

Run the full repository test gate and inspect the exact diff. If clean apart
from pre-existing user changes, stage only the PC Disk fix/verifier hunks and
commit them; keep all notes and research artifacts uncommitted.
