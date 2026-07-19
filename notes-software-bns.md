# Software-only BNS implementation handoff

## Objective

Make the supplied `.bns` ROMs operate as a working software-only BNS, using standard input/output for human interaction and software audio for SSI-263 speech.

## Current state (2026-07-18)

- Active branch: `master`.
- The worktree already contains user-owned tracked edits in `CLAUDE.md`, `qns/ssi263.py`, `qns/synth/__init__.py`, and `qns/synth/ssi263_synth.py`, plus many untracked research/assets. Preserve them.
- `qns/bns.py`, `qns/io.py`, `qns/memory.py`, `qns/cpu.py`, and the existing tests are clean at the start of this implementation.
- The Z180 CFFI core boots and executes the BSP English firmware. `.bns` update packages are detected and firmware is extracted from offset `0x3000`; up to four 64 KiB banks are loaded.
- The current runtime hardcodes a BSPLUS-style hardware map. Other supplied variants use different keyboard, speech, display, status, power, watchdog, and storage ports.
- `BrailleKeyboard.press()` can assert INT2, but the run loop and CLI never feed it input.
- `BrailleDisplay` is a placeholder and is registered over `0x80..0x83`; the separately constructed watchdog is never registered. This needs reconciliation against the selected BSP hardware model.
- The Z180 core's ASCI callbacks currently return no input and discard output.
- RTC, status/power behavior, persistent RAM/storage, and auxiliary `.hlp`/`.dic`/`.msg`/`.ima` assets are not integrated.
- The only test module is synth-focused; there is no CPU/peripheral/full-system authority.
- The current SSI-263 sound path is not authentic. Die/ROM recovery is a separate required workstream, but firmware-facing SSI-263 registers and interrupts must remain literal.

## Controlling implementation sequence

1. Establish the BSPENG boot, keyboard, display, serial, and idle-state contract from the ROM and original source.
2. Implement and verify end-to-end stdio interaction through those real firmware paths.
3. Complete BSPENG memory, interrupts, timers, status/power, RTC, and persistent state.
4. Recover and integrate software SSI-263 synthesis.
5. Add one hardware profile at a time for the remaining supplied variants.
6. Audit complete interactive and persistence workflows.

## Current blocker

No external blocker. Before editing, determine the exact BSPENG keyboard event encoding and observable output path; do not invent a terminal protocol that bypasses firmware behavior.

## Next action

Trace the BSPENG keyboard ISR and output routines against `BSPORTS.LIB`, then exercise `BrailleKeyboard.press()` against the running ROM to identify the first deterministic interactive transaction.

## Progress: BSP keyboard hardware contract

- `BSP.INC` defaults to the `BSPLUS` build used by BSP English.
- The normal BNS `USRIN` ISR treats the initial key-down interrupt as provisional. It accepts and queues a chord on the later all-keys-up interrupt.
- On key-up, the hardware data latch must still expose the completed chord on the ISR's first `UIPORT` read. Reading `KEYCLR` then acknowledges the interrupt and allows subsequent `UIPORT` reads to return zero.
- The existing `BrailleKeyboard.release()` erased the chord and raised no interrupt, so the firmware could never receive a completed key through that model.
- Added device tests for held-key visibility across acknowledgement and release-latch behavior. The release test failed against the old implementation and both tests pass with the corrected latch/edge state.
- `qns/io.py` and `tests/test_io.py` are the only source/test paths in this slice. Ruff reformatted `qns/io.py` to LF while the tracked file uses CRLF; this is a mechanical diff still to be normalized before commit.

## Immediate next action

Restore `qns/io.py` to its tracked CRLF convention with `unix2dos`, rerun the focused tests and static checks, commit this isolated slice, then drive one chord through the running BSP ROM.

## Kept slice: keyboard release latch

- Commit `59ac120` (`Model BNS keyboard release latch`) contains only `qns/io.py` and `tests/test_io.py`.
- Verification: both focused keyboard tests pass and Ruff passes on the committed paths.

## Progress: stdio input through firmware

- The regular English `_table` in `BSTABLES.ASM` is the ROM authority for ASCII-to-raw-key conversion. It defines raw chords for ASCII 0-127, with bit 6 for uppercase and bit 7 for control characters.
- Firmware `GETKEYS` treats physical raw `0x40` as space before converting it to table code zero. Terminal newline is being treated as the firmware's carriage-return chord `0x8D`.
- In-progress `qns/bns.py` changes add the exact English table and a stdin reader. Characters are not injected until the Z180 ITC shows INT2 enabled.
- Each character uses the hardware handshake instead of a fixed delay: assert key-down, wait for firmware `KEYCLR` acknowledgement, assert key-up, wait for the second acknowledgement, then accept the next character.
- The BSP target has no Braille display on port `0x80`; that port is watchdog on read and speech-power on write. The current placeholder display registration is wrong and remains to be removed in a separate kept slice after stdio input is proven.
- Current Ruff output on `qns/bns.py` includes an import-order issue caused by the new imports plus three pre-existing style findings (extraneous f-string and two long lines). These must be reconciled before committing the stdio slice.

## Immediate next action

Add focused mapping tests, run a piped character through the real BSP ROM with a finite cycle bound, and keep the stdio slice only if the ROM acknowledges both edges and produces a downstream observable response.

## Stdio runtime gate result

- Mapping tests pass for lowercase, uppercase, digits, physical space, terminal newline/carriage return, and delete.
- An 80,000,000-cycle BSP run with stdin `a` plus newline showed both key-down and key-up INT2 edges acknowledged for both characters.
- That is **not** a valid success: the input run ended with 35 phonemes, `BBR=0x00`, and PC `0x0B1C`, while the no-input baseline produced 1,342 phonemes, `BBR=0x1E`, and PC `0x5772`.
- The cause is proven in `BS.ASM`: the ROM enables INT2 in `NOCFG6` before it queues the ready announcement and before reaching `STARTA`. The provisional gate `ITC bit 2 set` therefore injects queued stdin during initialization; the key ISR clears `ONFLG` and changes the boot path.
- The current in-progress stdio slice must not be committed with that gate.
- `STARTA` is the real command loop: test key queue, get a key, call `process_key`, run `bg_task`, execute the RAM HALT instruction, and repeat after interrupts.
- Prior reports calling PC `0x0A30` the main loop are wrong; raw ROM bytes at `0x0A20` show delay routines there. Do not reuse that address as a substitute.

## Current blocker

The exact linked address or another externally observable state for the ROM's first entry into `STARTA` has not yet been established. No source edit beyond the uncommitted stdio slice should continue until that gate is identified.

## Immediate next action

Locate `STARTA` in the linked BSP image from its distinctive instruction sequence or an existing Ghidra project, then gate stdin on the first proven command-loop entry and repeat the baseline/input comparison.
- Exact linked `STARTA` is bank 0 address `0x09F9`; its loop runs through the
  `JR` at `0x0A15`, which targets `0x09F9`.
- In that loop, logical `bg_timer` at `0xD653` maps to physical `0x41653` with
  the BSP command-loop MMU mapping. A 20,000,000-cycle write trace showed the
  timer sequence `0, 0, 1, 2, 3, 4, 5, 0, 0, ...`.
- Source inspection shows initialization also clears `bg_timer`, while the
  command loop writes zero and immediately calls `bg_task`, which writes zero
  again. The stdio readiness gate therefore requires two consecutive zero
  writes to physical `0x41653`; a nonzero write resets the sequence.
- The in-progress `qns/bns.py` stdio slice now uses that gate and updates the
  recorded cycle count during execution so interrupt traces report real time.
- An 80,000,000-cycle BSP run with standard input `a` plus the pipe newline
  asserted keydown at about cycle 1,049,000, received firmware acknowledgement
  at about 1,453,000, completed keyup, and delivered the following character.
  It ended at PC `0x5772` with `CBR=0x34`, `BBR=0x1E`, `CBAR=0xC6`, matching
  the no-input baseline. The input run emitted 1,247 phonemes versus 1,342 in
  the baseline.
- A 10,000,000-cycle non-pause phoneme stream spells the startup announcement
  `BRAILLE N SPEAK READY`. A distinct audible echo for the typed character has
  not yet been proven.
- Comparing temporary 10,000,000-cycle RAM dumps showed input-dependent state
  changes including physical `0x4164E: 00 -> 03`, `0x41A37: 00 -> 01`, and
  `0x4214C: 5A -> 5D`. This proves firmware state changed, but those locations
  have not yet been assigned exact source-level meanings.
- Added an in-progress regression test requiring the exact two-zero `STARTA` /
  `bg_task` readiness sequence. Tests have not yet been rerun after adding it.
- Immediate next action: normalize the edited tracked file, fix only the new
  import ordering, run the focused tests and lint, review the exact diff, then
  either commit or fully revert the stdio slice before beginning another slice.
- Focused verification after the readiness-gate test was added:
  `uv run pytest tests\\test_bns.py tests\\test_io.py` passed all 4 tests.
- New-code lint verification:
  `uv run ruff check qns\\bns.py tests\\test_bns.py --ignore E501,F541`
  passed after applying Ruff's import-only ordering. The ignored findings are
  pre-existing in `qns/bns.py`.
- Reviewed the tracked `qns/bns.py` diff and the complete new
  `tests/test_bns.py`. The slice contains only the source-table character map,
  exact BSP command-loop readiness gate, stdin thread/queue, firmware-acknowledged
  key down/up state machine, cycle-stat correction, CLI stdio enablement, and
  focused regression tests.
- Current decision: the slice has a kept measured result (real firmware IRQ
  acknowledgement without disturbing the eventual BSP MMU/PC state), so it is
  eligible to commit rather than revert.
- Immediate next action: verify branch/worktree state, stage only
  `qns/bns.py` and `tests/test_bns.py`, inspect the staged diff, and commit this
  source slice before any different hardware work.
- Committed the complete stdio keyboard slice as `d8e95ad` (`Drive BSP
  keyboard from standard input`). Only `qns/bns.py` and `tests/test_bns.py`
  were staged; pre-existing user changes and untracked research assets remain
  untouched.
- Immediate next action: reread the active plan against the committed state,
  then establish and correct the BSP model's remaining I/O-port contract one
  independently measured and committed slice at a time.
- Verified the BSP port contract from the authoritative firmware sources:
  `BSP.INC` defaults to `BSPLUS=1`; the non-TNS/non-Lite branch of
  `LIB/BSPORTS.LIB` assigns `WATCH_DOG=0x80`, `SPPWR=0x80`, `UIPORT=0x40`,
  `KEYCLR=0x20`, and `SSI263=0xC0` through `0xC4`. It defines no Braille
  display for this speech-only BSP model.
- Firmware uses `SPPWR` value `1` to turn speech power on and value `0` to turn
  it off. Reads of `WATCH_DOG` service the watchdog on models/build paths that
  use it.
- Current `qns/bns.py` is wrong at this boundary: it constructs a
  `BrailleDisplay` and registers ports `0x80` through `0x83` as display I/O;
  the constructed `Watchdog` is not registered.
- A live 2,000,000-cycle `roms/bspeng.bns` I/O trace observed three firmware
  writes of `0x01` to port `0x80`, confirming that this ROM is exercising the
  speech-power output, not a display. The run reached PC `0xB44F`.
- Immediate next source slice: remove the BSP display instance/registration,
  register port `0x80` as watchdog-read/speech-power-write, track the exact
  firmware power bit, add focused tests, run the live ROM, and commit or revert
  the slice before touching another port family.
- Completed the BSP port `0x80` correction. Focused tests passed 5/5 and the
  scoped Ruff check passed. A 2,000,000-cycle live ROM rerun still reached PC
  `0xB44F`, matching the pre-change run.
- Committed the kept slice as `7a806c5` (`Model BSP speech power port`). The BSP
  model no longer constructs or registers a Braille display; reads at `0x80`
  service the watchdog, writes track speech-power bit zero, and `0x81` through
  `0x83` are unclaimed as the real hardware requires.
- Immediate next action: identify the BSP serial stdio contract from the actual
  Z180 ASCI implementation and firmware use, then implement one committed
  serial I/O slice without disturbing the keyboard or speech-port work.
- Confirmed the serial loss boundary: `tools/build_ffi.py` supplies Z180 ASCI
  receive/transmit stubs that always return no data and discard every outgoing
  byte. `qns/cpu.py` has no serial callback parameters.
- The vendored Z180 emulator's real byte callbacks are sufficient: RX returns
  a byte or `-1`; TX reports `(channel, byte)` after the configured ASCI frame
  completes. Its receive side polls the callback only when the channel receiver
  is enabled, then shifts the returned byte into the hardware FIFO.
- BSP firmware initializes ASCI channel 0 with `CNTLA0=0x64` (8-N-1) and
  `CNTLB0=2` for its initial 9600-baud configuration; normal firmware also
  configures channel 1 for the disk port. TX data registers are ports `0x06`
  and `0x07`, RX data registers are `0x08` and `0x09`.
- Began the serial bridge source slice in tracked `tools/build_ffi.py` and
  `qns/cpu.py`: the generated C wrapper now accepts/stores RX/TX callbacks and
  forwards the emulator's byte events; the Python `Z180` constructor accepts
  matching callbacks and keeps their CFFI handles alive.
- The edited files have been normalized to the repository's CRLF convention.
  The native extension has not yet been rebuilt and no tests have run for this
  in-progress slice.
- Immediate next action: rebuild the native extension using the repository's
  documented `uv run python tools/build_ffi.py` command, then exercise the
  callbacks through actual Z180 execution. Commit only if the native bridge and
  existing BSP boot remain verified; otherwise revert the entire slice.
- The first native rebuild succeeded and installed a new ignored/generated
  `_z180_cffi` C file and `.pyd`. Compiler warnings were confined to pre-existing
  upstream z180emu source diagnostics.
- Added in-progress `tests/test_cpu.py` programs that configure the real Z180
  channel-0 ASCI registers exactly like BSP (`CNTLA0=0x64`, `CNTLB0=2`) and test
  byte transmit plus receive-through-RDR using actual CPU instructions.
- The first execution of those tests failed both callbacks: no TX event and no
  RX byte. Investigation proved the new callback forwarding itself was not the
  cause. The wrapper never calls `z180asci_channel_device_timer`; only an unused
  `do_timers` function in upstream `markiv.c` demonstrates the required 16-cycle
  ASCI clocking. Thus the pre-existing bridge never advanced any serial frame.
- Updated the in-progress generator so each `qns_z180_execute` call executes the
  requested CPU chunk, accumulates its cycles, and clocks both ASCI channels
  once per 16 accumulated cycles. This preserves the existing CPU chunk
  behavior while advancing the real ASCI state machine; reset clears the cycle
  remainder.
- That timer edit has not yet been rebuilt or retested. Immediate next action:
  normalize `tools/build_ffi.py`, rebuild the extension, rerun only
  `tests/test_cpu.py`, and either continue verification on a passing bridge or
  revert the whole serial slice if the second measured attempt keeps nothing.
- The second serial attempt also produced no kept improvement: after rebuilding
  with ASCI clock advancement, both actual-Z180 TX and RX tests still failed
  exactly as before. This hit the two-consecutive-no-improvement halt required
  for the serial target.
- Fully rejected and reverted the serial slice: restored tracked
  `qns/cpu.py` and `tools/build_ffi.py`, deleted the in-progress
  `tests/test_cpu.py`, and rebuilt the ignored/generated CFFI extension from the
  restored baseline generator. No serial source change was kept or committed.
- Proven remaining serial blocker: the current native Z180 boundary neither
  forwards ASCI byte callbacks nor advances frames in a way validated by real
  CPU execution. Per the convergence rule, do not widen or retry this target in
  the current workstream without new evidence or explicit user direction.
- Immediate next action: verify the revert left no tracked serial diff, then
  continue the active whole-system plan on a different unfinished BSP hardware
  family that can produce a measured kept result, beginning with the real-time
  clock/status/persistence contract.
- Correction to the prior halt: the exact-convergence rule did not apply to
  this ordinary system-building task, and the two failed test iterations were
  not two source slices. The active goal has been resumed; serial debugging is
  continuing under the normal implementation and Git-accountability rules.
- Fresh inspection found the concrete ASCI failure: channel startup sets
  `m_brg_const=2` but neither startup nor reset initializes `m_brg_timer`.
  Calling the timer with its zero value decrements it to `65535`, preventing any
  frame from completing during the earlier tests.
- Reimplemented the in-progress native bridge in `tools/build_ffi.py` and
  `qns/cpu.py`: Python RX/TX byte callbacks are forwarded through CFFI, both
  channel baud timers are seeded after create/reset, and the wrapper advances
  both real ASCI state machines once per 16 accumulated CPU cycles.
- Added actual-instruction tests in `tests/test_cpu.py`. One program configures
  channel 0 exactly like BSP and transmits `A`; the other receives `0x5A`, polls
  `STAT0`, reads `RDR0`, and writes it to emulated memory.
- Rebuilt the native extension successfully. `uv run pytest tests\\test_cpu.py`
  now passes both tests, proving real Z180 TX and RX byte traversal rather than
  merely invoking wrapper callbacks directly.
- Immediate next action: run scoped lint, rerun the existing BSP keyboard/port
  tests, and live-boot `roms/bspeng.bns` with the new native extension. If all
  remain valid, review and commit this serial bridge slice before wiring its
  standard-I/O frontend.
- Serial bridge verification completed: all new-code scoped Ruff checks passed;
  `uv run pytest tests\\test_cpu.py tests\\test_bns.py tests\\test_io.py`
  passed 7/7; and a 2,000,000-cycle live BSP boot still reached PC `0xB44F`,
  matching the previous baseline.
- Reviewed and staged only `qns/cpu.py`, `tools/build_ffi.py`, and
  `tests/test_cpu.py`. Committed the kept native bridge as `cde9444`
  (`Connect Z180 serial byte callbacks`). User-owned SSI/synth changes and all
  research assets remain untouched.
- Immediate next source slice: wire the committed ASCI byte callbacks into the
  BNS standard-I/O frontend with an explicit, non-conflicting input routing
  contract; verify real firmware serial output/input and commit or revert that
  slice before beginning RTC or persistence work.
- Implemented the in-progress standard-stream routing contract in `qns/bns.py`:
  `--input` selects `keyboard`, `serial0`, or `serial1`; `--output` selects
  human-readable `console`, raw `serial0`, or raw `serial1`. Raw serial output
  reserves stdout for bytes and redirects all emulator diagnostics to stderr.
  This permits normal keyboard use and binary serial sessions without sending
  one stdin byte to two different hardware devices.
