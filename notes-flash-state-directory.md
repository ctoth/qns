# Flash state directory support

## Current findings and observations

- The existing `--state FILE` path stores RAM, the shadow-written bitmap, and
  flash in one versioned binary file and remains unchanged.
- The repository has no parser that maps the proprietary firmware flash file
  system to host files.
- The new `--state-dir DIR` path stores emulator state as three host files:
  `ram.bin`, `shadow.bin`, and `flash.bin`.
- Directory state validates all three component sizes before restoring memory.
- New directory saves use per-component temporary files and replacements.

## Current state

- Changes are confined to `qns/memory.py`, `qns/bns.py`, `qns/cli.py`,
  `tests/test_memory.py`, and `tests/test_bns.py`.
- `uv run pytest tests\test_memory.py tests\test_bns.py -q` passes with
  104 tests.
- `uv run ruff check qns\memory.py qns\bns.py qns\cli.py
  tests\test_memory.py tests\test_bns.py` passes.
- `uv run -m qns.bns --help` shows the mutually exclusive
  `--state FILE | --state-dir DIR` surface.
- The full suite cannot currently collect because unrelated dirty verifier
  work no longer exports `E_CHORD` to `tests/test_bs2_dictionary.py` and
  `tests/test_bs2_help.py`.
- With those two collection failures excluded, 250 tests pass and two more
  unrelated verifier tests fail because `send_stdio_chord` and
  `reach_stdio_editor_command_loop` are absent from the modified verifier.
- Existing unrelated tracked and untracked work remains untouched.

## Blocker

- The flash state directory slice itself has no blocker. A clean full-suite
  result is blocked by the unrelated in-progress verifier/test mismatch
  described above.

## Next action

- Hand off the implemented slice and focused green authorities without
  changing the unrelated verifier work.
- Keep this note uncommitted.

## 2026-07-20 correction: host-backed guest files

### Current findings and observations

- The current uncommitted `--state-dir` implementation does not expose host
  files to the guest. It only decomposes emulator state into `ram.bin`,
  `shadow.bin`, and `flash.bin`.
- The user's intended capability is to let the guest browse and modify files
  backed by a normal host directory.
- The supplied BS2 help documents a firmware-visible PC Disk surface with
  directory, load, save, delete, change-directory, make-directory, and
  delete-directory commands.
- Current QNS evidence proves only the initial PC Disk detection boundary:
  firmware probes ASCI1 and then ASCI0 with ENQ and falls back after NAK. The
  exact command and response protocol after an affirmative probe has not yet
  been recovered.
- A directory-backed PC Disk could satisfy the intended capability without
  decoding the proprietary internal flash filesystem, but only if the
  recovered wire protocol proves the documented file operations are direct
  host-disk operations.

### Current state

- This is a read/reverse-engineering task. No production implementation has
  been changed during the protocol investigation.
- The existing dirty `--state-dir` source and test slice remains untouched.
- The RE protocol is active; recovered firmware functions must be documented
  individually in `NOTES.md` before inspecting the next function.

### Blocker

- The exact PC Disk wire protocol is not yet known. ENQ/ACK/NAK discovery and
  the help text are insufficient authority for a directory-backed
  implementation.

### Next action

- Locate the supplied firmware source or decompile the first PC Disk owner,
  beginning with `disk_upload_download()`, document that function in
  `NOTES.md`, then follow only its next protocol-owning callee.
- Keep this note uncommitted.

## 2026-07-20 original PC software recovery

### Current findings and observations

- Freedom Scientific's current legacy download page still identifies WinDisk
  3.5 as the supported Windows program for post-July-2000 notetaker firmware.
- The Type Lite manual defines WinDisk in the opposite presentation direction
  from an ordinary host-directory mount: Windows Explorer exposes the
  notetaker's own RAM and flash folders as a drive, with bidirectional file
  copy plus whole-filesystem backup and restore.
