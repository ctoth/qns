# External BNS toolchain research

## Goal

Produce the primary documentation artifact explaining how to build a `.bns`
external program that runs on a Blazie note taker, including an executable plan
for completing and validating the toolchain.

## Current findings

- The QNS repository is primarily an emulator/recovery project. Its existing
  external-program lifecycle investigation proves that a supplied `BSNAME.BNS`
  can be imported over the real firmware YMODEM path and launched at logical
  `0x1000` with a program-size-derived MMU map.
- The authoritative external-program ABI artifacts are present under
  `C:\Users\Q\src\bns\bsp`:
  - `PROGHDR.ASM` defines the downloadable program header and C entry/exit
    sequence.
  - `include\BNSAPI.H` exposes the model-independent Blazie application API.
  - `BSAPI.C` implements the firmware side of that API.
- `PROGHDR.ASM` states the exact linker layout: SC180 library, `CODE` starting
  at logical `0x1000` but emitted at file offset zero, `CONST/DATA/BSS/BSSZ/STACK/END`
  grouping, `proghdr` first, application modules next, and `sc180.lib` last.
- Its on-disk header begins with a jump, `BNS\0`, code size, total program
  length, CRC placeholder, and stack pointer. It sets the stack, calls C
  `_main`, and terminates via API function zero (`RST 38h`) after `main`
  returns.
- Its stated program rules are: do not change the MMU; access hardware through
  the API; do not permanently disable interrupts; keep the stack at logical
  `0x1000` or above; and exit by returning as if called.
- `PGM.BAT` demonstrates historical environment variables `%asmpgm%` and
  `%linkpgm%`, but it appears to be a hardware test program rather than the
  complete third-party C application build recipe.
- `CHECK.BAT` identifies the historical Softools command names: assembler via
  `ASMPGM`, C compiler `sc180` via `CPGM`, and linker `slink` via `LINKPGM`.
  `PROGHDR.ASM` also requires the Softools `sc180.lib` runtime.
- The local source archives contain `PROGHDR.ASM` and `BNSAPI.H`, but no local
  `C:\softools` installation was found and `bsp\bin` is empty. The compiler,
  assembler, linker, and runtime library therefore have not yet been shown to
  be runnable on this host.
- `BUPDATE.C` documents a separate historical post-link step: its linked
  executable was processed by `BSUPDATE.EXE` to create a `.BNS`. This strongly
  indicates that header length/CRC finalization is a distinct tool, but the
  exact general external-program finalizer and CRC coverage still need to be
  identified rather than inferred.
- Firmware source `BS.ASM::_execute_program` and `FILEP.C` are the validation
  and launch authorities. Existing QNS investigation has already proven the
  size-derived MMU entry for a real `BSNAME.BNS`.
- `BS.ASM::_execute_program` makes the external-program validation contract
  exact:
  - logical entry is `0x1000`, corresponding to file offset `0`;
  - bytes `2..5` must be `BNS\0` (or `TNS\0` for TNS/Tiny Lite builds);
  - little-endian `code_size`, `program_length`, `code_crc`, and initial stack
    are at file offsets `6`, `8`, `10`, and `12`;
  - CRC starts at zero and covers exactly `code_size` bytes beginning at file
    offset `0x0E` (the entry code), explicitly excluding data;
  - final MMU coverage is derived from `program_length` by adding `0x1FFF` and
    rounding to a 4 KiB boundary.
- `PROGHDR.ASM` places a final `0xAA` marker in the `END` segment. Real samples
  confirm `file_size == program_length + 15`: the stored length begins at
  entry offset `0x0E` and stops before the one-byte final marker.
- Real header examples:
  - `BSNAME.BNS`: file size `25,108`, code size `0x1AEF`, program length
    `0x6205`, CRC `0x6E8A`, stack `0x7213`;
  - `CALSORT.BNS`: file size `17,092`, code size `0x2EDE`, program length
    `0x42B5`, CRC `0x0F57`, stack `0x52C3`.
- `BUPDATE.LNK` is a complete historical external-application link shape:
  search paths for Softools SC180, code linked at logical `0x1000` and emitted
  at file offset zero, combined const/data/bss/bssz/stack/end grouping,
  `proghdr` first, application object next, `sc180.lib` and `bsapi.lib` after
  it, flat-binary output.
- The distributed `BNSAPI.H` is principally declarations and standard-library
  remapping. The required prebuilt `bsapi.lib`, `proghdr` object/library, and
  `sc180.lib` are not present in the local source or code trees. A modern C SDK
  must therefore implement compiler-specific API call shims; it cannot merely
  point a new compiler at the historical header.
- No `zcc`, z88dk assembler, SDCC, `sjasmplus`, `pasmo`, or equivalent modern
  Z80/Z180 tool is currently installed on this host.
- Current official z88dk documentation describes custom target configuration,
  a `--no-crt` path for a project-owned startup, Z180 support, explicit binary
  origins, and a combined assembler/linker. These capabilities make it a
  candidate modern backend, but no candidate has yet been installed or proven
  against the BNS ABI.
- The current worktree was already dirty before this task; `master` is one
  commit ahead of `origin/master`. Existing tracked and untracked work must be
  preserved. This task note must remain uncommitted.
- The user explicitly instructed that `ward` must never be used.

## Current state

The primary document now exists at `docs/external-bns-toolchain.md`. It records
the verified external-program format and runtime contract, distinguishes it
from firmware-update `.bns` packages, selects z88dk 2.4 as the first modern
backend to qualify, names the exact planned repository artifacts, defines six
ordered implementation phases with gates, and preserves the source-defined
physical YMODEM/launch procedure. No toolchain code has been implemented.

The document deliberately contains no fictional quick-start build command. It
states that the current repository can import and execute supplied programs but
cannot yet build a new one. The working note and documentation file are both
uncommitted; no pre-existing user file was modified.

Final review read the complete primary document. Both task files have no
trailing whitespace, and Git reports them as the only two paths created by this
task. The document now pins Tera Term 5.6.1 x64 and its publisher-provided hash
as the planned physical YMODEM authority, and it replaces unspecified
disassembly steps with exact generated-listing and opcode gates.

Execution resumed after the user correctly rejected documentation-only work as
proof. Phase 1 is in progress in one uncommitted source slice:

- `toolchain/z88dk.lock` pins the official v2.4 Windows asset, byte size
  `117797132`, and publisher digest
  `26d9880ee2e43077808ac86a4b6247a81f5dadc30563ca7cedc58bc4fb5ccb57`.