- Added real CLI round-trip coverage: a temporary Z180 ROM reads `Z` from
  stdin through ASCI channel 0 and sends it back through TDR0. The subprocess
  produces exactly `b"Z"` on stdout, with diagnostics on stderr. Channel
  isolation is also covered directly.
- `uv run pytest tests\\test_bns.py tests\\test_cpu.py tests\\test_io.py`
  passed 9/9 and scoped Ruff passed. A live 2,000,000-cycle BSP boot still
  reached PC `0xB44F`. A 5,000,000-cycle live keyboard run delivered `a` plus
  newline with the expected four INT2 edge/ack pairs beginning around cycle
  1,049,000, proving the input refactor preserved real firmware keyboard I/O.
- Reviewed the full `qns/bns.py` and `tests/test_bns.py` diff; it is limited to
  explicit standard-stream routing, ASCI callbacks, raw-output diagnostic
  separation, and their tests.
- Immediate next action: stage only those two files, inspect the staged ledger,
  commit this kept serial-stdio slice, then proceed to the BSP RTC/status and
  persistence contract.
- Committed the standard-stream frontend as `b34e269` (`Route BNS serial
  through standard streams`). Only `qns/bns.py` and `tests/test_bns.py` were
  staged; unrelated user changes remain untouched.
- Immediate next action: establish the exact BSP real-time clock, status,
  RS-232 power, and persistent-memory contract from firmware source plus live
  I/O traces, then implement the first independently verifiable hardware slice.
- BSP source establishes the default BSPLUS port contract: the parallel clock
  window is `0x60` through `0x6F`, RS-232 power is written at `0xA0`, speech
  power is written at `0x80`, and the guarded `IOSTAT=0xE0` definitions belong
  to other models rather than BSPLUS. Do not invent a BSP status port at
  `0xE0`.
- A 5,000,000-cycle live BSP trace reads clock register F at `0x6F`, receives
  the current unmapped value `0xFF`, masks it to `0x04`, and writes `0x04`
  back. It also writes `0x00` to RS-232 power port `0xA0` twice.
- The directly addressed 4-bit clock layout and calendar fields identify an
  OKI MSM5832-family RTC, but the related MSM58321 register table is not exact
  enough: BSP specifically treats bit `0x04` of register F as the 12/24-hour
  selection. The exact MSM5832 control-register semantics still require visual
  confirmation from the actual datasheet before implementation.
- Immediate next action: inspect the MSM5832 datasheet itself, record the exact
  16-register map and write/control behavior, then implement and verify only
  the BSP RTC hardware slice.
- Correction from the matching chip contract: the BSP RTC is MSM6242-family,
  not MSM5832. `TIMENEW.C` directly uses registers D and F; the MSM6242B
  datasheet identifies D as HOLD/BUSY/IRQ/30-second adjust and F as
  RESET/STOP/24-hour/TEST. Its required 24-hour sequence is exactly the BSP's
  `1 -> 5 -> 4`, and its 12-hour sequence is `1 -> 0`.
- The in-progress RTC slice adds a direct-bus MSM6242 owner in `qns/io.py` and
  maps it across BSPLUS ports `0x60-0x6F` in `qns/bns.py`. It exposes the 13 BCD
  time/date/week registers, D/E/F controls, host-clock progression, HOLD/STOP,
  12/24-hour formatting, and clock-setting writes.
- Consecutive digit writes preserve raw intermediate values. This is required
  by BSP's `timea()` path, which changes the mode and then rewrites hour digits
  while the clock is running; an invalid intermediate hour must not cause the
  first digit write to be replaced before the second arrives.
- Immediate next action: add deterministic RTC register/control tests plus a
  BNS port-wiring test, normalize line endings, and run the focused suite.
- Added deterministic RTC coverage for the complete BCD field map, Sunday-zero
  weekday encoding, HOLD freeze/resume, atomic time setting, BSP's 12-hour and
  24-hour register-F sequences, and the `0x60-0x6F` BNS port wiring.
- The first focused run exposed one real mode-transition defect: after changing
  24/12 mode, the model reformatted existing hour digits before BSP could read
  and rewrite them. Register-F mode changes now mark those digits as raw
  old-format state, matching `timea()` and `timee()`.
- `uv run pytest tests\\test_io.py tests\\test_bns.py tests\\test_cpu.py`
  now passes 13/13. Scoped Ruff passes for all four RTC-slice files after its
  mechanical import normalization.
- Immediate next action: live-boot `roms/bspeng.bns` with I/O tracing, verify
  the boot reads `0x04` at `0x6F` and retains the established final PC, then
  review and commit or revert the RTC slice.
- Live `roms/bspeng.bns` verification at 2,000,000 cycles now shows
  `R port=6F val=04` followed by `W port=6F val=04` on both warm passes, rather
  than the former floating `0xFF` read. The firmware still reaches baseline PC
  `0xB44F`.
- Source inspection found no BSPLUS access to register E/`CLCKE`; BSP startup
  explicitly requires INT0 disabled. The RTC therefore stores register E but
  does not invent an unused periodic interrupt signal.
- Final slice review found mixed tracked line endings: `qns/io.py`,
  `qns/bns.py`, and `tests/test_bns.py` use CRLF while `tests/test_io.py` uses
  LF. Each touched file has been restored to its original convention. The
  scoped ledger is now 267 insertions and 2 expected import-line deletions,
  with no slice-local whitespace errors under `cr-at-eol`.
- The repository-wide `uv run pytest` result is 32 passed and one failure in
  the separate user-modified synth surface:
  `tests/test_synth.py::test_time_stretch_duration_modes` expects duration 3
  to shorten four samples, but the current synth returns all four. The RTC,
  BNS, CPU, and other tests all pass; do not modify the user's synth work as
  part of this slice.
- Immediate next action: stage only the four RTC-slice files, inspect the staged
  Git ledger, commit the kept RTC improvement, then continue with the next
  unfinished BSP hardware/persistence item.
- Committed the verified RTC slice as `5c570df` (`Model BSP real-time clock`).
  Only `qns/io.py`, `qns/bns.py`, `tests/test_io.py`, and `tests/test_bns.py`
  were included; user-owned synth and documentation changes remained unstaged.
- For the next power slice, firmware source proves BSPLUS `MAXON` writes `1`
  and `MAXOFF` writes `0` to `RSPWR=0xA0`; diagnostic value `9` also means on
  because bit zero is the latch state. The two live warm paths already showed
  writes of `0`, requesting the transceiver remain off.
- The in-progress power slice maps writes at `0xA0` to
  `bns.rs232_power_enabled` using bit zero. Reads remain floating `0xFF`, since
  this is an output latch and the firmware contract supplies no readback.
- `uv run pytest tests\\test_bns.py tests\\test_cpu.py tests\\test_io.py`
  passes 14/14 and scoped Ruff passes for the two changed files.
- Immediate next action: review and stage only `qns/bns.py` and
  `tests/test_bns.py`, commit or revert the RS-232 power slice, then inspect the
  next incomplete timer/persistence contract.
- Committed the RS-232 power slice as `abc14cf` (`Model BSP RS-232 power
  latch`). Only `qns/bns.py` and `tests/test_bns.py` were included.
- Persistence inspection found that RAM bytes alone are insufficient: the
  memory model's `_written_addrs` set determines which shadow-RAM bytes override
  ROM, including written zeroes. A durable state must preserve that bitmap as
  well as the 512 KiB RAM image.
- The in-progress persistence slice adds a versioned `QNSRAM` state format in
  `Memory`, containing the exact RAM size, written-address bitmap, and RAM
  bytes. Saves use a sibling temporary file followed by atomic replacement;
  loads reject unknown formats, truncated/extended files, and wrong RAM sizes.
- The CLI now accepts explicit `--state FILE`: it loads an existing state after
  the ROM, initializes RAM when the file is absent, and saves after execution.
  No implicit file is created when the option is omitted.
- A two-process integration test uses one Z180 ROM to write `0x5A` to shadow
  RAM behind ROM, then a second ROM loads the state and transmits the restored
  byte through real ASCI/stdout. Unit tests also prove written-zero overrides
  survive and invalid state files fail rather than being guessed.
- `uv run pytest tests\\test_memory.py tests\\test_bns.py tests\\test_cpu.py
  tests\\test_io.py` passes 18/18.
- Immediate next action: run scoped lint and live BSP persistence smoke
  verification, review the complete state slice, and commit or revert it.
- Scoped persistence lint passes; only the pre-existing unused `was_new` local
  in `Memory.write` is excluded as unrelated to this slice.
- Live BSP persistence smoke passed across two separate processes using an
  explicit temporary state file. The first initialized and saved state at PC
  `0xB44F`; the second reported loading that state, again reached `0xB44F`, and
  atomically resaved it. The temporary smoke file was then removed.
- Final `uv run pytest` result with the persistence tests included is 37 passed
  and the same one untouched user-synth failure in
  `test_time_stretch_duration_modes`. All state, BNS, CPU, RTC, and remaining
  tests pass.
- The tracked persistence diff is limited to `qns/memory.py`, `qns/bns.py`, and
  `tests/test_bns.py`; new `tests/test_memory.py` contains the three state-format
  unit tests. Mixed tracked line endings are preserved and the scoped diff is
  whitespace-clean under `cr-at-eol`.
- Immediate next action: stage exactly those four persistence files, inspect
  the staged ledger including the new test file, commit the kept slice, then
  continue the active BSP hardware/timer audit.
- Committed the persistence slice as `6057ef4` (`Persist BNS shadow RAM state`)
  with exactly `qns/memory.py`, `qns/bns.py`, `tests/test_memory.py`, and
  `tests/test_bns.py`.
- BSP timer/status audit found no missing implementation to patch. Default
  BSPLUS has no `IOSTAT`/`CEST` port; all such reads in `INTTIM0` are under
  TNS/Braille Lite guards. Do not map the other models' status semantics onto
  BSP.
- BSP's 100 ms service clock is Z180 PRT0: firmware loads `RLDR0`, enables
  countdown plus interrupt in `TCR`, and clears the interrupt by reading TCR
  and TMDR0. The native `z180emu` core already implements both PRT channels,
  pending internal PRT interrupts, cycle advancement, and continued timer
  advancement during HALT. Live BSP command-loop operation depends on and
  confirms this path.
- The observed write to `0xE0` is not authority to invent BSP status readback.
  `BSPORTS.LIB` assigns `HICLK=0xE0` only to BSNEW and assigns status at `0xE0`
  only to TNS/Braille Lite families; default BSPLUS defines neither.
- BSP hardware phase 3 is complete: memory/MMU boot, keyboard and interrupts,
  native PRT timers, serial/stdIO, port power contracts, MSM6242 RTC, and
  durable shadow RAM state are implemented or verified from the current core.
- Immediate next action: begin the required SSI-263/software-audio phase by
  reviewing the existing user-owned SSI/synth changes and their current tests
  without altering or staging those changes, then identify a clean authorized
  source boundary for the first kept speech slice.
- Speech review confirmed that the current dirty SC-01 formant substitution is
  not an SSI-263 model, while the tracked AppleWin-derived PCM bank represents
  only a fixed undocumented SSI-263 operating point. Neither supplies the
  register-driven phoneme parameters required for faithful software speech.
- The dedicated `notes-ssi263-re.md` reverse-engineering record inventoried the
  local evidence and classified the three `aicom` JPEGs as populated-board
  photographs, not die imagery.
- A bounded exact-path check found the previously referenced Visual6502 assets
  under `C:\Users\Q\AppData\Local\Temp\qns-ssi263-review`, including the raw
  7000-pixel SSI-263 die photograph and `suspected-rom.png`.
- Direct visual comparison shows that the candidate array is physically real
  and contains regular, column-varying presence/absence features at sufficient
  resolution for a possible bit extraction. The evidence does not yet prove
  that it is the phoneme-parameter store or establish orientation, polarity,
  address order, or logical grouping.
- Immediate next action: verify Git state, then measure the candidate grid
  reproducibly and compare its dimensions with the documented 64 phoneme
  addresses before assigning logical values or changing the speech runtime.
- Added isolated `tools/measure_ssi263_array.py`; it uses ImageMagick plus
  NumPy edge-profile autocorrelation and fractional lattice fitting without
  assigning logical bits or altering the emulator.
- Source-die measurement establishes an 18.77-pixel horizontal strip pitch and
  68 complete physical vertical strips between the visible decoder boundaries.
  The array is genuinely regular and bit-readable, but it is not a simple
  64-strip match to the documented phoneme code space.
- Retrieved the exact primary Visual6502 five-page SSI-263A Programming Guide
  into the temporary review directory and read its rendered page images. It
  confirms 64 resident addressable sounds and no duplicates, but its eight
  parameters are host-register controls; it discloses no internal phoneme
  coefficients, ROM word width, polarity, or address ordering.
- Immediate next action: inspect the primary datasheet functional diagrams for
  a named internal store or signal grouping that can identify the 68-strip
  candidate and constrain its other axis before attempting bit extraction.
- Primary Votrax patent US 3,908,085 establishes the matching logical design:
  six phoneme-address bits plus two timing-address bits drive two eight-output
  ROM banks; each output serializes four binary-weighted bits, for 16 four-bit
  parameters or 64 stored bits per phoneme.
- Die overlays confirm 64 physical data rows arranged as 16 four-row
  supercells and 64 active address columns plus four edge/dummy/reference
  strips. The candidate is therefore a high-confidence 64-by-64 phoneme
  characteristics ROM.
- The patent figures name the 16 ancestral parameter groups, while the SSI-263
  datasheet confirms a phoneme-characteristics ROM feeding five cascaded
  filter, source, amplitude, timing, closure, and transition controls. Exact
  SSI-263 field order and bit polarity still require extraction.
- Committed the isolated, lint-clean geometry tool as `ce2ceaa` (`Measure
  SSI-263 die array geometry`); no user-owned synth files were staged.
- Immediate next action: begin a separate raw-bit extraction slice that records
  physical cell classes without assuming polarity, address order, or parameter
  order, then test candidate interpretations against known silence/vowel/
  fricative constraints.
- The raw classifier slice separated rare contact/loop structures but produced
  physically implausible bit densities, so it yielded no accepted logical bits
  and was fully reverted before runtime work resumed.
- The primary Visual6502 page and Internet Archive inventory expose only the
  7000-pixel reduced surface image, not the stated 17265-by-14313 original,
  delayered imagery, or a vector trace. Exact optical coefficient recovery is
  externally blocked on stronger evidence.
- Added an isolated approximate PCM backend in `qns/synth/ssi263_pcm.py` and
  selected it directly from `qns/bns.py`, bypassing the dirty SC-01 package
  export without modifying the four pre-existing user-owned tracked files.
- The backend mirrors the documented five-register state, preserves amplitude
  zero as silence, uses the fixed AppleWin-derived SSI-263 captures for codes
  2 through 63, treats code 0 as pause, and uses code 2 for the missing code-1
  capture. It does not claim or invent unavailable articulation, inflection,
  rate, duration, or filter-frequency transformations.
- Verification: all 14 targeted BNS/PCM tests pass. The complete non-manual
  suite has 40 passes and the same unrelated `test_time_stretch_duration_modes`
  failure in untouched `qns/synth/dsp.py`; the new backend does not call it.
- Immediate next action: inspect the exact staged speech slice, commit it as
  the kept improvement, then inventory and execute the remaining `.bns`
  hardware-profile work from current ROM evidence.
- Committed the approximate audio boundary as `b6bf348` (`Use SSI-263 PCM
  audio backend`); only `qns/bns.py`, `qns/synth/ssi263_pcm.py`, and
  `tests/test_ssi263_pcm.py` were staged.
- The supplied corpus contains five distinct full English firmware packages:
  BSP, BS2, BSL, BL2, and BL4. The TNS directory contains only common updater
  payloads and a `.tns` support file, not a TNS firmware `.bns` image.
- The authoritative `BE_ENG.PRJ` build definitions identify the images as
  `BSPENG=BSPLUS`, `BS2ENG=BSNEW`, `BSLENG=B_LITE`,
  `BL2ENG=BSNEW+B_LITE`, and `BL4ENG=B_LITE_40`.
- BS2 is the first bounded non-BSP profile. Firmware source retains the BSP
  keyboard at `0x40`, key-clear at `0x20`, RTC at `0x60`, and SSI-263 at
  `0xC0`, but uses a combined power control at `0xA0`, PIO ports `0x80-0x83`,
  and high-bank control at `0xE0`.
- The package header begins with a generic `BNS` signature and executable
  updater code; it contains no plaintext model identifier in the inspected
  header. Automatic model selection therefore requires a verified image
  fingerprint/path convention or explicit model selection, not a guessed
  header field.
- Current state: no profile source changes have been made; the tree remains at
  the committed BSP/audio implementation plus the four pre-existing user-owned
  tracked edits.
- Immediate next action: trace the BS2 ROM under the current profile to measure
  its first missing I/O dependency, then choose the smallest truthful model
  selection boundary from the package/image evidence before editing.
- Live BS2 tracing under the BSP wiring reaches the full spoken startup
  greeting and then enters the RAM `HALT` instruction at 5,852,000 cycles.
  Source proves this is `STARTA`'s normal low-power wait for the next interrupt,
  not a ROM crash. The outer emulator loop currently exits on that state and
  must be corrected as a separate all-model core slice.
- The trace proves BS2 writes combined-power values `0x8C`, `0x2E`, and `0xAE`
  at `0xA0`, programs 8255 control port `0x83`, and writes high-bank latch
  `0xE0`. The BSP handler was falsely treating all `0xA0` values as only an
  RS-232 bit-zero latch.
- Firmware source defines BSNEW `OUTSEL` bit 0 as serial/RS-232 power, bit 1 as
  speech/audio power, bit 2 as flash power, bit 3 as disk/high-voltage power,
  and bit 7 as charge-output high. The shared `0x80` address is watchdog on
  reads and 8255 port A on writes; `0x81-0x83` are the remaining PIO ports.
- Current uncommitted BS2 slice adds explicit `model="bs2"` selection to the
  Python and CLI boundaries, wires the combined power/PIO/high-bank ports, and
  retains `bsp` as the default. It introduces no automatic filename guessing.
- Verification so far: import/format checks pass and all 11 focused BNS tests
  pass. The four pre-existing user-owned tracked edits remain untouched.
- Immediate next action: run the full non-manual suite and a live BS2 boot with
  the explicit profile, inspect/stage only `qns/bns.py` and `tests/test_bns.py`,
  then commit or fully revert this profile slice before addressing HALT.
- Committed the explicit BS2 profile as `b82e82e` (`Add BS2 hardware profile`)
  with only `qns/bns.py` and `tests/test_bns.py` staged.