- NFB99 firmware help separately documents the older external Disk Drive / PC
  disk command surface. That surface lets the notetaker request directory,
  load, save, delete, format, volume-label, change-directory,
  make-subdirectory, and delete-subdirectory operations. WinDisk mode and the
  external disk command menu must not be treated as the same protocol without
  wire evidence.
- An archived 2001 DB Techies download page names the original distribution
  artifacts `windisk.exe`, `windisk.doc`, and `windisk.txt`. The executable was
  recovered from the corresponding Wayback capture.
- Recovered `windisk.exe` is 1,545,242 bytes with SHA-256
  `0BA809C886C88287006F225C13B3001446A7A59614E05D716CAFA0FA9FD1BD7E`.
  It is an InstallShield self-extractor containing `data1.cab`, `data1.hdr`,
  `data2.cab`, `Setup.exe`, `Setup.ini`, `setup.inx`, `layout.bin`, and
  `ikernel.ex_`.
- The archived `windisk.txt` payload itself was not captured at the same
  timestamp; the manual and newsletter preserve its user-visible behavior but
  not the serial wire grammar.

### Current state

- The recovered installer and extracted outer cabinet are in
  `C:\Users\Q\AppData\Local\Temp\qns-pcdisk-re-20260720`; no recovered binary
  has been added to the repository.
- No QNS production source or tests have been changed.
- `NOTES.md` has not yet gained a protocol-function entry because no exact
  function body has yet been recovered; the RE protocol forbids documenting a
  guessed function.

### Blocker

- The WinDisk program files remain inside InstallShield `data1.cab` /
  `data2.cab`, which 7-Zip does not decode directly. The first protocol owner
  cannot yet be decompiled from the host binary.

### Next action

- Use an available InstallShield-capable extractor, without installing or
  executing the legacy product, then inventory the extracted executables and
  identify the serial protocol owner. If extraction cannot provide that
  owner, return to the linked firmware ROM at the already proven disk-probe
  entry.
- Keep this note uncommitted.

## 2026-07-20 first recovered WinDisk function

### Current findings and observations

- InstallShield 6 cabinet extraction recovered `WDComm.dll` and `WinDisk.dll`
  without installing or executing WinDisk.
- `WDComm.dll` is 49,152 bytes with SHA-256
  `9DF35738FF28C211039DD152881CD030F4DC71C22CA7B869E678872740ECAF62`.
  Its named exports include `getWhoWhat`, `enumFolder`, `getItem`,
  `receiveFile`, `sendFile`, `backup`, and `restore`.
- The first protocol owner, `CWDComm::getWhoWhat`, is now decompiled and
  recorded in `NOTES.md`. It sends exact bytes `05 04 57`, waits for exactly
  two reply bytes, and accepts device type `1..11` plus baud code `1..5`.
  This proves discovery framing but not directory or file framing.

### Current state

- The recovered DLLs remain only in the temporary analysis directory.
- No QNS production implementation or tests have changed.
- The RE documentation sequence is current: the first recovered function is
  in `NOTES.md` before inspection of the next function.

### Blocker

- No external blocker. Directory record and request framing remain unknown
  until the next function is recovered.

### Next action

- Decompile only `CWDComm::enumFolder`, inspect the constants and imported
  calls used by that function, then document its exact request and reply
  grammar in `NOTES.md` before moving to another function.
- Keep this note uncommitted.

## 2026-07-20 WinDisk direction and external PC Disk split

### Current findings and observations

- WinDisk protocol recovery is now documented function-by-function in
  `NOTES.md`: identity (`getWhoWhat`), directory enumeration (`enumFolder`),
  record control (`nextFunctionCharSend`), guest-to-host file receipt
  (`receiveFile`), and host-to-guest file transmission (`sendFile`).
- WinDisk directory requests are `05 04 46`, path, CR. The reply is a
  little-endian 16-bit count followed by fixed 31-byte records, acknowledged
  with `C`, retried with `R`, or cancelled with `X`.