- `.gitignore` now excludes repository-local `.toolchain/` installations.
- `toolchain/setup-z88dk.ps1` parses the lock, refuses size or SHA-256
  mismatches, downloads to a partial file before promotion, and installs under
  `.toolchain/z88dk-2.4` without modifying global `PATH`.
- The first setup run passed the hash gate but correctly stopped because the
  archive contains both `z88dk/bin/zcc.exe` and `z88dk/bin.x86/zcc.exe`; the
  script's one-`zcc.exe` assumption was wrong.
- The script now selects the release's exact `z88dk/bin` layout. The corrected
  setup completed, and an immediate second run returned the existing install
  path without downloading or extracting again.
- The failed first extraction directory remains ignored under `.toolchain/`;
  it is not a tracked repository artifact and has not been deleted.
- Actual v2.4 help established the flags: `zcc -mz180`,
  `z88dk-zsdcc -mz180`, and `z88dk-z80asm -mz180`. The assembler uses `-h`
  for help; `--help` is an error. `zcc` reports version
  `v23854-4d530b6eb7-20251002`, and zsdcc reports `4.5.0 #15242`.
- Added `tests/fixtures/z180_mlt.asm` and an initial focused test invoking the
  installed assembler and requiring bytes `ED 4C`.
- The first focused run failed. The assembler returned success and reported a
  two-byte `code` section, but produced a zero-byte requested primary binary
  and a separate two-byte `*_code.bin`. The cause is the smoke fixture's
  explicit `section code`, not a missing Z180 encoding.
- A verbose diagnostic also created `tests/fixtures/z180_mlt.o`; this is a
  generated task artifact that must be removed before the Phase 1 slice is
  reviewed.
- The fixture has now been corrected to use the default output section. The
  test still needs to be changed to keep all assembler intermediates inside
  `tmp_path` before it is rerun.
- The test now copies the fixture into `tmp_path`; the corrected focused run
  passed and proved `MLT BC` emits exactly `ED 4C` without writing new
  intermediates beside the tracked fixture.
- The known generated `tests/fixtures/z180_mlt.o` and `.lis` were removed.
- `toolchain/setup-z88dk.ps1` now wraps extraction in a verified-path cleanup
  block so future failed archive-layout checks do not leave extraction trees.
  Its installed-state path still runs successfully after this change.
- The previously abandoned extraction tree was resolved to the intended
  `.toolchain` child, but host policy rejected its recursive removal. No
  alternate deletion was attempted. It remains ignored and does not affect
  the tracked slice.
- Archive size revalidation still reports `117797132`. The combined formatting
  command did not render the SHA value usefully, so the digest must be queried
  again plainly before the gate is recorded.
- The first scoped Ruff run failed only on import ordering in
  `tests/test_bns_external.py`. No source semantics failed. The trailing-
  whitespace scan returned no matches.

## Blocker

The historical Softools compiler/assembler/linker and its `sc180.lib`,
`bsapi.lib`, and CRC finalizer remain unavailable locally. The modern backend
and Z180 opcode gate now work, but Phase 1 cannot be closed until the import
lint failure is fixed, the archive digest is plainly rechecked, the primary
document is updated, and the kept slice is committed. No new `.bns` has been
built or run.

## Next action

Fix only the reported import order, rerun Ruff and the focused test, plainly
recheck the archive SHA-256, reread the plan after the passing test, update the
primary document with proven Phase 1 commands/results, review the exact slice,
and commit it before starting Phase 2.
## 2026-07-20 Phase 1 final gate checkpoint

- The pinned archive's live SHA-256 is exactly
  `26D9880EE2E43077808AC86A4B6247A81F5DADC30563CA7CEDC58BC4FB5CCB57`,
  matching `toolchain/z88dk.lock`.
- `uv run pytest tests/test_bns_external.py -v --basetemp=.toolchain/pytest-smoke`
  passed: the pinned Z180 assembler emitted `ED 4C` for `MLT BC`.
- The retained smoke output is
  `.toolchain/pytest-smoke/test_pinned_assembler_emits_z10/z180_mlt.bin`;
  the first hash lookup used the wrong pytest-generated directory and made no
  project change.
- The active plan was reread after the passing targeted test. Phase 1 remains
  the active slice; Phase 2 has not started.
- Current blocker: none. The exact smoke-output SHA-256 still needs to be read
  from the located binary.
- Next action: hash that exact binary, update the primary document with only
  proven Phase 1 facts, review and commit the exact Phase 1 paths, then verify
  the clean-checkout gate before beginning Phase 2.

## 2026-07-20 Phase 1 staged-slice checkpoint

- The exact smoke-output SHA-256 is
  `88506B69237CE638A5A69F79B7A97E82FA23C5A4137F25FC1170723AFFFAB3EC`.
- The primary document now records the pinned archive, locally reported tool
  versions, actual help flags, successful setup/test/lint commands, emitted
  `ED 4C` bytes, and both SHA-256 values. It explicitly says that no newly
  built external program has yet been packaged or run.
- Only these Phase 1 paths are staged: `.gitignore`,
  `docs/external-bns-toolchain.md`, `toolchain/z88dk.lock`,
  `toolchain/setup-z88dk.ps1`, `tests/fixtures/z180_mlt.asm`, and
  `tests/test_bns_external.py`. This notes file and all pre-existing user
  changes remain unstaged.
- `git diff --cached --check` passes. The staged audit found a mixed line
  ending on the neighboring `.gitignore` `build/` line; semantically the only
  intended change is adding `.toolchain/`.
- Current blocker: none. The `.gitignore` line-ending noise must be corrected
  before the Phase 1 commit.
- Next action: normalize only `.gitignore` formatting, restage it, rerun the
  staged audit and Phase 1 gates, commit the slice, then reproduce the gate
  from a clean checkout before starting Phase 2.

## 2026-07-20 Phase 1 pre-commit gate checkpoint

- `.gitignore` now has a clean staged semantic diff containing only the added
  `.toolchain/` rule; `git diff --cached --check` passes.
- The exact staged `toolchain/setup-z88dk.ps1` reran successfully and returned
  the existing repository-local install path.
- `uv run pytest tests/test_bns_external.py -v` passed again: one test passed
  and the Z180 `MLT BC` output remains exactly `ED 4C`.
- The task notes remain unstaged, and no pre-existing user path was added to
  the index.
- Current blocker: none.
- Next action: reread the active plan as required after the passing targeted
  test, run the focused Ruff gate, review the staged index once more, and
  commit Phase 1 before its clean-checkout reproduction.

## 2026-07-20 Phase 1 clean-checkout checkpoint

- Phase 1 was committed as `df45be17b8b89c42eaedc29276986af9ee6b7a25`
  with only its six intended paths.