- Native `cpu_execute_z180()` already handles HALT correctly: it continues
  three-cycle idle slots, advances PRT timers, checks pending interrupts, and
  leaves HALT when an enabled interrupt is accepted. The Python `BNS.run()`
  condition was the sole reason emulation terminated at the first HALT.
- Current uncommitted core slice removes only the outer `not cpu.halted` stop
  condition and adds a regression proving a halted CPU still receives the full
  requested cycle budget. All 12 focused BNS tests pass.
- Immediate next action: live-run BS2 beyond 5,852,000 cycles and verify it
  wakes from HALT and continues the command loop, then run the full non-manual
  suite and commit or revert this two-file core slice before the next profile.
- Committed the HALT-loop correction as `ddfe380` (`Keep emulation running
  through HALT`). Live BS2 now consumes the full 7,000,000-cycle budget;
  post-HALT memory and SSI writes prove PRT interrupts wake the CPU and return
  it to the command loop.
- BSL (`B_LITE`) under BSP wiring reaches PC `0x2AF5` and waits forever before
  its greeting. Package-offset bytes and `BSSERIAL.ASM` identify this exactly
  as `_BRL_STATUS` polling CSI/O `CNTR` bits `0x30` after requesting status
  from the attached Braille display.
- The native Z180 core clears transmit-enable bit `0x10` on `CNTR` reads via a
  historical hard-coded workaround, but never completes receive-enable bit
  `0x20` and exposes no external CSI/O exchange. The BSL loop is therefore a
  missing peripheral boundary, not a memory or speech-volume failure.
- The repeated `[MEM] ... VOLUME` lines are stale BSP-only debug output from
  `qns/memory.py` address `0x4215C`; they do not identify the BSL write as its
  volume variable and must not be used as a diagnostic premise.
- A truthful BSL slice must carry CSI/O transmit bytes to a Braille-display
  model and return display status before clearing receive-enable. Forcing the
  bit clear while echoing the last transmit byte would substitute a fake
  success and is rejected.
- Current state: no BSL or CSI/O source changes exist. The public native state
  getter exposes `CNTR` and `TRDR`; whether a supported setter exists is still
  being established so the boundary can remain in this repository rather than
  changing the separate `z180emu` checkout.
- Immediate next action: finish checking the core public state/write surface
  and wrapper build contract, then implement the smallest callback-backed
  CSI/O transaction slice with tests or stop if the required durable boundary
  cannot be supplied from the current repository.
## 2026-07-18 - BSL CSI/O callback boundary in progress

- Finding: BSL waits in `_BRL_STATUS` because `z180emu` stores CSI/O receive-enable (`CNTR.RE`) but does not implement a CSI/O transfer that clears it.
- Observation: the public `z180_device` exposes `m_token`; `cpu_get_state_z180` exposes CNTR, TRDR, and IOCR; and linked `z180.c` provides `z180_writecontrol`. The transaction can therefore be completed in this repository's CFFI wrapper without modifying `C:\Users\Q\src\z180emu`.
- Current state: `tools/build_ffi.py` and `qns/cpu.py` now accept CSI/O receive/transmit callbacks. The wrapper services TE/RE from the existing per-instruction debugger hook so firmware cannot overwrite a pending transmit within a larger execute batch. A native regression program was added to `tests/test_cpu.py`. The CFFI extension builds successfully; only pre-existing warnings from external `z180emu` were emitted.
- Blocker: none currently. The regression has not yet been run. `git diff --check` also found one whitespace-only line in `tools/build_ffi.py` that must be removed before commit.
- Next action: remove that whitespace, run the focused native CPU tests, inspect the scoped diff, then either commit this CSI/O boundary slice or fully revert it before starting the BSL Braille-display profile.

### CSI/O callback verification checkpoint

- Finding: servicing CSI/O only after `qns_z180_execute` would lose transmit bytes because firmware can observe the native core's transmit-complete read behavior and overwrite CNTR within the same cycle batch. The service therefore runs from the core's existing per-instruction debugger hook.
- Observation: the native regression sends `0x81`, receives `0x0A`, waits on the real CNTR bits, and stores the received byte through an emulated Z180 program.
- Current state: `uv run pytest tests/test_cpu.py -q` passes all 3 tests. `git diff --check` is clean after restoring and reapplying the three-file slice. Git displays touched pre-existing CRLF lines as replacements because `apply_patch` emits LF for changed lines; untouched lines remain unchanged.
- Blocker: none. The scoped semantic diff still needs its final review before commit.
- Next action: review the remainder of the scoped diff, commit only `tools/build_ffi.py`, `qns/cpu.py`, and `tests/test_cpu.py` if correct, then reread this note and begin the separate BSL Braille-display model slice.
## 2026-07-18 - Active target correction: complete BS2 before BSL

- User direction: return to `bs2eng.bns` and make the BS2 system work completely before doing further Braille-display or BSL profile work.
- Correction: the prior 7,000,000-cycle boot, startup speech, profile-port checks, and HALT wake evidence established a working BS2 boot foundation, not a complete BS2 system. Treating that milestone as sufficient to move to BSL was wrong.
- Current BS2 authority: `BS2ENG=BSNEW` in `BE_ENG.PRJ`; the current profile models BSNEW combined power at `0xA0`, 8255 ports `0x80..0x83`, watchdog read sharing `0x80`, and `HICLK` at `0xE0`.
- Current gaps: no BS2-specific end-to-end stdin command assertion, no full serial/disk workflow assertion, no BS2 persistence/restart assertion, no sustained interactive audit, and no proof that the current passive 8255 model supplies every firmware status input correctly.
- BSL status: deferred. Commit `4b9ee6d` supplies a reusable Z180 CSI/O callback boundary, but no BSL display-profile work will continue while BS2 remains incomplete.
- Next action: establish the exact BSNEW keyboard, 8255 status, serial/disk, storage, and persistence contracts from source and live BS2 traces; then exercise each real firmware workflow and implement only proven missing BS2 boundaries as isolated committed slices.

### BS2 end-to-end audit checkpoint

- Keyboard result: piping `a` plus the terminal newline into `bs2eng.bns --model bs2 --input keyboard` produced firmware acknowledgements for every key-down/key-up INT2 edge. At 20,000,000 cycles, both the input and no-input runs returned to PC `0x1BDA`, `HALT`, `CBR=0x34`, `BBR=0x1E`, `CBAR=0xC6`. The input run produced 164 phonemes versus the 84-phoneme baseline.
- Persistence result: a 30,000,000-cycle run accepted `hello` followed by terminal `C` (the documented c-chord, “speak current line”), saved a 589,836-byte QNS state, and a fresh process loaded that state, accepted another `C`, produced 164 phonemes, and returned to the same idle PC/MMU/HALT state.
- Persistence limitation: the literal ASCII string `hello` is not present in the state image, consistent with translated/Braille storage but insufficient to prove content identity. The current evidence proves firmware interaction, state serialization/reload, and post-restart command execution, not yet exact file-content recovery.
- Supplied BS2 assets: `bs2eng.hlp`, `spell.dic`, `bsname.bns`, `calsort.bns`, `calsort.msg`, and update/readme text accompany the firmware. The help file is the workflow authority for writing, reading, files, serial transfer, printing, status, datebook, phone book, spellcheck, and external programs.
- 8255 finding: BSNEW uses `0x80` port A output, `0x81` port B status input, `0x82` port C control/status, and `0x83` control. The current passive `[0xFF] * 4` model makes printer-ready C7 high but also reports port-B busy/out-of-paper bits high; printer behavior is therefore not yet truthful.
- Next action: establish exact BSNEW OUTSEL defaults and exercise firmware serial stdio; then model the 8255's mode/control/status behavior and parallel output only from the source-backed contract, with focused tests and a live BS2 workflow.

### Correction: prior BS2 interaction evidence was pre-initialization

- The earlier premise was wrong: the additional 80-phoneme response is the uninitialized-file-system prompt, whose final phonemes correspond to “enter y or n.” The supplied `a`, `helloC`, and `Of` inputs were consumed by that prompt, not by the editor or file manager.
- Therefore the prior runs prove keyboard IRQ traversal, stable waiting, and state-file mechanics only. They do not prove normal BS2 editing, file-manager entry, or persisted file content.
- Causal next action: create a fresh state by answering the firmware's initialization prompt with lowercase `y` and allowing initialization to finish. Then restart from that initialized state and send exactly uppercase `O` (o-chord) followed by lowercase `f`; verify the spoken “Enter file command” prompt before proceeding.

### BS2 initialized-state and input-pacing checkpoint

- Main RAM initialization is now proven: a fresh run received `yy`, saved state, and a no-input restart from that state produced only the normal 84-phoneme startup instead of another yes/no prompt.
- The English source authority is `BRLYES=0x3D`, and terminal lowercase `y` maps to raw Braille `0x3D`; the two-confirmation sequence was correct.
- On the initialized state, `O` then `f` causes the firmware to say the phoneme sequence for “initialize flash system, enter y or n.” This is a second, flash-file-system initialization boundary reached through the real file manager.
- Preloading `Ofyy` is not a valid interactive test. INT2 tracing proves all four key-down/key-up pairs reached firmware, but they were delivered by about cycle 6,034,000 before the repeated prompt began. The firmware discarded the prematurely queued answers and repeated the prompt.
- Current blocker: exact prompt-paced interaction has not yet been exercised. Piped finite input is too early for multi-prompt workflows even though single keyboard transactions are correct.
- Next action: run BS2 interactively over a PTY with the initialized state, send `O` and `f` only after normal startup, wait for the flash initialization prompt, then send each `y` confirmation after its corresponding spoken prompt. Save state, restart, and verify `O`, `f` yields “Enter file command.”

### Windows interactive stdin defect and in-progress fix

- PTY evidence: a live Windows PTY kept stdin open, but entering `O` only echoed it at the terminal; no keyboard INT2 occurred until a newline would have been entered. A newline would also become an unwanted BNS carriage-return chord.
- Pipe evidence: a non-TTY process receives bytes immediately when preloaded, but its stdin is closed and cannot be fed later through the execution session. It cannot perform prompt-paced interaction.
- Proven defect: the runtime's unconditional `sys.stdin.read(1)` is line-buffered on an interactive Windows console, so the advertised keyboard stdio mode is not actually usable one chord at a time.
- Current source slice: `qns/bns.py` uses `msvcrt.getwch()` only when stdin is an interactive Windows console and preserves `sys.stdin.read(1)` for redirected input. Extended-key prefix pairs are consumed and ignored. `tests/test_bns.py` has a focused test proving an `O` console key is returned without a newline.
- Next action: run the focused tests and lint, then rebuild the live PTY workflow. Keep and commit this two-file slice only if `O` produces an immediate keyboard interrupt without Enter and the existing piped-input tests remain green; otherwise fully revert it.

### Windows interactive stdin kept result

- Verification: `uv run pytest tests\\test_bns.py -q` passes 13/13 and scoped Ruff passes. The full non-manual suite is 46 passed, 3 deselected, with only the pre-existing untouched `tests/test_synth.py::test_time_stretch_duration_modes` failure.
- Live gate: in a Windows PTY, sending `O` without Enter immediately asserted and cleared both firmware key edges on INT2. This directly fixes interactive one-chord-at-a-time stdio while redirected/piped input remains covered by the existing CLI tests.
- Flash workflow observation: prompt-paced `O` reached “initialize flash system, enter y or n”; the first later `y` reached firmware and produced “Are you sure? Enter y or n.” The next tool-mediated character did not produce INT2, and the unsaved run was stopped without modifying the initialized state. Do not claim flash initialization or file-manager entry from that run.
- Next action: commit only `qns/bns.py` and `tests/test_bns.py` as the interactive-console slice. Then establish a reliable prompt-driving test boundary or source-level state assertion before retrying flash initialization; do not preload multi-prompt input as a substitute.

### BS2 O-chord/file-manager live checkpoint

- The live BS2 run loaded `qns-bs2-init2-20260718.state`, spoke the flash-system initialization prompt, and accepted both prompt-paced lowercase `y` confirmations through complete INT2 key-down/key-up handshakes.
- Source/table correction: `LIB/BSEQUATS.LIB` defines `OCHORD EQU 55H`, and the English terminal table maps uppercase `O` to raw `0x55`. Uppercase terminal `O` is therefore the literal O-chord; lowercase `o` maps only the unchorded letter (`0x15`).
- After the confirmations, the correct uppercase `O`, lowercase `f` sequence traversed complete keyboard interrupt handshakes but did not produce the source-defined `enter file command` speech; only pause phonemes were emitted. A later lowercase `o`, `f` sequence was not the requested command and supplies no file-manager evidence.
- The raw Windows key reader also consumed Ctrl-C as a BNS chord, so the run could not shut down cleanly. The exact emulator process was identified and stopped; the on-disk state was not saved or overwritten.
- Source authority confirms `entcmd` is exactly `enter file command`, and `FILEP.C` emits `ENTCMD` from the file-command path. The current failure is downstream of keyboard delivery; file-manager entry or an initialization prerequisite is still not functioning.
- Current blocker: the firmware state reached after flash confirmation has not been identified, and no ready announcement or file-command prompt followed. Do not treat interrupt acknowledgement as file-manager success.
- Next action: trace the linked BS2 command path from O-chord through `process_key` and `FILEP.C`, and inspect the flash/folder initialization return path to identify the exact state or unmodeled hardware condition preventing `enter file command`.

### BS2 flash boundary identified

- The correct terminal encoding is settled: uppercase `O` maps to `0x55`, exactly `OCHORD`, and lowercase `f` maps to the unchorded file subcommand.
- A diagnostic restart declined flash initialization with `n`; it still did not reach a stable ready/file-command loop and repeated initialization behavior. The exact unsaved process was stopped, leaving the state file unchanged.
- `BSINIT.C` proves affirmative flash initialization calls `flashInit(1, 0x100000, 0x200000)`. `FLASH.C` defines BSNEW `bankPort=0xE0`, `bankEn=0x08`, and 512 KiB hardware pages.
- BSNEW maps a selected 512 KiB flash page into Z180 physical `0x80000..0xFFFFF`. Latch bit 3 enables flash and latch bits 0..2 select the page; logical flash starts at far address `0x100000` and BS2 uses 2 MiB.
- The current emulator only records writes to `0xE0`. Its `Memory` has 512 KiB RAM and no flash array, no high-bank translation, and no NOR command handling. Flash writes above RAM are discarded, so the firmware's erase poll can appear complete but its ID/FLAT programming cannot verify; `flashInit` consequently cannot finish truthfully.
- The required AMD-style BSNEW operations are source-defined: chip erase uses the `AA/55/80/AA/55/10` sequence; byte programming uses `AA/55/A0` followed by the target byte and immediate readback; sector erase uses `AA/55/80/AA/55/30`. Programming may only clear bits, while erase restores `0xFF`.
- Current blocker: BS2 cannot complete startup or enter the file manager until its banked flash is modeled and persisted. Keyboard delivery is not the blocker.
- Next action: implement the source-defined 2 MiB BSNEW banked NOR flash directly in the existing memory owner, connect the existing `0xE0` latch to it, add focused mapping/program/erase/persistence tests, and keep or fully revert that isolated slice based on the live flash-init and `O`, `f` gate.
## 2026-07-18 BS2 flash slice checkpoint

- The active isolated slice adds the source-backed BS2 2 MiB AMD flash mapping and command state machine, couples port `0xE0` to the memory mapper, and persists flash in the state format while retaining compatibility with version 1 RAM-only state files.
- Focused verification passes: `uv run pytest tests\test_memory.py tests\test_bns.py -q` reports 19 passed, and `git diff --check` passes for the four slice files.
- Live `bs2eng.bns` evidence changed the decision: two prompt-paced lowercase `y` responses advanced through flash initialization and produced the flash-initialized speech. The previous no-flash implementation could not do this.
- After the second flash-confirmation `y`, the native core reported `Z180 'z180' ill. opcode $d1 $11`, after which firmware restarted its initialization speech. No folder prompt or third key had occurred before the trap.
- The exact live process was stopped without saving after its PID was verified. `C:\Users\Q\AppData\Local\Temp\qns-bs2-init2-20260718.state` remains unchanged.
- The current blocker is an illegal opcode during affirmative flash initialization. Folder initialization has not been reached, and keyboard chord mapping is not the blocker.
- The next action is to identify the illegal instruction's PC and relevant memory mapping, then reconcile that evidence with the BS2 source before changing more code.
- The exact file-manager entry remains uppercase terminal `O` (raw `0x55`, `OCHORD`) followed by lowercase `f`; it has not yet reached the `enter file command` gate.
## 2026-07-18 illegal-opcode investigation checkpoint

- Added `investigations/bs2-folder-init-illegal-opcode.md` as the required competing-hypothesis record for the active flash slice.
- The native core's DD-prefix illegal handler proves that `Z180 'z180' ill. opcode $d1 $11` reports fetched bytes from memory: the first byte is read at `PC - 1` and the second at `PC` after the prefix fetch. They are not register values.
- The current CFFI `debugger_instruction_hook` only services CSI/O; it does not expose a trace callback. The existing Python CPU wrapper does expose `pc`, `bbr`, `cbr`, `cbar`, and single-instruction `step()`.
- Therefore changing the native bridge is not yet justified. The next diagnostic should use existing stepping to retain a short pre-instruction ring of PC, MMU state, high-bank latch, and fetched bytes while driving the exact initialization responses.
- Repo status confirms the active source slice is still confined to `qns/bns.py`, `qns/memory.py`, `tests/test_bns.py`, and `tests/test_memory.py`, plus the investigation record. User-owned tracked changes remain untouched.
- A bounded repo-file search did not find the BSNEW C source under `roms`; the already-established external source location must be located explicitly before source comparison.
## 2026-07-18 pre-trace checkpoint

- Added `tools/trace_bs2_folder_trap.py` for the current investigation. It boots normally, counts actual calls to the existing keyboard `press` owner, switches to single-instruction execution only after the third delivered key, and stops before executing a fetched `DD D1` sequence.
- The trace uses the Z180 core's exact `z180_mmu` formula to report logical PC, physical address, `CBR`, `BBR`, `CBAR`, high-bank latch, and eight mapped bytes. It does not patch the emulator or native core and does not save state.
- `uv run ruff check tools\trace_bs2_folder_trap.py` passes, and its `uv run python ... --help` import/CLI check passes.
- Pre-run SHA-256 for `C:\Users\Q\AppData\Local\Temp\qns-bs2-init2-20260718.state` is `144B2BD595B0E8ACC31072120092742D85443A11CEA3B69B8819997A39833348`.
- Next action: run this exact diagnostic against `roms\NFB99\BS2ENG\bs2eng.bns`, send prompt-paced lowercase `y`, `y`, `y`, and record the first pre-trap frame.
## 2026-07-18 causal-order correction