- WinDisk file bodies use X/YMODEM in both directions. It exposes the
  notetaker's filesystem to the host while the firmware is in WinDisk mode;
  it does not expose a host directory to the notetaker as its PC Disk.
- The older external PC Disk path is distinct. Its linked firmware uses a
  bare ENQ probe and expects an affirmative response before falling back to
  ordinary serial transfer.
- The shared linked send primitive begins at bank-zero logical `0x22CF`: it
  takes one byte, selects ASCI0 or ASCI1, waits for transmitter readiness, and
  writes the byte. The banked caller containing the external-disk probe is in
  bank one around file offsets `0x26F0..0x2778` (linked logical `0x66F0..0x6778`).

### Current state

- No QNS production source or tests have changed.
- The WinDisk functions recovered so far are current in `NOTES.md`.
- A temporary Ghidra project contains the WinDisk DLL and BS2 bank-zero ROM;
  bank-one bytes are extracted but their banked function boundary has not yet
  been created in the analysis project.

### Blocker

- The exact start of the bank-one external PC Disk function and its command
  dispatch callees remain unresolved. Decompiling from the observed PC alone
  would conflate the shared serial send routine with the disk protocol owner.

### Next action

- Recover the bank-one function start that contains the ENQ probe, import that
  bank at its linked logical base, decompile exactly that function, and record
  it in `NOTES.md` before following its affirmative-response callee.
- Keep this note uncommitted.

## 2026-07-20 external PC Disk owner recovered

### Current findings and observations

- BS2 bank one is now imported as a 48 KiB window at its linked logical base
  `0x4000`. The window SHA-256 is
  `9044385996921329888B829E53C01478589FAE0B1D12572F53A70B5470220426`.
- The preceding routine ends at logical `0x60DD`. The external Disk Drive / PC
  Disk owner starts immediately after it at `0x60DE`, with a compiler stack
  frame allocation, and returns at `0x677B`. This exact boundary supersedes
  the earlier unresolved start near the observed probe.
- The recovered owner covers both ordinary serial transfer and external disk
  transfer. In its disk branch it performs a two-port probe, then selects
  command characters according to the requested transfer mode. The decompiler
  exposes disk command bytes including `Y`, `S`, and `R`; the exact receive
  helper semantics and response values still require one-function-at-a-time
  recovery before assigning a complete wire grammar.
- The late probe/release sequence at `0x671F..0x677B` is part of this same
  owner. It resets the transfer state, uses byte `0x05`, sends `Y`, uses byte
  `E`, retries twice on `0xFF`, reports any remaining nonzero response, restores
  the selected serial channel, and finalizes the transfer.

### Current state

- No QNS production source or tests have changed.
- The recovered ROM, mapped bank window, Ghidra projects, and analysis scripts
  remain only in the temporary analysis directory.
- The exact external-disk owner is ready to be recorded in `NOTES.md`, as
  required before following any of its serial callees.

### Source-backed protocol correction

- The exact matching sources are present at
  `C:\Users\Q\src\bns\bsp\FILETRAN.C` and `BSSERIAL.ASM`.
- Logical `0x230F` is `ftran_send_wt(ch)`: it sends the supplied byte and calls
  logical `0x2322`, `ftran_recv(char *error)`, to return the peer's reply.
- External-disk discovery tries port 1 and then port 0. It sends ENQ (`0x05`),
  repeats while the reply is `?`, requires ACK (`0x06`), then sends ASCII `C`.
  Reply `1` or `3` means a YMODEM-capable drive; `3` additionally advertises
  38,400-baud operation.

### Blocker

- No external blocker. Discovery is exact; the remaining unknown relevant to
  a host-directory backend is the disk-specific command/path sequence inside
  `upload_download` and the separate directory-operation owner.

### Next action

- Read only the disk-specific branch of source `upload_download`, record its
  command and pathname grammar in `NOTES.md`, then locate the directory owner.
- Keep this note uncommitted.