- A detached clean worktree at that exact commit was created at
  `C:\Users\Q\code\qns-phase1-clean-df45be1` after confirming the path did
  not already exist.
- From that clean checkout, `toolchain/setup-z88dk.ps1` downloaded,
  checksum-verified, and installed the pinned archive into that worktree's own
  ignored `.toolchain` directory.
- From that clean checkout,
  `uv run pytest tests/test_bns_external.py -v --basetemp=.toolchain/pytest-smoke`
  created a fresh environment and passed.
- The clean-checkout smoke binary SHA-256 is exactly
  `88506B69237CE638A5A69F79B7A97E82FA23C5A4137F25FC1170723AFFFAB3EC`,
  matching the Phase 1 authority. The plan was reread after the passing test.
- Git and `Resolve-Path` both identify the temporary directory as the detached
  worktree at `df45be1`; no other path is in cleanup scope.
- Current blocker: none.
- Next action: remove that exact temporary worktree and its generated cache,
  update the primary document to record the passed clean-checkout gate, commit
  that record, reread the plan, and begin Phase 2 only after Phase 1 is closed.

## 2026-07-20 Phase 2 entry checkpoint

- The verified temporary clean worktree and only its generated cache were
  removed; the path no longer exists and Git lists only the main worktree.
- The clean-checkout gate record was committed as `a8d5f4a` after Phase 1's
  implementation commit `df45be1`. The active plan was reread after closure.
- Phase 2 is now the active phase. Its literal first task is `inspect`; `pack`,
  assembly, C, and integration work have not started.
- The branch is `master`, three commits ahead of `origin/master`. All listed
  tracked modifications and unrelated untracked paths are pre-existing user
  state and remain outside this task's index.
- The exact local fixtures exist at
  `roms/NFB99/BS2ENG/bsname.bns` and
  `roms/NFB99/BS2ENG/calsort.bns`.
- Current blocker: none.
- Next action: inspect the nearby CLI/test conventions and authoritative sample
  bytes, then implement only the Phase 2 `inspect` parser and its validation
  tests before any `pack` work.

## 2026-07-20 Phase 2 inspect checkpoint

- `tools/bns_external.py` now implements only `inspect`; no `pack` surface has
  been added yet.
- The source-backed stack check is logical `0x1000` or above. No stricter stack
  relationship was inferred from sample layout.
- The inspector checks the exact `JR 0x0e` entry, `BNS\0` identifier, minimum
  size, file-size invariant, nonzero/in-bounds code size, final `0xAA`, stack
  range, and firmware CRC over only the covered code.
- Tests cover a clean-checkout synthetic program, the exact `BSNAME.BNS` and
  `CALSORT.BNS` fields/CRCs, covered-code corruption, both header-bound cases,
  marker, stack, identifier, entry jump, and rejection of the actual local
  `bs2eng.bns` firmware-update package.
- `uv run pytest tests/test_bns_external.py -v` passed all 12 tests. It emitted
  one invalid-regex-escape warning; that test string has been changed to a raw
  string. The active plan was reread after the passing run.
- Current blocker: none.
- Next action: run the actual `inspect` CLI against both named supplied
  programs, rerun the warning-free focused suite and Ruff, then decide from
  those exact gates whether the inspect-only slice is ready to commit before
  beginning `pack`.

## 2026-07-20 Phase 2 inspect pre-commit checkpoint

- The actual CLI inspected `bsname.bns` as file size 25,108, code size
  `0x1AEF`, program length `0x6205`, CRC `0x6E8A`, stack `0x7213`.
- The actual CLI inspected `calsort.bns` as file size 17,092, code size
  `0x2EDE`, program length `0x42B5`, CRC `0x0F57`, stack `0x52C3`.
- The warning-free focused suite passes all 12 tests, and
  `uv run ruff check tools/bns_external.py tests/test_bns_external.py` passes.
  The plan was reread after the final passing targeted test.
- Only `tools/bns_external.py` and `tests/test_bns_external.py` are staged for
  the inspect slice. This notes file and all pre-existing user changes remain
  unstaged.
- Current blocker: none.
- Next action: run the staged whitespace/scope audit, commit the inspect-only
  slice, then verify branch/tracked state and begin Phase 2 `pack` from the
  committed inspector authority.

## 2026-07-20 Phase 2 pack entry checkpoint

- The inspect-only slice was committed as `74bf198`; Phase 2 `pack` is now the
  active task.
- Git remains on `master`, four commits ahead of `origin/master`. Pre-existing
  user changes remain unstaged.
- A probe built with the pinned `z88dk-z80asm -m` confirms the actual map-line
  form is `symbol = $hhhh ; metadata`, for example
  `__head = $0000 ; const, public, def, ...`.
- The probe used only ignored `.toolchain/pack-probe` artifacts and did not
  create a new source slice.
- Current blocker: none. The required four project symbols still need a real
  fixture so their public/global map form and logical values are tested.
- Next action: create the pack-image assembly fixture with the exact four
  required symbols, build its raw image/map using the pinned assembler, inspect
  those real artifacts, then implement `pack` against that proven map syntax.

## 2026-07-20 Phase 2 pack gate checkpoint

- `tests/fixtures/bns_pack_image.asm` exports exactly `__bns_entry`,
  `__bns_code_end`, `__bns_end_marker`, and `__bns_stack_top` at proven logical
  addresses in a real pinned-assembler map.
- `pack_external_program` parses those symbols, derives code size and program
  length, verifies the final marker and stack range, writes all four header
  words, computes the firmware CRC, and invokes the committed inspector on the
  result before returning it.
- The focused suite passes all 21 tests. Two separately assembled clean fixture
  builds pack to byte-identical outputs. The plan was reread after this pass.
- The actual public `pack` CLI emitted
  `.toolchain/pack-probe/bns_pack_image.bns`; the actual public `inspect` CLI
  validated it as file size 20, code size `0x0001`, program length `0x0005`,
  CRC `0x0000`, and stack `0x1013`.
- Current blocker: none.
- Next action: run Ruff, rerun the focused suite after any reported correction,
  update the primary document with the proven Phase 2 commands/results, review
  and commit the exact Phase 2 pack slice, then reread the plan before Phase 3.

## 2026-07-20 Phase 3 entry checkpoint

- The Phase 2 pack slice and primary-document update were committed as
  `f20309b`; the active plan was reread after the commit.
- Phase 3 is now active. Its gate is not compilation alone: the newly built
  assembly program must enter real firmware at `0x1000`, speak its unique
  phrase, exit, and leave a subsequent firmware key usable.