- The prior statement that a third lowercase `y` for folder initialization caused `Z180 'z180' ill. opcode $d1 $11` was wrong.
- In the prompt-paced trace run, only two keys had been delivered (`[Trap trace] delivered key 2: raw=0x3D`) when flash work and repeated mapped writes proceeded. The illegal opcode then occurred without any third key being sent.
- Therefore the trap occurs during the affirmative flash-initialization path after the second confirmation and before the folder-initialization response. The earlier third `y` was sent after the trap/restart and cannot explain the earlier failure.
- The current blocker is now precisely the flash-initialization control/data path. Folder initialization is not yet reached.
- The diagnostic's arm threshold of three keys was based on the false ordering and missed the pre-trap frame. The next action is to stop this unsaved process, change only that threshold to two delivered keys, and rerun the same two prompt-paced responses.
## 2026-07-18 prefix-trace correction

- The two-key-armed tracer did not stop at the known illegal-prefix path because its condition matched only `DD D1`.
- The Z180 core uses the same one-byte illegal-prefix behavior for both IX (`DD`) and IY (`FD`) prefixed opcodes; the native message reports the second opcode and following byte, so `$d1 $11` does not identify which of `DD` or `FD` preceded it.
- This is a diagnostic defect, not new emulator evidence. The process remains unsaved and must be stopped exactly.
- Next action: stop the exact leaf process, widen only the diagnostic prefix match to `(DD or FD) D1`, preserve the same two-key arm point, and rerun from the unchanged state hash.
## 2026-07-18 corrected prefix diagnostic result

- The corrected tracer armed after exactly two delivered keys and matched either `DD D1` or `FD D1`, but it still did not observe that prefix pair before the native core reported `Z180 'z180' ill. opcode $d1 $11`.
- The run spent approximately 45 seconds calling the native execute wrapper with a cycle budget of one after key 2. The native trap still occurred inside one of those calls and the firmware restarted; no third key was sent and no folder prompt was reached.
- This proves the Python wrapper observation is not presently an instruction-boundary trace of the failing fetch. The remaining live hypotheses are that `qns_z180_execute(cpu, 1)` can cross the failing prefix path before returning, or that the Python logical-to-physical fetch reconstruction diverges from the core's actual fetch.
- The exact leaf process was stopped without saving. The state file SHA-256 remains `144B2BD595B0E8ACC31072120092742D85443A11CEA3B69B8819997A39833348`.
- Next action: inspect the existing `qns_z180_execute` wrapper and native execute-loop cycle semantics, including pre/post PC behavior. Add a native pre-instruction trace only if that inspection proves the current wrapper cannot expose the failing instruction boundary.
## 2026-07-18 trap-transition diagnostic checkpoint

- Source inspection establishes that `qns_z180_execute(cpu, 1)` asks the native core for one cycle and the core completes one whole instruction before returning. However, `cpu_execute_z180` calls `check_interrupts` before `debugger_instruction_hook` and the opcode fetch, so a pending interrupt can replace the Python pre-call PC with its vector target.
- That ordering explains why the corrected pre-call `DD D1`/`FD D1` matcher could miss the native failing fetch without requiring the execute wrapper to run multiple ordinary instructions.
- The existing native illegal-prefix path sets bit `0x80` (`TRAP`) in Z180 register `ITC` (`0x34`) during the same execute call. The diagnostic now watches the transition of that exact native state after each one-cycle call, reconstructs the two-byte instruction start from post-call PC, and prints its MMU mapping plus the preceding pre-call ring.
- `uv run ruff check --fix tools\trace_bs2_folder_trap.py` corrected only import ordering and now passes.
- Current blocker: the exact PC, mapping, and bytes of the trap-producing instruction are still unknown; no emulator behavior has been changed by this diagnostic.
- Next action: rerun this exact two-key prompt-paced diagnostic from the unchanged state, capture the first `ITC.TRAP` transition, and stop without saving.
## 2026-07-18 exact BS2 trap capture

- The prompt-paced run delivered exactly two lowercase `y` responses and no third key. The diagnostic stopped on the first native `ITC.TRAP` transition without saving state.
- Exact trap state: logical instruction PC `0xC37B`, physical address `0x4037B`, `CBR=0x34`, `BBR=0x00`, `CBAR=0xC6`, and `HICLK=0x00`. The memory callback bytes were `FD 00 00 00 00 00 00 00`; the executed illegal prefixed instruction was therefore `FD 00`.
- The earlier interpretation of `Z180 'z180' ill. opcode $d1 $11` as the fetched instruction bytes was wrong. `ROP` correctly applies `MMU_REMAP_ADDR` before calling `read_raw_byte`, but `illegal_1` logs by calling `read_raw_byte` directly with logical `PC-1` and `PC`. At this MMU state, the logger therefore reread physical `0x0C37C..0x0C37D` instead of the actual fetch at physical `0x4037C..0x4037D`.
- The preceding mapped bytes at `0x40371` were `6F F0 36 01 00 08 1E 02 00 55 FD 00`. Execution had entered bytes that look like data rather than a valid routine, so the remaining fault is an earlier control-flow or RAM-content error, not a CPU implementation of a real `D1 11` instruction.
- The process exited through the diagnostic's `KeyboardInterrupt` path. The state file SHA-256 remains `144B2BD595B0E8ACC31072120092742D85443A11CEA3B69B8819997A39833348`.
- Correction: treating the optional BSNEW source/link map as a required user-supplied artifact was an invented blocker and a misuse of the momentum rule. The authorized runtime investigation can distinguish the remaining causes without it.
- Current blocker: none external. The active flash slice remains uncommitted and must be either proven and committed or fully reverted before another source slice begins.
- Next action: extend the existing diagnostic to capture the first control-flow entry into logical `0xC300..0xC3FF`, including prior PC, SP, stack bytes, MMU state, and mapped instruction bytes. Use that evidence to distinguish a corrupted jump/return/interrupt target from sequential execution into corrupted RAM.
## 2026-07-18 BS2 C300 return capture

- The first-entry diagnostic reproduced and exited cleanly without saving. `RET` at logical/physical `0x01F8` ran with `SP=0xFFFE`, popped bytes `00 C3` from physical `0x43FFE`, and entered logical `0xC300` with `SP=0x0000`.
- At that moment `CBR=0x34`, `BBR=0x00`, and `CBAR=0xC6`, so logical `0xC300` mapped to physical `0x40300`. The full mapped context from logical `0xC2E0..0xC31F` was zero-filled.
- This rules out a valid `CALL` ending at `0xC300`; there is no call instruction at logical `0xC2FD`. The later `FD 00` trap results from execution continuing through this zero-filled RAM region.
- Current blocker: none external. The producer of the stack word `00 C3` at physical `0x43FFE` is not yet identified.
- Next action: trace writes to physical `0x43FFE..0x43FFF` after the second flash confirmation and record the producing PC, SP, MMU state, written value, and surrounding mapped bytes. This will identify whether an interrupt push preserved an already-invalid `0xC300` PC or another path created the bad return target.
## 2026-07-18 first 43FFF producer capture

- The physical-write diagnostic stopped at the first post-confirmation write to `0x43FFF`. Pre-call PC was logical `0xD67D` / physical `0x4167D`, the mapped opcode was `0x77` (`LD (HL),A`), `SP=0xD3FE`, and the write was `0x43FFF=0x00`.
- This is ordinary firmware memory clearing, not a stack push. It explains the initial zero but not the later high byte `0xC3` in the return word `00 C3`.
- Current blocker: none external. The later producer of `0x43FFF=0xC3` remains unidentified.
- Next action: keep observing the same address but stop only on `0x43FFF=0xC3`, then record the pre/post PC, SP, MMU state, mapped bytes, and any paired write to `0x43FFE`.
## 2026-07-18 deliberate C300 transfer identified

- The narrowed trace captured the exact producer of `00 C3`: pre-call PC `0x01B1` executed `DD E5` (`PUSH IX`) with `SP=0x0000`, writing `0x43FFE=0x00` and `0x43FFF=0xC3`; post-call SP was `0xFFFE`.
- Firmware therefore deliberately places `IX=0xC300` on the stack. The later `RET` at `0x01F8` is a computed transfer to that IX target, not a corrupt return address.
- The proven fault is now missing executable contents at logical `0xC300` / physical `0x40300`: firmware intentionally transfers there, but the mapped region remains zero-filled and eventually reaches the `FD 00` trap.
- Current blocker: none external. The copy/load operation that should populate physical RAM `0x40300` has not yet been identified or verified.
- Next action: inspect the ROM bootstrap bytes around `0x01B1..0x01F8` and the Z180 DMA implementation/register path, then trace nonzero writes to physical `0x40300..0x403FF` to determine why the intended code is absent.
## 2026-07-18 bootstrap and DMA source inspection

- Finding: package bytes at firmware logical `01B1..01F8` show a context save/restore routine, not a RAM population routine. It begins with `PUSH IX`, saves registers, calls `5F7B`, restores registers and `SP`, enables interrupts, and returns.
- Finding: the earlier `00 C3` stack word is therefore deliberate preservation/return state for `IX=C300`; the unexplained failure remains that physical RAM `40300..403FF` is zero when execution resumes there.
- Observation: native Z180 DMA channel 0 explicitly implements fixed-destination modes `DMODE=20/24` as well as incrementing and decrementing destination modes. Repeated writes to physical `4215C` do not alone prove a DMA defect.
- State: the active flash source slice remains uncommitted in `qns/bns.py`, `qns/memory.py`, `tests/test_bns.py`, and `tests/test_memory.py`. User-owned changes in `CLAUDE.md` and the speech/synth files remain untouched. The exact uppercase `O`, lowercase `f`, spoken `Enter file command` gate is still not reached.
- Blocker: the intended population path for the executable continuation at logical `C300` is not yet identified; live evidence is needed for target-region writes and DMA state before `01B1` executes.
- Next action: change `tools/trace_bs2_folder_trap.py` to collect writes to physical `40300..403FF`, stop immediately before logical PC `01B1`, and report the target contents plus `SAR0`, `DAR0`, `BCR0`, `DSTAT`, `DMODE`, and `DCNTL`. Run it with the unchanged saved state and exactly two prompt-paced lowercase `y` responses.
## 2026-07-18 first post-confirmation interrupt is downstream

- Finding: the first `01B1` entry after the second lowercase `y` is not the later `C300` return. Before that entry, the CPU was already executing zero bytes sequentially at logical `DA99..DAB8`, physical `41A99..41AB8`.
- Observation: a maskable interrupt then correctly pushed continuation `DAB9` to physical stack `43FFE`, vectored through logical `0038` and `012B`, and reached the generic context handler at `01B1` with `IX=FFFF`. The handler is downstream of the original loss of control flow.
- Correction: stopping at `01B1` cannot identify the first cause. Earlier claims that the `C300` handler instance was the initial corruption were too late in the event sequence.
- State: the saved-state SHA-256 remained `144B2BD595B0E8ACC31072120092742D85443A11CEA3B69B8819997A39833348`; both diagnostics exited without saving. The active flash source slice remains uncommitted and isolated; the uppercase `O`, lowercase `f`, spoken `Enter file command` gate remains unverified.
- Blocker: the exact instruction that first transfers or falls through from valid firmware code into zero RAM after the second confirmation is not yet captured.
- Next action: change the diagnostic to count consecutive post-confirmation `00` opcodes, stop on the first run of 16, and print a sufficiently large preceding ring containing the last nonzero instruction and the transition. Do not stop on the later interrupt handler or retrace the known `C371..C37B` data writes.

## 2026-07-18 BS2 SLP continuation root cause

- Finding: the first transition into high logical memory after the second lowercase `y` is a legitimate `CALL D655` at logical `0A83`. The target bytes are `ED 76 C9 70 61 67 65 20`: Z180 `SLP`, `RET`, followed immediately by the ASCII string `page`.
- Observation: on entry to `D655`, the stack contains the correct caller continuation `0A86`. Correct wake behavior must resume at `D657`, execute `RET`, and return to `0A86`; the failing run instead begins invalid execution at `D658`, exactly one byte after the `RET`.
- Root cause: native `SLP` sets the shared `HALT` state after its two-byte opcode has advanced PC to `D657`, while `LEAVE_HALT` unconditionally increments PC. That HALT-specific increment advances SLP wake-up to `D658` and skips the `RET`.
- State: the saved-state SHA-256 remains `144B2BD595B0E8ACC31072120092742D85443A11CEA3B69B8819997A39833348`; diagnostics exited without saving. The active flash slice remains uncommitted in `qns/bns.py`, `qns/memory.py`, `tests/test_bns.py`, and `tests/test_memory.py`. The uppercase `O`, lowercase `f`, spoken `Enter file command` gate remains unverified.
- Blocker: none external. The owning QNS build/bridge boundary and the exact regression-test surface still need to be identified before changing implementation.
- Next action: inspect the QNS native build inputs and the earlier HALT-continuation change, add a focused `CALL; SLP; RET` wake regression at the owning boundary, correct the continuation semantics, and rerun the real BS2 gate.

## 2026-07-18 SLP ownership checkpoint

- Finding: `z180ops.h` implements ordinary `HALT` by decrementing PC and setting `HALT=1`; `LEAVE_HALT` clears any nonzero HALT state and increments PC. `SLP` sets `HALT=2` without decrementing PC, proving the one-byte wake overshoot in the native core.
- Observation: QNS tracks `tools/build_ffi.py` but intentionally ignores generated `qns/_z180_cffi.c` and the compiled `.pyd`. The build recipe compiles the clean external checkout at `C:\Users\Q\src\z180emu`; a generated-artifact-only change would be non-reproducible and is not an acceptable fix.
- State: the isolated BS2 flash improvement passed `uv run pytest tests\test_memory.py tests\test_bns.py -q` with 19 tests and was committed as `86b5784`. User-owned tracked changes remain untouched.
- Blocker: none external. A focused native integration regression has not yet been added, so the failure must be captured in a test before changing `z180emu`.
- Next action: add a QNS `CALL; EI; SLP; RET` program test that wakes on IRQ0 and must reach its caller continuation, run it to prove the current failure, then correct the native SLP/HALT continuation in its owner.

## 2026-07-18 SLP fix and live-gate preparation

- Finding: the new native integration regression executes `CALL` into `EI; SLP; RET`, wakes through an IM1 IRQ/`RETI`, and requires the caller to write `0x42` to RAM. It failed before the native fix with RAM still `0x00`, exactly matching the skipped-`RET` diagnosis.
- Fix: `C:\Users\Q\src\z180emu\z180\z180ops.h` now increments PC in `LEAVE_HALT` only when the state is ordinary `HALT=1`; `SLP=2` already points at the following instruction and is left unchanged.
- Verification: rebuilding with `uv run tools\build_ffi.py` succeeded. The exact regression now passes, and `uv run pytest tests\test_cpu.py -q` reports 4 passed.
- Observation: the tracked launcher is `uv run -m qns.bns`; `qns.bns --help` confirms the ROM, `--model bs2`, `--input keyboard`, `--cycles`, and `--state` contract. Normal completion with `--state` saves, so a preserved diagnostic state must not be passed to a run that may complete normally unless saving it is intended.
- State: QNS has an uncommitted `tests/test_cpu.py` regression and the clean-before-change external `z180emu` checkout has the one-file native fix. The rebuilt generated CFFI files remain intentionally ignored. The real uppercase `O`, lowercase `f`, spoken `Enter file command` gate is still unverified after the fix.
- Blocker: none external.
- Next action: launch the real BS2 firmware with the existing QNS entry point and a disposable copy of the unchanged state, answer the initialization prompts as required, then send uppercase `O` followed by lowercase `f` and capture the spoken result.

## 2026-07-18 BS2 file-manager gate passes

- Live evidence: `bs2eng.bns` ran through `uv run -m qns.bns` with the BS2 profile and a disposable copy of the verified state. Two prompt-paced lowercase `y` confirmations completed flash initialization without the former illegal opcode or firmware restart.
- Exact gate: after post-initialization work settled, uppercase terminal `O` was sent as its own O-chord event, followed by lowercase `f` as its own event.
- Result: the final phoneme groups were `EH N T ER` and `F AH E L K UH M AE N D`, unambiguously speaking `Enter file command`. The preceding groups also spoke the flash/folder status path, proving this was the real firmware workflow rather than a synthetic assertion.
- Process state: the unique disposable-session tree was verified by command line. Only leaf emulator PID `188756` was stopped; the PTY then exited with status 1 before CLI post-run state saving.
- State: the SLP slice consists of the QNS regression in `tests/test_cpu.py` and the native owner fix in `C:\Users\Q\src\z180emu\z180\z180ops.h`. The focused regression and all four native callback tests pass. The slice is not yet committed in either Git repository.
- Blocker: none external.
- Next action: verify both the preserved and disposable state hashes, inspect both repositories' exact diffs, then commit the kept SLP fix and regression before starting BS2 file create/read/delete/restart verification.

## 2026-07-18 BS2 file lifecycle authority

- State verification: both `qns-bs2-init2-20260718.state` and the disposable `qns-bs2-slp-gate-20260718.state` retained SHA-256 `144B2BD595B0E8ACC31072120092742D85443A11CEA3B69B8819997A39833348`; no live emulator remained after the gate run.
- Git state: the native owner fix is committed in `C:\Users\Q\src\z180emu` as `89de628`; the QNS regression is committed as `53f5c0c`. The SLP slice is closed.
- Help authority: `roms\NFB99\BS2ENG\bs2eng.hlp` is a 31,935-byte carriage-return-delimited text help file. Its `File Commands` section specifies: enter file menu with O-chord then `f`; create with `c`; open with `o`; delete with `d`; exit with e-chord.
- Naming behavior: files without an extension, or with `brl`, `brf`, `bfm`, or `br?`, are grade-2 files; other extensions are computer Braille. Search accepts partial names and wildcards via f-chord.
- Reading authority: the help specifies c-chord to speak the current line, l-chord to move to the top of a file, and e-chord as the normal command/string terminator where prompted.
- Blocker: the terminal mappings for e-chord and c-chord must be taken from the existing keyboard table before sending a filename/content lifecycle; they must not be guessed.
- Next action: inspect the existing terminal-to-raw key table for the exact e-chord/c-chord characters, then use the help-defined commands to create a uniquely named file, write known content, read it, save state, restart, reopen/read it, delete it, and verify absence.
## 2026-07-18 BS2 file lifecycle live checkpoint