## 2026-07-20 PC Disk protocol recovered enough for design

### Current findings and observations

- The old PC Disk interface is the requested directional surface: firmware
  sends filesystem operations to a serial peer that owns the external files.
  WinDisk is the inverse surface and must not be used for this feature.
- Discovery is `ENQ -> ACK`, followed by `C -> '1'|'3'`; `3` advertises the
  faster drive rate. Firmware tries serial port 1 and then port 0.
- The text/filesystem request frame is `ENQ`, peer `ACK`, command, optional
  path/name, CR. Recovered commands include directory (`d`), load (`L`), save
  (`S`/`T`), delete (`K`), chdir (`H`), mkdir (`M`), rmdir (`X`), label (`V`),
  and format (`F`). Directory replies are text terminated by Ctrl-Z; text saves
  are terminated by Ctrl-Z; loads are streamed back through the serial receive
  path with XON/XOFF support.
- The YMODEM path is also exact: guest-to-host uses `ENQ/ACK`, `Y R`, then a
  YMODEM batch; host-to-guest uses `ENQ/ACK`, `Y S path CR`, then a YMODEM
  batch. The completion query is `ENQ`, `Y`, `E`, returning `0` for success and
  `0xFF` for retry/busy.
- `NOTES.md` now contains the function-by-function recovery and the resulting
  architecture conclusion.

### Current state

- No QNS production source or tests changed. The existing uncommitted
  `--state-dir` implementation remains untouched.
- Temporary recovered binaries and Ghidra projects remain outside the repo.
- The task note and `NOTES.md` are the only files updated by this protocol
  recovery, and they remain uncommitted.

### Blocker

- Protocol recovery is not blocked. Implementing the host-directory backend
  requires a user decision about the CLI contract: replace/redefine the current
  `--state-dir` meaning or add a distinct PC Disk root option.

### Next action

- Ask for that CLI-boundary decision before changing production code. Once
  supplied, implement a rooted PC Disk serial peer with traversal containment,
  the recovered command grammar, and focused real-ROM tests.
- Keep this note uncommitted.

## 2026-07-20 separate `--pc-disk-dir` implementation

### Current findings and observations

- The user selected a separate flag named `--pc-disk-dir`; `--state-dir`
  remains unchanged.
- New concrete device `qns/pc_disk.py` owns the legacy protocol on ASCI0. It
  implements discovery/capability replies, rooted path resolution, directory,
  text load/save, delete, chdir, mkdir/rmdir, and both firmware YMODEM
  directions. Format/update requests are rejected rather than deleting or
  rewriting the configured host root.
- `BNS` routes ASCI0 transmit bytes through the device and gives its queued
  replies priority on ASCI0 receive. Existing raw and JSONL serial observation
  remains available; ASCI1 is unchanged.
- Focused protocol tests cover discovery, directory/load/save, traversal
  containment, directory management, guest-to-host YMODEM, host-to-guest
  YMODEM, ASCI routing, and coexistence with `--state-dir`.
- Focused Ruff is clean. `uv run pytest tests/test_pc_disk.py tests/test_bns.py
  -q` passes all 104 tests.
- A bounded live run used the supplied NFB99 `bs2eng.bns` and the recorded
  lifecycle state. Firmware emitted channel-1 ENQ, fell back to channel 0,
  emitted `ENQ` then `C`, consumed PC Disk's `ACK` and `1` capability replies,
  and reached the next stable firmware key prompt. Captured output was
  `05 11 05 43`; PC Disk returned to its idle state.

### Current state

- Intended implementation paths are `qns/pc_disk.py`, `qns/bns.py`,
  `qns/cli.py`, and `tests/test_pc_disk.py`.
- The existing dirty changes in `qns/bns.py`, `qns/cli.py`, and the state-dir
  tests predate this slice and have been preserved.
- No files have been staged, committed, or pushed. This task note remains
  uncommitted as required.

### Blocker