- Git is on `master`, five commits ahead of `origin/master`; all unrelated user
  modifications remain unstaged.
- The pinned z88dk installation confirms `.cfg` files are real `zcc` target
  configurations with keys such as `CRT0`, `OPTIONS`, `CLIB`, and `SUBTYPE`.
  `toolchain/bns.cfg` therefore cannot be a decorative response-file name.
- Current blocker: none. The minimal exact configuration and invocation still
  need to be proven from the pinned tool before source artifacts are written.
- Next action: inspect the smallest relevant pinned target configs and zcc's
  explicit custom-config/CRT controls, then create `toolchain/bns.cfg`,
  `sdk/bns_crt0.asm`, and `examples/hello-asm` only in the form actually
  consumed by the successful build command.

## 2026-07-20 Phase 3 first-build checkpoint

- `toolchain/bns.cfg`, `sdk/bns_crt0.asm`, and
  `examples/hello-asm/hello.asm` now exist as the active Phase 3 source slice.
- The startup exports all four pack symbols, has the 14-byte header at logical
  `0x1000`, enters at `0x100E`, allocates a 256-byte post-code stack, and exits
  through `RST 38h` API function zero.
- The example calls `API_SAY_WAIT` for `QNS ASSEMBLY HELLO` and returns to the
  startup.
- The first custom config used empty `CLIB none`/`SUBTYPE none` definitions;
  zcc rejected the empty subtype before compilation. It was corrected to the
  pinned configs' real `default` plus `-Cz+noop` form while retaining
  `-nostdlib`.
- The corrected config was genuinely consumed: zcc compiled the example,
  treated `sdk/bns_crt0.asm` as CRT, and reached the link step. Linking then
  failed because zcc invokes `z88dk-z80asm` by bare name and the pinned bin is
  intentionally not on global `PATH`.
- That failed run created generated `hello.asm.lis` and `hello.asm.sym` beside
  the source; they are untracked build artifacts and must not be committed.
- Current blocker: no functional blocker. The build command needs a
  process-local pinned-bin `PATH` prefix; global `PATH` must remain unchanged.
- Next action: rerun the same zcc target with only a process-local pinned-bin
  path prefix, inspect the linked map/listing/raw image, remove the two
  source-adjacent generated artifacts from the task slice, then pack and inspect
  the new program before attempting firmware execution.

## 2026-07-20 Phase 3 built-program checkpoint

- After removing only the three verified generated listing/symbol artifacts,
  the same zcc custom-target build succeeded with the pinned bin directory
  added only to that PowerShell process's `PATH`.
- The linked map proves `__bns_entry=0x100E`, `__bns_code_end=0x1032`, and
  `__bns_stack_top=__bns_end_marker=0x1132`. The generated listings contain the
  `API_SAY_WAIT` and `API_EXIT` `RST 38h` opcodes.
- z88dk emitted the nonempty contiguous linked image as
  `.toolchain/build/hello-asm/hello-asm_bns_header.bin`; its default-section
  `hello-asm.bin` is empty. The symbol-driven packer used the nonempty image.
- The newly built `.toolchain/build/hello-asm/hello-asm.bns` passes inspection:
  file size 307, code size `0x0024`, program length `0x0124`, CRC `0xA443`,
  stack `0x1132`.
- The existing verifier CLI has no expected-marker option. Its non-stdio path
  stops after proving entry at `0x1000`; its stdio path continues and prints
  captured phonemes, but for an unknown filename it does not require speech or
  a post-exit firmware key.
- Current blocker: none for an observational first run. The full Phase 3 gate
  cannot be claimed from entry-only evidence.
- Next action: run the newly built program through the real-ROM stdio path with
  a disposable state, inspect its actual speech/return behavior, then add only
  the exact assertion surface required to prove the unique marker and a
  subsequent firmware key if the observation succeeds.

## 2026-07-20 Phase 3 first firmware-entry checkpoint

- The real BS2ENG stdio path imported the newly built 307-byte
  `hello-asm.bns`, completed both serial probes and YMODEM, and observed entry
  at cycle 148,496,110 with `PC=0x1000` and header-derived `CBAR=0x21`.
- This does not yet prove the example ran. For an unknown filename,
  `execute_selected_stdio_program` returns immediately on the `PC=0x1000`
  watch; the process then closes. The printed phonemes are therefore pre-entry
  firmware speech and contain no authority for `QNS ASSEMBLY HELLO`.
- The active plan has a causal ordering defect: the Phase 3 speech/return/key
  gate depends on the explicit marker and return-proof verifier surface that it
  schedules only in Phase 5.
- Current blocker: the Phase 3 gate cannot be executed literally until that
  prerequisite is moved into Phase 3's ordered tasks. Entry-only evidence is
  not a substitute.
- Next action: correct the primary plan's ordering so Phase 3 explicitly adds
  the required expected-speech and post-exit-key assertions before its gate;
  keep Phase 5 for clean-checkout/repeatability hardening. Then implement only
  that corrected Phase 3 verifier surface and rerun the newly built program.

## 2026-07-20 Phase 3 return-proof implementation checkpoint

- The primary plan now places the explicit expected-phoneme and post-exit
  E-chord acceptance prerequisite in Phase 3. Phase 5 retains clean integration
  hardening instead of introducing this dependency after its first use.
- The example phrase is now `QNS ASSEMBLY DONE`; the source-backed final marker
  is `D UH1 N`. The first marker run will reveal whether the complete phrase
  matches and will not by itself justify a broader marker claim.
- `tools/verify_bs2_external_program.py` now accepts `--expected-speech` on its
  stdio path. When present, it requires the exact suffix after entry, then sends
  E-chord and requires the existing exact keyboard accepted/ready events.
- Built-in supplied-program marker behavior remains unchanged unless the new
  explicit option is provided.
- Current blocker: none. This change has not yet been tested, and the modified
  example has not yet been rebuilt or run.
- Next action: add the focused verifier unit authority, run its tests and Ruff,
  rebuild/repack/reinspect the changed example, then execute the full real-ROM
  command with `--expected-speech D UH1 N` and require the return-key line.

## 2026-07-20 Phase 3 rebuilt marker checkpoint

- The verifier-focused suite now passes all 27 tests after correcting only a
  missing `E_CHORD` test import. Ruff passes for the verifier and its test. The
  active plan was reread after the passing suite.
- Only the verified generated outputs were removed before rebuilding so zcc
  could not append to stale listings or reuse stale link products.
- The process-local-path zcc command rebuilt `QNS ASSEMBLY DONE`; the
  symbol-driven packer emitted a 306-byte `.bns` that inspects as code size
  `0x0023`, program length `0x0123`, CRC `0x50DB`, stack `0x1131`.