- Active finite emulator session: PTY session `60258`.
- Command state path: `C:\Users\Q\AppData\Local\Temp\qns-bs2-file-lifecycle-20260718.state`.
- The disposable lifecycle state was copied from the preserved initialized BS2 state before launch.
- The live firmware accepted lowercase `y`, lowercase `y`, uppercase `O`, then lowercase `f`; its SSI-263 output decoded as `Enter file command`.
- Lowercase `c` produced the firmware prompt `Enter file to create`.
- The ordinary filename text `qnstest.txt` has been entered. The filename has not yet been terminated.
- The emulator is still running, so this lifecycle state has not yet been saved.
- Exact next input is uppercase `E` to terminate the filename, followed by ordinary test content and uppercase `C` to request the current line. The finite run must then end normally so the nonvolatile state is saved.

### File-create/open result

- Uppercase `E` terminated the create filename and the finite run exited `0`, reporting `Executed 1,000,000,000 cycles` and `Saved nonvolatile RAM state`.
- The lifecycle image became 2,686,992 bytes with SHA-256 `CA12DEB8ECC4CE462092C50E85EA30BAAE83103303402C61DC3DC12A39268EFA`; the initialized source image remained 589,836 bytes with SHA-256 `144B2BD595B0E8ACC31072120092742D85443A11CEA3B69B8819997A39833348`.
- On the first restart I incorrectly substituted an assumption that the created file remained open for the required explicit reopen sequence. I typed content while the firmware was still in its startup/help context. That run was stopped at the exact emulator leaf before it could save; the lifecycle image retained the `CA12...EFA` hash.
- A clean restart then followed the required sequence literally: uppercase `O`, lowercase `f`, lowercase `o`, ordinary `qnstest.txt`, uppercase `E`.
- The firmware spoke `flash folder`, `no open`, and `Enter file command` after `O`, `f`; lowercase `o` spoke `file to open`.
- After the filename terminator the firmware spoke `can't find that file`, then returned to `Enter file command`.
- Therefore the changed flash image is not yet proof that `qnstest.txt` was created. The active session is PTY `21290`, currently back at the file-command prompt. The next diagnostic is the firmware's own file-search command to determine what file entries exist.

### Readable create reproduction

- The emulator has no quiet flag. A new unlimited run was started with its output filtered to load/start, phoneme, speech, stop, execute, and save lines; PTY session `20751`.
- Source inspection confirms `KeyboardInterrupt` returns from `BNS.run()` and the CLI then calls `save_state()`. Force-stopping the exact Python leaf bypasses that save.
- In the firmware file menu, lowercase `l` spoke `file list` followed by storage/page totals and no filename. This confirms the earlier finite create attempt did not leave a directory entry.
- The create sequence was then reproduced in the readable session. Lowercase `c` spoke `Enter file to create`; the prompt was allowed to finish completely before ordinary `qnstest.txt` and uppercase `E` were entered.
- This time the terminator produced no error and left the file menu, consistent with successful create/open.
- Ordinary `qns file test` was then entered. After speech became idle, uppercase `C` spoke `every` (`EH V ER E`) rather than the expected line.
- The current mutation has not been saved. The next diagnostic is the firmware's `O`, `f`, `t` sequence (`Tell name of open file`) to distinguish wrong-open-file state from incorrect ordinary-character encoding.

### Stdin burst root cause evidence

- The firmware's `O`, `f`, `t` response decoded as `T, one page, Braille file, is open`.
- The intended filename burst was `qnstest.txt`; the open filename being only its last character, `t`, proves the burst collapsed before the firmware could consume its characters.
- The earlier saved lifecycle image therefore contains a file named `t`, not `qnstest.txt`. The apparent file-list output is consistent with that one-character entry.
- The readable reproduction session was force-stopped at exact Python leaf PID `87120`, so its additional unsaved mutation did not overwrite the lifecycle image.
- Git accountability check before source work: branch `master`, ahead of `origin/master` by 2. User-owned tracked modifications remain limited to `CLAUDE.md`, `qns/ssi263.py`, `qns/synth/__init__.py`, and `qns/synth/ssi263_synth.py`; they must not be touched.
- Code search locates keyboard stdin queuing and delivery in `qns/bns.py` lines 405-453 and keyboard latch behavior in `qns/io.py` lines 179-244. Existing keyboard tests are in `tests/test_bns.py` and `tests/test_io.py`.
- Next action: read the exact queue-to-latch state machine and existing tests, add a failing regression for a multi-character burst, then repair only that handoff and commit the slice if it produces the kept reduction.

### Pacing hypothesis falsified; RTC dialog identified

- Reading `qns/bns.py` shows stdin characters are queued, and each next character is withheld until the preceding key-down and key-up latches have both been acknowledged by firmware.
- A real-ROM reproduction with `--trace-interrupts` entered a new filename one character at a time. Each of `a`, `b`, `c`, and terminating uppercase `E` produced a complete INT2 sequence: press assert/clear followed by release assert/clear.
- Therefore the evidence does not support host queue byte loss, and no source edit has been made.
- Immediately after uppercase `E`, the firmware spoke `Reset clock, first date, then time`.
- This corrects the earlier interpretation: `qns file test` was not necessarily collapsed or written to a one-character file. It was entered while the firmware's clock-setting dialog had taken control, and uppercase `C` then spoke dialog-derived content rather than a file line.
- The active unsaved trace session is PTY `24563`. Its test filename entry is not durable.
- Next action: allow the RTC prompt to finish, inspect the emulator's MSM6242 register contract against the firmware-visible values and existing tests, then either supply the exact prompted date/time or fix the RTC surface if current evidence proves it invalid.

### Clock dialog input

- `MSM6242RTC` currently exposes a direct 0x60-0x6F BCD register bank with current host date/time, year, and Sunday-zero weekday. Existing tests cover the BSP contract; no BS2-specific clock authority has yet been found in the ROM bundle.
- The BS2 help specifies dates as `mmddyyyy` and the live dialog explicitly said date first, then time.
- The active unsaved firmware session accepted date `07182026`, uppercase `E`, time `1903`, and uppercase `E`. Each character produced complete INT2 press and release acknowledgements, and the firmware produced no invalid-input or repeated-clock message after either terminator.
- This session also contains the unsaved paced filename `abc` created immediately before the clock dialog appeared.
- Next action: issue `O`, `f`, `t` after idle. If the firmware enters the file menu and names `abc` as open, that proves the clock dialog exited and the full paced filename survived. Then write/read persistence can continue before deciding whether any RTC source fix is required.

### Clock input not accepted as proof

- After date/time entry, later speech again contained `Reset clock, first date, then time`. Silent terminators therefore were not sufficient evidence that the dialog accepted the values or that the BS2 RTC was valid.
- The attempted `O`, `f`, `t` verification became interleaved with repeated clock speech and did not yield a trustworthy open-filename result.
- The entire paced filename/date/time reproduction remained unsaved and was discarded by force-stopping exact Python leaf PID `85308`.
- No source files were edited. The saved lifecycle image remains the prior finite-run image, known to contain at most the earlier one-character `t` entry.
- Current blocker inside file lifecycle: the BS2 firmware repeatedly judges the emulated clock invalid. Existing RTC tests validate only the BSP-style MSM6242 contract and do not explain BS2 behavior.
- Next action: run a disposable BS2 session with I/O tracing filtered to ports `0x60` through `0x6F`, capture the ROM's exact clock register access pattern and values, and compare that evidence with the emulator mapping before proposing a source change.

### BS2 clock is not the BSP MSM6242 window

- Disposable trace state: `C:\Users\Q\AppData\Local\Temp\qns-bs2-rtc-trace-20260718.state`, copied from the lifecycle image.
- A 600,000,000-cycle BS2 boot trace with `--trace-io` produced zero reads or writes at ports `0x60` through `0x6F`.
- Therefore the existing BSP MSM6242 mapping cannot explain or satisfy the BS2 ROM's clock behavior.
- Unique BS2 I/O directions during the same window were: reads from `0x40`, `0x80`, and `0x81`; writes to `0x83`, `0xA0`, `0xC0` through `0xC4`, and `0xE0`.
- Port `0x40` is the keyboard; `0xC0`-`0xC4` are SSI-263; `0x83` is the current 8255 control register; `0xA0` is the combined power latch; and `0xE0` is the bank latch. The unexplained BS2 input surfaces are 8255 ports `0x80` and `0x81`, which the emulator currently returns as `0xFF`.
- Next action: extract the exact values and access cadence for reads of `0x80` and `0x81`, then locate hardware/firmware evidence for the BSNEW 8255 input wiring before implementing anything.

### Authoritative BSNEW clock source corrected

- Port-value tracing confirms reads of `0x80` and `0x81` are both currently fixed at `0xFF`, 320 reads each over a 200,000,000-cycle sample.
- Authoritative local firmware source exists at `C:\Users\Q\src\bns\bsp`; the BS2/BSNEW image is selected by conditional `BSNEW` code in that common source tree.
- The earlier claim that `CLOCK.C` defined the BSNEW clock was wrong. The entire relevant implementation in `CLOCK.C` is guarded by `#if T_LITE`; its DS1306-style register map and wiring do not build into BSNEW and are not authority for BS2.
- The actual BSNEW clock source is `TNSCLK.C`, guarded by `#if TNS | B_LITE_40 || BSNEW`. It models a PIC 16C56 clock connected through the Z180 CSIO path.
- PIC-to-firmware bytes use the top three bits as the field selector: `0x20` minutes, `0x40` month, `0x60` day, `0x80` year since 1989, and `0xA0` hour. The firmware sends command `4` to request date/time; `TIMENEW.C::get_clock_values` reports `Reset clock, first date, then time` when the expected CSIO response never updates `year` before timeout.
- `TIMENEW.C::send_time` sends the minute and hour field bytes, while `send_date` sends month, day, and encoded year. `send_to_clock` transmits through CSIO, pulses 8255 port-C bit 4 with control writes `0x09` then `0x08`, and enables CSIO receive interrupts with `CNTR=0x67`.
- QNS already exposes native `csio_rx` and `csio_tx` callback boundaries in `qns/cpu.py`, but `qns/bns.py` does not wire a BSNEW clock device to them. The existing `MSM6242RTC` mapping is the separate BSP direct-port contract and must not be substituted for BS2.
- No source code has been changed in this investigation slice. Current blocker: BS2's date/time request receives no PIC response, so the file lifecycle cannot complete normally.
- Next action: verify the native CSIO receive-interrupt behavior and its existing tests, then add a focused failing BSNEW clock contract at the real CPU/device boundary before implementing and wiring the PIC protocol.

### Native CSIO interrupt gap verified

- `qns/_z180_cffi.c::service_csio` and its source in `tools/build_ffi.py` already transfer CSIO transmit bytes to Python and copy a Python receive byte into `TRDR`. The existing `test_csio_exchange_crosses_native_callback_boundary` proves only this polling path.
- On receive, the bridge clears `CNTR.RE` but never sets `CNTR.EF` and never marks the core's `Z180_INT_CSIO` pending. A firmware path that waits for its CSIO ISR therefore cannot observe the byte.
- The native core defines CSIO as internal interrupt index 9 and dispatches internal vectors as `IL + (irq - Z180_INT_IRQ1) * 2`; CSIO is consequently `IL + 0x0C`.
- BSNEW firmware's vector table agrees exactly: `.int5` loads `csioint`. That ISR disables CSIO interrupts, reads `TRDR`, calls `_pic_to_tns`, then writes `CNTR=0x67` to receive the next byte and returns with `RETI`.
- `CSIO_ON` writes `CNTR=0x07` followed by `0x67`. `send_to_clock` writes the command to `TRDR`, enables transmit with `0x17`, pulses 8255 C4, waits for `TE` to clear, then restores receive interrupts with `0x67`.
- Git pre-edit check: `master` is ahead of `origin/master` by two commits. The only tracked modifications are the four user-owned paths `CLAUDE.md`, `qns/ssi263.py`, `qns/synth/__init__.py`, and `qns/synth/ssi263_synth.py`; they remain out of scope and untouched.
- Current blocker: both the BSNEW clock device and the native CSIO receive interrupt assertion are absent.
- Next action: add one focused CPU test that installs an IM2 handler at `IL+0x0C`, enables CSIO receive interrupts, and requires the handler to consume the callback byte. Run it against the unchanged bridge and confirm the expected failure before editing implementation.

### Native CSIO interrupt slice passes

- Added `test_csio_receive_raises_internal_interrupt`, using the real firmware shape: IM2, `IL=0x40`, vector entry `0x4C`, `CNTR=0x67`, and an ISR that reads `TRDR` and stores the callback byte.
- Against the unchanged bridge, the test failed exactly as predicted: the Python callback byte was consumed but the ISR never ran, leaving the destination byte zero.
- The upstream core now owns CSIO completion semantics through `z180_set_csio_completion`: completion sets `CNTR.EF`, and asserts the internal CSIO interrupt only when `CNTR.EIE` is enabled. Reading `TRDR` clears `EF` and the pending interrupt. A `CNTR` write reconciles the pending state from `EF|EIE`.
- `tools/build_ffi.py::service_csio` now signals completion after either transmit or receive finishes, after first clearing the corresponding `TE` or `RE` bit.
- Rebuilt the native CFFI extension successfully with `uv run tools/build_ffi.py`. The pre-existing upstream compiler warnings remain; no new build error occurred.
- The focused real-ISR test now passes and reports the ISR read `TRDR=$8A`.
- Current source slice spans the clean upstream Z180 repository (`z180/z180.c`, `z180/z180.h`) and QNS (`tools/build_ffi.py`, `tests/test_cpu.py`). No BS2 clock-device code has started, and the user-owned tracked QNS modifications remain untouched.
- Next action: run the complete `tests/test_cpu.py` authority. If it passes, inspect both repository diffs, commit the upstream core portion and then the QNS bridge/test portion before starting the distinct BSNEW clock-device slice.

### Native CSIO core committed

- Full `tests/test_cpu.py` authority passes: 5 tests, including polling CSIO exchange, real IM2 CSIO interrupt delivery, ASCI transmit/receive, and SLP interrupt continuation.
- Diff inspection confirmed the upstream slice contains only 16 inserted lines in `z180/z180.c` and `z180/z180.h`. Those files are deliberately stored as CRLF in the repository (`i/crlf w/crlf`), and were normalized to that existing contract before staging.
- Committed the upstream core portion as `8933e04` (`Implement Z180 CSIO completion interrupts`). The upstream worktree was clean before this slice and the commit contains exactly the two intended files.
- The QNS half remains uncommitted and consists only of `tools/build_ffi.py` plus `tests/test_cpu.py`. The generated CFFI C/PYD outputs are ignored build products.
- Current blocker for the BS2 file lifecycle remains the absent BSNEW clock PIC device and its BNS wiring; the required native interrupt path is now implemented and committed upstream.
- Next action: stage exactly `tools/build_ffi.py` and `tests/test_cpu.py`, inspect the staged ledger, commit that QNS half, then begin the separate BSNEW clock-device slice from a reconciled Git state.

### BSNEW clock-device slice begins

- Committed the QNS bridge/test half as `410714d` (`Deliver Z180 CSIO completion interrupts`), containing exactly `tools/build_ffi.py` and `tests/test_cpu.py`. QNS is now ahead of origin by three commits; the four user-owned tracked modifications remain the only tracked worktree changes.
- The upstream Z180 repository is clean and ahead of origin by two commits after `8933e04`.
- Current `BNS` always constructs the BSP `MSM6242RTC`, does not construct a BSNEW clock PIC, and passes no `csio_rx`/`csio_tx` callbacks to `Z180`. Its BS2 8255 implementation merely stores raw writes; it does not implement bit-set/reset control or the C4 clock strobe.
- Firmware authority establishes the clock command boundary: `send_to_clock` transmits one CSIO byte, writes 8255 control `0x09` to set C4 and latch it into the PIC, then writes `0x08` to clear C4. The device must therefore hold a pending transmitted byte until the C4 rising edge.
- Command `4` requests current date/time. PIC responses are field-tagged bytes for minute, month, day, hour, and year; minute values above 31 require the separate `0x05` high-bit indication handled by `pic_to_tns`. The year response must be last because `get_clock_values` uses the changed year value as the completion sentinel.
- The five-bit year protocol represents 1989 through 2020 only. Tests for the literal hardware protocol must use a representable year; current-host dates after 2020 will necessarily follow the physical protocol's five-bit behavior unless later evidence proves an extension.
- Existing BS2 tests cover only combined power fields, raw 8255 control storage, high-bank wiring, and flash size. They do not cover 8255 bit-set/reset semantics, C4 strobes, or CPU CSIO callback wiring.
- Current blocker: no concrete BSNEW PIC clock device exists to respond to ROM command `4`.
- Next action: add focused failing peripheral and BNS wiring tests for command-4 field responses, year-last completion, C4 rising-edge latching, and CSIO callback ownership; then implement only that proven clock/strobe surface.

### BSNEW clock PIC live gate passes

- Added focused tests for the concrete PIC command/strobe response and BS2 callback/8255 ownership. They initially failed at import because no `PIC16C56Clock` existed.
- `qns/io.py` now provides the concrete BSNEW PIC device at the source-defined boundary: `transmit` holds a CSIO byte, `strobe` latches it, command `4` queues minute/month/day/hour/year field bytes with the year sentinel last, and `receive` returns one pending byte at a time.
- `qns/bns.py` constructs the PIC only for `model="bs2"`, passes its receive/transmit methods directly to `Z180`, and implements the 8255 bit-set/reset command needed for C4. A mode-set command resets port-C output latches; `0x09` produces one C4 rising strobe and `0x08` clears it.
- The two focused tests pass. The full relevant authority also passes: 25 tests across `tests/test_io.py`, `tests/test_bns.py`, and `tests/test_cpu.py`.
- Live disposable state `C:\Users\Q\AppData\Local\Temp\qns-bs2-clock-pic-20260718.state` was copied from the recorded 2,686,992-byte lifecycle image. The tracked launcher is running the real `bs2eng.bns` ROM with `--model bs2`, keyboard stdin, one billion cycles, and only that disposable state in PTY session `29135`.
- Exact live input was uppercase `O` followed only after its transaction by lowercase `f`. The firmware spoke `flash folder`, `no open`, then the phoneme sequence for `Enter file command`. It did not speak `Reset clock`.
- This proves the real ROM's `send_to_clock(4)` command crossed the 8255 C4 strobe, received PIC field bytes through native CSIO interrupts, completed `get_clock_values`, and returned to the file menu.
- Current source slice remains uncommitted in `qns/io.py`, `qns/bns.py`, `tests/test_io.py`, and `tests/test_bns.py`. The active live session is at the file-command prompt.
- Next action: continue the same real-ROM session with lowercase `c`, enter a unique filename only after the create prompt, terminate it with uppercase `E`, then exercise known content and current-line speech without any clock dialog. Save normally and verify reopen/read/delete across restart before closing this slice.