- None. The full current suite passes 268 tests. Scoped Ruff and `git diff
  --check` pass, CLI help advertises both separate flags, a CLI subprocess
  creates a missing PC Disk root, and a regular file supplied as the root is
  rejected with argparse exit status 2.

### Next action

- Report the completed implementation. Do not stage, commit, or push unless the
  user explicitly asks; the surrounding worktree remains intentionally dirty.
- Keep this note uncommitted.

## 2026-07-20 real-menu PC Disk failure investigation

### Current findings and observations

- The PC Disk slice was committed as `3d41e8f` (`Add host-backed PC Disk`).
- The user's exact interactive launch is `uv run -m qns.cli --model bs2
  --input keyboard --speech-stream english --pc-disk-dir .\
  roms\NFB99\BS2ENG\bs2eng.bns`.
- Selecting the feature in the real BS2 UI says `storage device missing`.
  Therefore the earlier bounded boot-time byte capture and direct state-machine
  tests did not prove the actual menu-driven discovery transaction.
- The command syntax is accepted and is not the diagnosed failure. The active
  possibilities are wrong ASCI channel selection, wrong discovery response
  bytes/order, or incorrect receive-ready timing in the ASCI integration.
- `investigations/pc-disk-storage-device-missing.md` now separates the verified
  facts from those theories and remains uncommitted.

### Current state

- No source fix has been made after the report.
- The pre-existing state-directory and unrelated dirty worktree changes remain
  untouched.
- Both this note and the investigation record remain uncommitted.

### Blocker

- None yet. The real menu transaction must be captured before choosing a fix.

### Next action

- Drive the supplied BS2 ROM through the same menu path under structured stdio,
  capture ASCI0 and ASCI1 transmit/receive state through the failure, and
  compare it to the recovered firmware control flow.
- Keep this note uncommitted.

## 2026-07-20 PC Disk ownership and real S-chord trace

### Current findings and observations

- PC Disk is not a guest `.bns` external program. The supplied July 1999
  `bs2eng.hlp` documents S-chord as the built-in Disk Drive activation and says
  most Disk Drive commands also work with PC Disk.
- The separate post-2000 WinDisk product is an inverse host-side browser of the
  notetaker's RAM/flash filesystem. It is not the older PC Disk device surface
  requested here, and the 1999 ROM predates its required firmware.
- Recovered source confirms the S-chord owner calls
  `disk_upload_download(-1)`, which probes transfer channel 1 and then channel
  0. `BSPROCES.ASM` explicitly labels a successful channel-0 selection as
  `pcdisk`; channel 1 is the physical Disk Drive path.
- The user's exact fresh launch was replayed through structured stdio. After
  both flash-initialization confirmations, S-chord emitted only ASCI1 ENQ
  (`BQ==`) and then spoke `storage device missing`; no ASCI0 byte transmitted.
- QNS correctly attaches the emulated PC Disk peer to ASCI0, but this fresh
  firmware lifecycle never reaches it. This matches the earlier proven
  `COMBYT`/ASCI0 initialization defect: the channel-0 fallback cannot transmit
  until the real cold-reset/persistent communication state is established.
- The earlier bounded live claim used a recorded lifecycle state and a transfer
  path that did reach ASCI0. It did not validate the user's fresh launch or the
  real S-chord Disk Drive menu and was not sufficient feature proof.

### Current state

- No implementation fix has been made during this research pass.
- `investigations/pc-disk-storage-device-missing.md` now contains the evidence
  table and corrected best theory.
- The task note and investigation record remain uncommitted.

### Blocker

- A product decision is required before implementation: whether
  `--pc-disk-dir` may require a correctly initialized persistent guest state,
  or must work from the user's fresh ROM-only launch without a separate cold
  lifecycle procedure.

### Next action

- Write the structured research report, then report the product distinction and
  root cause. Do not move PC Disk to ASCI1; first decide the fresh-start
  contract, then require a real-ROM S-chord directory/load/save gate.
- Keep this note uncommitted.