- Current blocker: none. Real firmware has not yet confirmed the new phrase or
  post-exit key.
- Next action: use a new disposable state path and run the exact stdio verifier
  with `--expected-speech D UH1 N`. Count it only if it reports entry and the
  explicit `return-key: E-chord accepted and firmware ready` line.

## 2026-07-20 Phase 3 marker-run retry authority

- The first marker-gated run timed out during fresh-state firmware
  initialization, before program import or entry. It provided no evidence for
  or against the built program.
- The user explicitly said `keep going yes`, authorizing continuation and an
  exact rerun of the blank-state gate.
- Current blocker: none.
- Next action: rerun the same real-ROM stdio command with the same nonexistent
  disposable state path and require both the expected `D UH1 N` marker and the
  explicit post-exit E-chord acceptance line.

## 2026-07-20 fresh-state initialization investigation

- The authorized exact rerun timed out at the same pre-import boundary. The
  generated program was neither imported nor launched.
- The final captured speech ends with the exact
  `FLASH_INITIALIZATION_PROMPT`, so the prompt constant is correct and the
  firmware is waiting for its initialization response.
- `reach_stdio_editor_command_loop` currently treats a keyboard `ready` event
  observed before the complete speech suffix as proof that initialization is
  finished. It returns, after which the O-chord/F inputs arrive while firmware
  is still waiting for initialization confirmation.
- The direct-harness startup path does not make this inference: it validates
  the initialization prompt and explicitly completes the required response and
  confirmation transitions.
- Current best theory: the stdio startup helper races speech completion against
  the keyboard-ready event. The repeated exact prompt tail rules out an
  incorrect prompt constant and a transient timeout.
- Current blocker: the helper has no unit authority for a `ready` event that
  precedes the completed initialization speech.
- Next action: add one focused failing test that presents `ready` before the
  prompt completes and requires the helper to wait for the exact prompt before
  responding. Then make the smallest helper correction and rerun that focused
  test.

## 2026-07-20 fresh-state event-order fix checkpoint

- The focused regression test fails against the old helper at its separate
  `wait_for_keyboard` sequence, before it can observe speech that completes
  after `ready`. This reproduces the control-flow defect without running the
  external program.
- The existing stdio helper now arms the source-backed editor-loop PC watch at
  `0xD657`, sends the existing power-on initialization chord itself, and uses
  one event-state predicate to retain accepted, ready, exact new prompt speech,
  and the command-loop watch regardless of arrival order.
- No delay, retry, alternate state file, or new public helper was added.
- The external-program caller and dictionary caller no longer send the chord
  before invoking the shared helper. The help caller still has the old send and
  must be corrected before tests.
- Current blocker: implementation is incomplete until the final shared-helper
  caller is updated and the focused test passes.
- Next action: remove the duplicate send/import from the help caller, rerun the
  focused regression test, then run the affected verifier suites and Ruff.

## 2026-07-20 power-on first-event correction

- All 32 affected verifier/help/dictionary tests passed, and Ruff passed for
  all six changed Python files.
- The real fresh-state rerun failed before speech or import because
  `--power-on-input` requires the first JSONL input event to be a keyboard
  event. The helper armed the PC watch first, so the emulator exited with
  `RuntimeError: power-on input requires a keyboard JSONL event`.
- This failure does not test the generated program or the original delayed-
  prompt fix. It identifies an exact startup contract missing from the focused
  test.
- Current best correction: send the power-on keyboard event first, enqueue the
  CPU watch event second without a separate acknowledgment wait, and retain
  watch acknowledgment, chord acceptance, ready, prompt speech, and PC hit in
  the same state predicate. This preserves the first-event contract and avoids
  discarding any causal event.
- Current blocker: the regression test does not yet require the keyboard event
  to precede the watch request.
- Next action: revise the focused test to require that exact outbound order,
  confirm it fails against the current implementation, then update the helper
  and rerun the focused and affected suites before another real-ROM attempt.

## 2026-07-20 fresh-state fixed, transfer-ready race exposed

- The revised focused test now requires keyboard I-chord as the first JSONL
  event and the CPU watch request second. It failed against the watch-first
  implementation, then passed after the helper was corrected.
- All 32 affected tests and Ruff passed after the correction.
- The real fresh-state run advanced past every earlier initialization failure,
  reached `Enter file command`, entered the transfer menu, and spoke the
  `send or receive` prompt. This proves the fresh-state initialization defect
  is fixed.
- The run then timed out in `receive_stdio_file` waiting for keyboard `ready`
  after the serial probe responses. The speech tail had already reached the
  transfer choice prompt. No YMODEM payload was sent, and the generated program
  was not imported or launched.
- Current best theory: `receive_stdio_file` performs serial waits before its
  separate keyboard-ready wait; those serial waits consume the earlier ready
  event, reproducing the same unmatched-event loss at the next workflow
  boundary.
- Current blocker: the transfer helper has no event-order test in which ready
  precedes completion of the ASCI probe sequence.
- Next action: inspect the exact transfer helper sequence and existing test,
  add a focused failing event-order case for ready-before-serial completion,
  then retain both authorities in one wait before another real-ROM attempt.

## 2026-07-20 YMODEM complete, post-import ready race

- The transfer-order test was revised to emit keyboard `ready` before the ASCI1
  probe completed. It failed against the separate waits, then passed after
  `receive_stdio_file` retained T-chord acceptance, ready, and ASCI1 ENQ in one
  predicate while preserving the required ASCI1-NAK-before-ASCI0 ordering.
- All 32 affected tests and Ruff passed after that correction.
- The next real fresh-state run completed the serial probes and YMODEM
  transfer. Its speech tail says `transfer complete` followed by the exact
  `Enter file command` prompt.
- The run then timed out at the final `wait_for_keyboard("ready")` in
  `receive_stdio_file`. The preceding speech-suffix wait consumed the ready
  event that arrived before the prompt speech completed. The program was
  imported but was not selected or launched.
- Current best theory is now confirmed at both pre-transfer and post-import
  boundaries: separate waits discard unmatched causal events.
- Current blocker: the transfer test does not yet order post-import `ready`
  before completion of `FILE_COMMAND_PROMPT`.
- Next action: extend the existing focused transfer test with that exact
  post-import ordering, confirm failure, then replace the separate suffix/ready
  waits with one retained predicate before rerunning the real gate.

## 2026-07-20 post-import boundary must be inside YMODEM

- The extended transfer test failed against the separate post-import waits and
  passed after they were joined in `receive_stdio_file`. All 32 affected tests
  and Ruff passed.