### Persisted file reopened; content write repeated with documented insert command

- The first finite run created `picclock.txt` and saved the disposable state normally, but its cycle budget ended immediately after the raw content input. The directory entry persisted; the content did not.
- Restarted the real `bs2eng.bns` ROM from that exact disposable state for two billion cycles. Exact input was uppercase `O`, lowercase `f`, lowercase `o`, `picclock.txt`, then uppercase `E`, with prompt pacing between commands.
- The ROM found the persisted file and spoke the successful `now open` branch. Uppercase `C` then spoke `file is empty`, proving the directory persistence while rejecting any claim that the earlier content had been saved.
- The ROM's own `bs2eng.hlp` gives the exact write operation as `i-chord; text; e-chord`. With the empty persisted file open, the session received uppercase `I`, `clock path works`, then uppercase `E` in that documented order.
- The finite run ended normally immediately after a final uppercase `C`, before the readback speech completed, and saved `C:\Users\Q\AppData\Local\Temp\qns-bs2-clock-pic-20260718.state` again.
- Current source slice remains uncommitted and unchanged in scope: `qns/io.py`, `qns/bns.py`, `tests/test_io.py`, and `tests/test_bns.py`.
- Next action: restart that exact saved state, reopen `picclock.txt` through uppercase `O`, lowercase `f`, lowercase `o`, filename, uppercase `E`, and use uppercase `C` to verify the inserted line. Only after a successful readback, delete the file through the documented file-menu command and verify absence after another restart.

### Content readback remains unproven

- Restarted from the exact state saved after `I`, `clock path works`, `E`. The ROM again accepted uppercase `O`, lowercase `f`, lowercase `o`, `picclock.txt`, uppercase `E`, and spoke the successful `now open` branch.
- Uppercase `C` at the reopened cursor produced no retained non-pause phonemes. The ROM help then supplied the exact cursor/read sequence: uppercase `L` for top of file, uppercase `C` for current line, and raw dots `12456` for speak-to-end. The tracked terminal table maps `]` exactly to that raw `0x7B` chord.
- The speak-to-end operation generated a large output transaction, but the retained beginning and end were insufficient to identify text. Uppercase `H`, the documented hear-again command, repeated only pause phonemes. Therefore `clock path works` is not verified and the file-content gate has not passed.
- A raw ASCII scan of the saved state found neither `picclock.txt` nor `clock path works`; this is not evidence of absence because the firmware file representation is not plain ASCII in the state image.
- The two-billion-cycle run ended normally and saved the same disposable state before the subsequent uppercase `O` could be followed by lowercase `f` and the documented lowercase `i` file-information command.
- No delete command has been issued. The source slice is still the same four uncommitted clock-device files, and no implementation change was made during these live checks.
- Next action: restart with enough finite cycle budget for one paced transaction, reopen the persisted file, and use the ROM's `O`, `f`, lowercase `i` information command to establish its firmware-reported size before deciding whether content entry or speech decoding is the failing surface.

### Firmware reports the attempted content as one byte

- Restarted the exact disposable state with a four-billion-cycle finite budget, reopened `picclock.txt` through the required `O`, `f`, `o`, filename, `E` sequence, and remained in the same file lifecycle target.
- From the file menu, lowercase `i` prompted for a filename and returned the long file-information response for `picclock.txt`; the response identifies the persisted entry as a text file.
- The narrower size command is raw dots `156`, documented by the ROM help and mapped exactly to terminal `:` by `_ASCII_TO_BNS_KEY`. After `:`, `picclock.txt`, uppercase `E`, the ROM reported `one byte` and returned to `Enter file command`.
- Therefore the earlier batched `clock path works` input did not complete before the finite run ended. Directory persistence works, but the known-content write/read gate has not passed; the one-byte file must not be treated as successful content persistence.
- The launcher's tracked contract catches `KeyboardInterrupt`, returns from `run`, and then executes the normal post-run `save_state`, but no interrupt or termination has been sent in this session.
- Next action: while the current finite session remains at `Enter file command`, create a fresh uniquely named file and submit a short known value one character per completed keyboard transaction, terminate insertion with uppercase `E`, then move to top and read it back before allowing the run to save.

### Paced create/write/read passes and state saves normally

- In the same real-ROM session, lowercase `c` at `Enter file command` produced `Enter file to create`. Entered `paced.txt`, uppercase `E`; the ROM spoke the successful `now open` branch.
- Entered the documented write sequence with completed transactions between characters: uppercase `I` produced `insert mode active`, then lowercase `o`, lowercase `k`, and uppercase `E`.
- Uppercase `L` spoke `top of file`; uppercase `C` then emitted the exact phoneme sequence for `okay`. This is the first verified known-content create/write/read pass in the real BS2 ROM.
- The four-billion-cycle run was allowed to finish without interruption. It reported `Executed 4,000,000,000 cycles`, final PC `D657`, and normally saved `C:\Users\Q\AppData\Local\Temp\qns-bs2-clock-pic-20260718.state`.
- The earlier `picclock.txt` remains a separate one-byte failed attempt and is not evidence for the passing gate.
- Next action: restart from the exact newly saved state, reopen `paced.txt` through uppercase `O`, lowercase `f`, lowercase `o`, filename, uppercase `E`, then uppercase `L`, uppercase `C`; require the ROM to speak `okay` before proceeding to deletion.

### Persisted content reopens; delete confirmation is ambiguous

- Restarted the real `bs2eng.bns` ROM from the exact saved disposable state. The exact sequence uppercase `O`, lowercase `f`, lowercase `o`, `paced.txt`, uppercase `E`, uppercase `L`, uppercase `C` reopened the file and again emitted the phonemes for `okay`. This proves known content persisted across a normal save and restart.
- From the returned file-command prompt, the exact delete sequence uppercase `O`, lowercase `f`, lowercase `d` produced `Enter file to delete`; `paced.txt`, uppercase `E` produced the confirmation speech ending in `Are you sure?`.
- Lowercase `y` did not produce an unambiguous deletion acknowledgement. The subsequent speech included `Enter Y or N`, then `help is open`, then `Enter file command`. No claim of successful deletion is made from that response.
- No implementation change was made during this live verification. The active source slice remains the same four uncommitted clock-device files.
- Next action: allow the finite run to finish and save normally, restart from that exact state, then attempt to open `paced.txt` through the same file-manager sequence. The decision gate is the ROM's found/not-found result after restart.

### File lifecycle gate passes completely

- The two-billion-cycle delete run ended normally at PC `1BDA` and saved the exact disposable state.
- Restarted the same real `bs2eng.bns` ROM using the tracked `uv run -m qns.bns` launcher, `--model bs2`, keyboard stdin, a two-billion-cycle finite boundary, and the exact saved state.
- Entered the required uppercase `O`, lowercase `f`, lowercase `o`, `paced.txt`, uppercase `E` sequence with completed transactions between stages.
- The ROM spoke the phoneme sequence for `can't find that file`, then returned to `Enter file command`. This proves `paced.txt` remained deleted across the normal save and restart.
- The BS2 file lifecycle gate now passes end to end: create, paced known-content write, immediate readback, normal save, reopen and readback after restart, delete, normal save, and not-found verification after restart.
- No implementation change was made during the lifecycle verification. The clock-device source slice remains limited to `qns/io.py`, `qns/bns.py`, `tests/test_io.py`, and `tests/test_bns.py` and is now ready for its Git/test closure.
- Next action: close the current clock-device source slice through its exact test and Git gates, then continue the active plan with serial stdio, the remaining clock/status/power behavior, and external-program execution.

### Clock-device slice reaches the commit gate

- The final not-found verification run reached its full two-billion-cycle boundary, ended at PC `1BDA`, and saved the disposable state normally.
- Reran the exact current authority with `uv run pytest tests/test_io.py tests/test_bns.py tests/test_cpu.py`: all 25 tests passed in 1.40 seconds.
- Reread the controlling plan after the passing substantial test run. The next unchecked action remains closure of this clock-device slice before starting serial stdio or any other source slice.
- `git diff --check` passes for the four implementation/test files. The intended source/test diff is 120 insertions and 23 deletions across `qns/io.py`, `qns/bns.py`, `tests/test_io.py`, and `tests/test_bns.py`.
- The mandatory `notes-software-bns.md` experiment/handoff record is included in the staged ledger as required by the Git accountability rule. The staged set is exactly that record plus the four source/test files.
- User-owned tracked modifications in `CLAUDE.md`, `qns/ssi263.py`, `qns/synth/__init__.py`, and `qns/synth/ssi263_synth.py`, and all unrelated untracked artifacts, remain unstaged and untouched.
- Next action: restage this checkpoint update, rerun the staged whitespace/name/status gates, commit the completed clock-device slice, then begin the serial-stdio item from the controlling implementation sequence.

### Serial stdio was already complete

- Commit `989ad8b` (`Implement BS2 clock PIC`) closed the preceding clock-device slice with the mandatory handoff record and the exact four source/test files.
- The assumption that serial stdio remained unimplemented was wrong. Current `qns/bns.py` already queues raw standard-input bytes for the selected `serial0` or `serial1` ASCI callback and emits only the selected output channel as raw standard output while redirecting emulator logs to standard error.
- `tests/test_bns.py` already contains both channel-isolation coverage and a subprocess-level CLI round trip from raw stdin through native ASCI and back to raw stdout. `tests/test_cpu.py` covers native ASCI transmit and receive callbacks.
- Those serial authorities were included in the just-completed 25-test run and passed. No serial implementation change or new serial source slice is justified.
- User-owned tracked modifications and unrelated untracked artifacts remain untouched.
- Next action: commit this plan correction as a record-only change, then establish the exact remaining BS2 clock/status/power command contract from current ROM/source evidence before editing implementation. External-program execution follows that contract work within the same active plan phase.

### Normal PIC clock-setting slice begins with a failing authority

- Commit `6584214` (`Correct serial stdio plan state`) contains only the preceding nine-line record correction. The next source slice started from a reconciled tracked state with only the four preserved user-owned modifications outside the slice.
- Authoritative `C:\Users\Q\src\bns\bsp\TNSCLK.C` defines raw command `2` as selecting the normal clock-value bank, raw command `4` as returning the selected date/time, tagged values `0x20`, `0x40`, `0x60`, `0x80`, and `0xA0` as minute, month, day, year-since-1989, and hour writes, and raw `0x05` as the sixth minute bit.
- Added one focused test in `tests/test_io.py` that selects the normal bank, writes 03:45 on December 31, 2019 through those exact protocol bytes, requests command `4`, and requires the same tagged fields back.
- The unchanged implementation fails exactly at the intended boundary: it returns the injected host clock's July 18, 19:45, 2020 fields (`[45, 5, 71, 114, 179, 159]`) instead of the written values (`[45, 5, 76, 127, 163, 158]`).
- Current slice scope is `tests/test_io.py`; no implementation file has yet been edited. User-owned tracked modifications and unrelated artifacts remain untouched.
- Blocker: none. Next action: implement only normal-bank field writes and command-4 readback in `PIC16C56Clock`, rerun the focused failure, then run the full clock/BNS/CPU authority and close or revert this slice before starting alarm-bank behavior.

### Normal PIC clock-setting slice passes

- `PIC16C56Clock` now snapshots the injected host time as the normal clock bank, advances that bank by elapsed host time, selects it on raw command `2`, and accepts the source-defined tagged minute/month/day/year/hour writes plus raw `0x05` for the sixth minute bit.
- Raw command `4` now serializes the maintained normal bank instead of rereading the host clock directly. Invalid intermediate date combinations during ordered month/day/year updates do not crash the device; ticking resumes once the fields form a valid date.
- The focused test that previously failed now passes. The full current authority also passes: 26 tests across `tests/test_io.py`, `tests/test_bns.py`, and `tests/test_cpu.py` in 1.58 seconds.
- Reread the controlling plan after the passing substantial test run. Passing tests authorize keeping this normal-clock reduction; they do not complete alarm selection/alerting, 8255 status inputs, power workflows, external programs, remaining ROM profiles, or the full audit.
- Current slice is exactly `qns/io.py`, `tests/test_io.py`, and this mandatory handoff update. User-owned tracked modifications and unrelated untracked artifacts remain untouched.
- Next action: inspect and commit this exact normal-clock slice. Then remain on the clock PIC target and begin the separate alarm-bank selection/storage/readback slice from authoritative `TNSCLK.C` commands `3`, `4`, and `2`.

### Alarm-bank selection and readback pass

- Commit `6edf0cb` (`Implement BS2 clock setting`) closed the normal-clock slice with exactly `qns/io.py`, `tests/test_io.py`, and the mandatory handoff update.
- Added a focused authority for `TNSCLK.C`'s alarm selection contract: raw command `3`, tagged alarm minute/month/day/hour/year writes, command `4` readback, command `2` restoration of the untouched normal bank, and a second command `4` readback.
- The unchanged implementation failed because command `3` still returned normal time. `PIC16C56Clock` now maintains an isolated alarm field bank, routes tagged writes to the selected bank, and serializes the selected bank on command `4`.
- The focused alarm-bank test now passes. The full current authority also passes: 27 tests across `tests/test_io.py`, `tests/test_bns.py`, and `tests/test_cpu.py` in 1.41 seconds.
- Reread the controlling plan after the passing substantial test run. Alarm storage/readback is a kept reduction, but actual due-alarm `0x0A` delivery and wake behavior remain unchecked on this same clock PIC target.
- Current slice is exactly `qns/io.py`, `tests/test_io.py`, and this mandatory handoff update. User-owned tracked modifications and unrelated untracked artifacts remain untouched.
- Blocker: none. Next action: inspect and commit this exact alarm-bank slice, then establish a focused failing authority for a due selected alarm producing the source-defined raw `0x0A` PIC-to-firmware notification without repeated delivery.

### Due-alarm matching research checkpoint

- Commit `07fe292` (`Implement BS2 alarm clock storage`) closed the preceding alarm-bank slice with exactly `qns/io.py`, `tests/test_io.py`, and the mandatory handoff update.
- `TNSCLK.C` establishes raw `0x0A` as the PIC-to-firmware alarm notification that sets `clock_alarm`; the clock PIC can power/wake the unit for an alarm.
- `TIMENEW.C::set_alarm` parses `x` in either hour digit as the `DONTCARE` hour value. It parses `x` in either month, day, or year digit pair as numeric zero for that field. Empty alarm-date input copies today's resolved date.
- Minute wildcard handling is indirect: `send_time` first transmits tagged minute low bits, then sends raw `0x06` when `minutes == 0xff`; raw `0x05` remains the add-32 command. The top-level `TNSCLK.C` protocol comment does not document raw `0x06`.
- The initial include-only search did not find `DONTCARE`; the subsequent complete firmware-source search found the exact definition at `TIMENEW.C:34`: `#define DONTCARE 0X1F`. No separate PIC firmware, simulator, or alarm matcher exists in the local source tree.
- Current tracked source state has no active QNS implementation slice beyond this handoff update; the four user-owned tracked modifications and unrelated artifacts remain untouched.
- Blocker: exact hour-wildcard value and PIC due-match semantics remain to be located in the authoritative source/build definitions. Next action: search the complete local firmware source for the `DONTCARE` definition and any PIC firmware, protocol note, simulator, or alarm-match implementation; only then define the failing due-alarm authority.

### Exact due-alarm notification passes

- With no PIC matcher source available, this slice was bounded to the exact observable non-wildcard contract: when a fully specified alarm matches the maintained normal clock, `receive()` returns raw `0x0A`, which `TNSCLK.C::pic_to_tns` consumes as the alarm notification.
- Added a focused test for 03:45 on December 31, 2019. The unchanged implementation returned `-1` at the due minute. `PIC16C56Clock` now compares fully specified alarm fields to the maintained normal clock and emits `0x0A` once per unique year/month/day/hour/minute token.
- Invalid, unset, or wildcard-shaped alarm fields do not match in this slice. Reconfiguring alarm fields clears the prior notification token. Queued command responses retain priority over an asynchronous due-alarm notification.
- The focused exact-alarm test now passes. The full current authority also passes: 28 tests across `tests/test_io.py`, `tests/test_bns.py`, and `tests/test_cpu.py` in 1.53 seconds.
- Reread the controlling plan after the passing substantial test run. This is a kept exact-alarm reduction; wildcard matching remains unclaimed and must be handled separately before declaring the clock PIC target complete.
- Current slice is exactly `qns/io.py`, `tests/test_io.py`, and this mandatory handoff update. User-owned tracked modifications and unrelated untracked artifacts remain untouched.
- Next action: inspect and commit this exact due-alarm slice. Then continue the same clock target by deriving the minute/hour/date wildcard behavior from the firmware's exact outbound encodings, explicitly marking any PIC-side inference where the unavailable hardware firmware prevents direct proof.

### Hour/month/day alarm-wildcard slice in progress

- Commit `982513b` (`Deliver BS2 clock alarm notifications`) closed the exact due-alarm slice with exactly `qns/io.py`, `tests/test_io.py`, and the mandatory handoff update.
- Exact firmware-side encodings establish hour `DONTCARE` as `0x1F` in the tagged hour field and month/day wildcard values as numeric zero in their tagged fields. This slice retains exact minute and exact year matching.
- Added a focused test that configures minute 45, any hour, any month, any day, and year 2020. It requires raw `0x0A` at 19:45 on July 18 and again at 08:45 on August 19, with the full current minute token providing deduplication.
- The unchanged matcher failed at the first due time because it rejected all wildcard-shaped fields. `qns/io.py` has now been edited so hour `0x1F` and month/day zero match any current value while minute/year remain exact.
- The implementation edit has not yet been tested. Current slice is exactly `qns/io.py`, `tests/test_io.py`, and this mandatory handoff update. User-owned tracked modifications and unrelated artifacts remain untouched.
- Blocker: none. Next action: run the focused wildcard test. If it passes, run the full clock/BNS/CPU authority, reread the plan, and close or revert this slice before investigating raw `0x06` minute wildcard behavior.

### Hour/month/day alarm wildcards pass

- The focused wildcard test now passes at 19:45 on July 18 and again at 08:45 on August 19 for the same any-hour/any-month/any-day alarm.
- The full current authority also passes: 29 tests across `tests/test_io.py`, `tests/test_bns.py`, and `tests/test_cpu.py` in 1.51 seconds.
- Reread the controlling plan after the passing substantial test run. This is a kept reduction on the clock PIC target; raw `0x06` minute wildcard behavior and wildcard-year ambiguity remain unclaimed.
- Current slice is exactly `qns/io.py`, `tests/test_io.py`, and this mandatory handoff update. User-owned tracked modifications and unrelated untracked artifacts remain untouched.
- Next action: inspect and commit this exact wildcard slice. Then stay on the clock PIC target and add a focused failing authority for raw `0x06` selecting any-minute behavior while hour and date remain exact.

### Raw 0x06 any-minute alarm slice reaches the full-suite gate

- Commit `2e24b27` (`Support BS2 clock alarm wildcards`) closed the preceding hour/month/day wildcard slice with exactly `qns/io.py`, `tests/test_io.py`, and the mandatory handoff update.
- `TIMENEW.C::send_time` sends a tagged minute value followed by raw `0x06` only when `minutes == 0xFF`, with the source comment `don't care about minutes`.
- Added a focused test for an exact 19:00-hour/date alarm with raw `0x06`; it requires `0x0A` at both 19:44 and 19:45 as distinct full-minute tokens.
- The unchanged implementation failed because it retained the preceding tagged minute value 31. `PIC16C56Clock` now records an alarm-only any-minute flag on raw `0x06`, clears it on a later tagged minute write, and uses it only in due matching.
- The focused raw-`0x06` test now passes. The full clock/BNS/CPU authority has not yet been rerun for this slice.
- Current slice is exactly `qns/io.py`, `tests/test_io.py`, and this mandatory handoff update. User-owned tracked modifications and unrelated artifacts remain untouched.
- Blocker: none for this slice. Next action: run the full clock/BNS/CPU authority, reread the plan, and close or revert the slice. Wildcard-year data `0x0B` remains ambiguous because no PIC matcher source exists and must not be claimed as resolved by this result.

### Raw 0x06 any-minute alarm slice passes

- The full current authority passes: 30 tests across `tests/test_io.py`, `tests/test_bns.py`, and `tests/test_cpu.py` in 1.38 seconds.
- Reread the controlling plan after the passing substantial test run. Raw `0x06` any-minute matching is a kept reduction; wildcard-year data `0x0B`, BSNEW 8255 passive status inputs, power workflows, and external programs remain unchecked.
- Current slice is exactly `qns/io.py`, `tests/test_io.py`, and this mandatory handoff update. User-owned tracked modifications and unrelated untracked artifacts remain untouched.
- Next action: inspect and commit this exact raw-`0x06` slice. Then finish the clock PIC audit by determining whether wildcard-year behavior can be resolved from any remaining shipped documentation or binary evidence; if it cannot, record that external-authority limit precisely before moving to BSNEW 8255 status inputs.

### Clock PIC wildcard-year audit reaches an external-authority limit

- Commit `8230229` (`Support BS2 any-minute alarms`) closed the raw-`0x06` slice with exactly `qns/io.py`, `tests/test_io.py`, and the mandatory handoff update.
- Shipped `roms\NFB99\BS2ENG\bs2eng.hlp` says `x` is the alarm wildcard character for the `hhmm` time and `mmddyy` date entry. Its explicit example `xx15` means 15 minutes after every hour and agrees with implemented hour wildcard `0x1F` plus exact minute 15.
- The shipped help does not state PIC byte encodings. A complete candidate-file search found no PIC 16C56 firmware, HEX, ROM, simulator, or separate alarm matcher in the supplied firmware source or ROM assets.
- `TIMENEW.C::set_alarm` converts wildcard year `xx` to numeric year `0`, and `send_date` encodes any year below 89 as `year + 11`; wildcard year therefore crosses the observed PIC boundary as tagged year data `0x0B`, exactly the same byte used for calendar year 2000.
- `include\BSAPI.H` says alarm year 89 disables an alarm, but `BSAPI.C::api_tns_alarm` is compiled only for `TNS | B_LITE_40 || T_LITE`, not `BSNEW`, so it cannot disambiguate the BS2 PIC's year-2000/wildcard collision.
- The available host firmware and shipped documentation therefore cannot prove whether the physical PIC treated year data `0x0B` as every year, year 2000, or by some hidden state. Implementing either meaning as exact BS2 behavior would be invention. Wildcard-year matching remains externally blocked and unclaimed; all directly observable normal clock, alarm storage/readback, exact alarm, hour/month/day wildcard, and raw-`0x06` minute wildcard surfaces are implemented and tested.
- Current QNS source state has no active implementation slice; this handoff audit update is the only tracked project change beyond the four preserved user-owned modifications.
- Next action: commit this record-only external-authority finding, then move to the next BSNEW target allowed by exact-convergence: establish the exact passive 8255 port-A/port-B input contract from BSNEW source definitions and live ROM read consumers before editing implementation.

### BSNEW 8255 passive-input discovery checkpoint

- Commit `3cbeb8a` (`Record BS2 clock protocol limit`) closed the wildcard-year audit as an eleven-line record-only commit. No new QNS source slice has started.
- `BS.ASM` initializes the BSNEW 8255 with control byte `0xA2`, explicitly documented as port A output, port B input, and port C output. Therefore returning a fabricated passive port-A input value is not justified; BSNEW writes port A and the shared address's read side remains the watchdog service boundary already modeled at `0x80`.
- The same initialization pulses port-C bits for the clock/parallel strobes. That output behavior is already covered by the committed C4 clock slice.
- `BSPARMS.C`'s BSNEW definitions identify `CEPW=0xA0`, `CHGIN=0x81`, and `CHOBIT=5`, with comments stating these are the BSNEW pin/port assignments. Its gas-gauge send routines drive output bit 5 through the combined power latch at `0xA0`; port B at `0x81` is the corresponding input surface.
- Broad source output also confirms the generic `IOSTAT` power-switch path is not a BSNEW port-A contract: the startup read is guarded by `.IF !BSNEW`.
- Current tracked project change is only this handoff update; the four user-owned tracked modifications and unrelated artifacts remain untouched.
- Blocker: the exact `CHGIN=0x81` bit value/cadence consumed by the gas-gauge receive path has not yet been isolated. Next action: locate literal reads of `CHGIN`, read that bounded routine and its caller, then define the first focused BSNEW port-B contract only if it changes a real firmware decision.

### BSNEW gas-gauge timing checkpoint

- `saybat40()` obtains percent charge by sending bq2010 commands `0x03`,
  `0x05`, and `0x01`, then reading eight reply bits from `CHGIN` (`0x81`)
  bit 3. The current fixed `0xFF` port-B value can therefore leave the ROM in
  the reply-start wait loop forever.
- The command is transmitted LSB-first on combined-power latch `0xA0` bit 5;
  short and long low pulses encode one and zero. A reply sequenced only by
  reads would be a substitute for the firmware-visible pulse protocol.
- QNS currently updates `stats['cycles']` only after each 1,000-cycle CPU
  execution chunk. Its I/O callbacks therefore cannot measure the latch
  pulses exactly.
- The Z180 core keeps an instruction-budget counter (`icount`), but its old
  generic CPU-info accessor is commented out and the wrapper exposes no
  current-cycle query. A narrow accessor for the already-existing `icount`
  is necessary to timestamp I/O at instruction boundaries without changing
  callback signatures or execution behavior.
- The first attempted header patch changed nothing because the declaration
  order in `z180.h` differed from the expected patch context.
- Current state: QNS has no gas-gauge source slice yet; the external Z180
  worktree remains clean and two commits ahead of its origin.
- Next action: add, build, and commit the isolated Z180 `icount` accessor;
  only then begin the QNS wrapper/device slice.

### Z180 current-cycle accessor ready to commit

- Added `cpu_get_icount_z180(device_t *)` to the external Z180 core. It returns
  the existing execution-budget counter and changes no execution or callback
  behavior.
- `mingw32-make z180.o` compiled the changed core successfully in 7.4 seconds.
  The generated untracked `z180.o` was then removed because it is reproducible
  build output and not part of the source slice.
- Git's default whitespace check treated CRLF line endings as trailing space;
  `git -c core.whitespace=cr-at-eol diff --check` passes with the repository's
  actual line-ending convention.
- Exactly `z180/z180.c` and `z180/z180.h` are staged in the external repository.
  No QNS implementation source has been edited.
- Blocker: none. Next action: commit this isolated external slice, then verify
  both repositories' tracked state before beginning the QNS wrapper/device
  slice.

### QNS timed-I/O bridge slice in progress

- External commit `607e1ed` (`Expose Z180 execution cycle position`) closed the
  isolated core slice. The external repository is clean and three commits
  ahead of its origin.
- The original TI bq2010 datasheet confirms an asynchronous, LSB-first,
  return-to-one single-wire protocol. Command `0x03` reads NACH, `0x05` reads
  LMD, and `0x01` reads FLGS1; FLGS1 bit 7 is the charging flag consumed by
  the BSNEW firmware.
- The datasheet specifies a 3 ms minimum break, 1 ms minimum break recovery,
  host and device bit cycles of 3 ms minimum, device start hold of 500 us,
  data setup by 750 us, and data valid for at least 1.5 ms. These match the
  firmware's break, transmit, polling, and delayed-sample structure.
- Added a focused native bridge test whose two `OUT0` callbacks must observe
  exact instruction-start positions 6 and 31, then an accumulated count of
  100 and 125 across two runs and zero after reset. The unchanged bridge
  failed because `Z180.cycle_count` did not exist; the callback exceptions
  left the observation list empty.
- `tools/build_ffi.py` now tracks completed and active-call cycles using the
  committed core `icount` accessor, and `qns/cpu.py` now exposes
  `cycle_count` for native and stub CPUs.
- The original `34` expectation was wrong because the core charges 13 cycles
  for `OUT0`; the second callback is at 31. After correcting that false test
  premise, the rebuilt native extension passes the focused timing authority.
- Reread the controlling plan after that pass. The next unchecked target
  remains the BSNEW port-B gas-gauge workflow.
- The shipped `bs2eng.hlp` gives the exact interactive sequence: dots 34 enters
  the Status Menu and dots 146 invokes `Percent of charge`. Correction: the
  Status Menu chord is raw `0x4C` (dots 34 plus chord bar), while terminal `/`
  maps to bare dots 34 raw `0x0C`; no current terminal character maps to raw
  `0x4C`. Terminal `%` does map to bare dots 146 raw `0x29` for the menu choice.
- Current state: the QNS timing bridge edits and focused test are uncommitted.
  No gas-gauge peripheral code exists yet.
- Blocker: none. Next action: run the bounded real-ROM measurement using `/`
  followed by `%`, record the literal bit-5 pulse widths through
  `Z180.cycle_count`, and use those measurements to fix the device thresholds.

### Real-ROM gas-gauge measurement and focused wiring checkpoint

- A temporary bounded measurement script loads the preserved initialized BS2
  state, delivers complete firmware key-down/key-up transactions, and records
  only `0xA0` bit-5 transitions through the new cycle counter.
- The first `/`, `%` run produced zero edges because its 500,000-cycle quiet
  window was shorter than one 64 ms speech completion; `%` could be injected
  while the Status Menu transaction was still speaking.
- The second run used a five-million-cycle quiet window. It spoke Status Menu
  entries but ultimately produced zero edges and returned to normal idle PC
  `D657`, showing that it waited past the active menu input boundary.
- The earlier terminal-input premise was wrong: `/` delivers bare dots 34 as
  raw `0x0C`, not the required chorded Status Menu command raw `0x4C`. Using
  literal raw `0x4C` followed by raw `0x29` reached `saybat40(1)` in the real
  ROM and produced the first bq2010 command.
- The measured command starts at cycle 18,641,753. Its initial break low pulse
  is 18,020 cycles. The eight following low pulses are 315, 324, 12,813,
  12,821, 12,821, 12,823, 12,824, and 12,824 cycles, which decodes LSB-first
  as command `0x03` (NACH). The temporary measurement script was then removed.
- `BQ2010GasGauge` now models measured break/bit timing and replies to commands
  `0x03`, `0x05`, and `0x01`; its focused measured-waveform test passes with
  NACH 100, LMD 100, and FLGS1 0.
- A focused BNS-level test now sends measured `0x03` timing through BSNEW power
  latch bit 5 and samples parallel-port B bit 3. It fails at the exact missing
  boundary: `_io_read(0x81)` returns fixed `0xFF` instead of expected `0xF7`
  while the modeled gauge drives the data line low.
- Current state: the timed-I/O bridge, bq2010 device model, focused authorities,
  and this record are uncommitted. User-owned tracked changes remain preserved.
- Blocker: none. Next action: wire the existing gauge model only at BSNEW power
  latch bit 5 and port-B bit 3, then rerun the focused BNS wiring authority.

### BSNEW gas-gauge wiring authority passes

- `qns/bns.py` now constructs the bq2010 model only for `model="bs2"`, drives
  its single-wire input from combined power-latch bit 5 at the native CPU's
  current cycle, and overlays only parallel-port B bit 3 with its timed output.
- The formerly failing BNS-level authority now passes: measured command `0x03`
  driven through `0xA0` produces a low sample as port-B value `0xF7` and later
  returns high as `0xFF`.
- The preserved initialized state exists at
  `C:\Users\Q\AppData\Local\Temp\qns-bs2-clock-pic-20260718.state`, length
  2,686,992 bytes. It is a disposable live artifact, not a tracked regression
  fixture and not by itself proof of the user-visible workflow.
- The repository's only declared integration convention is the `manual` pytest
  marker; current manual tests are audio-listening checks, not BS2 ROM workflow
  drivers.
- Current state: the timed-I/O bridge, bq2010 model, BS2 wiring, focused tests,
  and this record remain one uncommitted gas-gauge slice. The preserved
  user-owned tracked changes remain untouched.
- Blocker: none. Next action: exercise literal raw Status Menu chord `0x4C`
  followed by Percent of charge chord `0x29` against the real BS2 ROM and the
  disposable initialized state; require all three firmware commands `0x03`,
  `0x05`, and `0x01` plus the resulting percent/charging speech before closing
  this slice.

### BSNEW live battery gate preparation

- `BQ2010GasGauge.command_log` now retains each fully decoded host command.
  The measured-waveform authority asserts the exact `[0x03, 0x05, 0x01]`
  sequence and passes.
- Firmware source `BSPARMS.C::saybat40` confirms the causal output path: it
  reads NACH with `0x03`, LMD with `0x05`, FLGS1 with `0x01`, computes
  `NACH * 100 / LMD`, selects `charging` when FLGS1 bit 7 is set and
  `not_charging` otherwise, then sends the formatted text through `say`.
- `SSI263.set_phoneme_callback` is the existing non-invasive observation point
  for collecting real-ROM speech without changing firmware timing or clearing
  the emulator's own log prematurely.
- Current state: the focused device and BNS wiring authorities pass; no live
  three-command or resulting-speech claim has yet been made. The whole gas
  gauge slice remains uncommitted.
- Blocker: none. Next action: add a bounded reusable live verifier that loads
  the supplied BS2 ROM and explicit disposable state, delivers raw `0x4C` then
  raw `0x29` through complete keyboard handshakes, and fails unless the real
  ROM produces `[0x03, 0x05, 0x01]`; retain its phoneme output to establish the
  exact speech sequence rather than guessing it.

### BSNEW live battery synchronization correction

- Two bounded live-verifier attempts produced no bq2010 commands. The first
  used only the sticky command-loop-seen flag and could inject during startup;
  the second also required normal idle PC `D657` but still delivered `0x29`
  immediately after the `0x4C` key-up acknowledgement. Neither attempt proved
  a product reduction, and the rejected verifier file was fully removed.
- The passing measured-waveform and BNS wiring implementation remains intact;
  the failed live drivers do not contradict the modeled line behavior because
  the firmware never reached `saybat40` in either run.
- Source control flow now identifies the missing synchronization precisely:
  the Status Menu loop calls `get_menu_key()`, which blocks in `getkey()`, saves
  the physical chord in `bkey`, and only then translates it with `braasc`.
  A completed IRQ down/up handshake does not prove the preceding `0x4C` has
  been dispatched into that menu loop, so immediate `0x29` can be consumed in
  the wrong command context.
- No linker map, listing, or symbol file is present in the recovered source
  tree. The next boundary must therefore be established from live keyboard
  port reads/PCs or an equivalent current ROM state observation, not a guessed
  source address.
- Current state: the gas-gauge source/test slice remains uncommitted; the
  user-owned tracked modifications and unrelated artifacts remain untouched.
- Blocker: none. Next action: trace the real ROM's nonzero keyboard-port reads
  and consuming PCs for `0x4C`; identify the subsequent `get_menu_key` wait,
  then deliver `0x29` only at that proven state and rerun the three-command and
  spoken-result gate.

### BSNEW status-menu live-state trace in progress

- Added bounded `tools/trace_bs2_battery_menu.py`. It loads the explicit ROM
  and disposable state without saving, advances the CPU and SSI-263 together,
  delivers complete raw keyboard down/up handshakes, and suppresses unrelated
  emulator diagnostics so its result remains inspectable.
- Source ordering supports a state-based gate: after dispatching/speaking a
  status item, `parameters()` calls `get_menu_key()`, which blocks in `getkey`.
  This is the next decision-changing boundary; a fixed speech delay is neither
  required nor authorized.
- The first trace attempt required command-loop-seen, PC `D657`, and
  `cpu.halted` simultaneously at boot. It reached the 30-million-cycle bound
  without satisfying that conjunction. Earlier live runs prove PC `D657` is
  the normal idle boundary, but this sampling does not expose `halted` at the
  same instant; the added boot condition was unsupported.
- The trace now uses the previously proven command-loop-seen plus PC `D657`
  boot predicate. Its separate post-`0x4C` candidate menu-wait predicate remains
  `cpu.halted` at a non-`D657` PC and has not yet been observed or accepted.
- Current state: no product source changed from this diagnostic; the gas-gauge
  implementation slice remains uncommitted and the user-owned changes remain
  untouched.
- Blocker: none. Next action: rerun this corrected trace. Keep the menu-wait
  predicate only if the real ROM reaches it and then produces literal commands
  `03 05 01` after raw `0x29`; otherwise reject it and inspect the observed live
  control state rather than adding another timing assumption.

### BSNEW candidate wait `1BDA` rejected

- The corrected boot predicate reached normal idle and processed raw `0x4C`.
  The first non-`D657` halt occurred at cycle 13,666,000, PC `1BDA`, after 63
  phonemes. Sending raw `0x29` there produced no bq2010 command within the
  bounded 30-million-cycle continuation.
- Requiring no pending SSI-263 completion and the same halted PC/phoneme count
  across the next scheduler quantum still selected PC `1BDA`, at cycle
  14,451,000. Raw `0x29` again produced no bq2010 command. Therefore `1BDA` is
  a longer-lived firmware speech wait, not the menu's `getkey` boundary; both
  candidate predicates are rejected.