- The real run still timed out with the same completed-transfer/file-command
  speech tail. This proves the joined wait began too late: the earlier final
  serial-ACK wait inside `transfer_stdio_ymodem` had already consumed keyboard
  `ready`.
- The final empty-batch ACK is causally adjacent to firmware transfer
  completion. It is the first boundary that can retain the ACK, post-import
  ready, and new `FILE_COMMAND_PROMPT` together without a timing guess.
- The program was imported again but was not selected or launched.
- Current blocker: no focused authority yet orders post-import `ready` before
  the new prompt while the final empty-batch ACK is also pending.
- Next action: add that exact final-YMODEM event-order test, confirm failure,
  then move the joined ACK/ready/prompt predicate into the final YMODEM wait and
  remove the now-too-late wait from `receive_stdio_file`.

## 2026-07-20 final YMODEM boundary ready for live gate

- A focused one-block YMODEM test now orders post-import keyboard `ready`, the
  final empty-batch ACK, and the new `FILE_COMMAND_PROMPT` separately. It failed
  at the old final `wait_for_serial` exactly as predicted.
- `transfer_stdio_ymodem` now records its speech cursor at transfer start and
  retains final ACK, ready, and the new prompt in one final predicate.
  `receive_stdio_file` no longer performs the proven-too-late post-transfer
  wait.
- Both focused transfer tests pass. All 33 affected verifier/help/dictionary
  tests pass, and Ruff passes on all six changed Python files.
- The exact disposable state path is absent, so the next real run remains a
  fresh-state authority.
- Current blocker: none before the real gate. The generated program has still
  not been launched in a marker-gated run.
- Next action: rerun the exact fresh-state command with
  `--expected-speech D UH1 N` and require import, `PC=0x1000`, the speech
  marker, and post-exit E-chord accepted/ready output.

## 2026-07-20 ready must survive the entire YMODEM protocol

- The real run again completed transfer and the file-command prompt but timed
  out in the joined final ACK/ready/prompt predicate because it never observed
  `ready`.
- This proves `ready` is emitted before the final empty-batch wait and consumed
  by one of the earlier `wait_for_serial` calls. The most likely causal point is
  the ready event following Y-chord, before or during the initial CRC request.
- The final ACK and prompt authorities are correct; only the lifetime of the
  retained ready state is too short.
- The generated program was imported but still was not selected or launched.
- Current blocker: the focused YMODEM test emits ready only at the final wait,
  so it does not cover ready arriving during an earlier serial phase.
- Next action: revise that test so ready arrives during the initial YMODEM
  serial wait and must survive through the final ACK/prompt. Then replace the
  transfer's independent serial waits with transfer-local waits that carry the
  same ready state through the entire protocol.

## 2026-07-20 first successful generated-program run

- The transfer-wide ordering test failed at the first independent serial wait,
  then passed after all YMODEM serial phases began carrying one retained
  keyboard-ready state through the final ACK/prompt gate.
- All 33 affected verifier/help/dictionary tests pass and Ruff passes.
- The exact fresh-state marker command completed successfully with exit code
  zero. It reported:
  - `imported: hello-asm.bns (306 bytes)`
  - `entry: cycle=148380600 pc=1000 cbar=21`
  - `return-key: E-chord accepted and firmware ready`
  - `serial: ASCI1 ENQ/NAK; ASCI0 ENQ/NAK; YMODEM complete`
- The captured program suffix is
  `K YI U U EH1 N EH1 S UH1 S EH M B L E1 D UH1 N`, the full observed
  phoneme sequence for `QNS ASSEMBLY DONE`. The successful command required
  only the previously source-backed suffix `D UH1 N`, so the output proves the
  full phrase observationally but the repeatable gate does not yet require it.
- Current blocker: none.
- Next action: promote the full observed sequence to the explicit expected
  marker, rerun the same fresh-state command with that full marker, then record
  the structural/runtime evidence in the primary document and finish the
  Phase 3 test/commit gate.

## 2026-07-20 full-phrase Phase 3 runtime authority

- A second fresh-state run required the complete observed marker
  `K YI U U EH1 N EH1 S UH1 S EH M B L E1 D UH1 N`.
- It passed with exit code zero and reported:
  - `imported: hello-asm.bns (306 bytes)`
  - `entry: cycle=148381600 pc=1000 cbar=21`
  - `return-key: E-chord accepted and firmware ready`
  - `serial: ASCI1 ENQ/NAK; ASCI0 ENQ/NAK; YMODEM complete`
- This is the first repeatable proof that the newly assembled/packed program
  enters through unmodified BS2 firmware, speaks the entire expected phrase,
  exits, and returns control to firmware keyboard handling.
- Current blocker: none for Phase 3 runtime behavior.
- Next action: update the primary document with exact build/inspect/runtime
  commands and evidence, add/confirm the structural build/listing authority,
  run the complete Phase 3 tests and Ruff, clean generated source-adjacent
  artifacts, stage only Phase 3 paths, and commit the kept slice before Phase 4.

## 2026-07-20 documented rebuild and requested reusable harness

- The exact PowerShell commands now in `docs/external-bns-toolchain.md` ran in
  order and rebuilt the assembly example inside `.toolchain/build/hello-asm`.
- Inspection reproduced a 306-byte file, code size `0x0023`, program length
  `0x0123`, CRC `0x50db`, and stack `0x1131`.
- The full-marker real-ROM command then ran that rebuilt artifact successfully:
  import completed, entry was observed at `PC=0x1000`, the complete
  `QNS ASSEMBLY DONE` phoneme marker matched, and post-exit E-chord handling
  was accepted and ready.
- The user explicitly requested that file transfer, program execution, speech
  assertions, and related runtime operations become reusable harness helpers.
  This authorizes a helper extraction that the earlier plan did not name.
- Current blocker: none.
- Next action: run the complete Phase 3 tests and Ruff, stage and commit only
  the Phase 3 slice, then add the reusable-harness slice to the primary plan
  and implement it as a separate Git-accountable change before Phase 4.

## 2026-07-20 reusable-harness ownership inspection

- Phase 3 is committed as `85d47f7` after the documented rebuild, full-marker
  firmware run, 55-test gate, and Ruff gate passed.
- `tools/stdio_process.py::BNSStdioProcess` already owns the low-level bounded
  JSONL subprocess, event history, keyboard/serial writes, and primitive waits.
- The reusable BS2 workflow operations currently live in
  `tools/verify_bs2_external_program.py`: startup initialization, accepted
  chord delivery, file-menu YMODEM receipt, program selection/execution,
  speech assertion, and post-exit input proof.
- `tools/verify_bs2_help.py` and `tools/verify_bs2_dictionary.py` already import
  those operations from the external-program CLI, demonstrating that workflow
  ownership is misplaced in a verifier entrypoint.
- The requested slice can change that ownership decision by moving the proven
  workflow operations into one reusable BS2 stdio harness artifact while
  retaining `BNSStdioProcess` as its transport and migrating all three callers.
- Current blocker: the primary plan does not yet name the new artifact, exact
  operations, migration, or runtime gate.
- Next action: add an executable reusable-harness phase before the C SDK in
  `docs/external-bns-toolchain.md`, then test-drive the ownership move and
  rerun the full-marker real-ROM program through the migrated harness.

## 2026-07-20 reusable-harness extraction in progress

- The primary plan now has an exact Phase 4 artifact, migration list, focused
  test owner, and real-ROM gate. The former C SDK and later phases were
  renumbered; the C gate was corrected to require QNS before the later physical
  hardware phase so the plan is causally executable.
- `tools/bs2_stdio_harness.py` now owns the moved workflow implementation:
  protocol constants, CRC/YMODEM packets, accepted chords, first-boot startup,
  complete file-menu transfer, selected-program entry/speech, and post-exit
  input proof.
- The corresponding definitions were deleted from
  `tools/verify_bs2_external_program.py`; the external verifier now consumes
  the moved owner, and help/dictionary imports were migrated directly.
- `tests/test_bs2_stdio_harness.py` now contains direct focused authorities for
  startup event retention, transfer ordering, execution/return, CRC, and
  YMODEM packets.
- Removal of the old copies of the transfer-focused tests is incomplete. One
  deletion patch failed because the exact lambda parameter text differed from
  the inspected diff; no file content was changed by that failed patch.
- Current blocker: none; the exact current old-test text is now known.
- Next action: finish deleting the moved tests/imports from
  `tests/test_bs2_external_program.py`, migrate verifier-suite monkeypatch
  targets to the new owner where required, then run focused tests and Ruff.

## 2026-07-20 reusable ownership and migrated-suite gate

- All moved test copies and imports were removed from the external-program
  test module. The new harness test module is the direct owner of eight
  startup, transfer, execution, CRC, and packet tests.
- The exact full-marker real-ROM command passed once through the extracted
  implementation, reporting the 306-byte import, `PC=0x1000`/`CBAR=0x21`, the
  complete expected phoneme marker, and accepted/ready E-chord after exit.
- To satisfy the plan's no-re-export boundary literally, the external verifier
  now imports the harness module as one namespace and qualifies every moved
  constant/helper; the old helper names are no longer module attributes.
- That stricter ownership initially exposed two stale test imports of
  `E_CHORD`, `FILE_COMMAND_PROMPT`, and `Y_KEY` from the old owner. They were
  migrated directly to `tools.bs2_stdio_harness`.
- The four focused/migrated suites now pass again: 33 tests.
- Current blocker: none.
- Next action: document direct harness reuse and mark Phase 4 complete only
  after Ruff and the exact full-marker real-ROM command pass against the final
  namespace-qualified caller, then reconcile and commit this slice.

## 2026-07-20 reusable harness Phase 4 complete

- Ruff passed on the harness, all three migrated verifiers, and their four
  focused test modules.
- The exact final full-marker real-ROM command passed with the namespace-only
  owner boundary. It reported the 306-byte import, entry at cycle 148379600
  with `PC=0x1000` and `CBAR=0x21`, accepted/ready post-exit E-chord, completed
  serial/YMODEM path, and the full `QNS ASSEMBLY DONE` phoneme marker.
- The primary guide now documents the transport/helper layering, every public
  reusable operation and precondition, the retained-event warning, and Phase 4
  as complete. Phases 5 through 7 remain unchecked.
- Unrelated tracked changes appeared concurrently in `qns/bns.py`,
  `qns/cli.py`, `qns/memory.py`, `tests/test_bns.py`, `tests/test_memory.py`,
  and other pre-existing user paths. They are outside this slice and must not
  be staged.
- Current blocker: none.
- Next action: stage only the Phase 4 document, harness, migrated verifiers,
  and migrated tests; verify the cached diff; commit the kept slice; reread the
  plan and begin Phase 5 from its first unchecked calling-convention task.

## 2026-07-20 Phase 5 calling-convention probe started

- Phase 4 is committed as `2c43f9d`. The worktree after that commit contains
  only unrelated user changes and untracked research.
- The Phase 5 first task is active: confirm the selected compiler's real ABI
  from generated assembly before writing API shims.
- `zcc +toolchain/bns.cfg -specs` confirms the repository target still uses
  `sdk\\bns_crt0`, `-mz180`, and `-nostdlib` and exposes both compiler binaries.
- A disposable C probe under `.toolchain/build/calling-convention` declares
  `bns_say_wait(const char *)` and `bns_exit()` and calls both.
- The verbose `zcc +toolchain/bns.cfg -S` run proves the target's current
  default compiler is `z88dk-sccz80`; its preprocessor defines include
  `SCCZ80`, `SMALL_C`, and `__SCCZ80`.
- Current blocker: the generated call sequence has not yet been inspected, so
  argument order, stack cleanup, symbol spelling, and return preservation are
  not yet confirmed.
- Next action: read the generated probe assembly, record those exact ABI facts,
  then create wrapper/listing tests before implementing `bns_exit()` and
  `bns_say_wait()`.

## 2026-07-20 Phase 5 measured ABI and first C build

- The generated one-argument probe places the pointer at caller `SP+2`, emits
  `push hl; call _bns_say_wait; pop bc`, and therefore requires the wrapper to
  preserve both the return address and the argument for caller cleanup.
- A second generated probe proves C `main` is `_main`; with
  `--codeseg=bns_code --constseg=bns_code`, both code and the string literal
  are emitted in `bns_code` and therefore precede `__bns_code_end`.
- `sdk/include/bns_api.h` now has 16-bit pointer/integer compile-time asserts
  and the measured Small-C prototype. `sdk/bns_api.asm` now implements
  `_bns_say_wait` with stack restoration and `_bns_exit`, both through
  `RST 38h`.
- `sdk/bns_crt0.asm` now calls the compiler's `_main` symbol; the assembly
  example was migrated to export that same entry symbol. The new C example
  says `QNS C DONE` and returns through crt0.
- A focused build authority compiles the real C example, inspects the generated
  caller sequence, links both wrappers, packs the result from link symbols,
  and checks three `RST 38h` instructions. It initially failed on the missing
  example and now passes after the SDK implementation.