- The installed generic `objdump` supports only x86 targets, but the exact
  external Z180 source includes its own `cpu_disassemble_z180` implementation.
  No new disassembler integration has been added.
- The live trace now computes the current Z180 MMU mapping and will report the
  physical address plus 16 bytes around a candidate PC. That evidence can
  identify the instruction at `1BDA` and support a causal next predicate.
- Current state: no additional product source has changed; the gas-gauge slice
  and diagnostic trace remain uncommitted. User-owned changes remain untouched.
- Blocker: none. Next action: rerun the bounded trace once to collect the mapped
  bytes at `1BDA`, decode them with the authoritative Z180 table or source, then
  trace the actual post-status `getkey` wait without sending `0x29` at `1BDA`.

### BSNEW battery frame reaches the ROM path but decoder lacks resynchronization

- MMU mapping proves candidate PC `1BDA` is physical `01BDA`. Bytes around it
  are `... 3A 54 D6 76 CD FF 13 18 F0 ...`; byte `76` at the PC is the Z80 HALT
  in the firmware wait loop, not an arbitrary sampled instruction.
- Corrected an earlier overstatement: the failed three-command predicate did
  not prove zero commands. After adding failure-state output, the transaction
  showed one decoded command, `FF`.
- Clearing only the observational command log at proven post-boot idle still
  produced `FF`, so the byte belongs to this status transaction rather than a
  retained boot log entry.
- Literal bit-5 edges prove the ROM is sending the intended first command. The
  frame starts low at cycle 14,475,880 and rises at 14,493,904, an 18,024-cycle
  break. Its following low widths are 315, 324, 12,808, 12,826, 12,808,
  12,802, 12,821, and 12,821 cycles: LSB-first `03` exactly.
- The model decodes that frame as `FF` because earlier boot latch activity can
  leave `_awaiting_break` false with a partial frame. The current implementation
  treats the 18,024-cycle protocol break as another data bit unless it already
  expects a break. A physical bq2010 break is a frame resynchronization event;
  this state-machine behavior is wrong.
- Current state: no fix has been applied. The gas-gauge implementation and live
  trace remain uncommitted; user-owned tracked changes remain untouched.
- Blocker: none. Next action: add a focused authority that leaves the decoder
  mid-frame, presents the observed long-idle plus 18,024-cycle break and `03`
  waveform, and requires NACH 100. Then implement break resynchronization,
  rerun that authority, and rerun the unchanged real-ROM three-command gate.

### BSNEW real-ROM battery workflow passes

- The live post-boot decoder state was `_awaiting_break=false`, no accumulated
  command bits, and a bogus 656,686-cycle break captured from startup latch
  activity. This directly confirms the partial-frame contamination premise.
- Added a focused regression that leaves the receiver mid-frame, waits through
  the observed long idle, sends an 18,024-cycle break plus literal `03`, and
  requires command `03` with returned NACH 100. It failed as `37` before the
  fix and now passes.
- `BQ2010GasGauge` now treats a low pulse after more than twice the stored break
  width of high idle as a new frame break even when a partial frame exists. It
  discards the partial bits and recalibrates from that break. Ordinary bit-cell
  high intervals remain below this threshold in the measured ROM waveform.
- The unchanged real `bs2eng.bns` workflow now passes from the preserved state:
  raw Status Menu `0x4C`, a stable `get_menu_key` wait at PC `1BDA`, then raw
  Percent of charge `0x29` produce exact bq2010 commands `03 05 01`.
- The resulting non-pause SSI-263 suffix is `W UH1 N / E HF UH N D R EH1 D /
  P ER S EH N T / N AH T / T SCH AH ER D J I N KV`, the ROM's phonemes for
  `one hundred percent not charging`. This is the first complete user-visible
  BS2 battery-status pass.
- The earlier final verifier predicate requiring editor PC `D657` was wrong:
  the Status Menu remains in `get_menu_key` at HALT PC `1BDA` after speaking.
  Requiring the stable menu wait is the correct completion state.
- Current state: the timed-I/O bridge, bq2010 model and resynchronization fix,
  BS2 wiring, focused tests, live verifier, and this record remain one
  uncommitted kept slice. User-owned tracked changes remain untouched.
- Blocker: none. Next action: make the live verifier assert exact commands and
  the observed non-pause speech suffix, run focused and full current authority,
  reread the plan, inspect the exact diff, and commit this slice before moving
  to the next BS2 target.

### BSNEW gas-gauge slice at cleanup and commit gate

- The live verifier now asserts exact commands `[03, 05, 01]` and the complete
  non-pause suffix for `one hundred percent not charging`; it passes against
  the supplied ROM and preserved disposable state.
- The established full current authority passes: 34 tests across
  `tests/test_io.py`, `tests/test_bns.py`, and `tests/test_cpu.py` in 1.46
  seconds. The controlling plan was reread after this passing run; the current
  slice must be committed before moving to another BS2 target.
- Scoped Ruff initially reported four findings introduced by this slice plus
  older findings in touched bridge/runtime files. Import order in `qns/bns.py`
  and `tests/test_io.py`, and both verifier findings, are fixed.
- The user explicitly instructed: `take this chance to clean shit up and
  commit`. This authorizes cleaning the remaining lint findings in the current
  gas-gauge/timing slice before committing; it does not authorize touching the
  four preserved user-owned tracked edits or unrelated untracked artifacts.
- `qns/bns.py`'s older extraneous f-string and two overlong status lines are now
  cleaned. `qns/cpu.py` now imports `Callable` from `collections.abc`.
- Current state: cleanup of `tools/build_ffi.py` remains, then all verifier,
  test, lint, whitespace, diff-scope, and staging checks must be rerun. No commit
  has yet been made.
- Blocker: none. Next action: clean the reported `tools/build_ffi.py` import,
  f-string, and long-line findings; rerun all authorities, inspect/stage only
  the intended slice and this record, then commit it.

### BSNEW gas-gauge slice passes after cleanup

- All reported lint defects in the current timing/gas-gauge slice are cleaned.
  Scoped Ruff across the eight touched source/test/tool files reports
  `All checks passed!`.
- The embedded C wrapper now uses explicit `.format()` brace conversion instead
  of an otherwise-empty f-string. `uv run tools/build_ffi.py` successfully
  rebuilt and copied the native CFFI extension; only the same external Z180
  compiler warnings were emitted.
- The asserted real-ROM battery verifier passes against the rebuilt extension:
  stable menu wait PC `1BDA`, commands `03 05 01`, and the full phoneme suffix
  for `one hundred percent not charging`.
- The established full authority passes again against the rebuilt extension:
  34 tests across IO, BNS, and CPU in 1.81 seconds.
- Current state: the kept slice is still uncommitted. User-owned tracked edits
  and unrelated untracked artifacts remain outside its intended scope.
- Blocker: none. Next action: rerun scoped lint once on final files, check
  whitespace and line endings, inspect the exact diff and status, stage only
  `notes-software-bns.md`, `tools/build_ffi.py`,
  `tools/trace_bs2_battery_menu.py`, `qns/cpu.py`, `qns/io.py`, `qns/bns.py`,
  `tests/test_cpu.py`, `tests/test_io.py`, and `tests/test_bns.py`; inspect the
  staged diff, then commit this kept slice.

### Line-ending cleanup correction before commit

- An attempted CRLF normalization enlarged the scoped diff across whole files.
  Current Git authority shows `core.autocrlf=false` and no `text` or `eol`
  attributes on the intended paths, so literal LF is the repository format for
  this commit.
- The normalization was immediately reversed with `dos2unix` on only the nine
  intended slice files. Substantive gas-gauge, timing, verifier, test, cleanup,
  and handoff edits are preserved.
- One read-only tool call incorrectly combined the Git configuration and
  attribute inspections. It changed no project state, but violated the explicit
  rule against combining separate steps and is recorded here rather than
  excused by convenience.
- Current state: no files are staged and no commit has been made. The four
  user-owned tracked edits and unrelated untracked artifacts remain excluded.
- Blocker: none. Next action: confirm the scoped diff is compact again, rerun
  final Ruff and whitespace checks in LF form, inspect all intended diffs,
  stage the exact nine paths only, inspect staged status/diff, and commit.

### Mixed-line-ending staging correction

- The preceding statement that literal LF is the repository format is wrong.
  The tracked blobs themselves contain mixed line endings; both whole-file
  CRLF conversion and whole-file LF conversion therefore enlarge the ordinary
  working-tree diff.
- `git diff --ignore-space-at-eol` isolates the intended substantive edits. The
  exact corrective staging procedure is to apply that scoped patch to the
  index, add the new verifier separately, inspect the staged result, commit it,
  and then restore only residual line-ending noise in these known slice paths
  from the committed index.
- All nine intended files have now been inspected for substantive scope. The
  four user-owned tracked changes and unrelated untracked artifacts remain
  outside the slice.
- Blocker: none. Next action: stage only the exact substantive patch and new
  verifier, inspect the index, and commit the passing BSNEW gas-gauge slice.

### BSNEW gas-gauge slice committed

- Commit `03c5f26` (`Implement BS2 battery gas gauge`) contains exactly the
  nine intended files: the timed native bridge, bq2010 model and BS2 wiring,
  focused authorities, asserted real-ROM verifier, cleanup, and this handoff.
- The staged whitespace check passed. The remaining unstaged differences in
  the touched tracked paths were proven empty under
  `git diff --ignore-space-at-eol` and were restored from the committed index;
  no user-owned tracked path was restored or staged.
- The last established product authority remains the passing 34-test IO/BNS/CPU
  suite and the passing real-ROM Status Menu battery verifier with commands
  `03 05 01` and exact `one hundred percent not charging` phoneme suffix.
- Current state: the battery/status workflow slice is committed. User-owned
  tracked changes and unrelated untracked artifacts remain untouched. This
  checkpoint note is the only new project change after the commit.
- Blocker: none. Next action: reread the active plan and begin the first
  causally relevant unchecked BS2 power/status or external-program surface as
  one exact-convergence target.

### Remaining BS2 status target selected

- Commit `e5a600e` (`Record BS2 battery slice closure`) closed the mandatory
  post-commit checkpoint as a record-only slice. The tracked worktree again
  contains only the four preserved user-owned modifications.
- The active plan evidence confirms BS2 serial stdio is already implemented and
  covered by native callback and subprocess round-trip tests. Opening another
  serial source slice would repeat completed work.
- Authoritative `LIB/BSPORTS.LIB` defines the remaining BSNEW 8255 boundary:
  `PPORT=0x80` is the parallel data output, `BPORT=0x81` is miscellaneous
  status input, `CPORT=0x82` is port-C control/status, and `PIOCT=0x83` is the
  control register. The already-implemented gas gauge owns only BPORT bit 3.
- Current state: no new product source has been edited. The next target is the
  remaining BSNEW 8255 parallel/status contract, not another serial shim or a
  Braille-display profile.
- Blocker: none. Next action: read the bounded BSNEW parallel-output/status
  routines in `BSTXT.C`, derive the exact bit polarities and strobe semantics,
  then add a focused failing authority only for behavior that changes the real
  ROM's printer decision.

### BSNEW parallel/status focused authority passes

- `BSTXT.C::PARRDY` proves the exact ready predicate: port-C bit 7 must be high,
  then port-B bits 0 and 1 must both be zero. `api_psend` and `psend` write the
  byte to port A, reset C5 with control `0x0A`, and set C5 with `0x0B`; that
  low/high strobe commits the byte.
- Added a focused BNS authority using a byte stream. It initially failed at the
  missing `parallel_output` constructor boundary. The implementation now
  reports the source-defined ready status and writes exactly one port-A byte on
  the C5 rising edge. The focused authority passes.
- The complete current `tests/test_bns.py` run then found one stale passive-port
  expectation: clearing the source-defined port-B error bits changes gas-gauge
  low/high samples from fabricated `F7/FF` to `F4/FC`. The test is corrected to
  require the combined status contract; product gas-gauge behavior is unchanged.
- Current state: the source slice is limited to `qns/bns.py`,
  `tests/test_bns.py`, and this handoff record. It is not yet committed.
- Blocker: none. Next action: add a subprocess authority proving a native BSNEW
  ROM can send one parallel byte to raw stdout through `--output parallel`,
  implement only the necessary CLI selection, then rerun focused and full
  authorities before attempting a real firmware printer workflow.

### BSNEW parallel stdio boundary passes

- Added `--output parallel` as the literal raw-stdout selection. Console logs
  are redirected to stderr exactly as for raw serial output, and the selected
  stream is passed directly to the existing BSNEW 8255 owner.
- The native subprocess authority initially failed because the CLI rejected the
  missing choice. It now passes: a native Z180 program configures mode `A2`,
  writes byte `5A` to port A, pulses C5 with `0A/0B`, and stdout contains only
  `Z`.
- The complete current `tests/test_bns.py` authority passes: 17 tests in 1.90
  seconds. Per the active plan, this is a kept implementation reduction but not
  yet a complete real-ROM printer workflow.
- The supplied July 1999 `bs2eng.hlp` documents `t-chord` print/transmit options
  for the serial port but does not include the older help's parallel-port
  keystroke wording. The linked `BSTXT.C` still contains the BSNEW parallel
  implementation. Sending a guessed second chord would not be valid evidence.
- Current state: the active uncommitted slice remains `qns/bns.py`,
  `tests/test_bns.py`, and this record. User-owned changes remain untouched.
- Blocker: none. Next action: locate the linked transmit-command dispatcher and
  its serial/parallel selector from source or live ROM control flow, then drive
  that exact command against `bs2eng.bns` and require captured parallel bytes
  before closing the slice.

### Correction: BS2 parallel-output target is invalid

- The preceding target premise was wrong. `BE_ENG.PRJ` builds `BS2ENG` with
  `BSNEW=1` only; it does not set `B_LITE`.
- `BSTXT.C` compiles `api_psend`, `psend`, and the 8255 parallel route only for
  `TNS`, `B_LITE_40`, `T_LITE`, or `(B_LITE & BSNEW)`. Its generic output path
  compiles direct serial `send` for the BS2 configuration. `BSPROCES.ASM`
  likewise enables the chord-selected parallel flag only for the non-BS2
  configurations. This exactly explains why the supplied July 1999 BS2 help
  documents serial transmission and no parallel command.
- The focused and subprocess tests demonstrated that an invented BS2 parallel
  output could work, but they could not establish product progress because the
  real BS2 ROM contains no path to it. Keeping that feature would violate the
  issue-invalidity and exact-convergence rules.
- The entire rejected product slice was restored from Git: `qns/bns.py` and
  `tests/test_bns.py` are back at committed state. No source change from this
  invalid target remains.
- Current state: only this investigation record is modified. User-owned tracked
  changes and unrelated untracked artifacts remain untouched.
- Blocker: none. Next action: close this correction as a record-only commit,
  then move to the next genuine BS2 target: execute the supplied external
  `.bns` programs through the real file-manager path and identify only proven
  missing storage/loader boundaries.

### BS2 external-program contract discovery

- Commit `075fa4d` (`Record invalid BS2 parallel target`) closed the rejected
  experiment with no product-source change.
- Supplied BS2 external assets are `bsname.bns` (25,108 bytes), `calsort.bns`
  (17,092 bytes), and `calsort.msg` (1,557 bytes), alongside the main
  `bs2eng.bns` ROM, help, dictionary, and update text. Both program binaries
  begin with a jump followed by the literal `BNS\0` signature.
- `FILEP.C` treats external programs as ordinary firmware file-system entries
  of type `TY_EXEC`. From the file menu, `x` or x-chord executes the selected
  program; plain `x` may collect arguments. A flash-resident program is copied
  into RAM first, then `execute_program(file.top_of_file)` is called, and the
  temporary/moved copy is reconciled afterward.
- This proves that loading host `.bns` bytes directly into CPU memory would
  substitute for the real product path. The supplied assets must become real
  BS2 file-system entries before the ROM can select and execute them.
- Current state: no product source has been edited. User-owned changes and
  unrelated artifacts remain untouched.
- Blocker: none. Next action: read `execute_program` and the file-import/update
  paths to establish the exact executable header, placement, and supported
  transfer mechanism; then choose a real stdio-driven import gate without
  inventing an out-of-band loader.

### BS2 external-program import path established

- `BS.ASM::_execute_program` maps the selected firmware file at logical
  `0x1000`, requires `BNS\0` at offsets 2 through 5, reads code/data lengths and
  the stored CRC from the program header, validates the code beginning at
  `0x100E`, configures the application MMU and API vectors, and jumps to the
  program's real entry point. The supplied headers match this contract.
- `FILETRAN.C::upload_download` is the source-backed host import route. From the
  file menu, receive plus protocol `y` starts true batch YMODEM on the selected
  ASCI channel. Packet zero supplies the filename and exact size; the firmware
  creates the ordinary file entry, receives 128-byte or 1K blocks with CRC,
  calculates the `.bns` executable type, and returns through the file system.
- The exact YMODEM receiver sequence is standard and explicit in source: send
  `C`, accept a 128-byte block-zero header, ACK and request `C`, receive numbered
  data blocks, ACK EOT, request the next header with `C`, then accept an empty
  block zero to end the batch.
- Direct BNS driving can use the real keyboard IRQ path for menu chords while
  the existing serial receive/output callbacks carry YMODEM bytes. This avoids
  both a host-memory injector and any need to invent a second firmware loader.
- Current state: no product source has been edited; only this investigation
  record is modified.
- Blocker: none. Next action: add a bounded real-ROM verifier that loads the
  preserved initialized state, enters `O`, `f`, t-chord, receive, YMODEM,
  transfers `bsname.bns`, then exits the file menu and runs it through exact
  O-chord `x` plus the program name. Require loader/API execution evidence.

### External verifier rejected; speech output target selected

- The first verifier attempt reached the firmware transfer wait at PC `2303`
  but did not observe the YMODEM `C`. Moving the serial buffer reset before the
  final menu key did not change that result. No transfer or application
  execution was claimed.
- The unfinished verifier was removed in full before changing targets. No
  product source was edited by the external-program investigation.
- The user redirected the active work to remove repeated low-level speech noise
  and make phoneme, word-like grouping, and related speech observations easier
  to obtain. Existing user-owned SSI/synth edits are now directly in scope but
  must be inspected rather than overwritten.
- Current state: only this investigation record is new from the rejected slice;
  the prior user-owned tracked modifications remain present.
- Blocker: none. Next action: commit this record-only reconciliation, inspect
  the current SSI-263 logging/callback and user speech-tool diffs, then define
  the smallest shared capture surface that removes duplicate output and gives
  tools compact codes, names, and grouped speech.