- Current blocker: the exact packed header values and real-ROM speech marker
  for the C build are not yet recorded, so Phase 5's structural and runtime
  gates are not complete.
- Next action: perform the clean documented C build under
  `.toolchain/build/hello-c`, inspect its exact map/header/listings, strengthen
  the test with those facts, then run the assembly regression and the C
  full-marker real-ROM gate.

## 2026-07-20 C SDK real-ROM authority

- The clean repository-local C build produced `hello-c.bns` at exactly 317
  bytes with code size `0x002e`, program length `0x012e`, CRC `0xc03f`, and
  stack `0x113c`. Its map places `_main=0x1018`, `_bns_exit=0x102f`,
  `_bns_say_wait=0x1034`, and `__bns_code_end=0x103c`.
- The generated C listing contains the measured `push hl; call
  _bns_say_wait; pop bc` sequence and the string `QNS C DONE`. The wrapper
  listing proves `pop de; pop hl; push hl; push de` restores the caller-owned
  stack before API 2, and the linked listings contain three `RST 38h` calls.
- All 23 format/build tests pass, including the assembly regression after crt0
  moved to the compiler's `_main` symbol.
- The first real-ROM C run required the known `D UH1 N` suffix and exposed the
  complete program marker `K YI U U EH1 N EH1 S S E D UH1 N`.
- A second fresh-state run required that complete marker and passed: the exact
  317-byte C output imported, entered at cycle 147339242 with `PC=0x1000` and
  `CBAR=0x21`, spoke `QNS C DONE`, returned through crt0, and the firmware
  accepted and became ready after E-chord.
- Current blocker: none for Phase 5.
- Next action: add the exact successful C build/inspect/run commands and ABI
  evidence to the primary guide, mark Phase 5 complete, run Ruff and the full
  affected test gate, then commit this kept slice before Phase 6.

## 2026-07-20 Phase 5 committed; Phase 6 active

- The primary guide now contains the exact successful C build, pack, inspect,
  ABI, and full-marker runtime commands. Phase 5 is marked complete.
- Ruff passes, all 23 format/build tests pass, and the final focused C build
  authority passes after its caller-symbol assertion was made explicit.
- Phase 5 is committed as `3e3c588`; no unrelated user paths were staged.
- Phase 6 does not require a new runtime implementation: the shipped verifier
  already accepts arbitrary programs, explicit phoneme markers, disposable
  state paths, stdio process execution, program-derived CBAR checks, and
  post-exit firmware input proof. Its remaining decision-changing gate is to
  prove both examples from their final Phase 5 sources and record those exact
  commands together in the Phase 6 section.
- Current blocker: none.
- Next action: rebuild the assembly example from its final `_main` source,
  re-run its exact full-marker real-ROM command, retain the already-final C
  proof, then update the Phase 6 section as the repeatable two-example gate and
  commit the documentation slice before physical-hardware validation.

## 2026-07-20 Phase 6 two-example integration authority

- The exact documented assembly commands rebuilt the final `_main` source and
  reproduced 306 bytes, code size `0x0023`, program length `0x0123`, CRC
  `0x50db`, and stack `0x1131`.
- The rebuilt final assembly artifact passed its complete-marker fresh-state
  real-ROM run: import, `PC=0x1000`/`CBAR=0x21`, full `QNS ASSEMBLY DONE`
  speech, crt0 exit, and accepted/ready post-exit E-chord.
- The final C artifact already passed the parallel exact command after its
  Phase 5 build. Both examples therefore use the same arbitrary-program CLI,
  disposable state paths, unmodified firmware transfer/launch path, explicit
  marker, header-derived CBAR, and post-exit return proof.
- Current blocker: none for Phase 6.
- Next action: copy both proven commands into the Phase 6 section, mark it
  complete, update the current status/quick-start wording, verify the docs-only
  diff, and commit before starting the physical-hardware phase.

## 2026-07-20 Phase 7 portable transfer preparation

- Phase 6 is committed as `84c5bcc`; the guide contains both final integration
  commands and marks the two-example QNS gate complete.
- The official GitHub release API for tag `v5.6.1` confirms the exact portable
  asset URL, byte size 16,140,346, and SHA-256
  `4cd4a75dc6614c7be8e19955fadadd4ceb0fc4c7ad4475913e2deecb37cbc656`.
- The research skill's normal launch path could not be used because it
  conflicts with the explicit no-delegation and standing tool prohibition; a
  narrow official-source verification was used instead.
- The Phase 7 plan now explicitly creates and validates the previously planned
  lock/setup artifacts before a physical run.
- `toolchain/teraterm.lock` contains the official facts.
  `toolchain/setup-teraterm.ps1` follows the proven repository-local installer
  contract: verified partial download, verified cached archive, isolated
  extraction, exactly one `ttermpro.exe`, path-contained move/cleanup, no
  global install or PATH change, and an idempotent executable-path output.
- Current blocker: the setup script has not yet run, so archive structure and
  the twice-identical output gate remain unverified.
- Next action: run `toolchain/setup-teraterm.ps1` twice exactly, require the
  same executable path and inspect that repository-local file, then add
  installer tests/documentation before the physical-unit information blocker.

## 2026-07-20 Phase 7 portable setup authority

- The setup script ran twice and both runs returned the exact same path:
  `C:\Users\Q\code\qns\.toolchain\teraterm-5.6.1-x64\ttermpro.exe`.
- The installed executable is 1,905,464 bytes and reports product version
  `5.6.1 643bd0e`. The cached archive is exactly 16,140,346 bytes with the
  locked SHA-256
  `4cd4a75dc6614c7be8e19955fadadd4ceb0fc4c7ad4475913e2deecb37cbc656`.
- The lock-content test and the same-size corrupt-archive rejection test pass.
  All 25 external-toolchain tests pass, and Ruff passes for that test module.
- The guide now records the exact repository-local path, version, archive
  facts, and executable setup command. It does not claim a physical run.
- Current blocker: physical validation requires the unit model, firmware
  revision, available RAM, COM port and serial settings, and confirmation of a
  current backup before loading the assembly example into RAM.
- Next action: commit this bounded Phase 7 preparation slice, then obtain that
  exact hardware record before attempting the documented physical transfer.

## 2026-07-20 Phase 7 preparation committed

- The repository-local portable-transfer preparation is committed as
  `9bc1810`; only the guide, setup tests, lock, and setup script were staged.
- The checkpoint notes and all unrelated user changes remain uncommitted.
- Current blocker and next action are unchanged: obtain the exact physical-unit
  record and backup confirmation before opening the serial transfer session.
