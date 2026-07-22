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
## 2026-07-18 speech capture cleanup

- Current target: clean up the existing SSI-263 speech-output path so callers can obtain compact phoneme codes, names, and related representations without repeated diagnostic flooding.
- Current findings: `SSI263` already owns the raw `phoneme_log` and callback. Its register writes and phoneme playback print unconditionally. `BNS.run()` repeatedly prints the whole current log and clears it, which makes speech hard to consume after a run and forces tools to install their own capture callbacks.
- Existing authority: there is no `tests/test_ssi263.py`. The current SSI-263 integration coverage is in `tests/test_synth.py` and the PCM backend coverage is in `tests/test_ssi263_pcm.py`.
- Existing user changes that must be preserved: the corrected SSI-263 phoneme table in `qns/ssi263.py` and the current synthesizer changes in `qns/synth/`.
- State: the failed external-program verifier was removed and reconciliation was committed as `38d0026`; no speech-cleanup source edit has been made yet.
- Blocker: none. The exact existing test/API contract still needs to be read before selecting the smallest compatible capture representation.
- Next action: read the relevant SSI-263 implementation and integration tests, then add a focused failing test for silent default output and explicit compact speech capture before changing the existing owner.

### Speech capture design decision

- `qns/bns.py` is also the shipped argparse command surface. It currently has no speech-output option; during execution it prints every accumulated batch and immediately clears `SSI263.phoneme_log`.
- `tools/trace_bs2_battery_menu.py` demonstrates the resulting duplication: it installs a second callback solely to retain `(code, name)` pairs and redirects stdout solely to hide unconditional SSI-263 diagnostics.
- The existing synthesizer callbacks are audio-backend concerns and are not a replacement for the chip-owned capture log.
- Exact cleanup boundary: keep `SSI263.phoneme_log` as the single raw-code ledger, make chip diagnostics opt-in/silent by default, stop `BNS.run()` from clearing or repeatedly printing that ledger, and expose one typed chip-owned view that carries code, name, example, and IPA. This directly lets callers select codes, phoneme names, examples, or IPA without re-decoding the table.
- Spoken words cannot be recovered exactly from an arbitrary raw phoneme stream because the stream has no trustworthy word-boundary record; the API must not label example words or pause-separated fragments as recognized words.
- Next action: add focused tests for silent writes, the typed retained view, and non-destructive BNS execution, then make the smallest owner changes needed to pass them.

### Speech capture implementation state

- Added focused `tests/test_ssi263.py` coverage. It proves chip writes are silent, capture records retain code/name/example/IPA, pauses can be filtered, `BNS.run()` retains the raw log without repeated `[Speech]` batches, and the real CLI can request compact phoneme names.
- Added immutable `Phoneme` records and `SSI263.get_phonemes()` on the existing chip owner. `get_phoneme_text()` now derives non-pause names from that view instead of filtering stale `PA1`/`STOP` names.
- Removed unconditional SSI-263 RATEINF, CTRLAMP, phoneme, and reset prints.
- Replaced the `BNS.run()` print-and-clear loop with non-destructive statistics derived from the retained log.
- Added CLI `--speech {codes,names,ipa,examples}`. `examples` means the datasheet example-word field, not recognition of the spoken words.
- Updated `tools/trace_bs2_battery_menu.py` to use the shared retained capture instead of installing and maintaining a duplicate callback list.
- Current focused result: `uv run pytest tests/test_ssi263.py -q` passes 3 tests.
- Current state: implementation is uncommitted. The existing user phoneme-table correction in `qns/ssi263.py` remains preserved and overlaps the file changed by this slice.
- Blocker: none. The checkpoint requires this notes file to remain uncommitted, so it must not be staged with the source commit.
- Next action: run the relevant SSI-263, synth, and BS2 verifier tests plus Ruff; inspect the complete diff; then stage and commit only the intended code/tests/tool files, excluding this notes file.

### Speech capture verification state

- Final scoped Ruff command passes for `qns/ssi263.py`, `qns/bns.py`, `tools/trace_bs2_battery_menu.py`, and `tests/test_ssi263.py`.
- Final SSI-263/synth run reports 25 passing tests and 3 deselected manual tests. Its only failure is the pre-existing `tests/test_synth.py::test_time_stretch_duration_modes`: `qns.synth.dsp.time_stretch` returns four samples for duration 3 where that test expects fewer than four. This slice does not modify `qns/synth/dsp.py`.
- The focused speech authority itself remains green: all 3 tests in `tests/test_ssi263.py` pass.
- The prior notes establish that the real battery verifier requires an explicit preserved state argument, but do not record the exact state path used with `tools/trace_bs2_battery_menu.py`. No state was guessed and the real-ROM workflow was not rerun.
- State: source changes are ready for exact diff inspection. The checkpoint requires `notes-software-bns.md` to remain uncommitted and unstaged.
- Blocker: none for committing the speech cleanup. The unrelated DSP failure and unavailable historical verifier argument must be reported but are outside this slice.
- Next action: inspect the exact working and intended diffs, verify whitespace, stage only `qns/ssi263.py`, `qns/bns.py`, `tools/trace_bs2_battery_menu.py`, and `tests/test_ssi263.py`, inspect the staged diff, and commit those files without the notes.

### Speech capture commit gate

- Extended the CLI authority across every advertised representation: hexadecimal codes, SSI-263 names, IPA, and datasheet example words.
- Final focused command `uv run pytest tests/test_ssi263.py -q` passes 6 tests.
- Final scoped Ruff passes all four intended code/test files.
- Scoped whitespace passes with Git's `cr-at-eol` handling for the repository's tracked CRLF SSI-263 file.
- Exact intended commit paths are `qns/ssi263.py`, `qns/bns.py`, `tools/trace_bs2_battery_menu.py`, and the new `tests/test_ssi263.py`.
- `qns/ssi263.py` includes the user's pre-existing corrected datasheet phoneme table as well as this slice's capture API and logging cleanup. That table is directly part of the phoneme surface and has been preserved unchanged by this work.
- `CLAUDE.md`, all `qns/synth/` changes, all other untracked artifacts, and this notes file remain outside the commit.
- Blocker: none.
- Next action: stage exactly the four intended paths, inspect staged names/diff/whitespace, then commit the kept speech cleanup while leaving this notes file unstaged and uncommitted.

### Full software-BNS goal resumed after speech cleanup

- Commit `63986cb` (`Clean up SSI-263 speech capture`) contains the four intended speech paths. The checkpoint-required `notes-software-bns.md` update and all unrelated user-owned synth/artifact changes remain unstaged.
- The speech slice is supporting work only; it is not completion of the full working Braille 'N Speak objective.
- The first unfinished real-product path remains external program import and execution through the supplied `bs2eng.bns` ROM and its own file system.
- The user's literal correction controls the verifier: use O-chord first, then lowercase `f` when the ROM says `Enter file command`. The rejected verifier's direct/incorrect menu sequence must not be reconstructed or reused.
- The source-backed transfer mechanism remains firmware YMODEM over ASCI, and execution must occur from a real `TY_EXEC` file-system entry. Direct host-memory injection remains forbidden as a substitute.
- The active ordered phases are: real external-program import/execution; full chord-to-stdio keyboard and serial verification; remaining genuine supplied-ROM profiles; then a requirement-by-requirement end-to-end audit including boot, persistence, files, programs, speech/audio, and stdio.
- Current observation: no tracked verifier remains in the repository. Existing bounded keyboard-driving logic is only in `tools/trace_bs2_battery_menu.py`; current code search found no retained YMODEM driver.
- Current blocker: none. The exact raw O-chord value and the initialized state to use still need to be recovered from current authoritative code/records before any verifier edit or run.
- Next action: read the existing ASCII-to-BNS chord mapping and the recorded initialized-state authority, then build the bounded verifier around the exact O-chord followed by `f` sequence.

### External-program verifier authority recovered

- The tracked keyboard table maps uppercase `O` to raw `0x55`, lowercase `f` to `0x0B`, uppercase T-chord to `0x5E`, lowercase `r` to `0x17`, lowercase `y` to `0x3D`, and uppercase X-chord to `0x6D`.
- The exact recorded initialized file-system state exists at `C:\Users\Q\AppData\Local\Temp\qns-bs2-file-lifecycle-20260718.state` with the recorded length 2,686,992 bytes. A direct `BNS.load_state()` verifier does not save the state, so it can be used read-only.
- Firmware `FILEP.C` confirms the menu path: O-chord, lowercase `f`, then T-chord selects `upload_download(0)`.
- Firmware `FILETRAN.C` confirms receive selection: lowercase `r` selects download/receive and lowercase `y` selects batch YMODEM. The selected `ser_chan` is initialized through `ftran_init`; the existing BNS ASCI callbacks are the required host boundary.
- Firmware receive behavior is implementation-specific and now read directly: `ymodem_receive` repeatedly transmits `C` until it receives a 128-byte SOH block zero; it validates block number zero/complement and CRC, ACKs the header, creates/reserves the real file using the header filename and decimal size, then `xmodem_receive` transmits `C` and accepts numbered 128-byte SOH or 1K STX data blocks. Each valid block is ACKed; EOT is ACKed and the outer YMODEM loop again transmits `C`; an empty block-zero header is ACKed to finish the batch.
- The supplied `bsname.bns` must therefore be sent as a real block-zero filename/size plus numbered data blocks and an empty terminating header. Direct memory placement remains invalid.
- Current blocker: none. The verifier must capture and respond to serial channel 0 first, using the firmware's default `ser_chan`; if current live evidence proves another channel is selected, that finding must be handled explicitly rather than guessed.
- Next action: write the bounded real-ROM verifier with exact prompt-paced chords and firmware-specific YMODEM exchange, then run it against `bs2eng.bns`, the recorded state, and `bsname.bns`.

### Corrected external-program verifier first live result

- Added untracked `tools/verify_bs2_external_program.py`. It is bounded, lint-clean, uses the real ROM/state/file system, sends exact prompt-paced O-chord `0x55`, lowercase `f`, T-chord, lowercase `r`, and lowercase `y`, implements the firmware's CRC/YMODEM exchange, and requires the real external entry state `CBAR=0x11` with PC `0x1000` or `0x100E`.
- The first real run used `roms\NFB99\BS2ENG\bs2eng.bns`, the exact recorded lifecycle state, and `roms\NFB99\BS2ENG\bsname.bns`.
- It reached the receive wait but ASCI0 produced no initial `C` within 100,000,000 cycles. Exact failure state: PC `22DD`, empty serial tail. No file transfer or application execution is claimed.
- The run also exposed an existing unrelated unconditional `[MEM] Write to VOLUME` flood from the memory path; it obscures diagnostics but did not satisfy or alter the protocol predicate.
- This is the first no-improvement slice on the same exact target; the verifier remains uncommitted while the concrete failure is diagnosed.
- Current blocker: none. The evidence must distinguish wrong ASCI channel from an earlier firmware prompt/state before changing product code or widening the target.
- Next action: decode the captured post-key phoneme sequence on failure and map PC `22DD` against the linked firmware, then rerun the same exact verifier on the source-proven channel or correct the exact missing prompt transition.

### External transfer start sequence corrected

- The diagnostic rerun reproduced the same bounded no-output state at PC `22DD`, with normal BS2 MMU `CBR=34`, `BBR=0C`, `CBAR=C6` and no ASCI0 bytes.
- The retained phoneme tail proves the menu path was correct: it spoke the transfer-protocol choices and ended with the phrase `to start the transfer`.
- The prior sequence was incomplete. The July 1999 help explicitly says `Enter e-chord and begin the transfer`; lowercase `y` only selects YMODEM. This missing E-chord occurs before any serial `C`, so channel switching would have been a causally invalid response.
- Exact corrected suffix is therefore T-chord, lowercase `r`, lowercase `y`, wait for the prompt to settle, then uppercase E-chord raw `0x51`. Only after E-chord should the verifier wait for the initial YMODEM `C`.
- Next action: add that one missing prompt-paced E-chord to the verifier and rerun the same ROM/state/program gate unchanged.

### External transfer reaches the receiver loop

- The first E-chord rerun initially stopped in the verifier itself: after lowercase `y`, firmware waits for E-chord in a live loop at PC `22DD` rather than a HALT. Requiring the generic halted-key-wait prevented E-chord from being delivered.
- The verifier now waits for the spoken prompt to settle without requiring HALT, then delivers E-chord.
- With that exact correction, the unchanged real-ROM run advances to PC `2303`, the same receiver-loop location seen by the earlier rejected verifier. MMU remains the normal firmware mapping `CBR=34`, `BBR=0C`, `CBAR=C6`.
- ASCI0 still emits no initial `C` within 100,000,000 cycles. The speech tail ends after the YMODEM selection and E-chord; the menu/prompt path is no longer the blocker.
- This proves the next decision is specifically the selected serial channel versus a missing ASCI transmit behavior. It does not justify changing the loader, file system, or YMODEM protocol.
- Next action: make the verifier's existing real ASCI selection explicit and rerun the identical path on channel 1. If neither real channel emits, inspect the Z180 ASCI transmit callback boundary at PC `2303` before any product edit.

### Disk probe exposes ASCI receive-interrupt gap

- The channel-1 run emitted exactly `05` (ENQ) at PC `2303`. This matches `disk_upload_download(TRUE)`, which probes channel 1 and then channel 0 before ordinary serial transfer.
- The verifier responded with NAK on channel 1 and confirmed that the native Python receive callback consumed it. Firmware did not advance to a channel-0 ENQ; after the bound it remained in the probe routine at PC `22D7`.
- Existing QNS receive tests prove only polling: they wait on `STAT0.RDRF` and read `RDR0` directly. They do not prove the internal ASCI receive interrupt used by `BSSERIAL.ASM`.
- Firmware `ftran_init` sets `IL=0x40` and the receive ISR moves `RDR0/RDR1` into the shared `queue_count`. `ftran_recv` reads only that queue. A byte reaching the callback/RDR without the ISR therefore produces exactly the observed permanent wait.
- Native `z180asci_channel_receive_data` sets `RDRF` and calls `z180asci_channel_check_interrupts`. That function currently updates the pending ASCI interrupt only inside `if (IFF1)`, so a receive event arriving while interrupts are temporarily disabled can fail to latch a pending interrupt for later service.
- Current state: the exact external-program target is still active; no transfer or execution is claimed. The untracked verifier is the only new code path.
- Next action: inspect internal interrupt service/vector logic and add a focused native regression where an ASCI byte arrives while `IFF1=0`, then `EI` must service the latched receive interrupt. Fix the native owner only if that authority fails for the current implementation.
## Hard-testing pass: Hypothesis and ASCI interrupt authority

- Added Hypothesis as a development dependency with `uv add --dev hypothesis` and committed only `pyproject.toml` and `uv.lock` as `707b8f9` (`Add Hypothesis test dependency`). The existing synth changes and this checkpoint note were not staged.
- `C:\Users\Q\src\z180emu` is clean on `master` and ahead of its remote by three commits before the interrupt test slice.
- Native ASCI receive currently calls `z180asci_channel_check_interrupts()` after setting `STAT_RDRF`, but that function only updates the CPU's ASCI pending bit when `IFF1` is already enabled. A byte accepted while interrupts are disabled can therefore remain readable through polling without becoming serviceable after `EI`.
- CPU interrupt dispatch separately gates maskable interrupt service on `IFF1 && !after_EI`, so the peripheral-side `IFF1` gate is redundant and is the current suspected cause of the real BS2 firmware ignoring the disk-probe NAK.
- Internal vector calculation is authoritative in `z180op.c`: `(IL & Z180_IL_IL) + (irq - Z180_INT_IRQ1) * 2`, combined with `I << 8`. The focused regression must use that exact calculation rather than a guessed ASCI vector.
- Current blocker: no focused regression yet proves that ASCI data arriving under `DI` is serviced after `EI`.
- Next action: inspect the existing QNS CPU interrupt-test construction and ASCI register constants, add a focused failing receive-interrupt latch test (property-based over bytes/channels where appropriate), and patch the native owner only if that test fails.
## ASCI interrupt-latch failure proven

- Added `test_asci_receive_interrupt_survives_disabled_interrupts` to `tests/test_cpu.py` and committed it as `fd47daf` (`Test ASCI receive interrupt latching`).
- The Hypothesis test covers both ASCI channels and arbitrary byte values. It configures IM2 and the exact internal vector (`IL+0Eh` for ASCI0, `IL+10h` for ASCI1), receives a byte while `IFF1` is disabled, proves the Python callback byte was consumed, then executes `EI` and requires the ISR to read the same byte.
- Current native extension fails the test. Hypothesis shrank the failure to channel 0 and byte `00`: the callback queue is consumed while `DI`, but the ISR marker remains unset after `EI`.
- This confirms the real-ROM disk-probe NAK failure is not a verifier timing guess: native ASCI receive loses the interrupt-pending state when data arrives while `IFF1` is clear.
- Current blocker: `z180asci_channel_check_interrupts()` in the native owner gates pending-state updates on `IFF1`.
- Next action: remove only that peripheral-side `IFF1` gate, rebuild the QNS extension using the repository's exact build entrypoint, rerun the property regression, and keep or revert the native slice based on that result.
## ASCI latch fixed locally; real-ROM gate still fails

- Removed only the `IFF1` condition around `z180_set_asci_irq()` in `C:\Users\Q\src\z180emu\z180\z180asci.c`, rebuilt with `uv run tools/build_ffi.py`, and reran the focused Hypothesis authority.
- The property regression passes all 32 generated channel/byte examples. The complete native CPU callback/interrupt module also passes: `7 passed`.
- The genuine BS2 external-program verifier still fails after the change. Firmware emits the ASCI1 disk-drive ENQ, consumes the queued NAK from Python, but never emits the expected ASCI0 ENQ within 100,000,000 cycles. Final state remains `PC=22D7 CBR=34 BBR=0C CBAR=C6`; the required external-program entry is not reached.
- Therefore the native change fixes a proven emulator defect but has not yet produced a kept reduction in the active real-ROM target. It remains uncommitted pending causal tracing; do not call the external-program gate passed.
- Current blocker: it is not yet known whether the ASCI1 ISR actually reads the NAK into firmware's shared queue, whether the firmware rejects it, or whether the verifier switches input channels before frame completion.
- Next action: inspect and instrument the existing verifier/native-visible state narrowly around the ASCI1 response and firmware ISR/queue transition, then either keep the native slice with a demonstrated real-ROM improvement or revert it completely before another source slice.
## Debugging-tool improvement requested

- The user explicitly redirected the next work to reread and improve the debugging tooling instead of continuing with coarse timeout diagnosis.
- Existing verifier evidence is insufficiently discriminating: an empty Python input queue proves only that the ASCI callback accepted a byte at the beginning of a frame. It does not prove frame completion, `RDRF`, ASCI pending state, internal-vector dispatch, ISR entry, or the firmware shared queue increment.
- Firmware authority in `BSSERIAL.ASM` confirms `ftran_send_wt()` waits on `queue_count`; `ftser0`/`ftser1` must read `RDR0`/`RDR1` and call `put_char` before the disk-probe response exists at the C level.
- The minimal native `IFF1`-gate removal remains the only emulator source diff. It passes the 32-example property test and all seven CPU callback/interrupt tests. It will be committed before the separate debugging-tool source slice so Git remains the accountability ledger.
- Current blocker: QNS exposes CPU/MMU state and serial callback bytes but not the intermediate ASCI or internal-interrupt state needed to locate the lost NAK.
- Next action: commit the proven native slice, reread `tools/build_ffi.py`, `qns/cpu.py`, and the existing BS2 trace tools, then add the smallest reusable observability needed to report callback consumption, ASCI frame state, pending interrupt, and firmware queue/ISR progress during the real-ROM verifier.
## Native ASCI observability seam

- Reread the existing CFFI wrapper and native ASCI structures. `tools/build_ffi.py` already owns a per-instruction hook and the native device pointer; `z180asci.h` exposes channel status, remaining receive bits, and FIFO pointers, while `z180.c` kept the ASCI pending bit private.
- Added a narrow read-only native API, `z180_get_asci_irq_pending(device, channel)`, in `z180/z180.h` and `z180/z180.c`. It exposes only the two existing ASCI pending bits and returns zero for an invalid channel.
- Rebuilt the QNS CFFI extension successfully with the exact `uv run tools/build_ffi.py` entrypoint. Only the two pre-existing upstream compiler warnings were emitted; `git diff --check` is clean.
- Current blocker: QNS does not yet bind or display this API, and the wrapper does not yet expose ASCI status/frame/FIFO state or PC-watch hits.
- Next action: commit the two-file native debug seam, then implement and test the corresponding read-only QNS diagnostics and use them in the real-ROM transfer verifier.
## QNS causal ASCI diagnostics implemented, not yet verified

- Committed the native read-only pending-state seam as `465158c` (`Expose ASCI interrupt pending state`) after normalizing the touched source regions back to the repository's CRLF format.
- Extended `tools/build_ffi.py` with read-only ASCI status, receive-bit count, receive-FIFO depth, and pending-interrupt getters. Reused its existing per-instruction hook for one resettable PC watch address, hit count, and last-hit cycle; this avoids a Python callback on every instruction.
- Extended `qns/cpu.py` with `asci_debug_state(channel)`, `watch_pc(address)`, `pc_watch_count`, and `pc_watch_cycle`. Invalid channels and watch addresses raise instead of silently aliasing state.
- Strengthened the existing Hypothesis ASCI latch regression so every generated channel/byte example must show the completed frame in the FIFO with an IRQ pending before `EI`, then prove the ISR address was entered exactly once and the FIFO/RDRF state was drained afterward. Added explicit invalid-channel coverage.
- Current blocker: these QNS edits have not yet been rebuilt, linted, or executed; the verifier has not yet consumed the new diagnostics.
- Next action: normalize touched tracked files to CRLF, rebuild the CFFI extension, run focused lint/property tests, then add phase snapshots to the real-ROM verifier and rerun it to locate the NAK precisely.
## QNS line-ending contamination removed

- Whole-file `unix2dos`/`dos2unix` conversion could not reproduce these Python files' existing mixed line endings and produced hundreds of false Git changes. `git diff --check` exposed the mistake before staging.
- Restored exactly `tools/build_ffi.py`, `qns/cpu.py`, and `tests/test_cpu.py` to their committed `HEAD`; all three were clean before this diagnostic slice, so no user-owned work was discarded.
- Reapplied only the semantic CFFI diagnostic and `Z180` Python API hunks with `apply_patch`. The strengthened test hunk has not yet been reapplied at this checkpoint.
- Current blocker: finish reapplying the test assertions, then confirm the diff is narrow before rebuilding and rerunning the already-passing authorities.
- Next action: reapply the focused test hunk, inspect `git diff --stat` and `git diff --check`, rebuild, lint, and rerun the focused and full CPU tests.
## Causal ASCI debug surface committed

- Reapplied only the semantic hunks after the line-ending repair. The final tracked diff was limited to `tools/build_ffi.py`, `qns/cpu.py`, and `tests/test_cpu.py`; `git diff --check` passed.
- Rebuilt successfully, Ruff passed, both focused diagnostic tests passed, and the full native CPU module reports `8 passed`. The Hypothesis regression still covers 32 generated channel/byte combinations.
- Committed the QNS diagnostic surface as `558e55e` (`Expose causal ASCI debug state`). The uncommitted checkpoint note and all user-owned synth changes remained unstaged.
- Current blocker: the untracked real-ROM verifier does not yet read the ASCI snapshot or configure a PC watch, so its timeout still cannot distinguish frame, interrupt, ISR, and firmware-queue stages.
- Next action: update only `tools/verify_bs2_external_program.py` to resolve the current ASCI ISR vector, watch that address, wait for frame completion rather than callback consumption, and include the causal ASCI/watch state in phase failures; then lint and rerun the real-ROM gate.
## First causal verifier run exposed a tooling timeout defect

- Added causal disk-probe tracing to `tools/verify_bs2_external_program.py`: callback acceptance, receive shift, completed frame/FIFO, IRQ pending, and ISR drain. Serial timeout errors now include both ASCI native snapshots and prior phase context.
- Added `tests/test_bs2_external_program.py` with Hypothesis authorities: 100 CRC inputs checked against independent `binascii.crc_hqx`, 64 randomized 128/1024-byte YMODEM packet envelopes, and randomized wrong-size rejection. All three tests pass; verifier/test Ruff passes.
- The real-ROM run did not finish after more than three times its prior wall-clock baseline because the new instruction-level receive trace inherited the product-scale `100,000,000` cycle limit. That can require tens of millions of Python/native crossings and is not an acceptable diagnostic bound.
- The process backend could not send Ctrl-C. I enumerated the exact launched process tree by command line, then stopped only PIDs `1980`, `103000`, `125380`, and `190032`; no unrelated process or project state was touched.
- Current blocker: the ASCI debug snapshot does not expose configured bit rate/frame width, so the tool cannot yet derive a hardware-based frame deadline.
- Next action: expose read-only ASCI bit rate and frame width, test them, derive the receive-trace bound from the actual configuration, and rerun the real-ROM verifier.
## ASCI scheduler timing exposed and committed

- Reread QNS's actual ASCI scheduler: `qns_z180_execute` calls each channel timer once per 16 accumulated CPU cycles, while the channel exposes `m_brg_const` and `m_bit_count`.
- Added those exact values to the read-only ASCI snapshot as `brg_divisor` and `frame_bits`; strengthened the Hypothesis regression to require both to be configured.
- Rebuilt successfully, Ruff passed, and the full CPU module still reports `8 passed`.
- Committed the timing diagnostics as `6a458ab` (`Report ASCI frame timing state`).
- Current blocker: `wait_for_firmware_receive` still uses the old product-scale `CYCLE_LIMIT`; the newly exposed values are not yet used to bound its instruction-level loop.
- Next action: calculate the trace limit from `16 * brg_divisor * (frame_bits + callback allowance)`, with the observed 50,000-cycle regression baseline and modest slack as the floor; include divisor/frame values in formatting, then rerun the verifier.
## Causal verifier identifies missing RIE

- The bounded real-ROM run now completes diagnostically in about 12.5 seconds instead of hanging. Its exact ASCI1 sequence was: callback accepted at cycle `29616032`, 10-bit shift started, frame completed at cycle `29619232` with FIFO depth 1, then no interrupt or drain within the 100,000-cycle trace bound.
- Final ASCI1 state was `STAT=86 bits=0 fifo=1 irq=0 div=20 frame=10`. `RDRF` and `TDRE` are set, but `RIE` (`08`) is clear. The NAK reaches the native receive FIFO; the firmware ISR is not requested.
- Firmware source authority is explicit: BSNEW `_DSKION` loads `A=08h` and executes `OUT0 (STAT1),A` before the disk ENQ. Therefore the intended ROM path enables receive interrupts, but the observed native state does not retain RIE through response arrival.
- Committed the improved verifier and its three Hypothesis property authorities as `634ca65` (`Trace BS2 external program transfers`).
- Current blocker: a current-state snapshot cannot show whether RIE was never set or was set and later cleared by another STAT1 write.
- Next action: extend the existing native instruction-hook diagnostics with RIE set/clear transition counts and last transition PC/cycle for each channel, test those counters, and rerun the same ROM path to identify the responsible transition.
## RIE transition tracing verified

- Extended the existing native instruction hook with per-channel RIE set/clear counts and the previous instruction PC/cycle for the most recent edge. Added an explicit reset operation so a real-ROM phase can discard earlier boot transitions.
- The first build found that the hook's generic `device_t *` cannot directly dereference `z180asci`; corrected the two accesses to use the already-matched concrete `g_cpu->device`. No change to the diagnostic semantics was needed.
- The focused Hypothesis test passes all 32 channel/byte examples and confirms one RIE set, no clear, exact setter PC `001A`, and a nonzero transition cycle. Ruff passes and the complete CPU module reports `8 passed`.
- Current blocker: the tracked RIE counter slice is not yet committed, and the real-ROM verifier does not yet reset or display these counters.
- Next action: commit exactly `tools/build_ffi.py`, `qns/cpu.py`, and `tests/test_cpu.py`, then update the verifier formatting/reset point and rerun the same BS2 disk-probe path.
## Real ROM shows no RIE edge during transfer start

- Reset RIE transition history immediately before delivering E-chord and reran the identical real-ROM path.
- The receive sequence is unchanged through callback, 10-bit shift, and completed FIFO frame, but the final diagnostic now reports `rie:+0/-0@0000/0`. RIE was neither set nor cleared after the transfer-start reset.
- This rules out a later RIE-clearing transition within the observed phase. It does not yet distinguish no STAT1 write from an attempted STAT1 write that carried another value or decoded outside the ASCI channel.
- Committed the bounded/attributed verifier update as `50c8e82` (`Bound and attribute BS2 ASCI receive traces`).
- Current blocker: native ASCI exposes resulting status but not the count/value of attempted STAT register writes.
- Next action: add minimal native STAT-write count/last-value evidence, bind it through the existing QNS ASCI snapshot with phase baselining and previous-PC attribution, test it, then rerun the ROM path.
## Native STAT-write evidence committed

- Added `m_stat_write_count` and `m_stat_last_write` to each native ASCI channel. Device reset clears both; writes to STAT0/STAT1 increment the counter and retain the exact byte before applying existing register semantics.
- The CFFI extension compiles successfully with the new native layout. Initial `unix2dos` was wrong for these LF-based ASCI files; `git diff --check` exposed the false whole-file diff, `dos2unix` restored repository format, and the final native diff was exactly eight inserted lines.
- Committed the native evidence surface as `ea21f73` (`Record ASCI status register writes`).
- Current blocker: QNS does not yet expose write count/value or attribute observed writes to prior instruction PC/cycle.
- Next action: baseline the native write counters in `reset_asci_debug`, track count changes in the existing instruction hook, expose phase write count/last value/PC/cycle in `asci_debug_state`, test exact STAT writes, and rerun the real ROM.
## STAT-write attribution bound and tested

- `reset_asci_debug` now baselines each channel's native STAT-write counter. The instruction hook detects later count changes and records the preceding instruction PC and current cycle.
- `asci_debug_state` now reports phase-local STAT write count, last byte, last write PC, and last write cycle.
- The Hypothesis ASCI regression proves the synthetic `OUT0 (STAT),08h` as exactly one write of `08` attributed to PC `001A`, alongside the RIE set edge. The extension builds, Ruff passes, and the full CPU module reports `8 passed`.
- Committed the QNS binding as `ef58450` (`Attribute ASCI status register writes`).
- Current blocker: the real-ROM verifier formatting does not yet print these four fields.
- Next action: add the STAT-write evidence to `format_asci_state`, rerun the identical ROM path, and use count/value/PC/cycle to decide whether the fault is missing firmware execution or incorrect register decoding.
## 2026-07-18: Cycle-stamped serial output proved stale disk-probe handling

- Current debugging-tool slice adds raw ASCI STAT-write attribution to verifier failures and a `TimestampedBytesIO` serial sink that records each emitted byte with its emulated CPU cycle.
- Added a focused authority proving the sink preserves bytes and records the cycle supplied at each write. `uv run ruff check tools/verify_bs2_external_program.py tests/test_bs2_external_program.py` passes; `uv run pytest tests/test_bs2_external_program.py -q` passes (`4 passed`).
- The bounded real-ROM verifier now proves the channel-1 ENQ was emitted at cycle `17801000`, before the `E` chord phase (`before_E=29599000`, `after_E=29616000`).
- The existing verifier found that old ENQ after `E`, queued NAK at cycle `29616032`, and then failed because firmware had already disabled RIE: `stat:86`, `irq:0`, `rie:+0/-0`, `statw:0:04`.
- This is a verifier orchestration defect, not evidence that the ROM failed to receive an on-time disk-probe response. The verifier must answer each probe in the phase where the ROM emits it instead of consuming stale serial output after `E`.
- Current blocker: identify the exact chord transition during which each channel's ENQ is emitted, then place `reject_disk_probes` at that causal point while retaining the same real-ROM/YMODEM/external-entry acceptance gate.
- Next action: use the existing cycle-stamped event list around each already-instructed chord boundary, then move only the probe-response orchestration to the proven boundary and rerun the exact verifier.

### Probe handling moved to the correct command phase

- Per-chord serial attribution proved the first disk ENQ belongs exactly to the T-chord phase: `O=[]; f=[]; T=[05@17801000]; r=[]; y=[]`.
- The task record and firmware source agree on the semantics: T-chord enters `upload_download(0)` and performs disk probes; lowercase `r`, lowercase `y`, and E-chord select receive, YMODEM, and transfer start only after probing.
- The verifier was reordered to handle both disk probes after T and before `r`, `y`, and `E`. Ruff and all four focused/property tests still pass.
- The first reordered real-ROM run still answered too late because it retained `run_until_stable_key_wait()` after T. The NAK entered ASCI1 at cycle `25601312`, but firmware had already cleared RIE at cycle `19456352`, attributed to PC `0E7E`; phase-local evidence was `rie:+0/-1` and `statw:2:04`.
- Current blocker: the generic post-key idle wait is not valid during a live serial handshake and delays the host response beyond firmware's probe window.
- Next action: remove only the stable-key wait after T, begin `reject_disk_probes` immediately after T key acknowledgment, and rerun the exact real-ROM verifier. If key acknowledgment itself returns after the probe window, add timestamps around its existing key-down/key-up boundaries before altering it.

### On-time ASCI1 probe now reaches the firmware ISR

- Removed only the invalid stable-key wait after T. The real-ROM run now queues NAK while RIE is active: callback at cycle `17801312`, frame and IRQ at `17804512`, firmware drain at cycle `17804526` with PC `23FB`.
- This is a kept causal reduction: the host response crosses the Python callback, native frame/FIFO, ASCI interrupt, and firmware ISR instead of remaining stranded after RIE shutdown.
- Committed the timestamp/STAT attribution, source-backed probe ordering, and focused timestamp authority as `cccecea` (`Trace BS2 serial phases causally`). The checkpoint note and user-owned files remain unstaged.
- The next exact real-ROM failure is channel 0: no ASCI0 ENQ reached the selected serial sink within the existing bound. Final diagnostics show ASCI0 was initialized and later disabled (`rie:+1/-1@2971/19434135`, `statw:2:00@2971/19434135`, `STAT=00`), while ASCI1 is fully drained.
- Firmware `disk_upload_download()` explicitly loops ports 1 then 0, calling `ftran_done()` after a non-ACK. QNS switches capture/input to channel 0 immediately after the ASCI1 drain, before the observed ASCI0 init/disable transition.
- Current blocker: existing diagnostics do not distinguish a byte stuck in TDR with transmitter disabled, an active/stalled transmit shift register, or a completed transmit callback.
- Next action: extend the existing read-only `asci_debug_state` with native `CNTLA`, `tx_bits_rem`, shift-register byte, and TDR byte; strengthen the existing channel-0 transmit test around those states; rebuild and rerun the exact ROM gate before changing emulator behavior.

### Bidirectional ASCI state authority staged

- Extended the existing read-only `asci_debug_state` rather than adding another interface. It now exposes native `CNTLA`, TX bits remaining, shift-register byte, and TDR byte for either ASCI channel.
- Upgraded the existing fixed channel-0 transmit test to a 32-example Hypothesis authority across channels 0/1 and arbitrary byte values. Every example must expose the exact in-flight frame and registers, then emit one exact `(channel, byte)` callback and finish with zero TX bits.
- Rebuilt successfully with `uv run tools/build_ffi.py`; only the two known upstream compiler warnings remain. Scoped Ruff passes. The focused property authority passes, and the full CPU module reports `8 passed`.
- Staged exactly `tools/build_ffi.py`, `qns/cpu.py`, and `tests/test_cpu.py`; staged whitespace is clean. The note and all user-owned paths remain unstaged.
- Current blocker: the real-ROM failure has not yet been rerun with TX fields included in verifier formatting, so the ASCI0 failure mechanism is not yet identified.
- Next action: commit the staged diagnostic slice, then update only verifier formatting to print the four TX fields and rerun the exact ROM/state/program gate.

### ASCI0 ENQ is stuck in a disabled transmitter

- Committed the bidirectional ASCI snapshot and property authority as `8fd7247` (`Expose ASCI transmit debug state`).
- Added the four TX fields to the verifier failure line, reran Ruff and the four verifier/property tests, then reran the exact real-ROM command.
- Decisive ASCI0 state is `STAT=00`, `CNTLA=11`, `txbits=0`, `TSR=00`, `TDR=05`. Native `CNTLA_TE` is bit `20`, so the firmware wrote ENQ into TDR while the transmitter was disabled; it never entered the shift register and no callback could occur.
- Committed that two-line verifier reporting slice as `32cae69` (`Report ASCI transmit state`).
- The `.state` loader intentionally restores only nonvolatile memory; the ROM boots and configures peripherals normally. This is not a purported full CPU snapshot restoration failure.
- Exact firmware source shows channel-0 `ftran_init()` calls `SERON`; `DTRON` loads `COMBYT`, clears bit 4, ORs `08`, and writes CNTLA0. Boot initializes `COMBYT=64` and writes CNTLA0. Therefore the later `CNTLA=11` requires a control value lacking TE/RE before the probe write/teardown.
- Current blocker: existing diagnostics show only final CNTLA. They do not attribute the value-changing CNTLA0 write or show the firmware `COMBYT` byte at that instruction.
- Next action: locate the linked `COMBYT` address and add phase-local CNTLA transition value/PC/cycle attribution to the existing instruction hook; then rerun the exact ROM gate to distinguish corrupted firmware memory from incorrect native CNTLA behavior.

### Causal stuck-TDR detector identifies firmware control value

- No generated map/symbol/list artifact exists under the firmware source tree, so there is no authoritative linked `COMBYT` address available for a direct memory watch.
- Improved the existing serial wait instead: each call now names its real ASCI channel and, for a single expected byte, fails immediately only when that exact byte is in TDR, no TX frame is active, and `CNTLA.TE` is clear. Completed output is checked first.
- Added a native-backed regression where a Z180 program writes ENQ to TDR0 with TE disabled. The verifier reports the causal stuck state; the full verifier/property module reports `5 passed`, and Ruff passes.
- The exact real-ROM run now fails in 7.3 seconds instead of waiting through 100,000,000 cycles. Causal state at cycle `17806526`, PC `22E4`: `CNTLA=01`, `STAT=08`, `TDR=05`, `TSR=00`, `txbits=0`; RIE was set at PC `2940` immediately beforehand.
- Firmware `DTRON` writes `COMBYT | 08` to CNTLA0, and `ftran_init` subsequently clears bit 3 before sending ENQ. Therefore causal `CNTLA=01` proves the firmware-side `COMBYT` value supplied `01`, lacking both TE and RE; this is before `ftran_done` teardown.
- Committed the channel-aware early detector and regression as `8729941` (`Detect disabled ASCI transfers causally`).
- Current blocker: why `COMBYT` is `01` rather than the boot-initialized `64` is not yet known.
- Next action: locate the linked `DTRON` instruction sequence in the real ROM to recover the exact `COMBYT` logical address, then trace writes to that address across boot and the loaded-state workflow before changing emulator behavior.

### Linked COMBYT address recovered from the supplied ROM

- Existing firmware tools could extract/summarize banks but could not search masked instruction sequences; installed GNU objdump has no Z80 backend.
- Added a read-only masked ROM-pattern finder with automatic `.bns` payload handling and bank/logical offset reporting. Added randomized Hypothesis coverage for arbitrary linked operands/placement, malformed-pattern cases, and exact BNS header stripping. Ruff passes and the focused module reports `6 passed`.
- Searching the exact assembled `DTRON` sequence produced one match: file offset `0x005946`, firmware offset `0x002946`, bank 0 logical address `0x2946`, bytes `F5 E5 21 B0 D4 CB A6 7E F6 08 ED 39 00 E1 F1 C9`.
- The linked operand proves `COMBYT` is logical address `0xD4B0`. Under the observed/common `CBR=34` mapping this is physical `0x414B0`, consistent with the repository's existing `D653 -> 0x41653` translation authority.
- Existing BNS single-address tracing only prints `[TRACE]` values. The verifier redirects stdout, and the trace carries neither cycle nor PC, so it cannot serve as the causal write ledger required here.
- Current state: `tools/find_rom_pattern.py` and `tests/test_find_rom_pattern.py` are uncommitted; all six tests pass.
- Current blocker: no retained causal record yet shows when/where physical `0x414B0` changes from boot `64` to `01`.
- Next action: inspect and commit the ROM finder slice, then improve the existing BNS address/range tracer to retain cycle/PC/address/value events with focused tests; use that exact trace in the real verifier.

### Causal memory-write trace implementation pending verification

- Committed the masked ROM finder and six authorities as `25ae93b` (`Add masked ROM pattern finder`).
- The existing native instruction hook already retains the exact instruction-start PC. Added a read-only CFFI getter and `Z180.instruction_pc` property rather than creating another watcher.
- Extended existing BNS address/range tracing to retain matched `(cycle, instruction_pc, physical_address, value)` events in `traced_writes` while preserving current printed trace output. Overlapping address/range selectors append only one retained event.
- Added a firmware-facing test that executes `LD (F000h),A` and requires the exact retained event `(6, 0002, F000, 5A)` once under overlapping selectors.
- Current state: changes are uncommitted in `tools/build_ffi.py`, `qns/cpu.py`, `qns/bns.py`, and `tests/test_bns.py`; they have not yet been rebuilt or tested.
- Current blocker: the new CFFI getter and exact event expectation are not yet verified against the native extension.
- Next action: rebuild with `uv run tools/build_ffi.py`, run scoped Ruff and the focused trace test, then the relevant BNS/CPU modules; keep or revert this slice based on those authorities before wiring physical `0x414B0` into the verifier.

### Causal memory-write tracing verified and committed

- Rebuilt the native extension successfully; only the known upstream warnings remain. Scoped Ruff passes.
- The exact trace authority passes with retained event `(cycle=6, instruction_pc=0002, physical=F000, value=5A)` once despite overlapping address/range selectors.
- Full relevant gates pass: `tests/test_bns.py` reports `16 passed`; `tests/test_cpu.py` reports `8 passed`.
- Committed the instruction-PC getter and retained BNS trace ledger as `d832c77` (`Retain causal memory write traces`).
- Wired the real verifier to the unique physical `COMBYT` address `0x414B0`; ASCI0 failure context now formats every retained value as `value@cycle/pc=instruction`.
- The verifier integration is uncommitted but scoped Ruff passes and its full focused/property module reports `5 passed`.
- Current blocker: the real ROM has not yet been rerun with the retained `COMBYT` history, so the writer that changes `64` to `01` is still unknown.
- Next action: run the exact ROM/state/program verifier and use its `COMBYT` history to locate the first causally relevant writer; then keep/commit or revert the integration based on whether it produces that decision-changing evidence.

### Boot initializer is absent from the loaded-state startup path

- The first physical `COMBYT` trace remained empty through the causal ASCI0 failure, proving `0x414B0` was not written during that run.
- The ROM finder uniquely located the boot `LD (D4B0),A` instruction at PC `07F2`.
- A diagnostic that required reaching `07F2` was invalid for this startup path: after 100,000,000 cycles the ROM was already idling at the editor command loop `D657`, and the initializer had never been reached. No product conclusion was inferred from forcing that stale gate.
- Corrected the verifier immediately: it now uses the existing non-blocking PC watch for `07F2`, retains the original command-loop gate, and reports loaded/current physical `COMBYT` plus initializer hit count/cycle.
- Scoped Ruff and the five verifier/property tests pass after the correction.
- Current blocker: the corrected real-ROM trace has not yet reported whether the loaded state already contains `01` and whether it remains unchanged to the command loop.
- Next action: rerun the exact ROM/state/program verifier with the non-blocking watch. If it proves `loaded=command=01`, inspect the state format/lifecycle authority for why volatile firmware workspace is restored without the cold initializer; do not alter serial hardware first.

## Test-harness cleanup fixed-point log - 2026-07-18

Literal outcome:
- Clean up and beautify the test harnesses, explicitly abstracting repeated mechanics into helpers so real-ROM goals are easier to express and test.

Active slice:
- Tracked BS2 harness family: `tools/verify_bs2_external_program.py`, `tools/trace_bs2_battery_menu.py`, `tests/test_bs2_external_program.py`, and relevant `tests/test_bns.py` authorities.

Target architecture (provisional until the whole slice is read):
- One test-owned BS2 harness owner for bounded emulation advance, acknowledged chords, speech/key waits, serial capture/waits, and causal context.
- Scenario tools should state the ROM workflow and assertions; they should not duplicate low-level CPU/SSI/keyboard polling.

Forbidden surfaces:
- Parallel copies of `advance`, generic bounded waits, chord delivery, stable-key waits, speech-idle waits, and ad hoc context concatenation in scenario scripts.
- A renamed wrapper that merely preserves the same duplication.
- New and old harness paths coexisting after callers move.

Search gates:
- Exact duplicate helper definitions across tracked `tools/`.
- Direct scenario access to `_pending_irq_cycle`, keyboard latch polling, and repeated CPU/SSI advance sequences after ownership moves.

Runtime gates:
- Scoped Ruff; focused harness/property tests; full `tests/test_bns.py` and `tests/test_cpu.py`; unchanged exact real-ROM verifier command.

Iteration 1 state:
- Fully read the external-program verifier and focused tests.
- The verifier mixes five responsibilities: emulator timing, input choreography, serial protocol transport, diagnostics/context formatting, and the external-program scenario.
- Existing focused tests strongly own CRC/YMODEM construction, timestamp capture, and disabled-transmitter diagnosis; those capabilities must survive under the correct owner.
- `tools/trace_bs2_battery_menu.py` and the full relevant BNS test file are not yet read, so helper ownership is not yet final and no refactor edit has started.
- Current blocker: none; required whole-slice reading is incomplete.
- Next action: read the battery harness and full BNS tests, classify every overlapping helper, then choose the smallest real owner and delete duplicated scenario-local mechanics first.

### Iteration 1 ownership dispositions finalized

Whole slice read:
- `tools/verify_bs2_external_program.py`
- `tools/trace_bs2_battery_menu.py`
- `tests/test_bs2_external_program.py`
- `tests/test_bns.py`

Surfaces:
- Repeated CPU/SSI advancement, bounded predicates, acknowledged chords, stable key waits, and speech-idle waits.
  - Disposition: consolidate.
  - Owner after cleanup: one test-only `tools/bs2_harness.py` `BS2Harness`.
- `TimestampedBytesIO` plus standalone event formatting.
  - Disposition: rewrite/consolidate.
  - Owner after cleanup: harness-owned `SerialCapture` with its own event formatting.
- Serial queueing, ASCI formatting, receive-path tracing, and output waits.
  - Disposition: move.
  - Owner after cleanup: `BS2Harness`; these are reusable firmware-test mechanics, not external-program semantics.
- CRC-16/XMODEM packet construction and batch/file transfer sequencing.
  - Disposition: keep in external-program scenario; this protocol is specific to that scenario and already has independent property authorities.
- Disk-probe rejection and external entry assertion.
  - Disposition: rewrite callers to accept `BS2Harness`, but keep as scenario helpers.
- Gas-gauge edge capture, expected commands/speech, and logical-to-physical diagnostic mapping.
  - Disposition: keep in battery scenario; they are scenario-specific assertions.
- `tests/test_bns.py` production-facing BNS/stdio/state tests.
  - Disposition: keep; they test product owners, not harness mechanics.
- Timestamp and disabled-transmitter tests currently in `tests/test_bs2_external_program.py`.
  - Disposition: move to a dedicated harness test module. YMODEM properties remain with the external-program scenario.

Search gates after caller migration:
- `rg -n '^def (advance|run_until|deliver_chord|run_until_stable_key_wait|run_until_speech_idle|queue_serial|format_asci_state|wait_for_firmware_receive|wait_for_serial)' tools/trace_bs2_battery_menu.py tools/verify_bs2_external_program.py` must return no duplicate mechanics.
- `rg -n 'TimestampedBytesIO|_pending_irq_cycle|keyboard\.latched' tools/trace_bs2_battery_menu.py tools/verify_bs2_external_program.py` must return no scenario-owned harness internals.
- New and old mechanics must not coexist.

Next action:
- Delete duplicated mechanics/imports from scenario files, create the single harness owner, move callers and harness authorities, then run the recorded search/runtime gates.

### Iteration 1 implementation state - runtime gates pending

### Iteration 1 verification update

- Focused harness/protocol authority passes: `uv run pytest tests/test_bs2_harness.py tests/test_bs2_external_program.py -q` reports 5 passed.
- Product BNS authority passes: `uv run pytest tests/test_bns.py -q` reports 16 passed.
- CPU authority passes: `uv run pytest tests/test_cpu.py -q` reports 8 passed.
- Both forbidden-surface searches are clean: the scenario tools no longer define the deleted timing/input/serial helpers and no longer access `_pending_irq_cycle`, the keyboard latch, or the serial input queue directly.
- The exact external-program real-ROM command retains the pre-refactor causal result: ASCI1 NAK crosses and drains the ISR, then ASCI0 ENQ is stuck at cycle 17806526, PC 22E4, with TE disabled; `loaded_COMBYT=00`, `command_COMBYT=00`, and the cold initializer was never hit. This expected nonzero verifier result is the active state/lifecycle blocker, not a cleanup regression.
- The battery real-ROM gate remains unavailable because the prior record explicitly says its required preserved-state path was not recorded. No state path was guessed.
- Worktree audit confirms the intended cleanup paths are `tools/bs2_harness.py`, `tests/test_bs2_harness.py`, `tools/verify_bs2_external_program.py`, `tools/trace_bs2_battery_menu.py`, and `tests/test_bs2_external_program.py`. Existing user changes and unrelated artifacts remain outside the slice.
- Current state: the new owner and test were read in full after runtime verification. The remaining clarity issue is the inherited unparenthesized transmitter-enable bit test in `BS2Harness.wait_for_serial`; the exact intended diff still needs its final lint, whitespace, and staged inspection.
- Blocker: no blocker to the cleanup commit. The missing battery-state authority blocks only that optional real-ROM gate.
- Next action: parenthesize the transmitter-enable bit test for explicitness, rerun scoped Ruff and focused tests, run whitespace checks, stage only the five intended cleanup paths, inspect the staged diff, and commit the kept slice while leaving this notes file unstaged.

### Iteration 1 cleanup commit

- Commit `6c07648` (`Unify BS2 real-ROM harnesses`) contains exactly the five intended paths: the new shared harness and its authorities plus the two migrated scenario tools and retained external-protocol tests.
- The staged whitespace gate was clean and the complete staged patch was inspected before commit. `notes-software-bns.md`, `CLAUDE.md`, the user's synth changes, ROMs, investigation artifacts, and all other unrelated paths remained outside the commit.
- Final source gates for the committed slice: scoped Ruff passes; the focused harness/protocol suite passes 5 tests; the product BNS suite passes 16 tests; the CPU suite passes 8 tests; both forbidden duplicate/private-access searches are clean.
- The exact real-ROM external-program verifier retains its causal pre-cleanup failure at cycle 17806526 / PC 22E4: the loaded warm state has `COMBYT=00`, never runs the cold initializer, drains ASCI1 NAK, then leaves ASCI0 ENQ in TDR with TE disabled.
- Current state: the first source slice is committed and the worktree accountability boundary is restored. The cleanup task is not yet declared at fixed point; the committed scenario surface must be reread for any remaining repeated choreography that materially impedes testing before choosing another source slice.
- Blocker: the battery verifier's exact preserved-state path is still absent from the durable record, so that real-ROM gate remains unavailable without user-provided authority. This does not invalidate the committed shared mechanics, which are covered by focused and product tests.
- Next action: verify post-commit status and reread the committed harness/scenario surfaces for one concrete remaining cleanup decision. If no duplicated or confusing test mechanic remains, close the cleanup plan; if one does, record and execute only that single next slice.

### BS2 harness cleanup fixed point

- Post-commit status confirms the five cleanup paths are clean. Only the pre-existing user-owned tracked changes and this required notes file remain modified; unrelated untracked artifacts remain untouched.
- The bounded ownership search finds every direct `cpu.run`, SSI-263 timing update, keyboard press/release, serial input queue access, and serial output-channel assignment only in `tools/bs2_harness.py`.
- The remaining repeated `chord`, wait, and serial-event lines in the external verifier are ordered scenario choreography: O and f require stable key waits, T enters disk probing, y requires speech settling, E begins YMODEM, and X requires external-program entry. A generic phase wrapper would erase those distinct assertions and is not another duplicated harness mechanic.
- Fixed-point decision: no second cleanup slice is justified. The requested mechanics are abstracted under one tested owner, the scenario tools read as scenarios, and the cleanup plan is complete.
- Remaining product blocker: the supplied warm state still skips the cold `COMBYT` initializer and reaches ASCI0 with TE disabled, so complete BS2ENG execution still requires the separate state/lifecycle correction. The battery verifier still lacks its exact preserved-state argument.
- Next action: resume the product goal at the recorded state/lifecycle blocker when explicitly directed; do not turn remaining scenario choreography into another helper layer.

## BS2 state lifecycle investigation - 2026-07-18

- Opened `investigations/bs2-state-lifecycle.md` under the structured investigation protocol with three competing theories: wrong state lifecycle, incomplete state serialization, or a missing reset transition.
- Current `BNS.load_state()` delegates only to `Memory.load_state()`; it does not restore CPU execution state. A new `BNS` therefore begins with a reset CPU and loads nonvolatile memory before normal ROM execution.
- State format v2 restores the complete 512 KiB RAM byte array, the complete shadow-written bitmap, and the complete 2 MiB flash image byte-for-byte. Ordinary save/load does not omit individual RAM cells.
- For exact physical `COMBYT` address `0x414B0`, the state-file bitmap byte at file offset `0x82A6` is `00`; bit 0 is clear, proving firmware had never marked that cell written in the preserved image. The raw RAM byte at file offset `0x514C0` is also `00`.
- This rules out an explicitly persisted firmware value of zero and substantially weakens the theory that CPU snapshot restoration is involved. The loaded read is zero because the cell is unwritten and zero-filled, while this reset path never reaches the ROM initializer at PC `07F2`.
- Prior source-backed evidence says cold boot assigns `COMBYT=0x64`; later `DTRON` derives CNTLA0 from it. The current state/reset combination therefore enters a path that assumes volatile workspace initialization without having performed it.
- Current best theory: the preserved nonvolatile image is lifecycle-inconsistent, likely because its warm/cold sentinel or flash state selects a warm path while required shadow RAM was never initialized. The exact ROM branch selecting `07F2` must be recovered before choosing whether state creation or QNS reset modeling is wrong.
- Blocker: none. No product source has been changed in this investigation slice.
- Next action: locate the ROM startup branch and every linked reference to `COMBYT`, then run one read-only cold-versus-current-state experiment that predicts whether a genuinely blank state reaches `07F2` and writes `0x64`.

### Blank-state startup comparison in progress

- The ROM contains exactly one direct absolute `LD (D4B0),A`, at firmware PC `0x07F2`. The initializer is inline inside a larger zero/default-initialization block; there is no direct call or jump target to `0x07F2`.
- Address-taking references exist in `DTRON` at `0x2948` and several bank-2 routines; direct reads also exist, but no second direct absolute writer was found.
- Created a new disposable state at `C:\Users\Q\AppData\Local\Temp\qns-bs2-blank-lifecycle-20260718.state` through the shipped CLI only after verifying the path did not exist.
- A blank-state run of 1,000,000 cycles reached PC `0x0AA3` and saved normally. A physical trace at `0x414B0` emitted no write.
- That absence is not yet evidence that `0x07F2` was skipped: `D4B0` is a logical operand, while `0x414B0` was derived from the later command-loop `CBR=0x34` mapping. The MMU mapping active during early initialization may place the write at physical `0x0D4B0` instead.
- Current state: no source changes. The disposable blank state now preserves the early-run shadow bitmap, so exact physical ownership can be inspected without another run.
- Blocker: none.
- Next action: inspect the blank state's bitmap/raw byte at physical `0x0D4B0`; if written as `0x64`, compare MMU mapping transitions and determine why the preserved lifecycle state lacks the later physical copy.

### Blank-state verifier distinguishes the lifecycle path

- The blank state's bitmap at physical candidate `0x0D4B0` is also clear, so the simple assumption that early `D4B0` maps identically is false or the initializer was not executed during the first one-million-cycle run.
- The exact external-program verifier was then run read-only against the new blank state. Two initially launched runs lost their output attachment because the orchestration wrapper did not retain the underlying session; both completed naturally before an attempted stop, and no process was terminated.
- A third identical run was attached correctly and reached the verifier's full 100,000,000-cycle bound at PC `0x1BDA` without reaching the BS2 editor command loop. It did not reproduce the preserved state's seven-second ASCI0 stuck-TDR failure.
- This proves the blank and preserved nonvolatile images select materially different firmware lifecycle paths. It does not yet establish whether the blank run executed PC `0x07F2`, because the command-loop timeout path fails before formatting the verifier's existing PC-watch count.
- Current state: no product source changes. One diagnostic deficiency is now concrete: the verifier installs the initializer PC watch before its boot gate but reports that watch only after the boot gate succeeds, making failed startup paths opaque.
- Blocker: none.
- Next action: add the existing initializer watch count/cycle and current MMU values as lazy context on the existing command-loop wait, cover that failure context, commit the diagnostic slice if tests pass, then rerun only the blank-state verifier once.

### Boot-timeout context committed

- Added lazy context to the verifier's existing editor-command-loop wait. On timeout it now reports the already-installed initializer PC watch count/cycle plus current CBR, BBR, and CBAR values.
- Added a focused harness authority proving timeout context is evaluated exactly once at failure and included in the causal error.
- Scoped Ruff passes; the harness/external-protocol suite reports 6 passed.
- Commit `d367b3e` (`Expose BS2 boot timeout context`) contains exactly `tools/verify_bs2_external_program.py`, `tests/test_bs2_harness.py`, and the new required investigation ledger `investigations/bs2-state-lifecycle.md`.
- The complete staged patch and whitespace gate were inspected before commit. This notes file and all user-owned changes remained unstaged.
- Current state: source slice committed and clean. No lifecycle behavior has been changed.
- Blocker: none.
- Next action: run the exact verifier once against `qns-bs2-blank-lifecycle-20260718.state`, retain its terminal output, and use `initializer_hits`, `initializer_cycle`, and final MMU registers to select the next root-cause experiment.

### Pristine-state comparison corrects the lifecycle theory

- The prior `qns-bs2-blank-lifecycle-20260718.state` was not a valid first-boot authority: it had already run for 1,000,000 cycles and been saved before the verifier. Its later `initializer_hits=0` result was correctly rejected as evidence about pristine startup.
- The ROM reset vector begins with non-writing instruction `DI` at PC `0000`, followed by `JP 032F`.
- Created `C:\Users\Q\AppData\Local\Temp\qns-bs2-pristine-lifecycle-20260718.state` through the shipped CLI with exactly one requested cycle. The run completed only `DI`, ended at PC `0001`, and saved an untouched nonvolatile image.
- The exact verifier against that pristine image reached its 100,000,000-cycle boot bound at PC `1BDA` with `initializer_hits=0`, `initializer_cycle=0`, `CBR=34`, `BBR=1E`, and `CBAR=C6`.
- This rules out the preserved lifecycle state as the reason PC `07F2` is skipped. Both pristine and previously advanced blank images take the same cold-start path and stall before the editor; the preserved initialized image contains state that bypasses this path and reaches the command loop.
- The earlier working theory that missing persisted `COMBYT` itself selects the wrong warm path is false. `COMBYT=00` remains a downstream inconsistency in the initialized image, but the root startup problem is now the cold path at PC `1BDA`.
- Current state: no new source behavior changes. The committed timeout context produced the required decision-changing evidence.
- Blocker: none.
- Next action: identify what firmware PC `1BDA` is waiting for by using existing boot trace/speech/I/O surfaces; then compare the corresponding state/device condition between pristine and preserved startup before changing code.

### Cold-start wait identified from retained speech

- The shipped `--trace` mode cannot identify this wait; it only steps ten reset instructions.
- Copied the untouched pristine state to a disposable speech-run path so the authority itself remained unchanged, then ran the real ROM for the same 100,000,000-cycle bound with retained phoneme names and final stats.
- The run ended successfully at halted PC `1BDA`, MMU `34/1E/C6`, after 84 phonemes. The retained sequence decodes as `Initialize flash system. Enter Y or N.`
- Therefore PC `1BDA` is a correct firmware prompt, not a missing device interrupt or emulator stall. Pristine startup requires an explicit prompt-paced affirmative keyboard response before the editor command loop can exist.
- The current external-program verifier's boot gate is incomplete: it waits only for editor readiness and cannot participate in the real first-boot flash initialization dialogue. The preserved state bypasses the prompt because its flash/filesystem has already been initialized.
- Current state: no uncommitted product source changes. The investigation record is modified with this new evidence and must be committed before a source slice.
- Blocker: none.
- Next action: update and commit the investigation record, then teach the real-ROM verifier scenario—not the shared low-level harness—to recognize the exact cold-start prompt state, send lowercase `y` through the acknowledged keyboard path, and continue to the existing command-loop gate. Verify first against the untouched pristine state.

### First-boot verifier workflow pending real-ROM gate

- Committed the corrected cold-start evidence as `28c2c65` (`Record BS2 cold-start prompt`) before starting the source slice.
- `tools/verify_bs2_external_program.py` now waits for the first stable firmware key state. It accepts the existing editor loop directly, or requires both halted PC `1BDA` and the exact retained phoneme-name suffix for `Initialize flash system. Enter Y or N.` before sending acknowledged lowercase `y`.
- Any other boot wait fails with its PC and speech tail. The shared low-level harness and product emulator are unchanged.
- Added property authority that arbitrary prior speech may precede the exact prompt suffix, plus negative authorities for partial and altered prompts.
- Scoped Ruff passes; `tests/test_bs2_harness.py` plus `tests/test_bs2_external_program.py` report 8 passed.
- Current state: the source slice is uncommitted in exactly the verifier and its focused test. The untouched pristine state remains at `C:\Users\Q\AppData\Local\Temp\qns-bs2-pristine-lifecycle-20260718.state` because verifier runs do not save state.
- Blocker: none.
- Next action: run the modified exact verifier against that pristine authority. Keep and commit the slice only if it crosses the real prompt correctly and produces decision-changing firmware evidence.

### First-boot response slice rejected after two no-improvement attempts

- Attempt 1 recognized the exact flash-initialization prompt at halted PC `1BDA`, sent acknowledged lowercase `y` (`0x3D`), then reached the full subsequent 100,000,000-cycle bound back at the same halted PC with zero initializer hits.
- The authoritative terminal table proved uppercase `Y` is raw chord `0x7D`, distinct from lowercase `y`; the prompt itself says `Y or N`. The slice was corrected to uppercase `Y` and gained a focused stdio-mapping authority. Ruff passed and the focused suite reported 9 passed.
- Attempt 2 sent acknowledged uppercase `Y` (`0x7D`) but produced the same no-improvement result: cycle `106654000`, halted PC `1BDA`, `initializer_hits=0`, MMU `34/1E/C6`.
- Passing prompt-recognition and mapping tests do not substitute for crossing the real prompt. Neither response produced a kept reduction on the exact target.
- Exact-convergence consequence: after two consecutive no-improvement attempts on this target, do not add speech-tail diagnostics, inspect unrelated devices, try more keys, or widen the search. Reject and fully revert the uncommitted verifier/test slice.
- Current state: uncommitted changes exist only in `tools/verify_bs2_external_program.py` and `tests/test_bs2_external_program.py`; they must be restored to commit `d367b3e` before any later source work. This notes file remains uncommitted.
- Blocker: the firmware acknowledges both raw key edges but returns to the same initialization prompt; current evidence does not establish whether it rejected the response, failed flash initialization, or deliberately repeated the dialogue.
- Next action: restore the two rejected source files, update the committed investigation ledger with the two no-improvement results, and stop this convergence turn without widening.

### Exact-convergence rule correction after erroneous revert

- The two verifier experiments were revisions within one uncommitted code-change attempt, not two consecutive slices. Applying the two-slice stop rule was wrong.
- The passing prompt-recognition/mapping work and its real-ROM evidence should have remained in the active slice while the same first-boot target was investigated. Reverting `tools/verify_bs2_external_program.py` and `tests/test_bs2_external_program.py` at that point was premature.
- Corrected persistent `C:\Users\Q\.codex\AGENTS.md` so exact convergence activates only when the user explicitly requests exact convergence, zero diff, 100% conformance, or names that workflow. General debugging, making a system work, real-artifact execution, and end-to-end completion do not activate it merely because the final result must be correct.
- The corrected rule now defines a slice as one complete code-change attempt ending in a commit or full restore. Hypotheses, commands, tests, inputs, diagnostic runs, and revisions within an uncommitted attempt are explicitly not slices.
- Failed experiments are now explicitly evidence within the active slice and cannot force a revert or stop. Diagnostic/tooling commits and experiments do not count toward the two-slice no-improvement limit.
- The two-slice stop can apply only to completed slices explicitly intended to reduce a named convergence metric; it cannot abandon the overall plan, revert independently valid work, or count experiments as slices.
- Current state: the persistent rule is fixed. The rejected two-file verifier slice remains restored; `investigations/bs2-state-lifecycle.md` contains an uncommitted experiment-record update from the interrupted turn; this notes file remains uncommitted as required.
- Blocker: none for the requested rule/failure correction.
- Next action: write the separate failure record in the established `C:\Users\Q\.codex\failures` ledger, verify both durable artifacts contain the requested correction, and report exactly what was changed.

### Premature revert repaired in the active QNS slice

- Wrote `C:\Users\Q\.codex\failures\2026-07-19-qns-experiments-miscounted-as-slices.md` with the exact repeated failure, harm, root cause, durable rule correction, and prevention requirements.
- Corrected `investigations/bs2-state-lifecycle.md` so the two response attempts are evidence within one active slice, not two convergence slices or a halt trigger. Committed that required experiment record as `31f302a` (`Record BS2 flash prompt responses`).
- Restored the prematurely reverted first-boot verifier behavior in `tools/verify_bs2_external_program.py` and its focused authorities in `tests/test_bs2_external_program.py`.
- The restored scenario again recognizes only the exact `Initialize flash system. Enter Y or N.` speech at halted PC `1BDA` and sends the authoritative uppercase `Y` chord `0x7D`; lowercase `y` remains distinct for the later YMODEM menu.
- Continued the same slice at the proven evidence gap: after acknowledged uppercase `Y`, the verifier now waits for the next stable firmware key state and reports only the speech produced since the response, plus PC, initializer watch, and MMU state. It no longer discards that evidence inside another blind editor-loop timeout.
- Current state: exactly the verifier and its focused test are uncommitted source changes. The required notes file remains unstaged. User-owned `CLAUDE.md` and synth changes remain untouched.
- Blocker: none. The restored slice has not yet run lint, focused tests, or the pristine real-ROM gate.
- Next action: run scoped Ruff and the focused harness/protocol suite; if they pass, run the untouched pristine-state verifier once and use the exact post-response speech to choose the next change within this same slice.

### Flash confirmation source contract recovered

- The restored verifier passed scoped Ruff and 9 focused tests, then the pristine real-ROM run captured the exact full initialization prompt repeated after acknowledged uppercase `Y`.
- Existing durable live evidence at this file's earlier flash checkpoint was decisive: prompt-paced lowercase `y` produced `Are you sure? Enter y or n.`, and a later run accepted both lowercase `y` confirmations through complete key handshakes.
- Firmware source confirms the exact control flow. `BSINIT.C::ask_flash()` calls `ask_sure(flinit)` and invokes `flashInit(...)` only if that helper returns true.
- `BS.ASM::ASKSURE` speaks the supplied prompt, calls `GETKEY`, compares directly to `BRLYES`, then speaks `_SURE` plus the yes/no prompt and performs a second `GETKEY` comparison to `BRLYES`.
- The linked English `LIB/BSEQUATS.LIB` definition is `BRLYES EQU 3DH`. This is the lowercase terminal `y` raw chord. Uppercase terminal `Y` is `0x7D` and can never pass either comparison.
- Corrected the active verifier constant from `0x7D` back to source-defined `0x3D`. The focused test still needs the corresponding expectation correction before gates run.
- Current state: the same uncommitted verifier/test slice remains active; no second source slice was started. The investigation record is part of this slice and records the post-uppercase repeated prompt.
- Blocker: none.
- Next action: correct the focused key-mapping authority to require lowercase `y`, rerun scoped gates, then run the pristine verifier once to capture the exact confirmation phonemes. Add the second lowercase confirmation only after matching that exact prompt.

### Two-confirmation workflow crosses the prompt

- Corrected the focused authority to require source-defined lowercase `y`; scoped Ruff passes and the focused harness/protocol suite initially reported 9 passed.
- The pristine real-ROM run then accepted the first lowercase `y` and produced exact confirmation phonemes `AH ER YI U U SCH O ER EH N T ER W AH E OU ER EH N`, matching `Are you sure? Enter Y or N.`
- Added an exact confirmation-prompt suffix gate and a second source-defined lowercase `y`, with property and negative authorities. Scoped Ruff passes and the focused suite now reports 11 passed.
- The next pristine run no longer returned to the initialization prompt. It continued beyond the earlier response timing and consumed the full following 100,000,000-cycle bound inside the second `wait_for_key()`.
- This is a measured real-ROM improvement: both firmware `GETKEY`/`BRLYES` comparisons are crossed. The current blocker is downstream inside `flashInit`, not prompt recognition or keyboard delivery.
- Existing `BS2Harness.wait_for_key()` loses causal state on timeout; it reports only the cycle limit, unlike `run_until()` and serial waits. The next decision requires the terminal PC, halted state, pending speech IRQ, and phoneme count from that exact failure.
- Current state: the same active source slice remains uncommitted in the verifier, its tests, and the investigation record. No unrelated source file has been changed.
- Blocker: none.
- Next action: improve the existing `wait_for_key()` timeout message in place with its already available causal state, add a focused authority, rerun the gates, then repeat the pristine two-confirmation run once to identify the flash-initialization PC/state.

### Flash initialization reaches the editor command loop

- Improved `BS2Harness.wait_for_key()` timeout in place to report cycle, PC, halted state, pending speech IRQ, and phoneme count. Extended its existing bounded-loop authority; scoped Ruff passes and the focused suite reports 11 passed.
- The pristine two-confirmation run then ended its stable-key bound at cycle `109787000`, PC `D657`, `halted=0`, no pending speech IRQ, and 311 completed phonemes.
- PC `D657` plus the already-established `_bsp_command_loop_ready` flag is the exact editor authority used successfully before this first-boot work. Flash initialization had completed; only the verifier's sampled-HALT requirement prevented success.
- Corrected only the post-second-confirmation transition to use the existing exact editor predicate. The initial flash prompt and confirmation remain stable firmware key waits.
- Scoped Ruff passes and the focused harness/protocol suite remains 11 passed after the correction.
- Current state: the same active source slice remains uncommitted across `tools/bs2_harness.py`, `tools/verify_bs2_external_program.py`, their two focused tests, and the investigation record. This is one coherent first-boot/verifier improvement.
- Blocker: none.
- Next action: run the untouched pristine-state external-program verifier. It must now cross flash initialization and continue the exact O/f/T/r/y/YMODEM/X scenario; use its first downstream failure as the next decision without stopping or reverting the useful slice.

### First-boot verifier slice committed

- The untouched pristine-state verifier crossed both lowercase `y` confirmations, reached the exact editor predicate, executed O/f/T, completed ASCI1 ENQ/NAK through the receive ISR, and then reproduced the original ASCI0 TE-disabled failure.
- Exact downstream state: cycle `26778366`, PC `23AE`, ASCI0 `CNTLA=01`, `TDR=05`, no TX frame, `loaded_COMBYT=00`, `command_COMBYT=00`, zero PC `07F2` initializer hits, and no retained write to physical `0x414B0`.
- This proves the preserved lifecycle image was not the cause of the serial failure. A pristine real initialization path reaches the same `COMBYT`/ASCI0 defect.
- Final gates for the kept slice: scoped Ruff passes; focused harness/protocol suite 11 passed; product BNS suite 16 passed; CPU suite 8 passed; staged whitespace clean; complete staged patch inspected.
- Commit `58dc429` (`Handle BS2 flash initialization prompts`) contains exactly the two tools, their two focused tests, and the investigation record. This notes file and user-owned changes remained unstaged.
- Current state: the first-boot slice is committed and the Git boundary is clean. The active plan remains on the lifecycle/serial root cause; BS2ENG external import has not yet succeeded.
- Blocker: none.
- Next action: recover the actual linked BS2ENG startup path from reset entry `0000 -> 032F` to the serial initialization used before `DTRON`. Determine whether PC `07F2` belongs to another compile-time/model path or whether an emulated reset condition skips required initialization; do not patch `COMBYT` directly.

### Power-on hard-reset path reaches the persistent serial initializer

- Source and linked-ROM inspection resolved the startup discrepancy. Ordinary power-up writes ASCI0 `CNTLA0=0x64` directly, while `WARM0` in the cold-reset path additionally writes the persistent `COMBYT=0x64` mirror at linked PC `07F2`.
- The firmware help and startup source identify the required cold-reset gesture exactly: hold I-chord, raw `0x4A`, while power is applied. The emulator's ordinary stdio keyboard path cannot currently express this because it defers queued keyboard input until the editor loop.
- The external-program verifier now holds raw `0x4A` from reset until its existing PC `07F2` watch fires, then releases the chord. It does not patch RAM or the state file.
- The pristine real-ROM run hit PC `07F2`, proving that the firmware accepted the power-on chord and executed the real serial/configuration initializer. It then halted at PC `1BDA` after speaking phonemes for `Initialize file system. Enter Y or N.` (`... F AH E L S I S T EH M ...`).
- This is distinct from the already-supported flash-only prompt (`... F L AE SCH S I S T EH M ...`). Firmware help confirms the cold-reset dialogue order: file system, flash system, folder system, then file-area data.
- Current state: one uncommitted verifier change holds and releases the authoritative power-on I-chord. Ruff passes. The exact real-ROM gate now fails only because the verifier recognizes the later flash prompt but not the newly exposed earlier file-system prompt.
- Blocker: none. The next required behavior is the source-backed cold-reset dialogue, not a serial workaround.
- Next action: encode the exact file-system prompt and its required response/confirmation sequence, rerun the same pristine BS2ENG verifier, and continue through each subsequent cold-reset prompt until the editor and external-program path complete.

### Cold-reset dialogue reaches the final file-area prompt

- Added exact, independently tested phoneme suffixes for `Initialize file system. Enter Y or N.` and `Initialize folder system. Enter Y or N.` The file-system prompt uses `ASKSURE` and therefore two lowercase `y` confirmations; the folder prompt uses C `yorn()` and accepts one lowercase `y`.
- The same pristine real-ROM run now crosses file initialization, speaks and crosses `Are you sure?`, initializes flash after its own two-confirmation dialogue, speaks `Flash initialized`, then reaches and crosses folder initialization.
- After the folder response, the firmware halts at PC `1BDA` with exact speech tail `... D I L E T AW LF D A E T UH1 I N F AH E L EH R E UH1 EH N T ER W AH E OU ER EH N`.
- Source identifies this as `BSMESENG.C::wipeout = "delete all data in file area."`. `BS.ASM` checks `ONFLG == 'i'`, loads `_WIPEOUT`, and calls `ASKSURE`, so this final destructive prompt requires the same two lowercase `y` confirmations.
- Focused prompt/YMODEM authorities are at 15 passing tests; scoped Ruff passes after organizing the test imports.
- Current state: the verifier and its focused test are the only intended uncommitted source changes. The verifier has crossed every cold-reset dialogue except the final `WIPEOUT` confirmation. The notes file remains unstaged.
- Blocker: none.
- Next action: add the exact wipeout prompt to the `ASKSURE` classifier, run its two-confirmation path, then rerun the complete pristine BS2ENG import/entry verifier.

### Keyboard edge acknowledgment is not chord acceptance

- Added and property-tested the exact `_WIPEOUT` suffix for `Delete all data in file area. Enter Y or N.`; focused authorities now report 17 passing tests and scoped Ruff passes.
- The first wipeout `y` is reproducibly lost: the keyboard latch clears, but no confirmation phonemes are produced even after the full bound. This is not a prompt mismatch.
- Firmware source explains the phase boundary. The BS2 keyboard ISR clears `KEYCLR` near entry, then debounces the held chord. Only the later key-up path calls `_put_key` and makes the chord visible to `GETKEY`. `BS2Harness.chord()` and product stdio currently release as soon as `latched` clears, incorrectly treating ISR entry as chord acceptance.
- The wipeout phase exposes this because `ONFLG='i'`. If release occurs inside the initial ISR, the ISR reaches `USB200`, clears `ONFLG`, and deliberately does not enqueue that chord. Earlier initialization prompts had `ONFLG=0`, so the same premature release happened to work.
- Masked linked-ROM search located the exact BS2 ISR operands: PC `0B1F` reads `ONFLG` at logical `D469`; PC `0B79` (`USB200`) writes `_IIB` at logical `F27D`, clears `ONFLG`, and exits. These are firmware consumption markers; the early hardware latch is not.
- Current state: intended uncommitted changes remain confined to the verifier and its focused test. The exact gate crosses file, flash, and folder initialization and reaches wipeout, but cannot yet deliver the first wipeout chord reliably.
- Blocker: none; the acceptance boundary is now identified.
- Next action: map linked logical `_IIB`/queue writes to physical RAM under the active MMU and change the shared chord driver to hold the key through the completed key-down ISR before releasing. Verify the fix against both wipeout and ordinary editor commands, then rerun the full import/entry gate.

### Firmware-level chord handshake completes YMODEM import

- Mapped logical `_IIB=F27D` to physical `4327D` under the linked BS2 MMU (`CBR=34`). `BS2Harness.chord()` now holds key-down until firmware writes the chord to `_IIB`, then releases and waits until the key-up ISR clears `_IIB` while buffering the chord.
- Scoped Ruff and the 17 focused harness/protocol authorities pass with this semantic handshake.
- The pristine real-ROM verifier now reliably crosses file, flash, folder, and wipeout initialization, including both wipeout confirmations that the old latch-only handshake dropped.
- It then enters the real file manager through O-chord then lowercase `f`, completes ASCI1 and ASCI0 ENQ/NAK receive paths, completes the YMODEM transfer, and returns to exact editor PC `D657` with no pending speech IRQ.
- The next failure was only `wait_for_key()` requiring HALT after transfer. As during first-boot flash completion, the real editor loop at `D657` is non-halting. Replaced that post-transfer wait with the existing exact `_bsp_command_loop_ready && PC==D657` predicate.
- Current state: intended uncommitted source changes are `tools/bs2_harness.py`, `tools/verify_bs2_external_program.py`, and `tests/test_bs2_external_program.py`; the investigation record still needs this evidence. Notes remain unstaged.
- Blocker: none.
- Next action: rerun focused gates and the same pristine end-to-end verifier. Its remaining required authority is the real external launcher MMU state and entry PC `1000` or `100E` after X-chord.

### Post-import file-manager pointer navigation

- Bare X-chord after YMODEM was correctly delivered but ran in editor context, where it means `control character follows`; source confirmed transfer had returned from the file manager.
- Re-entering O-chord then lowercase `f` before X reached the file manager, but X spoke `file is not a program`, proving `fnext` still pointed at a non-executable.
- `FILEP.C` provides the exact navigation command: `C5` scans forward until `file.type == TY_EXEC`, then speaks the selected program. The first attempt sent bare dot 5 (`0x10`) and firmware spoke `invalid file command`.
- Source defines `C5=0x150`: BNS raw input must include the chord/space bit, so the physical dot-5 chord is `0x50`. Corrected the verifier and added a focused authority distinguishing `0x50` from bare `0x10`.
- The YMODEM-created `.bns` is source-defined `TY_EXEC`; the next successful C5 scan should therefore select `BSNAME.BNS` before X.
- The external-entry loop now uses the native PC `1000` watch in 1,000-cycle chunks. This preserved exact instruction detection and removed the prior 100-million Python-call bottleneck.
- Current state: intended uncommitted changes are the shared harness, verifier, focused verifier test, and investigation record. The exact gate has not yet run with corrected `C5=0x50`.
- Blocker: none.
- Next action: rerun scoped lint/focused tests and the same pristine BS2ENG verifier. Require dot-5 to select the executable and X to hit PC `1000` under `CBAR=11`.

### BSNAME executes; entry authority now captures MMU at the hit

- Corrected file-manager C5 to raw dot-5 chord `0x50`. The exact run no longer spoke `invalid file command` or `file is not a program`.
- The native PC `1000` watch hit exactly once. Afterward, retained speech came from BSNAME itself, including its input instructions, proving the imported external program executed and returned to firmware.
- The verifier still reported failure because it sampled current `CBAR=C6` after BSNAME had already returned. A short-lived external program can enter under `CBAR=11` and restore firmware MMU state within one 1,000-cycle chunk.
- Extended the existing native PC watch to capture `CBAR` at the exact watched instruction and exposed it as `Z180.pc_watch_cbar`. The verifier now requires `pc_watch_count>0` and captured `pc_watch_cbar==0x11`, while retaining the exact hit cycle.
- Added CPU authority that a new watch resets count/cycle/CBAR and that a hit captures the then-current CBAR. The CFFI extension still needs rebuilding before this authority can run.
- Current state: intended uncommitted changes now include `tools/build_ffi.py`, `qns/cpu.py`, `tests/test_cpu.py`, the shared harness/verifier tests, verifier, and investigation record. Notes remain unstaged.
- Blocker: none.
- Next action: rebuild the CFFI extension with `uv run tools/build_ffi.py`, run CPU and focused gates, then run the pristine verifier once more. It must report `entry: ... pc=1000 cbar=11` from the at-hit capture.

### BSNAME entry map corrected from the firmware formula

- The rebuilt exact verifier captured one real PC `1000` hit with `CBAR=81`, then retained BSNAME's own spoken field instructions. It rejected that hit only because the verifier incorrectly required `CBAR=11`.
- `BS.ASM::_execute_program` proves `CBAR=11` is the temporary validation map and the final map only for a program large enough to overflow the 16-bit `length + 0x1fff` calculation. Smaller programs derive final CBAR as `((length + 0x1fff) high nibble) | 1` before jumping to logical `1000`.
- The supplied `bsname.bns` header stores total program length `0x6205` at offsets 8 through 9. `0x6205 + 0x1fff = 0x8204`, so its exact source-defined entry CBAR is `0x81`.
- The verifier now derives the required entry CBAR from the transferred BNS header and still requires the native PC `1000` watch to capture that exact value at the instruction hit. It does not accept an arbitrary PC hit or a post-return MMU sample.
- Added a Hypothesis authority over every 16-bit header length, a supplied-BSNAME `0x81` example, and invalid-header rejection cases.
- Current state: the lifecycle, firmware keyboard handshake, cold-reset dialogue, YMODEM import, post-import file selection, and native entry-watch changes remain one uncommitted source slice. User-owned tracked changes and unrelated untracked artifacts remain untouched. This notes file remains unstaged as required.
- Blocker: none. Next action: run scoped lint and focused tests, then rerun the same pristine real-ROM verifier. Keep and commit the slice only if it reports PC `1000` with the header-derived `CBAR=81`.

### Exact BS2ENG import and BSNAME execution gate passes

- Scoped Ruff passed and the CPU, shared-harness, and external-verifier authorities passed: 31 tests.
- The same pristine-state real-ROM verifier exited `0`. It imported `bsname.bns` as 25,108 bytes through firmware YMODEM and reported `entry: cycle=344424483 pc=1000 cbar=81` from the native instruction watch.
- Both disk-probe rejections crossed the actual ASCI receive/interrupt path. The final retained phonemes include BSNAME identifying itself and speaking its own command/input instructions, independently confirming execution beyond the entry watch.
- The lifecycle/import/execution slice is accepted. It has not yet been committed; user-owned tracked changes and unrelated untracked artifacts remain untouched, and this notes file remains unstaged.
- Blocker: none. Next action: run the full repository gate, inspect and stage only the accepted slice, commit it, then begin the separate product stdio keyboard-lifecycle slice.

### Lifecycle/import/entry slice committed

- Full repository pytest result was 103 passed and 1 failed. The sole failure is the separate user-owned synth change in `tests/test_synth.py::test_time_stretch_duration_modes`; this accepted BS2 slice's 31 focused authorities and exact real-ROM gate pass.
- Global `git diff --check` reported trailing whitespace only in the separate user-owned `CLAUDE.md` and synth diffs. The seven intended BS2 paths passed scoped diff checking.
- Committed only the accepted lifecycle/import/entry slice as `81bb8c5` (`Complete BS2 external program lifecycle`). This notes file, user-owned tracked changes, ignored CFFI build products, and unrelated untracked artifacts were not staged.
- Current state: BS2 lifecycle root cause, firmware-level harness handshake, full cold initialization, real YMODEM import, and exact BSNAME execution are closed in Git. Product stdio keyboard delivery still uses the older readiness/latch behavior and remains the next unchecked whole-system boundary.
- Blocker: none. Next action: inspect the committed product stdio input scheduler and its tests against the now-proven power-on I-chord and firmware key-down/key-up acceptance contract, then make one separate product slice.

### Product stdio lifecycle/keyboard slice in progress

- The product defect is confirmed in `BNS.run`: queued keyboard stdin was withheld until the editor command-loop marker, so it could not answer genuine initialization prompts, and each chord was released as soon as the hardware latch cleared, before firmware `_IIB` acceptance.
- The source-backed correction adds `--power-on-input`. It synchronously consumes the first keyboard character from stdin before cycle one, requires the documented uppercase I-chord `0x4A`, and holds it until the real physical `COMBYT` initialization write proves the cold-reset path accepted it. Runtime keyboard data still comes only from stdin.
- Ordinary queued stdin is now eligible only at a stable halted firmware key wait with no pending speech IRQ. Each chord remains down until physical `_IIB=0x4327D` equals the chord, then remains in key-up phase until the latch clears and `_IIB` returns to zero.
- Added focused fake-CPU authorities for I-chord being down before the first CPU cycle, release only after the `COMBYT` write, strict uppercase-I validation, rejection on serial stdin, stable-wait gating, and both `_IIB` phases.
- Current state: `qns/bns.py` and `tests/test_bns.py` form one uncommitted product slice. The prior lifecycle/import slice is committed. User-owned tracked changes and unrelated untracked artifacts remain untouched; this notes file remains unstaged.
- Blocker: none known. Next action: run scoped Ruff and focused tests. If they pass, run the exact pristine BS2ENG CLI with `--power-on-input` and keyboard stdin to prove the shipped product path reaches and crosses the initialization dialogue without the verifier's direct keyboard calls.

### Product stdin lifecycle gate passes

- Scoped Ruff passed and the product/hardware/harness/verifier focus reported 58 passing tests.
- A disposable copy of the pristine lifecycle state was launched through the shipped `qns.bns` CLI with `--model bs2 --input keyboard --power-on-input`; its entire keyboard stream was `Iyyyyyyy` from stdin.
- The process exited `0` after 200,000,000 cycles at final PC `D657`, MMU `CBR=34 BBR=00 CBAR=C6`, after 962 phonemes. This proves the product path held I before cycle one, crossed every cold-reset destructive prompt through paced stdin chords, and reached the editor command loop without direct verifier keyboard calls.
- The live run exposed a separate output-owner defect: default console mode emitted thousands of unconditional `[Serial0]`, memory-error, and `[MEM] Write to VOLUME` debug lines. That makes stdio noisy even when trace flags are not selected, but it does not invalidate the accepted keyboard-input result.
- Current state: the accepted product stdin lifecycle slice remains uncommitted in `qns/bns.py` and `tests/test_bns.py`. The disposable state is outside the repository. User-owned tracked changes and unrelated untracked artifacts remain untouched; this notes file remains unstaged.
- Blocker: none. Next action: run the full suite, inspect/stage/commit only the accepted input slice, then begin a separate deletion of unconditional console diagnostics so default stdio has an intentional output contract.

### Product stdin lifecycle slice committed

- The full suite after the product change reported 109 passed and the same one unrelated user-owned synth failure in `test_time_stretch_duration_modes`.
- Scoped diff checking passed. Only `qns/bns.py` and `tests/test_bns.py` were staged and committed as `9fa1c8f` (`Drive BS2 initialization from standard input`).
- Current state: the shipped CLI can now perform the documented power-on I reset and all initialization confirmations from keyboard stdin, with firmware-level key acceptance. The separate unconditional console-output pollution remains unmodified and is the next product boundary.
- User-owned tracked changes and unrelated untracked artifacts remain untouched; this notes file remains unstaged.
- Blocker: none. Next action: locate every unconditional default console emission observed in the live run, distinguish intentional user-facing status from debug/device bytes, and delete or correctly gate only the debug emissions in one separate slice.

### Default stdio output cleanup in progress

- Exact owners were `BNS._serial_transmit`, which printed every unselected ASCI byte as `[SerialN]`, and `Memory.write`, which unconditionally printed every physical `0x4215C` write from an old amplitude workaround.
- The CLI already has the explicit `--output serial0|serial1` raw-byte contract. Therefore unsolicited serial console rendering is a duplicate debug surface, not product output. It was deleted; selected raw output remains unchanged and channel-filtered.
- The old VOLUME print and its unused `was_new` local were deleted. Shadow-RAM write tracking remains unchanged.
- Added authorities that unselected ASCI transmissions and the formerly special VOLUME write emit nothing. Scoped Ruff passes and the BNS/memory tests report 30 passed.
- Current state: `qns/bns.py`, `qns/memory.py`, `tests/test_bns.py`, and `tests/test_memory.py` form one uncommitted deletion-first output slice. User-owned tracked changes and unrelated untracked artifacts remain untouched; this notes file remains unstaged.
- Blocker: none. Next action: rerun the product CLI on the already-initialized disposable state without trace flags and verify the console is bounded while final PC remains a valid firmware wait, then run the full suite and commit the kept cleanup.

### Native CSIO output owner corrected

- The first quiet-console rerun removed all Python serial/memory pollution and still reached PC `D657`, but exposed unsolicited native `Z180 ... TRDR rd` lines.
- The exact owner is `C:\Users\Q\src\z180emu\z180\z180.c`: the TRDR read case alone used unconditional `logerror`, while adjacent register reads and TRDR writes use the compile-time `LOG` gate.
- Changed only that call from `logerror` to `LOG` in the clean native owner repository and added a `capfd` assertion to the existing QNS CSIO exchange authority. Rebuilt the ignored CFFI products with the tracked recipe.
- Scoped Ruff passes and the CPU/BNS/memory focus reports 38 passed with no native TRDR output.
- Current state: the QNS deletion-first output slice now includes `qns/bns.py`, `qns/memory.py`, `tests/test_bns.py`, `tests/test_memory.py`, and `tests/test_cpu.py`. The native owner has one uncommitted one-line change. User-owned changes and unrelated artifacts remain untouched; this notes file remains unstaged.
- Blocker: none. Next action: rerun the same initialized-state CLI gate to require bounded output with no trailing native lines, then run full suites and commit each repository's owned part before continuing.

### Quiet output gate passes; native owner committed

- The repeated initialized-state CLI run emitted only intentional load/run/state/stat lines, exited `0`, and again ended at PC `D657`; no Python device diagnostics or native TRDR lines remained.
- Full QNS pytest result is 111 passed and the same one unrelated user-owned synth failure in `test_time_stretch_duration_modes`.
- The native one-line owner change passed diff checking and the tracked QNS build recipe. It is committed in `C:\Users\Q\src\z180emu` as `3ed003a` (`Silence routine CSIO reads`).
- Current state: the QNS half of the accepted output slice remains uncommitted in five intended paths. The native repository is clean after its owner commit. User-owned changes and unrelated artifacts remain untouched; this notes file remains unstaged.
- Blocker: none. Next action: stage, inspect, and commit only the five QNS output-cleanup paths, then resume the remaining whole-system audit from the active plan.

### Output cleanup committed; supplied-profile audit resumed

- The five-path QNS output cleanup is committed as `86947a9` (`Silence unsolicited device diagnostics`). Together with native owner commit `3ed003a`, default console operation is bounded and explicit raw serial output still uses `--output serial0|serial1`.
- The supplied corpus has five firmware images: `BSPENG` (`BSPLUS`), `BS2ENG` (`BSNEW`), `BSLENG` (`B_LITE`), `BL2ENG` (`BSNEW+B_LITE`), and `BL4ENG` (`B_LITE_40`). The TNS directory has `tnseng.tns` and common assets, but no TNS firmware `.bns` image.
- Current product profiles cover only `bsp` and `bs2`; BSL, BL2, and BL4 have no explicit hardware-profile authority. Passing BS2 gates do not establish those variants.
- `BE_ENG.PRJ` is the authoritative build classification. `BSP.INC` defaults only the plain build to BSPLUS and leaves the B_LITE branches distinct; they cannot be relabeled as BSP/BS2 without live and source evidence.
- Current state: all accepted lifecycle, external-program, stdin, and output slices are committed. Only the preserved user-owned synth changes and unrelated artifacts remain dirty; this notes file remains unstaged.
- Blocker: none. Next action: inspect `LIB/BSPORTS.LIB` and the B_LITE conditionals that determine BSL ports, then run BSLENG under the closest current profile to measure the first actual divergence before adding any model surface.

### BSL display boundary re-established

- A fresh current run of supplied `bsleng.bns` under the closest `bsp` wiring reproduces the recorded divergence exactly: after 20,000,000 cycles it has no non-pause speech and remains at PC `0x2AF5`, MMU `34/00/C6`.
- `LIB/BSPORTS.LIB` proves plain `B_LITE` uses BSP's direct RTC `0x60`, keyboard `0x40`, key-clear `0x20`, SSI-263 `0xC0`, speech power `0x80`, and RS-232 power `0xA0`. Its distinct missing hardware is the attached Braille display over Z180 CSI/O, not a wholesale port remap.
- `BSSERIAL.ASM::_BRL_STATUS` identifies the stall: transmit command `0x81`, wait for `CNTR.TE` to clear, start receive, wait for `CNTR.RE` to clear, read TRDR, and merge the returned low status nibble.
- The source-defined BSL display protocol is exact: `0x81` requests status, `0x82` clears the display, `0x83` makes the next byte a display cell, `0x85` requests battery, and `0x86` requests current. The existing native CSI/O callback boundary is the correct owner path.
- Current state: no BSL source changes exist. Accepted prior work remains committed; user-owned changes and unrelated artifacts remain untouched; this notes file remains unstaged.
- Blocker: none. Next action: inspect existing display/peripheral classes and BSL source defaults for status/battery/current values, then add the smallest `bsl` profile and callback-backed 18-cell display model with protocol tests. Keep it only if the real BSL ROM leaves PC `2AF5` and reaches its startup/idle path.

### BSL profile slice in progress

- Replaced the unused direct-port `BrailleDisplay` placeholder with the exact BSL CSI/O command owner: status `0x81`, clear `0x82`, next-cell `0x83`, battery `0x85`, and current `0x86`.
- Source-derived idle values are status `0x0A` (advance bars up), battery `238` (the firmware's 7.0 V/100% threshold), and current `0xFF` (not charging). The model captures 18 display cells and returns each response once.
- Added explicit `bsl` model selection and wired only that profile's display to the existing native CSI/O callbacks. BSP/BS2 port wiring is otherwise unchanged.
- Added protocol, Hypothesis cell-stream, and BNS callback-wiring authorities. Scoped Ruff passes; the 47-test focus has 46 passes and one regression: BSP now has a `display=None` attribute, contradicting its established speech-only no-display contract.
- Current state: `qns/io.py`, `qns/bns.py`, `tests/test_io.py`, and `tests/test_bns.py` form one uncommitted BSL slice. User-owned changes and unrelated artifacts remain untouched; this notes file remains unstaged.
- Blocker: none. Next action: construct the display attribute only for `model="bsl"` and select the CSI/O device by model, rerun focused gates, then run the real BSL ROM and require it to leave PC `2AF5` and reach a valid startup/idle state.

### BSL display/profile boot gate passes

- Corrected construction so only `model="bsl"` owns a display attribute; the established BSP no-display surface remains literal.
- Scoped Ruff passes and all 47 focused I/O, BNS, and CPU authorities pass.
- The same supplied `bsleng.bns` run under `--model bsl` exits `0`, leaves the former CSI/O stall at PC `2AF5`, and reaches the BSL command loop at PC `D656`, MMU `34/00/C6`, after 20,000,000 cycles.
- The retained seven phonemes are pauses, so this evidence proves BSL display handshaking and boot/idle progress, not spoken startup. The display buffer is the primary unchecked output surface for this profile.
- Current state: the four-path BSL display/profile slice is accepted but uncommitted. BSL keyboard stdio remains unproven because the product acceptance handshake still uses BS2's linked `_IIB` physical address. User-owned changes and unrelated artifacts remain untouched; this notes file remains unstaged.
- Blocker: none. Next action: run the full suite, inspect/stage/commit only the accepted BSL display/profile slice, then begin a separate diagnostic slice to derive BSL's linked firmware keyboard-acceptance address and verify one stdin chord end to end.

### BSL display committed; per-profile keyboard owner derived

- Full suite for the display/profile slice reported 114 passed and the same unrelated user-owned synth failure. The accepted four paths are committed as `ab683ea` (`Add Braille Lite display profile`).
- A masked search around the source-defined `USB200: LD (_IIB),A` instruction found each English ROM's exact linked operand without runtime guessing: BSP logical `F27C`, BS2 `F27D`, and BSL `F3E5`.
- Under the confirmed command-loop `CBR=34` mapping, the physical acceptance bytes are BSP `0x4327C`, BS2 `0x4327D`, and BSL `0x433E5`.
- This proves the product's current global `_BS2_IIB_PHYSICAL=0x4327D` is wrong for both BSP and BSL stdin, even though BS2 passes. The prior BSL profile commit did not claim keyboard completion.
- Current state: no new source changes after the BSL commit. User-owned changes and unrelated artifacts remain untouched; this notes file remains unstaged.
- Blocker: none. Next action: replace the global BS2 keyboard-acceptance address with an explicit model-owned map, restrict the BS2-specific power-on reset mode to BS2, add linked-address/profile authorities, and live-verify one BSL stdin chord through both firmware phases.

### Per-profile stdin handshake in progress

- Replaced the global BS2 `_IIB` address with the linked BSP/BS2/BSL physical map and restricted `--power-on-input` to BS2 because only that profile's COMBYT release boundary is proven.
- The first real BSL stdin `a` run still emitted no keyboard IRQ. It returned to PC `D656`; this disproved the assumption that BSL remains in a stable halted key wait for two 1,000-cycle host quanta.
- The source-defined STARTA loop and masked linked patterns provide the exact alternate readiness signal: each command loop writes zero to `bg_timer` before `bg_task` and HALT. BSP/BSL link it at physical `0x41653`; BS2 links it at `0x41654`.
- The scheduler now paces queued command input by new command-loop write epochs and continues using stable halted/no-speech waits for initialization prompts. Each submitted chord still must cross its model-owned `_IIB` down/up phases before the next chord.
- Added exact linked-map authorities and a non-halted timer-woken BSL scheduler authority. Scoped Ruff passes and the focused suite reports 53 passed.
- Current state: `qns/bns.py` and `tests/test_bns.py` form one uncommitted per-profile stdin slice. User-owned changes and unrelated artifacts remain untouched; this notes file remains unstaged.
- Blocker: none. Next action: rerun the same real BSL `a` stdin gate with interrupt tracing. Require both key edges and return to PC `D656`; if it passes, rerun BS2 focused/end-to-end gates before committing the shared scheduler change.

- Deleted duplicated timing, predicate, chord, stable-key, speech-idle, serial queue, ASCI formatting, receive tracing, and serial wait definitions from both scenario files before recreating them in one owner.
- Added `tools/bs2_harness.py` with `BS2Harness` and `SerialCapture`. The owner loads real ROM/state files and owns bounded emulation mechanics; scenario tools retain only their domain workflows.
- Rewrote external-program helpers to accept one harness instead of repeated `bns`, output, and channel parameters. Main now reads as O/f/T, probes, r/y/E, YMODEM, X/entry.
- Rewrote the battery scenario to use the same harness; its gas-gauge command context remains scenario-specific through the harness timeout callback.
- Moved serial-capture and disabled-transmitter authorities into new `tests/test_bs2_harness.py`. Serial capture is now property-tested over arbitrary lists of cycle-stamped byte chunks. YMODEM properties remain in `tests/test_bs2_external_program.py`.
- Search gates show no duplicate helper definitions and no scenario-owned `TimestampedBytesIO`, `_pending_irq_cycle`, or keyboard-latch polling. Remaining textual hits are direct calls to the shared harness and the scenario-specific `run_until_program_entry`.
- Scoped Ruff passes all five refactor files.
- Current state: refactor is uncommitted. Runtime tests and real-ROM gates have not yet run.
- Current blocker: none; runtime equivalence is unverified.
- Next action: run the harness and external focused modules, full BNS/CPU modules, battery real-ROM command if its exact state/ROM arguments are discoverable, and the unchanged external-program real-ROM command. Fix ownership/design failures without restoring old paths.

### 2026-07-19 linked command-loop boundary correction

- Finding: treating any two zero writes to the linked `bg_timer` as a command-loop epoch was wrong. BSL clears that RAM during early initialization, so stdin `a` was asserted around cycle 657,000 before normal startup; INT2 never cleared and execution ended at PC `060F`.
- Correction under test: each model now counts an input-ready epoch only when the zero write comes from the linked `STARTA` instruction itself: BSP `0A0D`, BS2 `0A7E`, BSL `0A97`.
- Current state: scoped Ruff passes, and `uv run pytest tests/test_bns.py tests/test_io.py -q` passes with 47 tests. The earlier invocation naming nonexistent `tests/test_cli_bns.py` ran no tests and is not validation.
- Current blocker: the correction has not yet been verified against live BSL firmware stdin, so the source slice is not yet keepable or committable.
- Next action: rerun the same bounded BSL `a` stdin case and require the firmware to acknowledge both key phases without diverting startup; if it fails, restore or continue correcting this same slice rather than widening scope.

### Linked command-loop boundary passes BSL live gate

- The first rerun used the shell's unquoted `set /p =a` form and supplied `a`, carriage return, and line feed; its six interrupt pairs were three real input characters, not scheduler duplication, so it was not accepted as the one-character authority.
- The canonical no-newline producer `set /p "=a"` supplied exactly one BSL character. The firmware produced exactly two keyboard assert/clear pairs for chord down/up, returned to PC `D656`, retained MMU `34/00/C6`, and completed the bounded 30,000,000-cycle run.
- The shared BNS/BS2 focus now passes: `uv run pytest tests/test_bns.py tests/test_io.py tests/test_bs2_harness.py tests/test_bs2_external_program.py -q` reports 70 passed.
- Current state: `qns/bns.py` and `tests/test_bns.py` remain the one uncommitted stdin slice; the linked-PC correction is BSL-proven but not yet BS2-regression-proven. Notes remain unstaged.
- Current blocker: none. The intended disposable BS2 gate state path does not exist yet, so it can be safely created without overwriting prior evidence.
- Next action: copy the proven pristine BS2 state to the checked disposable path, run the exact cold stdin gate, then run the real BS2 external-program verifier before the full suite and commit decision.

### BS2 cold gate passes; verifier caller corrected

- The first piped BS2 attempt returned no captured stdout and did not update its disposable state, so it was rejected as evidence.
- A fresh pristine state copy plus a real PTY supplied exactly `Iyyyyyyy`. The product completed 200,000,000 cycles with exit `0`, saved the disposable state, and ended at PC `D657`, MMU `34/00/C6`; observed keyboard interrupts were acknowledged.
- The unchanged external-program verifier then failed immediately because it still referenced deleted `_bsp_command_loop_ready`. This was a real compatibility regression missed by the focused suite, not a ROM failure.
- Both real-ROM tool callers now use the exact retained `_command_loop_write_count > 0` STARTA epoch directly. No replacement interface/helper was introduced. A verifier unit authority exercises that boundary without the deleted attribute, and scoped Ruff passes.
- Current state: the same uncommitted stdin slice now includes `qns/bns.py`, both dependent real-ROM tools, `tests/test_bns.py`, and `tests/test_bs2_external_program.py`. The verifier caller correction is not yet runtime-validated; notes remain unstaged.
- Current blocker: none. Next action: rerun the focused tests and unchanged external-program verifier. If both pass, run the full suite, inspect/stage only this slice, and commit it before beginning any other source work.

### Verifier rerun remains active

- The corrected focused suite passes 71 tests.
- Two non-PTY verifier invocations completed through the execution wrapper without returning stdout or an inspectable exit result, so neither is counted as validation.
- The exact verifier command is now running through a PTY to preserve its own final evidence. It has produced no intermediate output and has not completed after roughly 90 seconds.
- Current state: no further source changes were made. The stdin slice remains uncommitted and cannot be accepted while the real-ROM verifier result is unknown; notes remain unstaged.
- Current blocker: the unchanged verifier is still running within its own bounded workflow. Next action: continue waiting for that process to exit or raise its explicit bounded failure, then diagnose only the exact failed verifier stage if necessary.

### Per-profile stdin slice committed

- The PTY-captured real-ROM verifier completed with exit `0`: `bsname.bns` imported at 25,108 bytes and entered at cycle `344423523`, PC `1000`, CBAR `81`, with both ASCI probes and retained BSNAME speech.
- The full suite reports 123 passed and the same unrelated user-owned synth failure in `tests/test_synth.py::test_time_stretch_duration_modes`.
- Exact staging contained only `qns/bns.py`, `tools/verify_bs2_external_program.py`, `tools/trace_bs2_battery_menu.py`, `tests/test_bns.py`, and `tests/test_bs2_external_program.py`. The slice is committed as `408b3b8` (`Support firmware-paced keyboard input across profiles`). This notes file and all user-owned/unrelated paths remain unstaged.
- The next supplied-ROM targets are BL2ENG and BL4ENG. The authoritative firmware source location is already established at `C:\Users\Q\src\bns\bsp`; the ROM directory itself does not contain the source tree.
- Current state: no new product source slice has started. Branch `master` is ahead of origin by 20 commits.
- Current blocker: none. Next action: inspect `BE_ENG.PRJ`, `BSP.INC`, `LIB/BSPORTS.LIB`, and the B_LITE/BSNEW/B_LITE_40 conditionals at the authoritative source location, then measure BL2ENG and BL4ENG under only their closest current proven profiles before deciding whether another model surface is required.

### BL2 and BL4 hardware contracts differ from BSL

- `BE_ENG.PRJ` proves BL2ENG is `BSNEW=1` plus `B_LITE=1`; BL4ENG is `B_LITE_40=1`.
- `BSSERIAL.ASM` proves BL2's `BSNEW` conditional and BL4 both use the direct bit-clocked 8255 display path, not BSL's CSI/O command/reply protocol. BL2 uses BSNEW ports (`PIOCT=0x83`, 18 cells); BL4 uses `PIOCT=0xA3`, 40 cells.
- BL4 also has a distinct keyboard and speech contract: dot keys at `0xB0`, space at `0xC0`, latch clear at `0xD0`, SSI-263 at `0x90`, and display/status wiring through the 8255 and `0xE0` latch. `GET40KEY` explicitly combines the split dot/space reads and preserves dots 7/8 separately.
- Live BL2ENG under the closest current BS2 profile completes 20,000,000 cycles at halted PC `1DB8`, MMU `34/12/C6`, with six pause phonemes and no retained speech. This does not prove direct-display output.
- Live BL4ENG under the closest current BSL profile completes 20,000,000 cycles at PC `0BAE`, MMU `34/00/C6`, with zero phonemes. That profile lacks BL4's source-defined ports and is only a divergence baseline.
- Current state: no new QNS source files are modified; the preceding stdin slice remains committed. Notes remain unstaged.
- Current blocker: none. Next action: map BL2's halted PC and direct-display writes against the linked ROM/source to identify its first causal missing boundary. Do not implement BL4 simultaneously; its distinct port/keyboard/SSI surface must be a later isolated profile slice.

### BL2 halt investigation narrows before implementation

- Firmware bytes at logical/physical `1DB8` are opcode `0x76` (`HALT`) inside a source-like wait loop: load a RAM flag, return if set, otherwise halt, call a task, and repeat. This is a deliberate wait, not an illegal opcode or CPU crash.
- A 5,000,000-cycle BL2 I/O trace filtered to `PIOCT=0x83` shows only startup writes `A2, 08, 0B, 03`. No display-cell bitstream or display strobe occurs before the wait.
- Therefore the prior hypothesis that missing direct-display capture causally produced the current `1DB8` halt is not yet supported. Display capture remains required for completeness, but it must not be implemented as the explanation for this earlier wait.
- Source `USB200` confirms the key-down ISR stores the held chord in linked `_IIB`, and the key-up path clears `_IIB` before queueing the completed chord. This supplies the exact next diagnostic boundary.
- Current state: no QNS source slice has started; notes remain unstaged.
- Current blocker: none. Next action: derive BL2's linked `_IIB` and STARTA addresses from the actual ROM, then run one exact stdin chord under a temporary diagnostic configuration or the closest proven address only if the ROM match proves it. Use the result to classify `1DB8` before implementing display hardware.

### BL2 profile source slice opened

- Masked ROM matches derive BL2's exact linked input boundaries: `USB200` stores to logical `_IIB=F3E6` (physical `0x433E6` under CBR 34); STARTA clears logical `bg_timer=D654` (physical `0x41654`) from instruction PC `0AF5` and calls HALT at `D655`.
- The active source slice adds one concrete `ParallelBrailleDisplay` owner for the source-defined 8255 BSR bit stream. It samples data C0 on rising clock C1 and latches on rising strobe C2; the 18-cell variant removes the six source-defined spacer cells from its 24-byte physical chain.
- The new `bl2` profile composes the existing BSNEW flash, PIC clock, gas gauge, power, 8255, and high-bank ownership with the 18-cell direct display and the derived keyboard/STARTA addresses. BSL's CSI/O display path is unchanged.
- Current state: only `qns/io.py` and `qns/bns.py` are modified in this uncommitted slice; tests have not been added or run, and no live BL2 result exists. Notes remain unstaged.
- Current blocker: none. Next action: add focused direct-display bit/latch authorities and BL2 wiring/map authorities, run scoped Ruff/tests, then run BL2ENG with one exact stdin chord and inspect both firmware acknowledgement and the latched display before deciding to keep or revert this slice.

### BL2 focused and keyboard gates pass; power-on display gate derived

- Scoped Ruff passes and `uv run pytest tests/test_io.py tests/test_bns.py -q` reports 53 passed, including Hypothesis authorities for arbitrary complete 18-cell and 40-cell frames.
- A canonical no-newline BL2 stdin `a` run produces exactly two INT2 assert/clear pairs and returns to deliberate halted PC `1DB8`, MMU `34/12/C6`, after 30,000,000 cycles. This classifies the wait as the normal interactive state.
- A 10,000,000-cycle post-`a` PIO trace still shows only initialization control writes and no display frame. Source explains why: raw chord `0x03` held during power-on selects Braille-display-only mode; an ordinary post-boot character cannot exercise that branch.
- Masked ROM evidence proves BL2 initializes the same linked `COMBYT=D4B0` with `LD A,64; LD (D4B0),A` as BS2. Under the linked common mapping, the existing physical release boundary `0x414B0` is valid for BL2 too.
- Current state: the four-path BL2 source/test slice is uncommitted. Power-on input remains BS2-only and the parallel display remains source/property-tested but not live-latched. Notes remain unstaged.
- Current blocker: none. Next action: make the existing power-on-input mechanism accept BL2's first source-defined chord while preserving BS2's uppercase-I requirement, add exact rejection/hold tests, then run BL2 with no-newline lowercase `b` (raw `0x03`) and require a latched display frame before accepting the slice.

### BL2 power-on and display stdio implementation in progress

- Power-on input now allows only profiles with proven linked `COMBYT` boundaries: BS2 and BL2. BS2 still rejects every first character except uppercase `I`; BL2 maps and holds its supplied first terminal character, enabling source-defined lowercase `b` / raw chord `0x03` Braille-only startup.
- Renamed the shared physical boundary from BS2-specific `_BS2_COMBYT_PHYSICAL` to `_COMBYT_PHYSICAL` and the counter accordingly; no compatibility alias was retained.
- The first focused run found that empty BS2 input no longer mentioned `uppercase I`. The implementation restored that exact BS2 message and added a distinct BL2 missing-chord authority rather than weakening the existing test. Ruff and the expanded focused suite then passed 78 tests.
- Added `--display codes|unicode`, which prints the final retained built-in display through standard output. It reads the existing concrete display buffer directly; no adapter/helper output layer was added. A subprocess authority checks the 18-cell BL2 code surface.
- Current state: the BL2 slice now spans `qns/io.py`, `qns/bns.py`, `tests/test_io.py`, and `tests/test_bns.py`; the latest display CLI addition has not yet been linted or tested. Notes remain unstaged.
- Current blocker: none. Next action: run scoped Ruff and focused tests, then run real BL2ENG with canonical no-newline lowercase `b`, `--power-on-input`, and `--display codes`; require an acknowledged power-on chord and a nonempty latched frame before full-suite/commit consideration.

### BL2 live display gate passes after causal release correction

- The first lowercase-`b` power-on run failed: BL2 never wrote physical `0x414B0`, the held key produced no release edge, firmware waited at PC `064C`, and the display stayed empty. The shared logical COMBYT symbol was not the causal BL2 release event despite the ROM match.
- Source and live ordering agree on the BL2 boundary: after the keyboard ISR acknowledges the sampled key-down latch, firmware waits for physical key-up. BL2 now releases on that latch acknowledgement; BS2 alone retains the linked COMBYT release rule.
- Scoped Ruff and all 79 focused BNS/I/O/harness/external-program tests pass after the correction.
- The repeated canonical no-newline lowercase-`b` live run produces INT2 down assert/clear and up assert/clear, returns to normal halted PC `1DB8`, MMU `34/12/C6`, and latches a nonempty 18-cell display frame: `09 95 09 8D 08 10 1D 08 D4 90 01 18 1C 11 0C 98 00 00`.
- Current state: the four-path BL2 profile/display/stdout slice is live-proven but uncommitted. Notes remain unstaged.
- Current blocker: none. Next action: run the full suite and the exact real-ROM BS2 external-program verifier because shared power/input code changed; then inspect/stage only the four BL2 slice paths and commit if both gates preserve their prior authorities.

### BL2 profile slice ready for Git closure

- Full suite result: 131 passed with only the same unrelated user-owned synth failure in `tests/test_synth.py::test_time_stretch_duration_modes`.
- The unchanged real-ROM BS2 verifier passes with exit `0`: `bsname.bns` imported at 25,108 bytes and entered at PC `1000`, CBAR `81`, after both ASCI probes; retained BSNAME speech remains present.
- `git diff --check` passes. The intended slice is exactly `qns/io.py`, `qns/bns.py`, `tests/test_io.py`, and `tests/test_bns.py`, with 245 insertions and 37 deletions. The task notes and user-owned/unrelated paths are outside the slice and remain unstaged.
- Current state: BL2 profile, 18-cell direct display, source-derived keyboard/power-on boundaries, and display stdio are accepted but not yet committed.
- Current blocker: none. Next action: stage exactly those four paths, verify the cached ledger, and commit the kept BL2 slice before starting the separate BL4 hardware profile.

### BL2 committed; BL4 contract audit in progress

- Commit `823047e` (`Add Braille Lite 2000 hardware profile`) closes the four-path BL2 slice. Notes and user-owned/unrelated work remain unstaged.
- BL4 source defines a distinct 4 MiB flash profile with high-bank/language latch at `0xF0`; QNS memory already supports eight 512 KiB pages, but no BL4 profile supplies the 4 MiB capacity or port yet.
- BL4's direct devices are exact: SSI-263 `0x90..0x94`; dot keyboard `0xB0`; space input `0xC0`; latch clear `0xD0`; 8255 `0xA0..0xA3`; power/gas output `0x80`; gas/status input and latch writes at `0xE0`.
- The existing PIC clock protocol is also used by BL4 through CSI/O, with its strobe on 8255 C4. Its 40-cell display shares that 8255 control register but uses C0 data, C1 clock, and C2 strobe.
- ROM evidence already gives BL4 `_IIB=F3F0` (physical `0x433F0`) and finds STARTA at logical `0B33`, clearing `bg_timer=D65A`. The complete STARTA bytes/instruction PC still need extraction.
- Current state: no BL4 product source slice has started; branch remains at the committed BL2 boundary. Notes remain unstaged.
- Current blocker: none. Next action: extract the complete linked STARTA sequence, identify BL4's normal halted command-loop PC, and inspect its exact port-B/status defaults. Then open one isolated BL4 profile slice covering only the proven hardware contract.

### BL4 profile slice in progress; display startup not yet proven

- Complete linked STARTA bytes are `21 5A D6 36 00 CD 58 16 CD 5B D6 18 DC`: start `0B33`, timer-write instruction `0B36`, logical timer `D65A` / physical `0x4165A`, and HALT routine `D65B`.
- The active BL4 slice adds the exact model maps, 4 MiB flash, SSI-263 at `0x90`, split dot/space keyboard at `0xB0/0xC0`, clear at `0xD0`, 8255 at `0xA0..0xA3`, high-bank latch at `0xF0`, power/gas lines, PIC clock strobe, and existing 40-cell display decoder. No other profile's ports were moved.
- Scoped Ruff passes and focused BNS/I/O/memory tests report 66 passed.
- Ordinary BL4 boot now reaches a deliberate halted wait at PC `1FC7`, MMU `34/30/C6`, with six pause phonemes. This is a substantial improvement over the pre-profile baseline at running PC `0BAE` with no phonemes.
- A lowercase-`b` power-on run acknowledges both host-generated key edges and returns to PC `1FC7`, but the display remains all zero. Unlike BL2, BL4 clears the key latch at cycle 0, so reusing latch-clear as proof of startup-chord acceptance is not causally established.
- A 10,000,000-cycle trace shows only A3 initialization writes `A2, 08, 0B, 03`; no display bitstream or strobe occurs. The empty buffer is therefore not a decoder failure.
- Current state: `qns/bns.py` and `tests/test_bns.py` are the uncommitted BL4 slice. It is not accepted while Braille-only startup remains unproven. Notes remain unstaged.
- Current blocker: none external. Next action: trace the linked BL4 `_IIB=F3F0` write and startup key-read flow to identify the exact chord-acceptance boundary, then rerun the same lowercase-`b` display gate. Do not commit or widen to another target before this resolves or the slice is reverted.

### BL4 live power-on, display, and ordinary stdin gates pass

- `_IIB` tracing showed no linked write during the early false release. A 100,000-cycle I/O trace then proved the only keyboard-port action was `D0` latch clear; firmware had not read `B0` dots or `C0` space.
- BL4's exact release boundary now counts completed `C0` reads, which occur after source-defined `B0` dot sampling. BS2 remains COMBYT-gated and BL2 remains latch-acknowledgement-gated.
- Scoped Ruff and all 66 focused BNS/I/O/memory tests pass after the correction.
- Canonical no-newline lowercase-`b` power-on now holds through the real B0/C0 sample, produces acknowledged down/up edges, returns to halted PC `1FC7`, MMU `34/30/C6`, and latches a nonempty 40-cell display frame beginning `09 95 09 8D 08 10 1D 08`.
- A separate ordinary no-newline `a` run exercises the linked `_IIB=F3F0` scheduler path: exactly two INT2 assert/clear pairs occur and firmware returns to PC `1FC7`. Its display correctly remains empty because Braille-only power-on was not selected.
- Current state: the two-path BL4 profile/test slice is live-proven but uncommitted. Notes remain unstaged.
- Current blocker: none. Next action: run the full suite, rerun the live BL2 power-on/display authority, and run the exact BS2 external-program verifier. If all pass, inspect/stage only `qns/bns.py` and `tests/test_bns.py` and commit BL4 before continuing the remaining whole-system audit.

### BL4 closure gates partially complete

- Full suite result: 135 passed with only the unchanged user-owned synth failure in `tests/test_synth.py::test_time_stretch_duration_modes`.
- The exact BL2 lowercase-`b` power-on/display regression gate still passes: both key edges clear, final PC is `1DB8`, MMU `34/12/C6`, and the same nonempty 18-cell frame is retained.
- The exact BS2 external-program verifier is active through the PTY capture path. It has emitted no intermediate output after roughly 90 seconds and has not yet supplied an exit result, so BS2 regression validation remains pending.
- Current state: no source changed during these gates. The BL4 slice remains exactly `qns/bns.py` and `tests/test_bns.py`, uncommitted; notes remain unstaged.
- Current blocker: the bounded BS2 verifier is still running. Next action: wait for its own exit/import/entry evidence, then inspect and close the BL4 Git slice only if it passes.

### BL4 profile committed; supplied-profile audit advances

- The BS2 verifier completed with exit `0`: 25,108-byte BSNAME import, entry PC `1000`, CBAR `81`, both ASCI probes, and retained BSNAME speech.
- Final scoped Ruff and 66 focused BNS/I/O/memory tests pass. Exact staging contained only `qns/bns.py` and `tests/test_bns.py`; the BL4 slice is committed as `73afc75` (`Add Braille Lite 40 hardware profile`).
- All supplied English firmware images now have explicit profiles: BSPENG=`bsp`, BS2ENG=`bs2`, BSLENG=`bsl`, BL2ENG=`bl2`, BL4ENG=`bl4`. The supplied TNS directory contains no firmware `.bns` image to execute.
- Current state: no active implementation slice. User-owned synth changes, task notes, and unrelated artifacts remain unstaged; branch is ahead of origin by 22 commits.
- Current blocker: none. Next action: audit the remaining whole-system requirements against current code and live authorities: per-profile state persistence, file/program workflows, stdio input/serial/display/speech output, and software speech/audio. Identify the first concrete missing or failing boundary before editing another source file.

### Remaining-system audit and interactive display slice

- Product speech authorities are healthy: all 12 SSI-263 capture/PCM tests pass, and a real BSP stdin `a` run returns to PC `D656` with 168 retained phonemes and IPA on stdout.
- The sole full-suite failure is not on the product path: `dsp.time_stretch` belongs to the legacy standalone synth currently replaced by preserved dirty user work, while `BNS(audio=True)` directly owns `SSI263PCMSynth`. Under issue invalidity, no dead-path DSP change was made.
- BL4 4 MiB persistence passes live creation and reload through `--state`, returning both times to PC `1FC7`; BSP state and the complete BS2 lifecycle already have separate authorities.
- Concrete remaining stdio defect: `--display` printed only after `run()` returned, so unlimited interactive sessions could never observe display changes.
- The active three-file slice adds completed-frame callbacks directly to `BrailleDisplay` and `ParallelBrailleDisplay`. BSL emits on clear or full 18-cell wrap; BL2/BL4 emit on their hardware latch strobe. The CLI prints each frame immediately with flush, and retains one final snapshot only when no frame was emitted.
- Added callback authorities to both direct-display Hypothesis properties and a complete BSL frame test. No new adapter/interface or speech code was introduced.
- Current state: `qns/io.py`, `qns/bns.py`, and `tests/test_io.py` are modified and uncommitted; no lint, tests, or live interactive display gate has run. Notes remain unstaged.
- Current blocker: none. Next action: run scoped Ruff and display/BNS tests, then run a real BL2 or BL4 Braille-only session and prove the display line appears before final execution/statistics output. If it passes, run full/BS2 regressions and close this slice before considering speech streaming.

### Interactive display closure and speech-stream audit

- Committed the verified interactive display slice as `cb4ea19` (`Stream Braille display frames to standard output`). The commit contains only `qns/bns.py`, `qns/io.py`, and `tests/test_io.py`; this notes file and the user-owned synth changes remain unstaged.
- Scoped Ruff and the 60 focused display/BNS tests passed. A real BL2 run emitted a nonempty `Display codes:` frame before the final `Executed 30,000,000 cycles` statistics line. The unchanged BS2 external-program verifier also completed with exit `0`, imported the 25,108-byte BSNAME program, entered it at PC `1000` with CBAR `81`, exercised both ASCI probes, and retained BSNAME speech.
- The full current suite reports 136 passes and one failure in `tests/test_synth.py::test_time_stretch_duration_modes`. That test targets the legacy `qns/synth/dsp.py` path; the product uses `SSI263PCMSynth`, while preserved user-owned synth edits replace the legacy standalone DSP. Under the issue-invalidity rule this unrelated dead-path failure is not being changed or used to widen the active slice.
- Current stdio finding: `--speech {codes,names,ipa,examples}` formats retained phonemes only after `BNS.run()` returns. Therefore an unlimited interactive run can provide live audio but cannot provide phoneme text through stdout. `SSI263.set_phoneme_callback(code, name)` is the existing event boundary and is invoked as each real-ROM phoneme begins; the retained capture remains available through `get_phonemes()`.
- Current blocker: none. Next action: verify Git branch/tracked state for a new isolated source slice, add explicit live speech-text semantics without changing the existing retained `--speech` behavior, test event order and formatting, and prove output appears before final execution statistics on a real ROM.

### Live speech-text stdio slice verified

- Added an explicit `--speech-stream {codes,names,ipa,examples}` CLI contract while preserving the existing post-run retained `--speech` summary. It attaches to the existing `SSI263.set_phoneme_callback` event boundary, ignores pause code `0`, and flushes one formatted `Speech <format>:` line for each real phoneme as it begins.
- Added four format authorities that drive the SSI-263 through register writes during `BNS.run()` and prove the phoneme line precedes a `Run returned` marker. All 10 SSI-263 capture tests pass; the combined speech/BNS/display focus reports 70 passes; scoped Ruff passes.
- A real supplied BSPENG stdin run (`a`, 30,000,000 cycles) streamed 48 named non-pause phonemes before the `Executed 30,000,000 cycles` line and ended at the established PC `D656`. This proves live text comes from firmware execution rather than a post-run retained-log dump.
- The full current suite reports 140 passes and the same sole invalid legacy `qns/synth/dsp.py` duration assertion. No legacy DSP or user-owned synth file was changed.
- The unchanged real-ROM BS2 verifier completed with exit `0`: it imported `bsname.bns` at 25,108 bytes, entered at cycle `344423523`, PC `1000`, CBAR `81`, completed both ASCI NAK paths, and retained BSNAME speech.
- State: the active source slice is limited to `qns/bns.py` and `tests/test_ssi263.py`; this notes file remains outside it. Current blocker: none. Next action: inspect the exact two-file diff, stage only those paths, run cached whitespace/name checks, commit the kept live-speech slice, then resume the remaining whole-system audit.

### Whole-system audit resumed after live speech commit

- Committed the live speech-text slice as `47667e5` (`Stream SSI-263 phonemes to standard output`). The source worktree returned to the pre-existing user-owned synth/CLAUDE changes plus this unstaged notes file and unrelated artifacts.
- Persistence authorities cover shadow RAM state, 2 MiB BS2/BL2 flash format, wrong-size/unknown-state rejection, a real BS2 lifecycle state, and a live BL4 4 MiB save/reload. The same model-owned `Memory` state format is used by the CLI.
- Keyboard stdin has profile-specific command-loop and interrupt-phase authorities for BSP, BS2, BSL, BL2, and BL4. Serial stdin/stdout has isolated-channel and binary CLI round-trip authority. BSL, BL2, and BL4 displays have device/frame authorities and real-ROM output; BSP/BS2 are correctly speech-only. SSI-263 capture, live text, and PCM software-audio authorities pass.
- First concrete unproven product boundary: `BNS.stdin_device` and CLI `--input` select exactly one of keyboard, serial0, or serial1 for the lifetime of a run. The ordinary CLI therefore cannot navigate the ROM file manager with keyboard chords and then provide a serial transfer in the same live session. The specialized BS2 verifier proves the combined internal path and executes BSNAME, but that is not yet an ordinary runtime stdio control surface.
- Packaging has no project script entry point and no tracked README; the user-owned `CLAUDE.md` mentions module execution and tools. Those documentation/package observations do not replace or widen the active runtime boundary.
- Current blocker: the literal stdio requirement does not itself specify how one byte stream should distinguish keyboard characters from binary serial bytes. Next action: inspect the existing verifier choreography and available stream boundaries only enough to determine whether an already-existing exact control encoding can be reused. If none exists, stop and request the missing user decision rather than inventing an escape protocol or direct-import shortcut.

### Structured stdio implementation in progress

- The user authorized the recommended newline-delimited JSON design and directed continuation to the complete working system. The active target is a shipped-process boundary that can carry keyboard and both binary ASCI channels concurrently; completing this protocol slice is not completion of the whole goal.
- Added `qns/stdio.py` with validated keyboard text/raw-chord and base64 serial input events plus atomic, immediately flushed JSONL output. Added `tests/test_stdio.py`; all 10 protocol authorities pass, including a Hypothesis round trip over arbitrary binary data on both serial channels.
- Added failing BNS authorities for simultaneous keyboard/ASCI0/ASCI1 routing, a raw uppercase-I JSONL power-on chord, and a real subprocess binary serial echo with stdout isolated from diagnostics. Before integration those authorities failed at the exact absent boundaries: JSONL was treated as raw binary stdin, power-on rejected it, and argparse lacked `--stdio`.
- Current implementation adds independent JSONL serial queues, preserves the legacy verifier's selected `_serial_input_queue`, accepts JSONL keyboard input through the existing firmware-paced down/up scheduler, checks parse failures on the emulation thread, and emits serial output through the structured writer. The CLI now has `--stdio jsonl`, redirects boot/stats/diagnostics to stderr, and automatically emits full phoneme metadata and Braille cell frames as structured events.
- The structured mode is deliberately exclusive with legacy `--input`, `--output`, `--speech`, `--speech-stream`, and `--display` selectors so no text or raw bytes can contaminate the JSONL stdout stream. Existing simple human modes remain available unchanged.
- State: the active source slice is exactly `qns/stdio.py`, `qns/bns.py`, `tests/test_stdio.py`, and `tests/test_bns.py`; notes and user-owned synth/CLAUDE changes remain outside it. Current blocker: none. Next action: run scoped Ruff and the protocol/BNS authorities, correct only failures in this defined stdio contract, then prove structured speech/display events before real-ROM and BS2 regression gates.

### Structured stdio slice passes its closure gates

- Scoped Ruff passes. The protocol/BNS focus reports 56 passes, including simultaneous keyboard/ASCI0/ASCI1 input, raw uppercase-I power-on, subprocess binary serial echo, full structured speech metadata, and complete Braille frame output. Legacy single-device stdin/stdout behavior remains covered by the same suite.
- A real supplied BL2ENG subprocess consumed `{"device":"keyboard","text":"b"}` through `--stdio jsonl --power-on-input`, emitted six structured pause phonemes and the exact known 18-cell frame `[9,149,9,141,8,16,29,8,212,144,1,24,28,17,12,152,0,0]`, and ended at the established PC `1DB8`, MMU `34/12/C6` after 30,000,000 cycles.
- The full current suite reports 154 passes and only the same invalid legacy `qns/synth/dsp.py` duration assertion. No legacy DSP or user-owned synth file was changed.
- The unchanged internal real-ROM BS2 verifier completed with exit `0`: 25,108-byte BSNAME import, entry cycle `344423580`, PC `1000`, CBAR `81`, both ASCI NAK paths, and retained BSNAME speech.
- State: the active four-file protocol slice is verified but uncommitted. Current blocker: none. Next action: inspect the exact diffs, stage only `qns/stdio.py`, `qns/bns.py`, `tests/test_stdio.py`, and `tests/test_bns.py`, commit the kept slice, then begin the distinct verifier-to-subprocess slice required to prove the full program workflow through shipped JSONL stdio.

### Structured stdio staging checkpoint

- Staged names were exactly the intended four files. The first cached whitespace gate identified CRLF residue only on newly changed import lines in `tests/test_bns.py`.
- A whole-file Ruff format produced an unacceptably broad 1,373-line mechanical diff and was not kept. Because the intended pre-format test content was already present in the index, restored the worktree copy of `tests/test_bns.py` from that exact index version, then rewrote only its import block and restaged the file. No source behavior or test authority was reverted.
- Current blocker: none. Next action: rerun the cached whitespace/name gates and scoped Ruff/tests. Commit only if the staged slice remains exact and clean; otherwise correct only the remaining staged defect.

### Shipped subprocess flow-control boundary

- Committed the structured runtime as `857c7b1` (`Add multiplexed JSONL standard I/O`). The commit contains only `qns/bns.py`, `qns/stdio.py`, `tests/test_bns.py`, and `tests/test_stdio.py`; the notes and user-owned changes remain unstaged.
- Read the current exact verifier and source-owned `upload_download` flow. The firmware sequence remains: power-on I; prompt-specific initialization responses; O-chord then lowercase f; exact `Enter file command`; T-chord; reject ASCI1 then ASCI0 disk probes; lowercase r; lowercase y; E-chord; YMODEM; return to editor; O-chord/f; dot-5 next program; X-chord execute.
- The JSONL process can carry all device data, but an external controller must not infer keyboard timing. The existing runtime scheduler already proves acceptance from the linked `_IIB` down/up phases and readiness from stable halted/no-speech or command-loop epochs. Those exact facts need structured output events so a subprocess client can pace without sleeps.
- Added failing expectations to the existing simultaneous-device and power-on tests: JSONL must emit `keyboard accepted` with the exact chord, then `keyboard ready` when the firmware can accept another command. No scheduler behavior has yet been changed.
- State: the new source slice currently changes only `tests/test_bns.py`. Current blocker: none. Next action: run the focused test to confirm the exact missing events, implement them only at the already-proven scheduler boundaries in `qns/bns.py`, then close and commit this small flow-control slice before adding the subprocess controller.

### JSONL subprocess controller in progress

- The keyboard flow-control authorities failed exactly because no structured events existed, then passed after events were emitted only at the established power-on acceptance, linked `_IIB` clear, and stable-ready boundaries. Scoped Ruff and all 56 BNS/stdio tests passed. A real BL2 run emitted accepted chord `3`, its exact display frame, and `keyboard ready` at PC `1DB8`.
- Committed that isolated two-file slice as `d16a2e5` (`Expose firmware-paced keyboard flow control`). The source worktree was clean apart from preserved user-owned changes and notes before starting the controller slice.
- Added `tools/stdio_process.py` as a process-boundary driver only: it launches `qns.bns --stdio jsonl`, sends keyboard/raw-chord and base64 serial events, parses flushed output on a reader thread, drains diagnostics independently, retains speech/serial history, enforces bounded causal waits, and terminates its verification child without saving the disposable state.
- Direct review before testing caught that a negative remaining deadline would stay truthy in a walrus-expression loop. Replaced it with an explicit `remaining <= 0` break, so expiry cannot spin or pass a negative queue timeout.
- State: the active slice currently adds only `tools/stdio_process.py`; no verifier scenario has been changed yet. Current blocker: none. Next action: add focused process-driver authorities using a finite real echo ROM and synthetic event process where appropriate, run Ruff/tests, then implement the exact BS2 scenario on top of this bounded driver.

### Exact subprocess program-entry authority

- Added two process-driver authorities. A finite real CLI subprocess round-trips `00 FF 5A` through ASCI0 and structured stdout with diagnostics isolated; invalid keyboard calls are rejected before input. Scoped Ruff passes and both tests pass.
- Committed the bounded driver as `1a69397` (`Add bounded JSONL process driver`) with exactly `tools/stdio_process.py` and `tests/test_stdio_process.py`.
- The external verifier must retain the established exact entry proof rather than weakening it to plausible BSNAME speech alone. The native CPU already exposes `watch_pc(address)`, `pc_watch_count`, `pc_watch_cycle`, and `pc_watch_cbar`; the current internal verifier uses those fields at PC `1000`.
- Next product slice: add a JSONL-only CLI PC-watch option that calls the existing native watch and emits one structured CPU event containing the watched PC, exact native cycle, and CBAR when the first hit occurs. This does not alter CPU timing or introduce a second watch implementation.
- State: no source edit has been made for the watch slice yet; source worktree is at the committed runtime plus preserved user-owned changes. Current blocker: none. Next action: add a failing real-CLI watch-event authority, implement the event at the existing `BNS.run()` chunk observation point, run real/focused/full gates, and commit before changing the verifier scenario.

### Structured native PC-watch slice verified

- Added a real finite subprocess authority whose ROM jumps to logical `0010`; before implementation argparse rejected `--watch-pc`, and after implementation stdout contains exactly one structured CPU `pc-watch` event with PC `16`, a positive native cycle, and CBAR `F0`.
- The CLI option is restricted to `--stdio jsonl` and to logical addresses `0000` through `FFFF`. `BNS` delegates directly to the existing native `Z180.watch_pc` and reports its existing native cycle/CBAR fields after the first hit; CPU execution is unchanged.
- The first whole `tests/test_bns.py` run exposed that JSONL unit tests replace the CPU with minimal timing doubles that have no watch fields. Guarded watch observation by the configured `_stdio_watch_pc`, so ordinary structured runs never touch watch properties. All 47 BNS tests then pass.
- Scoped Ruff passes. The full current suite reports 157 passes and only the same invalid legacy `qns/synth/dsp.py` duration assertion. No synth work was changed.
- State: the active watch slice is limited to `qns/bns.py` and `tests/test_bns.py`; it is verified and uncommitted. Current blocker: none. Next action: inspect/stage exactly those two files, run cached whitespace/name gates, commit, then extend the already-committed process driver and existing verifier scenario to consume the exact CPU event.

### Causally armed subprocess PC watch

- Committed static native-watch reporting as `90a1218` (`Report native PC watches through JSONL`) after its exact two-file staged gate.
- A process-launch watch is too early for the external-program proof because a prior firmware visit to logical `1000` could satisfy it. Added a structured CPU input event `{"device":"cpu","watch_pc":4096}` with address validation, a main-thread watch queue, and a structured `watch-armed` acknowledgment emitted before the next emulation chunk.
- The dynamic real-CLI authority uses a looping target at `0010` and proves ordered `watch-armed` then native `pc-watch` events without process restart. The watch event retains the native cycle and CBAR fields.
- Scoped Ruff passes; all 60 structured protocol and BNS tests pass. No internal CPU/native implementation was changed.
- State: the active dynamic-watch slice is exactly `qns/stdio.py`, `qns/bns.py`, `tests/test_stdio.py`, and `tests/test_bns.py`; it is verified and uncommitted. Current blocker: none. Next action: inspect/stage these four files, cached whitespace/name check, commit, then extend the process driver with watch arming and implement the exact external BS2 scenario.

### First full shipped-process BS2 run exposed transfer-start key gap

- Committed dynamic watch arming as `b0026e0` (`Arm native PC watches through JSONL`). Extended the process driver with history-aware speech/serial waits and exact watch acknowledgment/hit methods; its three real-process tests pass.
- Added `--stdio` to the existing BS2 external-program verifier. The scenario reuses the existing constants, prompt suffixes, CRC/YMODEM packet builder, expected-CBAR calculation, and exact physical chord sequence. All 24 focused driver/verifier tests pass.
- The first real shipped-process run successfully completed first boot, O-chord then lowercase f, the `Enter file command` prompt, T-chord, both ASCI disk probes and NAK responses, lowercase r, and lowercase y. It then spoke a suffix ending `D J E S T AH ER T THV UH1 T R AE N S F ER` (the transfer-start prompt) but produced no structured `keyboard ready` event within the 60-second causal bound.
- This is not a verifier-timing issue: the old internal verifier deliberately calls `wait_for_speech()` after y, not `wait_for_key()`, then injects E-chord directly. The ordinary runtime scheduler currently admits stdin only at stable halted/no-speech waits or command-loop timer epochs, so this nonstandard transfer-start wait is not yet exposed to stdio.
- State: the active verifier slice changes `tools/stdio_process.py`, `tests/test_stdio_process.py`, and `tools/verify_bs2_external_program.py`; it remains uncommitted because its live gate failed. Current blocker: none. Next action: identify the exact source/runtime condition used by `wait()` after `FTRANGO`, reproduce its terminal PC and input-buffer state with the existing internal harness, then extend the product scheduler only for that proven firmware key boundary before rerunning the same subprocess scenario.

### Source correction and exact post-transfer command boundary

- `BSSPEECH.ASM::_wait` waits for speech completion; it does not request a key. `FILETRAN.C` calls `say(FTRANGO); wait();` and enters `ymodem_receive()` directly after lowercase y. Therefore the old internal verifier's later E-chord is not a source-owned transfer-start command. Corrected the subprocess scenario to wait for serial `C` after accepted y rather than inventing a nonexistent keyboard-ready boundary.
- The second shipped-process run passed that point and completed the YMODEM transfer. It failed only after import: a generic ready event arrived before the firmware's editor command loop, so O/f was delivered against the protected HELP file and speech ended with `help is open, file is write protected` instead of `Enter file command`.
- The product already proves the real editor boundary by counting writes from each profile's linked STARTA instruction to its command-loop timer. Added a failing then passing JSONL authority for a `keyboard command-ready` event carrying that exact epoch. The event is emitted only when `_command_loop_write_count` advances; no PC guess or wait time was added.
- State: the active end-to-end slice now also changes `qns/bns.py` and `tests/test_bns.py`. Current blocker: none. Next action: make the process driver retain command epochs and provide a history-aware wait; change only the post-transfer verifier wait to require a later command epoch; rerun focused tests and the same full shipped-process scenario.

### Command-epoch premise rejected and fully removed

- The third shipped-process run completed YMODEM and produced exact speech `BSNAME.BNS transfer complete Enter file command`, then timed out only because the verifier incorrectly waited for an editor command-loop epoch.
- This proves the earlier premise was wrong: the firmware remains inside the file manager after the T/r/y transfer and is already at its next file-command prompt. Sending post-transfer O/f or waiting for editor STARTA is incorrect for this live path.
- Fully removed the uncommitted command-ready runtime event, its BNS authority, process-driver epoch retention/wait, and driver unit. `git diff --name-only` confirms `qns/bns.py` and `tests/test_bns.py` are no longer part of the active slice; no product behavior from that invalid premise remains.
- Corrected the subprocess scenario to wait for the already-observed exact post-import `Enter file command` suffix and the existing firmware-ready event, then deliver dot-5 directly. The required initial O-chord then lowercase f remains unchanged.
- State: the active slice is again limited to `tools/stdio_process.py`, `tests/test_stdio_process.py`, and `tools/verify_bs2_external_program.py`; notes and user-owned changes remain outside it. Current blocker: none. Next action: rerun scoped Ruff/focused authorities and the identical full shipped-process verifier. If it passes, run the legacy internal exact gate, full suite, inspect/stage/commit this kept slice, then resume the whole-system audit.

### External entry proven; speech marker corrected

- The fourth shipped-process run completed initialization, exact initial O/f file-manager entry, both disk probes, YMODEM import, the post-transfer file-command prompt, dot-5 selection, dynamic PC-watch arming, X-chord, and the exact native PC `1000` hit with expected CBAR. The verifier advanced past the PC/CBAR assertion, so external program entry is proven through the shipped boundary.
- The run failed only because the proposed BSNAME name-style phoneme marker was not spoken in this invocation. The actual external program spoke its distinctive prompt: `add two braille in this field; enter a chord when you are done`, observed as the exact suffix `A E1 D T U U B R A E L I N THV I S F E L D EH N T ER E K OU ER D W EH N YI U U AH ER D UH1 N`.
- Replaced only the incorrect speech marker with that observed BSNAME instruction suffix. PC/cycle/CBAR remains the primary execution authority; the marker proves observable program behavior after entry.
- Current blocker: none. Next action: rerun focused Ruff/tests, then the identical full shipped-process verifier for the fifth time. Do not change another boundary unless that exact run reports a new causal failure.

### Shipped-process BS2 program workflow passes

- The fifth shipped-process verifier completed with exit `0`. It imported supplied `bsname.bns` at 25,108 bytes; rejected ASCI1 and ASCI0 disk probes; completed YMODEM; dynamically armed the native watch; entered at exact cycle `341622282`, PC `1000`, CBAR `81`; and observed BSNAME's full spoken instruction through JSONL stdout.
- The unchanged internal verifier independently completed with exit `0`: entry cycle `344430603`, PC `1000`, CBAR `81`, both native ASCI receive traces, and retained BSNAME speech. The new external authority therefore did not replace or weaken the low-level gate.
- Scoped Ruff and all 24 process-driver/verifier authorities pass. The full current suite reports 161 passes and only the same invalid legacy `qns/synth/dsp.py` duration assertion; no synth code was changed.
- The kept implementation corrects two stale assumptions from the old internal choreography: after y, source `wait()` leads directly to YMODEM without E-chord; after transfer, the filer itself returns to `Enter file command`, so no second O/f is sent. The required initial O-chord then lowercase f remains exact and is proven live.
- State: the verified active slice is exactly `tools/stdio_process.py`, `tests/test_stdio_process.py`, and `tools/verify_bs2_external_program.py`. Current blocker: none. Next action: inspect those three diffs, stage only them, cached name/whitespace gates, commit, then resume the final requirement audit rather than stopping at this major milestone.

### Graceful JSONL shutdown and persistence gap

- Committed the shipped-process external-program authority as `4ca091d` (`Verify BS2 programs through shipped standard I/O`) with exactly the three intended driver/verifier paths. The plan remains active beyond that milestone.
- Whole-system audit found the next concrete gap: an unlimited JSONL process can modify nonvolatile RAM/flash, but `BNSStdioProcess.stop()` terminates the child and bypasses the CLI's post-run `save_state`. Structured clients therefore cannot yet end a session while preserving files/programs.
- Defined the missing contract as input `{"device":"system","action":"stop"}` and output `{"device":"system","state":"exited"}` emitted only after `BNS.run()` returns and post-run state saving finishes.
- Added protocol parse expectations and a real-process authority: a raw ROM writes `5A` behind ROM, a native PC watch proves the write loop executed, graceful stop must exit code `0`, stderr must report state save, and a fresh `Memory` load must read `5A` at physical `F000`.
- The focused run fails at the exact absent `StopInput` import; no implementation exists yet. State: active slice currently changes only `tests/test_stdio.py` and `tests/test_stdio_process.py`. Current blocker: none. Next action: add the stop input type/parser, main-thread stop flag, post-save exited event, and process-driver request method; then run the exact persistence authority before broader gates.

### Graceful JSONL persistence slice verified

- Added validated `system/stop` input, a thread-safe stop request observed on the emulation thread, normal `BNS.run()` return, and a terminal `system/exited` event emitted only after dump/state/trace/stat post-run actions. The process driver now requests this path, requires the exited event, waits for process return code `0`, and reports failures with captured diagnostics.
- The real-process persistence authority passes: firmware wrote `5A` to shadow RAM, dynamic PC watch proved execution, graceful stop saved the state, the child exited `0`, and a fresh `Memory` instance loaded `5A` from physical `F000`.
- Updated three pre-existing JSONL output authorities to include the terminal exited event after serial, CPU-watch, speech, and display events. All 73 stdio/BNS/process/memory authorities pass.
- Scoped Ruff passes. The full current suite reports 164 passes and only the same invalid legacy `qns/synth/dsp.py` duration assertion; no synth code was changed.
- State: active slice is exactly `qns/stdio.py`, `qns/bns.py`, `tools/stdio_process.py`, `tests/test_stdio.py`, `tests/test_bns.py`, and `tests/test_stdio_process.py`. Current blocker: none. Next action: inspect/stage exactly those six files, cached name/whitespace gates, commit, then audit persisted real BS2 external programs and the remaining final requirements.

### Persisted BSNAME restart verification in progress

- Committed graceful JSONL persistence as `6d00a86` (`Persist state on graceful JSONL shutdown`) with the exact six intended paths.
- Added verifier `--stdio --persist`: process one imports/executes BSNAME and calls graceful stop so the real flash state is saved; process two loads the same state and attempts execution without any serial transfer. Focused Ruff and 25 driver/verifier tests pass.
- Copied the pristine lifecycle authority to disposable `C:\Users\Q\AppData\Local\Temp\qns-bs2-persist-gate-20260719.state`. Process one completed with exit authority: import 25,108 bytes, entry cycle `341646282`, PC `1000`, CBAR `81`, BSNAME speech, graceful save.
- Fresh process two loaded that state and reached the file manager without initialization loss. A single dot-5 then X did not select BSNAME; firmware spoke exact suffix `F AH E L I Z N AH T A E1 P R O OU K HVC R AE M` (`file is not a program`) and returned to `Enter file command`. No claim of persisted execution is made yet.
- Current blocker: none. Next action: inspect the source-owned next-program selection bounds/semantics, then make the persisted verifier cycle dot-5 only on the exact `file is not a program` response until native PC `1000` or the real source-defined bound is exhausted. Do not retransfer the program or directly inspect flash as a substitute.

### Interactive display closure gates in progress

- Scoped Ruff passes and all 60 display/BNS focused tests pass.
- The real BL2 Braille-only run prints its nonempty 18-cell `Display codes:` line before `Executed 30,000,000 cycles`, proving hardware-strobe-time stdout emission rather than a post-run snapshot.
- Full suite result: 136 passed with only the same invalid legacy-DSP duration test outside the product PCM path.
- The exact BS2 external-program verifier is still active through PTY capture after roughly 90 seconds and has emitted no intermediate output. It is not counted as passing until its exit/import/entry result is visible.
- Current state: the three-path interactive-display slice remains uncommitted; no additional source changes were made. Notes remain unstaged.
- Current blocker: bounded BS2 verifier still running. Next action: wait for its result, then inspect/stage only `qns/io.py`, `qns/bns.py`, and `tests/test_io.py` and commit if the verifier passes.
### Persisted BSNAME selection investigation

- The first persisted-process attempt is not yet a valid execution proof: after reload, one dot-5 followed by X produced the exact speech for `file is not a program` and returned to `Enter file command`.
- Firmware source `FILEP.C` defines dot-5 (`case C5`) as “next program file”: it repeatedly calls `find_next_file`, filters for `file.type == TY_EXEC` in the current folder, speaks that file, and restores the prior `fnext` only when no later program exists.
- `FILEAPI.C::find_next_file` advances through RAM directory entries and, when `flash_bsp` is active, continues through flash entries until an entry has no `top_of_file`; there is no invented retry count in the firmware path.
- Therefore, the observed `file is not a program` after dot-5 contradicts the assumption that the sent input selected a program. A retry loop would hide that contradiction and is not yet justified.
- Current intended source slice remains only `tools/verify_bs2_external_program.py`; `notes-software-bns.md` must remain unstaged. User-owned `CLAUDE.md` and synth changes remain untouched.
- Next action: inspect the verifier's chord encoding and wait/event ordering around dot-5 and X, then compare those exact inputs against the firmware key constants before changing the persisted verification algorithm.

#### Persistence correction

- The verifier's raw inputs match the firmware mapping: `get_menu_key()` maps physical dot-5 `0x50` to `C5 == 0x150` and physical X-chord `0x6D` to `XCHORD == 0x16D`.
- The hypothesis that graceful state omitted the BS2 flash device was wrong. `Memory.save_state()` writes v2 state containing the written-address bitmap, all RAM, and the entire configured flash array; `Memory.load_state()` validates the flash size and restores those bytes.
- The earlier graceful-stop gate only asserted shadow RAM, but the implementation itself includes flash. The active failure must therefore be narrowed to boot reconstruction/volatile directory metadata, persisted flash contents, or verifier event sequencing.
- Next action: trace the firmware boot/load path that reconstructs `flash_bsp`, flash FCBs, `folder_pointer`, `fileon`, and `fnext`, and compare it with what the emulator resets versus restores. Do not add a retry loop or claim persisted execution until that lifecycle is causally understood.

#### Persisted restart root cause

- Proven cause: process two was launched with `power_on_input=True`, sent the I-chord cold-reset input, and `reach_stdio_editor_command_loop()` answered Y to every recognized initialization prompt. Firmware `BSINIT.C::ask_flash()` calls destructive `flashInit(1, ...)` after Y, erasing the persisted executable before the verifier selected it.
- Normal firmware startup instead detects the existing flash and calls the non-destructive setup path. The restart verifier must therefore launch without `--power-on-input`, wait for the ordinary firmware `keyboard ready` event, and only then send O-chord/f.
- The proposed dot-5 retry/cycling workaround was based on a false premise and is abandoned. One dot-5 remains the source-defined “next executable program” action after a valid normal restart.
- A first patch accidentally matched the identical constructor block in `verify_through_stdio()` rather than `verify_persisted_stdio_program()`. It was caught by immediate inspection before any execution; the import process was restored to cold-reset initialization and only the restart process now uses normal boot.
- Next action: add a focused test that distinguishes the two subprocess launch contracts, run Ruff and the focused BS2/stdio tests, then run a fresh two-process live gate from a new copy of the pristine state.

#### Persisted BSNAME restart verified

- Added a regression authority proving the restart process is constructed with `model="bs2"` and the saved state but without `power_on_input`; its exact input sequence is O-chord, lowercase f, dot-5, X-chord, with no destructive I-chord.
- Focused checks pass: Ruff is clean and `tests/test_bs2_external_program.py`, `tests/test_stdio_process.py`, and `tests/test_stdio.py` report 40 passed.
- Preserved pristine authority: `C:\Users\Q\AppData\Local\Temp\qns-bs2-pristine-lifecycle-20260718.state`.
- Created and used only new disposable state: `C:\Users\Q\AppData\Local\Temp\qns-bs2-persist-gate2-20260719.state`.
- Complete shipped-CLI `--stdio --persist` gate passed:
  - Process one imported `bsname.bns` (25,108 bytes), completed ASCI1/ASCI0 ENQ/NAK and YMODEM, entered native PC `1000` at cycle `341632282` with CBAR `81`, and emitted the exact BSNAME speech marker.
  - Graceful stop saved state and flash.
  - Fresh process two loaded that state, used normal power-on, performed no transfer, selected the persisted executable through the real file manager, entered native PC `1000` at cycle `16969026` with CBAR `81`, and emitted the same exact BSNAME speech marker.
- Persisted BS2 import/execution is now proven end-to-end through shipped stdio across a real process restart.
- Next action: reread the active plan after this substantial passing gate, identify its next unchecked requirement, and continue. Before committing this slice, run the full suite and reconcile only the known invalid legacy DSP failure if it remains the sole failure.

#### Persisted verifier full-suite gate

- Full suite result after the passing two-process live gate: 165 passed, one failed.
- The sole failure remains `tests/test_synth.py::test_time_stretch_duration_modes`, which asserts behavior of the invalid legacy `qns/synth/dsp.py` path. The product audio owner is `SSI263PCMSynth`, and the preserved user-owned synth replacement remains outside this slice; no synth edit is authorized or needed.
- Active kept slice is exactly `tools/verify_bs2_external_program.py` plus its focused regression in `tests/test_bs2_external_program.py`. Notes remain unstaged.
- Next action: inspect the exact two-file diff, run whitespace/name gates, stage only those files, inspect the cached diff, and commit the kept persistence-verifier slice. Then resume the final whole-system requirement audit.

#### Persisted verifier slice committed

- Exact staged paths were `tools/verify_bs2_external_program.py` and `tests/test_bs2_external_program.py`; cached name and whitespace gates were clean.
- Committed as `63f2f87` (`Verify persisted BS2 programs after restart`). Notes, `CLAUDE.md`, user-owned synth changes, and unrelated artifacts were not staged.
- Next action: audit the objective's remaining system requirements against current product code and live gates. Identify the first concrete missing or failing boundary before opening another source slice; do not treat this commit as completion.

### Supplied TNS firmware omission discovered

- Correction: the earlier statement that TNS had no supplied firmware because it had no `.bns` file was extension-literal and wrong. `roms/NFB99/TNSENG/tnseng.tns` is a 273,970-byte update package with the same `18 0C 42 4E 53 00` (`BNS\0`) header as the supported firmware packages.
- `BNS.load_rom()` identifies update packages by header rather than suffix, so it can already extract the `.tns` image. The missing product boundary is the hardware profile: constructor and CLI choices expose only `bsp`, `bs2`, `bsl`, `bl2`, and `bl4`.
- Authoritative `BSPORTS.LIB` shows TNS is not safely represented by an existing profile: SSI-263 is at `90..94`, QWERTY user input is at `D0`, its 8255 is at `C0..C3`, power is at `B0`, and status/latch is at `E0`; current profiles use materially different ownership at those ports.
- This is the first concrete unimplemented supplied-firmware requirement found by the final audit. No source edit has begun.
- Next action: derive the exact TNS keyboard interrupt/data contract and its linked command-loop readiness addresses from the supplied ROM/source, then define the smallest literal TNS profile slice and its first failing authority before implementation.

#### TNS hardware contract narrowed

- `BS.ASM::USRIN` proves TNS input is not the Braille latch handshake used by current profiles. On each INT2 event it reads one PIC byte from `UIPORT D0`; key-down bytes have bit 7 set and key-up bytes clear it. English `a` is down `94`, up `14`; the firmware owns modifier state and translation through `TNSKBX.C`.
- TNS also owns the PIC16C56 clock over native CSI/O, using its 8255 control port `C3` as the clock strobe. This matches the existing clock-PIC concept but at TNS-specific PIO ownership.
- TNS has no Braille display. Its other core ports are SSI-263 `90..94`, 8255 `C0..C3`, power `B0`, watchdog-read/speech-power-write `80`, and status/latch `E0`.
- The linked command-loop variables still come from the common `BS.ASM`/`BSBGTASK.ASM`, but their TNS physical/link addresses must be recovered from the actual package before firmware-paced stdin can be claimed.
- No product source is modified. Next action: recover TNS linked `_iib`, `bg_timer`, and STARTA timer-write PC from the exact firmware image, then add failing boot/profile authorities for only the proven port map. Keep scan-code stdin as the next distinct source slice rather than pretending the Braille keyboard device is sufficient.

#### TNS profile slice opened

- Exact package pattern matching recovered STARTA `0AE1`, `LD (bg_timer),0` instruction PC `0AF9`, logical `bg_timer D659` / physical `41659`, and logical `_iib F29D` / physical `4329D`.
- Added failing authorities for those linked constants, exact TNS model/port ownership, and distinct keyboard-PIC down/up scan-byte INT2 events.
- The first focused run failed exactly because `TNSKeyboard` did not exist.
- Implemented only `TNSKeyboard` in `qns/io.py`: press presents bit-7 key-down, release presents the matching bit-7-clear key-up, each event asserts INT2, and the source-owned `D0` read acknowledges it.
- Active tracked slice is `qns/io.py`, `qns/bns.py` not yet modified, `tests/test_io.py`, and `tests/test_bns.py`. Current blocker: none.
- Next action: wire the exact TNS model constants and port map in `qns/bns.py`, rerun the focused tests, then live-boot the supplied `tnseng.tns` and require real SSI-263 speech before keeping the slice.

#### TNS hardware profile live gate passes

- Wired the TNS model only at its source-defined owners: SSI-263 `90..94`, `TNSKeyboard` at `D0`, PIC clock on CSI/O, no display/direct RTC, 8255 `C0..C3`, speech/watchdog `80`, power `B0`, and status/latch `E0`.
- Corrected one invalid test premise: `IOBus` has no public `read_handlers`; the authority now drives the real bus and observes device state instead of requiring a nonexistent introspection API.
- Scoped Ruff passes and all 69 BNS/I/O focused tests pass.
- Live supplied `tnseng.tns` run at 30,000,000 cycles exited `0`, retained 114 SSI-263 phonemes including the startup `Type 'n Speak ready` announcement, reached PC `D65C`, and established MMU `CBR=34 BBR=00 CBAR=C6`.
- Active slice is exactly `qns/io.py`, `qns/bns.py`, `tests/test_io.py`, and `tests/test_bns.py`; it proves TNS boot, hardware ownership, and speech, but not stdio text delivery yet.
- Next action: run the full suite, inspect/stage/commit exactly these four files if the known legacy DSP failure remains sole, then open the distinct TNS scan-code stdin slice and prove a real key transaction.

#### TNS line-ending recovery required

- Full suite after the live TNS gate reports 168 passed and only the same invalid legacy DSP failure.
- Initial four-file diff was behaviorally correct and `git diff --check` was clean, but mixed line endings were visible around patched hunks.
- Running `unix2dos` was wrong for this checkout and broadened all four files; subsequent `dos2unix` removed whitespace errors but still broadened three historically mixed files. This mechanical result must not be staged.
- These four paths were clean before the TNS slice and contain no user-owned edits. Next action: restore exactly `qns/io.py`, `qns/bns.py`, `tests/test_io.py`, and `tests/test_bns.py` from the current index, reapply only the proven TNS hunks, then rerun focused tests/Ruff and require the narrow diff before staging.

#### TNS profile commit gate recovered

- Restored the four active paths from the index and reapplied only the proven TNS hunks. The broadened line-ending rewrite is fully gone.
- Recovered diff is narrow: 141 additions and 23 replaced lines across exactly `qns/bns.py`, `qns/io.py`, `tests/test_bns.py`, and `tests/test_io.py`.
- Ruff passes, all 69 focused tests pass, cached names are exactly those four files, and cached whitespace is clean.
- Next action: commit this TNS boot/hardware profile slice, then begin a distinct scan-code stdin slice. The complete goal remains active until real TNS text input and the remaining auxiliary asset/workflow audit are closed.

### TNS scan-code stdin slice passes live gate

- Committed the TNS hardware profile as `6b459ce` (`Add Type n Speak hardware profile`).
- Added model-aware TNS scan mapping for source-proven unshifted English letters, space, and return. Existing Braille profiles retain their exact chord table.
- TNS firmware pacing now advances on the keyboard PIC's read acknowledgment for each down/up byte; other profiles retain their `_iib` value/clear handshake.
- Ruff passes and all 70 focused BNS/I/O tests pass.
- Live supplied `tnseng.tns` JSONL run consumed text `a` as scan `94`, emitted exact `keyboard accepted` chord 148 and then `keyboard ready`, and ended at the established PC `D65C` after 30,000,000 cycles.
- Active slice is exactly `qns/bns.py` and `tests/test_bns.py`. Next action: run full suite, stage/commit those two paths if clean, then continue TNS input coverage for shifted/digit/punctuation keys before claiming complete human keyboard operation.

#### TNS basic stdin committed

- Full suite reported 169 passed with only the established invalid legacy DSP failure.
- Exact two-file slice committed as `35a9cc9` (`Drive Type n Speak keyboard from standard input`).
- Remaining TNS keyboard gap: uppercase, digits, and punctuation require source-defined modifier/down/up scan sequences; the current one-character scheduler intentionally does not fake those as Braille chords.
- Next action: derive the English physical-key/shift sequence table from `TNSKBX.C`, extend the queued input representation to emit the exact sequence while retaining one accepted event per user character, then prove representative uppercase/digit/punctuation transactions live.

#### Full TNS keyboard source contract

- Current Git authority remains `35a9cc9` on `master`, ahead of `origin/master` by 34 commits. The only tracked modifications are the pre-existing user-owned `CLAUDE.md`, synth files, and this unstaged notes file; no new product edit has begun.
- `TNSKBX.C::keydecode()` and `BS.ASM::USRIN` prove that shifted input must be emitted as four distinct PIC events: left-shift down `E1`, key down, key up, then left-shift up `61`. `USRIN` owns modifier state and ignores ordinary key-up bytes after clearing modifier state where applicable.
- Source-defined digit-row scans are `8B 8D 95 AD 97 AF B7 BF C7 CF`; shifted firmware meanings are `! @ # $ % ^ & * ( )`. The source also defines `D7` for `-/_`, `DF` for `=/+`, `D0` and `D8` for brackets/braces, `DC` for semicolon/colon, `D3` for apostrophe/quote, `CB` for comma/less-than, `C2` for period/greater-than, `CA` for slash/question, and `E0` for backslash/pipe. Tab is `91`, backspace is `ED`, enter is `DB`, and space is `A9`.
- `TNSKeyboard` currently remembers only the most recent key-down code and `release()` cannot name the modifier being released after a nested main-key transaction. The smallest required device change is an optional explicit scan argument to `release`, preserving its existing no-argument behavior.
- Current blocker: none. Next action: add focused failing authorities for scan selection and nested shift/main down-up delivery, then implement the exact scheduler phases, run scoped gates, and live-verify representative uppercase, digit, and punctuation input through the shipped JSONL CLI before committing the slice.

#### Full TNS keyboard implementation opened

- Added focused authorities for the complete ordinary English scan/shift table, nested modifier/main-key release, and the exact `E1 94 14 61` PIC transaction for uppercase `A`. The first focused run failed at collection because `_tns_input_scan` was absent, which is the intended missing boundary.
- Implemented the source-defined unshifted and shifted scan tables in `qns/bns.py`. Unsupported grave/tilde are deliberately not fabricated: English firmware treats physical `B9` as an alternate-character prefix unless Alt is held, so they need a separately proven physical sequence if required.
- Extended `TNSKeyboard.release()` with an optional explicit scan while preserving no-argument latest-key behavior. This permits main-key release followed by left-shift release without inventing combined chords.
- Added TNS-only scheduler phases: shift down, main down, main up, shift up. Existing Braille profile scheduling is unchanged, and the JSONL accepted event remains one event per host character with the main physical scan.
- Active product/test slice is exactly `qns/bns.py`, `qns/io.py`, `tests/test_bns.py`, and `tests/test_io.py`; it is not yet proven or staged. User-owned tracked files and notes remain untouched/unstaged.
- Current blocker: none. Next action: run the three focused authorities. If they pass, run scoped Ruff and the complete BNS/I/O test families before constructing a real-firmware JSONL live gate.

#### Full TNS keyboard real-ROM gate and final printable gap

- After correcting two invalid fake-CPU readiness expectations, all 32 focused authorities passed, scoped Ruff passed, and the full BNS/I/O families reported 102 passed.
- The shipped CLI live gate used the supplied `roms/NFB99/TNSENG/tnseng.tns`, model `tns`, JSONL stdio, and the bounded established 30,000,000-cycle run. It booted with real startup speech, accepted uppercase `A` as main scan `94`, digit `1` as `8B`, and shifted punctuation `?` as `CA`, returned to `keyboard ready`, exited `0`, and ended at established PC `D65C`.
- Source inspection proves the final printable-ASCII exception: English `TNSKBX.C` emits grave/tilde from physical scan `B9` only while Alt is held; `BS.ASM::USRIN` defines Alt down `A1` and Alt up `21`. Tilde additionally holds left shift (`E1`/`61`).
- Added failing authorities for grave scan `B9`, shifted tilde scan `B9`, and exact tilde PIC sequence `E1 A1 B9 39 21 61`. They fail because `_tns_input_scan` currently rejects both characters, exactly identifying the missing boundary.
- Current blocker: none. Next action: add TNS-only Alt phase state to the existing scheduler, rerun focused/scoped gates, then live-verify grave and tilde through the same supplied firmware before the full-suite/commit gate.

#### Full TNS keyboard completion gate

- Implemented source-defined Alt sequencing without a synthetic chord layer: grave emits `A1 B9 39 21`; tilde emits `E1 A1 B9 39 21 61`. The same scheduler still emits one accepted event for the main `B9` scan.
- Focused modifier/mapping/device authorities report 35 passed, scoped Ruff is clean, and the complete BNS/I/O families report 105 passed.
- The supplied English TNS real-ROM JSONL gate accepted both grave and tilde as scan `B9`, returned to `keyboard ready`, exited `0`, and ended at established PC `D65C` after 30,000,000 cycles.
- Full repository suite reports 204 passed and exactly one failure: the established invalid `tests/test_synth.py::test_time_stretch_duration_modes` assertion against legacy `qns/synth/dsp.py`. The product audio owner remains `SSI263PCMSynth`; this keyboard slice does not touch synth code.
- Active kept slice remains exactly `qns/bns.py`, `qns/io.py`, `tests/test_bns.py`, and `tests/test_io.py`. Notes and the three user-owned tracked files remain unstaged.
- Next action: inspect the exact four-file diff, run targeted whitespace/name gates, stage only those four files, inspect the cached diff, and commit the complete TNS keyboard slice. Then continue the auxiliary help/dictionary/message/program asset workflow audit.

#### TNS keyboard committed; auxiliary asset audit opened

- Committed the complete printable TNS keyboard slice as `af0c8dc` (`Complete Type n Speak standard input`). Only `qns/bns.py`, `qns/io.py`, `tests/test_bns.py`, and `tests/test_io.py` were staged. Notes and user-owned tracked files remain unstaged.
- Supplied per-profile auxiliary inventory is exact: six `.hlp`, six `spell.dic`, six `calsort.msg`, six `calsort.bns`; BSP/BS2/BL4 also supply `bsname.bns`. The shared dictionary is 348,536 bytes, `calsort.msg` is 1,557 bytes, and `calsort.bns` is 17,092 bytes.
- The shipped update instructions define these as ordinary firmware filesystem files, not emulator-side ROM overlays: transfer them through YMODEM; rename the profile help file to `help`; `spell.dic` enables the spellchecker; and `calsort.bns` must execute with `calsort.msg` present.
- Current `tools/verify_bs2_external_program.py` already sends arbitrary path bytes through the real YMODEM receiver, but its scenario is hard-coded to one `program`, one file transfer, a BNS header/CBAR check, and the BSNAME speech marker. It cannot currently prove non-program file import or a program/resource pair.
- BS2 help supplies exact post-import authorities: `c-chord` speaks the selected file, `25-chord` spells it, `156-chord` gives its size, `r-chord` renames it, and external programs are selected/executed through the file menu. Firmware mini-help explicitly says a full help file replaces mini help when loaded, and spellcheck source/help explicitly requires `spell.dic` in the unit.
- Source search did not locate Calsort application source in the supplied BSP tree; its binary/resource behavior must therefore be verified through the real program entry and firmware-visible results, not inferred from an unavailable source file.
- Current blocker: none. Next action: determine the smallest real-ROM authority for an imported ordinary file and for `calsort.bns` with `calsort.msg`; then add a failing verifier authority before generalizing the existing one-file/BSNAME-only choreography. Do not add an emulator-side asset loader.

#### Generic auxiliary receive verifier slice opened

- Corrected the earlier premise: the emulator product path already supports arbitrary firmware YMODEM files. The missing boundary is the retained verifier's one-BSNAME restriction, not an absent runtime asset loader.
- Added failing authorities for a reusable file-menu receive transaction and exact persisted payload checks. Their initial collection failure proved the named verifier functions were absent.
- Implemented `receive_stdio_file()` by moving the existing exact T/ASCI1 probe/ASCI0 probe/r/y/YMODEM/file-command sequence into one owner. `verify_through_stdio()` now receives zero or more `--resource` paths before its external program using that same path.
- Implemented `require_persisted_files()` against the existing BS2 v2 state format. It loads the real 2 MiB flash plus RAM state and requires every supplied payload verbatim in one persisted region; it does not inject or modify firmware files.
- The first focused run passed exact state checking. The receive test failed only because its expected transfer cursor was incorrectly the pre-ENQ serial length `4`; the real helper correctly passes the post-ENQ cursor `5` to the YMODEM wait. The test expectation is corrected.
- Active tracked slice is exactly `tools/verify_bs2_external_program.py` and `tests/test_bs2_external_program.py`; it is not staged. Notes and user-owned tracked files remain unstaged.
- Current blocker: none. Next action: rerun focused/Ruff/full verifier tests, add authority that resources are ordered before the program and checked after graceful persistence, then run a disposable real-ROM `calsort.msg` plus `calsort.bns` import/entry gate.

#### Calsort resource use proven; marker correction required

- Focused generic receive/persistence authorities pass, scoped Ruff is clean, and the full external-program/stdio-process families report 29 passed. A separate authority proves resource order is `resources..., program` and that graceful persistence checks the same complete tuple.
- Preserved pristine BS2 state SHA-256 is `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5`. A fresh disposable copy at `C:\Users\Q\AppData\Local\Temp\qns-bs2-aux-gate-20260720-1.state` matched that hash before the live run.
- The real shipped-process run imported `calsort.msg` followed by `calsort.bns`, reached native program entry, and then timed out only because `execute_selected_stdio_program()` still demanded the BSNAME-specific speech marker.
- The retained real Calsort speech tail was `R ER ER K OO D N AH T O OU P EH1 N D A E1 T B OO K`, exactly the `calsort.msg` default-English resource string `ERROR, could not open datebook`, followed by `ok, enter file command`. This proves the external program located and consumed the imported resource through the firmware filesystem.
- The diagnostic failed before graceful stop, so no persisted success is claimed and the disposable state was not used as persistence evidence.
- Current blocker: none. Next action: replace the verifier's unconditional BSNAME marker with program-specific supplied markers (BSNAME and Calsort; native entry only for unknown programs), add focused authority, rerun tests, then repeat the same disposable live gate and require graceful persistence plus exact payloads.

#### Calsort persisted-state authority failed

- The intended verifier/test slice remains exactly `tools/verify_bs2_external_program.py` and `tests/test_bs2_external_program.py`; it is uncommitted and unstaged. User-owned tracked files and this notes file remain separate.
- Fresh disposable state `C:\Users\Q\AppData\Local\Temp\qns-bs2-aux-gate-20260720-2.state` matched the pristine BS2 lifecycle state SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5` immediately before the live run.
- The real supplied-ROM/stdin run imported `calsort.msg` and `calsort.bns`, accepted the Calsort-specific resource speech marker, and reached graceful-stop persistence. It then failed only at `require_persisted_files()` because the saved state did not contain the complete `calsort.bns` host payload as one verbatim RAM/flash substring.
- This invalidates the proposed whole-payload-substring check as a general firmware-filesystem persistence authority; no persisted success is claimed from this run. The result does not show that Calsort failed to persist, because the firmware may transform, split, or omit transfer framing/header bytes in its on-device representation.
- Current blocker: none. Next action: inspect the saved state and firmware file representation read-only, compare it with the transferred program/resource bytes, and identify the existing real firmware-visible restart authority. Correct or remove the invalid assertion before rerunning this same slice; do not begin help or dictionary work.

#### Calsort resource/import/restart gate passes

- Read-only state inspection found the executed `BNS` image in RAM rather than an unchanged complete host-program substring. The earlier whole-program-payload persistence premise was wrong: native execution mutates the loaded image. The verifier now applies exact byte persistence only to ordinary resources; executable persistence is proven by a no-transfer restart and native re-entry.
- Renamed the corrected authority to `require_persisted_resources()`. The resource-order test now requires exact persistence for `calsort.msg`/other resources only, while the existing restart verifier remains responsible for the selected `.bns` program.
- The complete external-program and stdio-process focused families pass: 30 tests.
- Fresh disposable state `C:\Users\Q\AppData\Local\Temp\qns-bs2-aux-gate-20260720-3.state` matched the pristine SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5` before the rerun.
- The supplied `bs2eng.bns` real-ROM/stdin gate passed end to end: imported exact 1,557-byte `calsort.msg`, imported 17,092-byte `calsort.bns`, entered native code at PC `1000` with expected CBAR `61`, gracefully persisted, restarted without retransmission, re-entered at PC `1000`/CBAR `61`, and again spoke the resource-backed `ERROR, could not open datebook` marker.
- Current blocker: none. Next action: run scoped Ruff, whitespace, and full-suite gates; inspect and commit exactly `tools/verify_bs2_external_program.py` plus `tests/test_bs2_external_program.py` if the known unrelated legacy DSP assertion remains the sole full-suite failure. Then begin the separate full-help workflow slice.

#### Calsort slice committed; full-help slice opened

- Scoped Ruff and whitespace gates passed. The full repository suite reported 208 passed and only the established invalid legacy `tests/test_synth.py::test_time_stretch_duration_modes` assertion against non-product `qns/synth/dsp.py`.
- Staged exactly `tools/verify_bs2_external_program.py` and `tests/test_bs2_external_program.py`; committed them as `25bd0b1` (`Verify supplied BS2 program resources`). Notes and user-owned tracked files remained unstaged.
- Supplied-source `FILEP.C` defines pointed-file rename as `RCHORD = 0x157` (stdio chord byte `0x57`), prompts with `ENTNAM`, reads the new name through `glin(name, 20)`, rejects an existing name, renames the RAM/flash file, and speaks OK.
- Firmware mini-help states that `bs2eng.hlp` must be loaded and renamed `help`. `BSPROCES.ASM` opens Help on dots 1456, and `FILEP.C::helpo()` opens the special HELPFILE and speaks `help is open`.
- The supplied payload is `roms/NFB99/BS2ENG/bs2eng.hlp`, 31,935 bytes. Its first line is `Braille 'n Speak Two Thousand Help File July 1999`, which distinguishes it from the built-in mini-help.
- Current blocker: none. Next action: add a focused failing authority for the literal import/rename/exit/open/read choreography, implement that scenario using the existing stdio process and receive helper, then prove the supplied full-help content before and after restart from a fresh disposable state.

#### Full-help stdio scenario opened

- Git authority before editing was `master` ahead of `origin/master` by 36, with no uncommitted tracked source beyond the pre-existing user-owned files and unstaged notes.
- Added `tests/test_bs2_help.py` first. Its initial collection failed exactly because `tools.verify_bs2_help` did not exist.
- Added the narrow scenario verifier `tools/verify_bs2_help.py`. It reuses `BNSStdioProcess`, `reach_stdio_editor_command_loop()`, `receive_stdio_file()`, `send_stdio_chord()`, and `require_persisted_resources()` rather than adding a runtime asset loader.
- The scenario performs the source-defined sequence: enter file menu, YMODEM-import `bs2eng.hlp`, R-chord rename to text `help`, E-chord terminate, E-chord exit, dots-1456 open Help, C-chord speak current line, graceful save, normal restart, and repeat Help/C-chord without retransmission.
- Focused choreography authorities report 2 passed and scoped Ruff is clean. The verifier currently prints the observed title phonemes rather than asserting an invented sequence; the first disposable real-ROM run is explicitly diagnostic and must immediately supply the retained marker for a second authoritative run.
- Active slice is exactly new files `tools/verify_bs2_help.py` and `tests/test_bs2_help.py`; it is uncommitted and unstaged. Notes and user-owned tracked files remain separate.
- Current blocker: none. Next action: copy the preserved pristine BS2 state to a fresh disposable target, run the supplied ROM/help scenario, retain the real title phonemes, add the exact full-help content marker and focused authority, then rerun from another pristine state for the actual import/persistence gate.

#### Full-help diagnostic live run in progress

- Fresh disposable state `C:\Users\Q\AppData\Local\Temp\qns-bs2-help-gate-20260720-1.state` did not previously exist and matched pristine SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5` before launch.
- The exact live command uses supplied `bs2eng.bns`, that disposable state, and supplied `bs2eng.hlp` through `uv run -m tools.verify_bs2_help`.
- The process remains active after the larger 31,935-byte transfer window and has emitted neither output nor a verifier exception. No result or persisted success is claimed while it is still running.
- Current blocker: none. Next action: continue polling the same process without restarting or changing procedure; when it completes, retain its imported/reloaded title phonemes or diagnose its exact failing boundary.

#### Full-help selection premise corrected

- The first diagnostic run failed at the post-rename prompt. Its speech tail was two repetitions of `file is write protected`; no rename, Help content, or persistence success is claimed.
- The earlier selection premise was wrong. Supplied `FILEP.C::filer()` initializes `fnext = fileon`, so the file menu still points at built-in Help after importing an ordinary file. Dot-5 is explicitly for the next external program and is not the authority for `.hlp`.
- Supplied help text and `FILEP.C` define dot-4 chord (`C4 = 0x148`, stdio byte `0x48`) as `Move forward through file list`. That is the required step from built-in Help to the imported `bs2eng.hlp` before R-chord rename.
- Corrected the focused choreography authority first; it failed because `DOT4_CHORD` was absent. Added source-defined `DOT4_CHORD = 0x48` and sent it immediately after import and before R-chord. Both focused tests now pass.
- Active slice remains exactly new `tools/verify_bs2_help.py` and `tests/test_bs2_help.py`, uncommitted and unstaged. The first disposable state is diagnostic-only and must not be reused.
- Current blocker: none. Next action: create a second state from the preserved pristine image, rerun the corrected help workflow, retain the real imported/reloaded title phonemes, then add the exact content marker before an authoritative third run.

#### Corrected full-help diagnostic still running

- Second disposable state `C:\Users\Q\AppData\Local\Temp\qns-bs2-help-gate-20260720-2.state` was absent before creation and matched the pristine SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5` before launch.
- The corrected live process includes the required dot-4 selection before R-chord. It remains active through the larger transfer/save/restart window and has emitted neither a verifier exception nor final output.
- No rename, content, or persistence success is claimed until this process completes.
- Current blocker: none. Next action: continue polling the same process; use its exact completion output to add the full-help title authority, or diagnose only its exact failing boundary.

#### Two-step ordinary-file traversal proven in source

- The second diagnostic completed with the same `file is write protected` timeout, so one dot-4 move was still an invalid selection premise; no success is claimed from its state.
- Supplied `BSP.H` fixes the file-handle ordering: `HELPFILE = 0`, `CLIPFILE = 1`, `FIRSTFILE = 1`. `FILEP.C::rename()` accepts only handles greater than `FIRSTFILE`. Therefore the first imported ordinary file requires two dot-4 moves: Help to Clipboard, then Clipboard to the imported file.
- Corrected the focused authority first and observed its expected failure at the missing second dot-4 call. Added the second call; both focused tests pass again.
- Third disposable state `C:\Users\Q\AppData\Local\Temp\qns-bs2-help-gate-20260720-3.state` was absent before creation and matched pristine SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5` before launch.
- The third corrected live process remains active without output or exception through the larger transfer/save/restart window. No result is claimed while it is running.
- Active slice remains exactly `tools/verify_bs2_help.py` and `tests/test_bs2_help.py`, uncommitted and unstaged.
- Current blocker: none. Next action: continue polling this same process; retain its exact title phonemes on success or diagnose only its exact failing boundary.

#### Positional help selection rejected; exact-name run active

- The third diagnostic completed without a process error but spoke `help is open; file is empty` both before and after restart. That proves a persistent empty ordinary file was renamed, not the supplied help payload; no full-help success is claimed from that state.
- Supplied `FILEP.C` provides exact-name selection: F-chord (`0x14B`) prompts for a wildcard/name, tags matching files, and the following dot-4 moves `fnext` to the tagged match. This removes dependence on unknown pre-existing ordinary files in the preserved lifecycle state.
- Corrected the focused authority first to require `F-chord`, text `bs2eng.hlp`, E-chord, dot-4, then R-chord. It failed at the absent `F_CHORD`; production now implements the exact sequence and both focused tests pass.
- Fourth disposable state `C:\Users\Q\AppData\Local\Temp\qns-bs2-help-gate-20260720-4.state` was absent before creation and matched pristine SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5` before launch.
- The exact-name live process remains active through transfer/save/reload with no output or exception. No result is claimed while it is running.
- Current blocker: none. Next action: continue polling this same process; retain the exact non-empty full-help title phonemes or diagnose only its exact failing boundary.

#### F-chord tag exit semantics corrected

- The fourth diagnostic selected the imported file by exact name but still did not read Help: imported speech was the file-menu pull-down menu, and reloaded capture was only `I`. No full-help success is claimed.
- Supplied `FILEP.C` proves why: F-chord selection leaves `tag_active = 1`; the first E-chord received by the file-menu loop only clears tag mode and breaks, while a second E-chord speaks exit and leaves the menu.
- Corrected the focused authority first to require two post-rename file-menu E-chords after the E-chord that terminates the rename input. It failed at the absent second exit call; production now implements it and both focused tests pass.
- Fifth disposable state `C:\Users\Q\AppData\Local\Temp\qns-bs2-help-gate-20260720-5.state` was absent before creation and matched pristine SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5` before launch.
- The fifth corrected live process remains active without final output or exception. No result is claimed while it is running.
- Current blocker: none. Next action: continue polling the same process; retain a non-empty full-help title marker or diagnose only the exact failing boundary.

#### Help-title speech completion made causal

- The fifth diagnostic completed with exact resource persistence and `help is open` before and after restart, but captured no title beyond that phrase. Keyboard `ready` is not a speech-completion authority, so no full-help content success is claimed from that run.
- JSONL already exposes every SSI-263 event, including `PA`. The verifier now waits for the observed exact `help is open` suffix `HF EH L P I Z O OU P EH1 N`, records the title start, issues C-chord, and waits for a `PA` event after at least one title phoneme. This is a causal line-end event, not an invented delay.
- Added the focused title-completion authority first; it failed because `HELP_OPEN_MARKER` was absent. Production now implements the marker and terminal-pause condition. All three focused help tests pass.
- Active slice remains exactly `tools/verify_bs2_help.py` and `tests/test_bs2_help.py`, uncommitted and unstaged.
- Current blocker: none. Next action: run the corrected causal title capture on a sixth pristine disposable state, retain the exact full-title sequence, then convert it into an asserted content marker and run a final pristine authoritative gate.

#### Sixth causal full-help diagnostic running

- Sixth disposable state `C:\Users\Q\AppData\Local\Temp\qns-bs2-help-gate-20260720-6.state` was absent before creation and matched pristine SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5` before launch.
- The live process uses exact-name selection, tag clear, real menu exit, exact `help is open` suffix, and a terminal `PA` event after title speech. It remains active without final output or exception.
- No title or persistence success is claimed while it is running.
- Current blocker: none. Next action: continue polling the same process and use its complete imported/reloaded title sequence to finalize the content authority.

#### Overshoot-safe help marker run active

- The sixth diagnostic reached a complete imported title read, saved, restarted, and then timed out waiting for `help is open` only because that marker had already occurred and speech advanced one phoneme beyond it before the suffix wait began. The retained tail included the sequence, so this was a verifier race, not evidence that persisted Help failed.
- Added a cursor-bounded contiguous speech-sequence wait. It searches retained speech from the pre-command cursor before waiting for more events, so it accepts marker overshoot while rejecting older unrelated occurrences.
- Added the focused race authority first; it reproduced the old failure with marker plus overshoot already retained. The corrected sequence search and terminal-pause logic pass, and the complete help workflow fake now emits rather than bypasses required speech. All three focused tests pass.
- Seventh disposable state `C:\Users\Q\AppData\Local\Temp\qns-bs2-help-gate-20260720-7.state` was absent before creation and matched pristine SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5` before launch.
- The seventh overshoot-safe live process remains active without output or exception. No final title/persistence result is claimed while it is running.
- Current blocker: none. Next action: continue polling this same process; retain the exact complete imported and reloaded title phonemes when it finishes.

#### Persisted Help-open state corrected

- The seventh diagnostic again completed the imported title path but timed out on the restart marker. The retained marker was older than the restart verifier cursor because the first session saved with Help still open; on restart firmware resumed/opened Help before the verifier called it, and a new Help-chord is source-defined to be ignored while `HOPEN` is set.
- Supplied `BSPROCES.ASM` proves Z-chord calls `_HELPC`, clears `HOPEN`, and returns to the prior file. Added the focused requirement first; it failed because `Z_CHORD` was absent. Production now sends source-defined Z-chord `0x75` after each completed title read and before each graceful stop.
- All three focused help tests pass. Active slice remains exactly `tools/verify_bs2_help.py` and `tests/test_bs2_help.py`, uncommitted and unstaged.
- Current blocker: none. Next action: run the close-before-save workflow from an eighth pristine disposable state, retain full title phonemes before and after restart, then add the exact full-title content marker and perform the final authoritative run.

#### Eighth close-before-save help run active

- Eighth disposable state `C:\Users\Q\AppData\Local\Temp\qns-bs2-help-gate-20260720-8.state` was absent before creation and matched pristine SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5` before launch.
- The live process now closes Help with source-defined Z-chord after the imported title read and before persistence, then performs a normal restart and a fresh Help open/title read.
- It remains active without final output or exception. No title or persistence success is claimed while it is running.
- Current blocker: none. Next action: continue polling this same process and retain its complete imported/reloaded title sequences.

#### Generic PA rejected; stdio speech-idle boundary identified

- The eighth run confirmed firmware restores Help as the current open file and announces it before the restart verifier's new command cursor. The workflow now consumes that boot-time marker and issues C-chord directly; all three focused tests pass.
- The ninth pristine run completed import, rename, exact resource persistence, restart, and title commands, but captured only `B` in each session. This disproves the generic `PA` line-end premise: SSI-263 code `0x00` is also emitted as a stop closure inside words. No full-title success is claimed.
- Current `BNS.run()` already computes the exact stable speech-complete/key-wait condition each loop: CPU halted, no pending SSI-263 completion IRQ, and the same `(pc, phoneme_count)` signature for two consecutive chunks. This is the proper owner for a stdio speech-idle acknowledgment; it does not require a guessed delay or pause code.
- Current JSONL input types are keyboard, serial, PC watch, and stop. There is no speech-idle request/acknowledgment yet. Adding one narrow request at this existing run-loop authority will let the help verifier wait for complete title output causally and will improve stdio debugging rather than altering firmware behavior.
- Active help slice is still uncommitted. The required next related change will touch `qns/stdio.py`, `qns/bns.py`, `tools/stdio_process.py`, their focused tests, and the two help verifier files; user-owned synth files and notes remain separate.
- Current blocker: none. Next action: add failing parse/run/process authorities for `{"device":"speech","action":"wait-idle"}`, implement its acknowledgment only at the existing stable-key-wait condition, replace the invalid PA wait, and rerun focused/live gates from another pristine state.
### 2026-07-20: JSONL speech-idle barrier implemented; focused result unknown

- Added a `speech` / `wait-idle` JSONL input request and a matching `speech` / `idle` output event.
- The runtime acknowledgement is emitted only at the existing two-chunk stable key-wait boundary: CPU halted, no pending SSI-263 IRQ, and unchanged PC/phoneme count.
- Added parser, runtime-routing, and subprocess-client tests for the new barrier.
- The combined focused pytest run produced output beyond the available tool context, so its pass/fail result is unknown and must not be treated as passing.
- Next exact action: rerun the parser, runtime-routing, and subprocess speech-idle tests separately, then repair only the failing surface before replacing the invalid PA-based help-title wait.

### 2026-07-20: Speech-idle barrier confirmed and help verifier migrated

- The parser gate passed: `16 passed`.
- The in-process runtime-routing gate passed: `1 passed`.
- The real subprocess acknowledgement gate passed: `1 passed`.
- Replaced the disproven generic-`PA` full-help title heuristic with `BNSStdioProcess.wait_for_speech_idle(timeout=60)`.
- The full affected families passed: `109 passed in 5.61s`.
- Ruff passed on exactly the eight active source/test files.
- The active plan remains on full-help import/rename/use/restart; no later plan item has begun.
- Next exact action: create a fresh state copy from the hashed pristine BS2 lifecycle state, verify the copy hash, and run the supplied `bs2eng.hlp` workflow through the real `bs2eng.bns` firmware to capture the complete imported and restarted title sequences.

### 2026-07-20: Real full-help attempt 10 in progress

- Confirmed the pristine source state hash as `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5`.
- Confirmed `qns-bs2-help-gate-20260720-10.state` did not exist, copied it from that pristine source, and confirmed the copy has the same SHA-256.
- Started the supplied `bs2eng.bns` plus supplied 31,935-byte `bs2eng.hlp` verifier against attempt 10.
- The same verifier process remains alive after roughly 150 seconds and has emitted neither stdout nor a traceback. It has not been restarted or interrupted.
- Next exact action: continue waiting on subprocess session `86010` for its terminal result; do not create a new attempt or infer success from process liveness.

### 2026-07-20: Attempt 10 disproved the halted-loop idle premise

- Attempt 10 failed in `read_help_title()` after `wait_for_speech_idle(timeout=60)` received no acknowledgement.
- The timeout speech tail ended with `T U U TH AH OU Z AE N D E HF EH L P F AH E L J U U1 L AH E1 W UH1 N N AH E N N AH E N N AH E N`, showing title speech continued and reached its final words; the emulator remained alive.
- The earlier premise that the stable halted key loop is a universal speech-idle boundary was wrong. The halted-ROM subprocess test did not cover the BS2 full-help reader's non-halted loop.
- Repository authority already exists in `BS2Harness.wait_for_speech()`: no pending SSI-263 IRQ and unchanged phoneme count across 100,000 emulated cycles, explicitly for firmware key loops that do not halt.
- Added, but have not yet run, a JSONL runtime test requiring idle acknowledgement with a non-halted CPU. Adjusted the mixed routing expectation to the existing 100,000-cycle speech-settle interval; corrected an initially mis-targeted test-line edit before running tests.
- No runtime implementation change has been made since the attempt-10 failure.
- Next exact action: run the two affected runtime tests to confirm they fail against the halted-only implementation, then align the JSONL acknowledgement with the existing `BS2Harness.wait_for_speech()` condition.

### 2026-07-20: Non-halted speech settle implemented; attempt 11 in progress

- Both new/adjusted runtime tests failed against the halted-only implementation: the halted loop acknowledged at cycle 2,000 instead of after the speech-settle interval, and the non-halted loop never acknowledged.
- Aligned the JSONL acknowledgement with `BS2Harness.wait_for_speech()`: no pending SSI-263 IRQ and unchanged phoneme count for 100,000 emulated cycles, independent of CPU HALT state.
- The two regressions then passed; all affected families passed `110 passed in 5.03s`; Ruff passed on the eight active files.
- Confirmed `qns-bs2-help-gate-20260720-11.state` was absent, copied it from the pristine source, and verified SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5`.
- Attempt 11 is running in subprocess session `74418`; after roughly one minute it has emitted neither a result nor an error and has not been interrupted.
- Next exact action: continue waiting on session `74418` for the imported and restarted full-title phoneme sequences or its terminal failure.

### 2026-07-20: Attempt 11 exposed a pre-speech idle race

- Attempt 11 exited `0` and persisted the supplied help resource, but printed empty imported and reloaded title phoneme sequences.
- Therefore attempt 11 did not verify help content and is not a successful full-help gate.
- Cause: after C-chord acceptance, the firmware can spend more than the 100,000-cycle settle interval preparing the line before emitting its first phoneme. The idle request settled during that pre-speech interval, and the verifier closed Help before title speech began.
- Added a failing authority test requiring observed speech activity after C-chord before the idle request. It failed with only the post-idle fake phonemes, proving the missing ordering.
- Updated `read_help_title()` to wait for at least one speech event after its captured `speech_start`, then request the established idle boundary. All three help-verifier tests pass.
- Next exact action: rerun all affected families and Ruff, then use a new pristine attempt-12 state for the real firmware discovery run. Do not reuse mutated attempt 11.

### 2026-07-20: Attempt 12 in progress after green pre-speech ordering gates

- All affected families pass `110 passed in 5.36s`; Ruff passes on the eight active files.
- Confirmed `qns-bs2-help-gate-20260720-12.state` was absent, copied it from the pristine source, and verified SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5`.
- Attempt 12 is running in subprocess session `11502`; after roughly 90 seconds it has emitted neither a terminal result nor an error and has not been interrupted.
- This remains a discovery run. Nonempty phoneme output is required to derive the content marker, but will not by itself complete the full-help gate.
- Next exact action: continue waiting on session `11502` for its terminal result.

### 2026-07-20: Attempt 12 disproved quiet-window speech completion

- Attempt 12 exited `0`, but captured only `B R A E L` before restart and `B R A E L EH N S P E K T U U` after restart.
- These are different prefixes of the title, not the complete title, so attempt 12 is not a successful full-help gate.
- The 100,000-cycle quiet window can occur between phonemes/words while the Help reader prepares more text. It is not a valid end-of-utterance boundary for this firmware.
- Confirmed the supplied first help line is exactly `Braille 'n Speak Two Thousand Help File July 1999`.
- The complete attempt-10 timeout tail contains the distinctive terminal phoneme sequence for `Help File July 1999`: `HF EH L P F AH E L J U U1 L AH E1 W UH1 N N AH E N N AH E N N AH E N`.
- Began fully removing the rejected, uncommitted JSONL speech-idle API from `qns/stdio.py`, `qns/bns.py`, `tools/stdio_process.py`, `tests/test_stdio.py`, and `tests/test_bns.py`. No prior committed work is being reverted.
- Remaining removal: delete the subprocess idle test. Then make `read_help_title()` wait for the exact terminal title sequence and return only through that marker; update its tests before another live attempt.

### 2026-07-20: Exact full-title terminal marker ready; attempt 13 pristine

- Fully removed the rejected JSONL speech-idle API and all of its tests; a bounded search confirms no `SpeechIdleInput`, `wait_for_speech_idle`, `wait-idle`, or runtime idle-candidate references remain.
- `read_help_title()` now waits for the exact terminal phoneme sequence corresponding to `Help File July 1999` and returns only through the marker end, excluding any later speech.
- Its authority test proves the verifier waits for the complete marker and bounds trailing speech.
- All affected families pass `106 passed in 4.52s`; Ruff passes on the eight active files.
- Confirmed attempt-13 state did not exist, copied it from the pristine state, and verified SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5`.
- Next exact action: run attempt 13 with the supplied `bs2eng.bns` and `bs2eng.hlp`. Success requires the exact title-ending marker before and after restart plus exact persisted resource bytes.

### 2026-07-20: Attempt 13 passed the real supplied full-help gate

- Imported exact supplied `bs2eng.hlp` (`31,935` bytes) as firmware file `help` through the real `bs2eng.bns` JSONL stdio workflow.
- Exact resource persistence check passed.
- The imported session spoke the complete title phonemes:
  `B R A E L EH N S P E K T U U TH AH OU Z AE N D E HF EH L P F AH E L J U U1 L AH E1 W UH1 N N AH E N N AH E N N AH E N`
- Restarted from saved state without another transfer and received the identical complete title sequence.
- Attempt 13 exited `0`; this completes the live import/rename/use/restart evidence for the full-help slice.
- Next exact action: run the full suite, accepting only the already-known legacy `tests/test_synth.py::test_time_stretch_duration_modes` failure; inspect the exact slice diff, stage only intended files (never this notes file or user-owned tracked files), and commit the kept full-help slice before starting `spell.dic`.

### 2026-07-20: Full-help slice committed

- Full suite result: `211 passed`, with only the already-known unrelated legacy failure `tests/test_synth.py::test_time_stretch_duration_modes` against `qns/synth/dsp.py`.
- Rejected speech-idle work left no tracked residue; the exact kept diff was only `tools/verify_bs2_help.py` and `tests/test_bs2_help.py`.
- Cached diff check passed; notes, user-owned synth files, ROMs, and unrelated research remained unstaged.
- Committed the kept slice on `master` as `6408149 Verify supplied BS2 full help`.
- The full-help import/rename/use/restart plan item is complete.
- Next exact action: begin the `spell.dic` workflow by inspecting the supplied dictionary artifact and the firmware source commands that import/select/use it; do not reuse the Help assumptions or start cross-profile gates early.

### 2026-07-20: Spell dictionary source authority recovered

- New slice starts on `master` with only pre-existing user-owned tracked changes and untracked research/assets; no spell source change exists yet.
- Supplied BS2 dictionary is `roms/NFB99/BS2ENG/spell.dic`; the shared per-profile dictionary size recorded earlier is 348,536 bytes.
- Authoritative source is under `C:\Users\Q\src\bns\bsp`.
- `BSSPELL.C` defines the required filename exactly as `spell.dic`. `opendict()` and `find_spelldic_file()` call `exists_anywhere("spell.dic")`; if absent, firmware speaks `spell.dic` followed by `does not exist` and returns false.
- On successful spellcheck completion, `BSSPELL.C::spellcheck()` speaks `say_spellcomplete`.
- `BSPROCES.ASM::SPCHK` rejects insert mode and an empty file, verifies `spell.dic`, backs the cursor to a word boundary, asks `spell check what?`, then accepts `w` for one word or `z` for the rest of the document before calling `_spellcheck`.
- The editor dispatch compares the option subcommand to `SPELLCHKBRL`; English `BSEQUATS.LIB` defines that as raw dots 1-6 value `0x21`. The outer O-chord is raw `0x55`; `C16=0x61` is a different chorded value and must not be substituted for the unchorded option subcommand.
- Next exact action: identify the English speech markers for `spell.dic does not exist`, `spell check what`, and `spell check complete`, then design the smallest real workflow: create/use a nonempty text file, prove absence behavior, import exact `spell.dic` through existing YMODEM, invoke O-chord plus raw `0x21`, choose one-word `w`, and prove successful dictionary-backed completion before and after restart.

### 2026-07-20: Spell dictionary verifier slice opened

- English source strings are exact: successful spellcheck completion is `done`; the selection prompt is `spell check what?`; absent dictionary speaks `spell.dic` followed by `file doesn't exist`.
- Supplied BS2 `spell.dic` is exactly 348,536 bytes with SHA-256 `7AE0CC5D640E1A65FB20597AEE9B638284D8D54D18F2D0DDFD77ECE92BBAFDB6`.
- Added a focused choreography authority first; it initially failed at import because `tools.verify_bs2_dictionary` did not yet exist.
- Added the new verifier using only established owners: real JSONL process, real YMODEM receive, firmware file-menu create, accepted text input, exact spell command chords, exact `done` phoneme suffix, exact persisted resource bytes, and no-transfer restart.
- The next test run reached assertions but the test ledger was wrong: it omitted the verifier's explicitly required pre-transfer `Enter file command` speech wait. This is a test expectation defect, not a production workflow failure.
- No live dictionary run has occurred and no spell success is claimed yet.
- Next exact action: correct the focused test's speech-wait ledger to include `FILE_COMMAND_PROMPT`, rerun it and Ruff, then create a fresh pristine disposable state for the first real dictionary run.

### 2026-07-20: Real spell dictionary attempt 1 in progress

- Corrected the focused ledger to include the pre-transfer `Enter file command` wait. The choreography test passes; Ruff passes on the two new files.
- Confirmed `qns-bs2-dictionary-gate-20260720-1.state` did not exist, copied it from the pristine lifecycle state, and verified SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5`.
- Started the real supplied `bs2eng.bns` plus 348,536-byte `spell.dic` workflow in subprocess session `49461`.
- After roughly 90 seconds the same process remains active with no stdout or terminal error; it has not been restarted or interrupted.
- The transfer has 341 firmware-acknowledged 1,024-byte data blocks, so no inference is drawn from elapsed time.
- Next exact action: continue waiting on session `49461` for its terminal result; on failure, diagnose only the exact boundary and do not reuse the mutated state.

### 2026-07-20: Attempt 1 failed; exact-boundary diagnostics added; attempt 2 active

- Attempt 1 failed inside the YMODEM data-block ACK loop. Firmware speech ended with `transfer cancelled, enter file command`; no dictionary import or spellcheck success is claimed.
- The timeout omitted the `wait_for()` description, hiding the failing block number. Added a focused failing test proving this diagnostic loss, then changed `BNSStdioProcess.wait_for()` to preserve the exact boundary and underlying event/speech/stderr context in its timeout.
- The diagnostic regression and dictionary choreography test pass; Ruff passes on the four active files.
- Confirmed attempt-2 state did not exist, copied it from the pristine source, and verified SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5`.
- Attempt 2 is running in subprocess session `27959`; after roughly one minute it has emitted no terminal result and has not been interrupted.
- Next exact action: continue waiting on session `27959`. If it fails, use the newly retained `data block N ACK` boundary to test the specific protocol/storage hypothesis rather than guessing.

### 2026-07-20: Attempt 2 proved RAM header-capacity rejection

- Attempt 2 reproduced the failure at the exact boundary `header ACK and data CRC request`, before data block 1.
- `FILETRAN.C::ymodem_receive()` parses the declared size from the header and, for a RAM transfer, aborts when `file_address + set_size > last_download_address`. For a flash-folder transfer it instead calls `flashReserve()` with the declared size.
- The verifier had remained in built-in folder 0, RAM Startup. The earlier block-wrap/throughput hypothesis is rejected.
- `FILEP.C` defines file-menu digit `1` as selecting built-in Flash Startup and digit `0` as selecting RAM Startup, provided the current mode is folder mode. The pristine state has been operating in folder mode.
- Added a failing choreography authority requiring exact Flash Startup selection before YMODEM and RAM Startup selection after transfer before creating the writable spellcheck file.
- Implemented those two source-defined selections. The dictionary choreography and exact-timeout diagnostic tests pass; Ruff passes.
- No live flash-folder dictionary transfer has run yet; attempts 1 and 2 are invalid and must not be reused.
- Next exact action: create a fresh pristine attempt-3 state, verify its hash, and run the same real workflow with Flash Startup selected for `spell.dic`.

### 2026-07-20: Attempt 3 proved pristine state was in All Files mode

- Attempt 3 used a fresh state with the expected pristine SHA-256 but still failed at `header ACK and data CRC request`, with the same `transfer cancelled` speech.
- This disproves the assumption that the pristine file menu was already in Folder Mode. `FILEP.C` routes digit folder selection to `not_in_folder_mode` when the All Files bit is set; the continued RAM header rejection proves digit `1` did not change `folder_pointer`.
- The shipped help and `FILEP.C` define file-menu spacebar as the exact toggle from All Files Mode to Folder Mode.
- Added a failing choreography authority requiring spacebar between file-menu entry and digit `1`; it failed because `SPACE_KEY` was absent.
- Added `SPACE_KEY` from the tracked ASCII-to-BNS table and sent it in that exact position. The two focused tests pass and Ruff passes.
- Attempt 3 is invalid and will not be reused.
- Next exact action: create and hash a fresh attempt-4 state, then rerun the real transfer with spacebar, Flash Startup digit `1`, and the existing return to RAM Startup digit `0`.

### 2026-07-20: Attempt 4 proved Allow Folder Mode was disabled

- Attempt 4 used the exact pristine hash and added file-menu spacebar before digit `1`, but still failed at the YMODEM header with RAM-style `transfer cancelled`.
- This disproves the assumption that the persistent `Allow folder mode` setting was enabled. `FILEP.C` only toggles the All Files bit on spacebar when `allow_folder_mode & 0x80` is set.
- Warm-reset source explicitly initializes `folder_pointer = 0x80` (All Files) and `allow_folder_mode = 0` (disabled), matching attempts 3 and 4.
- Shipped Help gives the prerequisite literally: status menu `34-chord`, `f-chord`, `y`; then the file-menu spacebar can enter Folder Mode. `BSPARMS.C` maps F-chord to parameter 43, and `BSPROCES.ASM::_pp42` sets bit 7 of `allow_folder_mode` on Braille `y`.
- Shipped `read0597.txt` confirms direct-to-flash YMODEM requires the desired flash folder to be active first.
- Attempts 3 and 4 are invalid and will not be reused.
- Next exact action: add the exact status-menu enable sequence to the focused choreography authority before changing the verifier, then rerun from a fresh attempt-5 state.

### 2026-07-20: Allow Folder Mode sequence implemented; attempt 5 active

- Added a failing choreography requirement for status `34-chord`, F-chord, `y`, E-chord before file-menu entry. It failed because `STATUS_CHORD` was absent.
- Added source-defined `STATUS_CHORD = 0x4C`, reused the exact F-chord and tracked `y` mapping, and sent the four inputs before O-chord/F file-menu entry.
- The dictionary choreography and timeout-diagnostic tests pass; Ruff passes on the four active files.
- Confirmed attempt-5 state was absent, copied it from the pristine source, and verified SHA-256 `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5`.
- Attempt 5 is running in subprocess session `67322`; after roughly one minute it has emitted no terminal result and has not been interrupted.
- Next exact action: continue waiting on session `67322`; completion still requires all 341 blocks, dictionary-backed `done`, exact byte persistence, restart, and a second `done`.

### 2026-07-20: Attempt 5 passed the prior header boundary and remains active

- The same attempt-5 process has remained active for roughly four minutes without the previous `header ACK and data CRC request` timeout or `transfer cancelled` speech.
- This confirms the status-menu enable plus Folder Mode/Flash Startup selection changed the live firmware path; it does not yet prove transfer or spellcheck completion.
- Session remains `67322`, with no restart, intervention, or alternate state.
- Next exact action: continue waiting on session `67322` for the terminal result. Do not infer completion from elapsed time.

### 2026-07-20: Attempt 5 still transferring after roughly seven minutes

- Session `67322` remains active with no stdout, timeout, cancellation, or terminal result after roughly seven minutes.
- No individual block has exceeded its 60-second ACK bound; the process has not been restarted or modified.
- Current state remains unproven beyond having passed the prior header rejection.
- Next exact action: continue waiting on the same session for its terminal result.

### 2026-07-20: Attempt 5 still active after roughly ten minutes

- Session `67322` remains active after roughly ten minutes with no per-block timeout, cancellation, stdout, or terminal result.
- The exact gate is unchanged and no success has been inferred.
- Next exact action: continue waiting on the same session.

### 2026-07-20: Attempt 5 still active after roughly thirteen minutes

- Session `67322` remains active after roughly thirteen minutes; no individual ACK wait has timed out and no terminal output has appeared.
- The process and state remain unchanged.
- Next exact action: continue waiting on the same session for the exact terminal result.

### 2026-07-20: Attempt 5 completed transfer but failed at spell-check invocation

- Session `67322` terminated with exit code `1` only after reaching `run_spellcheck`; the full direct-to-flash transfer therefore passed its prior header and block boundaries.
- The exact failed boundary was `imported dictionary spellcheck completion`: no BNS event for 60 seconds while waiting for the expected `D UH1 N` suffix.
- The terminal speech tail was `[O OU E EH L EH L O OU EH N T ER A E1 B E S E E O OU AH ER EH S OU ER A E1 T SCH F OU ER E HF EH L P]`, ending in help-like output instead of dictionary-backed completion.
- This disproves the verifier's current assumption that `O-chord`, raw key `0x21`, then `w` invokes spell check from this editor state. Attempt 5 is failed and its state will not be reused.
- Next exact action: trace the firmware's actual outer-menu spell-check key path and correct the focused choreography authority before changing the verifier.

### 2026-07-20: Attempt 5 reached the word-not-found interaction

- The prior diagnosis that the spell-check invocation itself was wrong is corrected: `BSPARMS.C` defines the option-menu spellchecker hotkey as `*`, the English Braille `ch` sign; `BSPROCES.ASM` converts it back to `SPELLCHKBRL = 0x21`; and shipped `bs2eng.hlp` says `o-chord ch (dots 16)`.
- The attempt-5 speech tail matches `BSSPELL.C::do_not_found`: it says the unrecognized word, spells it, then offers the word-not-found commands ending with help. Thus the supplied dictionary was opened and queried, but `hello` was not accepted.
- The focused test now requires `TEST_WORD == "the"`, a deliberate dictionary-core fixture. This test has not yet been run and the verifier still says `hello`, so the expected next result is a focused test failure.
- Attempt-5 state remains failed and will not be reused.
- Next exact action: run the focused test to establish the expected red result, then change only the verifier fixture and rerun the focused authorities.

### 2026-07-20: Dictionary-core fixture corrected; attempt 6 active

- The focused choreography test failed exactly because the verifier still used `hello`; changing only `TEST_WORD` to `the` made the dictionary choreography plus stdio timeout diagnostics pass `6 passed`. Ruff passes on all four active files.
- Confirmed the pristine source state SHA-256 as `AB962765C8753FBABA3B9BA7D57F6E278B935401B6FB747CC3916AD78A67CFE5`.
- Confirmed `qns-bs2-dictionary-gate-20260720-6.state` was absent, copied it from that source, and confirmed the copy has the same SHA-256.
- Attempt 6 is running in subprocess session `57279`. After roughly ninety seconds it has emitted no stdout, timeout, or terminal result and has not been restarted or interrupted.
- Next exact action: continue waiting on session `57279`; success still requires firmware `done` for `the`, exact dictionary bytes persisted, restart without transfer, and a second `done`.

### 2026-07-20: Attempt 6 still transferring after roughly four and a half minutes

- Session `57279` remains active with no stdout, traceback, cancellation, terminal success, or individual firmware-acknowledgment timeout.
- No state has been reused or process restarted. Liveness alone is not treated as completion.
- Next exact action: continue waiting on the same session for its terminal result.

### 2026-07-20: Attempt 6 still transferring after roughly seven and a half minutes

- Session `57279` remains active with no individual transfer-boundary timeout, cancellation, traceback, or terminal success report.
- The exact live gate and disposable attempt-6 state remain unchanged.
- Next exact action: continue waiting on session `57279` for the terminal result.

### 2026-07-20: Attempt 6 still transferring after roughly ten and a half minutes

- Session `57279` remains active. No firmware acknowledgment wait has timed out, and there is still no cancellation, traceback, or terminal success output.
- No conclusion beyond ongoing transfer is claimed.
- Next exact action: continue waiting on this exact session.

### 2026-07-20: Attempt 6 still active after roughly thirteen and a half minutes

- Session `57279` remains active without a per-boundary timeout or terminal output, consistent with the observed duration of the prior complete flash transfer.
- This timing does not prove transfer, spellcheck, persistence, or restart success.
- Next exact action: continue waiting on session `57279` for its exact terminal result.

### 2026-07-20: Attempt 6 still active after roughly sixteen and a half minutes

- Session `57279` remains active with no transfer-boundary timeout, cancellation, traceback, or terminal success output.
- The run has not been restarted, modified, or replaced.
- Next exact action: continue waiting on this exact session for the terminal result.

### 2026-07-20: Attempt 6 passed the complete supplied dictionary gate

- Session `57279` exited `0` with exact terminal output `imported: spell.dic (348536 bytes)` and `spellchecked: the before and after restart`.
- The real BS2 firmware therefore completed the supplied dictionary's direct-to-flash transfer, recognized `the`, saved the nonvolatile state, restarted without another transfer, reopened the exact persisted dictionary bytes, and recognized `the` again.
- This corrects attempt 5's test-fixture error without weakening the required `done` oracle.
- The active dictionary slice remains uncommitted in the verifier, its focused test, the stdio timeout diagnostic, and its focused regression. Notes remain unstaged.
- Next exact action: rerun focused tests and Ruff, then the full suite. If the only full-suite failure remains the known unrelated legacy DSP test, inspect the exact diff and commit only the four intended dictionary-slice files.

### 2026-07-20: Supplied spell dictionary slice committed

- Final focused gates pass: `6 passed`; Ruff passes on the four intended files.
- Full repository gate reports `213 passed, 1 failed`; the sole failure is the pre-existing unrelated `tests/test_synth.py::test_time_stretch_duration_modes` assertion against legacy `qns/synth/dsp.py`. Product audio ownership remains the SSI263 PCM synth, and no user-owned synth file was changed or staged.
- Inspected the complete staged patch and passed `git diff --cached --check`.
- Commit `e588017` (`Verify supplied BS2 spell dictionary`) contains exactly `tools/verify_bs2_dictionary.py`, `tests/test_bs2_dictionary.py`, `tools/stdio_process.py`, and `tests/test_stdio_process.py`.
- `notes-software-bns.md`, `CLAUDE.md`, and the user-owned synth changes remained unstaged; unrelated untracked assets remain untouched.
- Active plan status: Calsort, full Help, and `spell.dic` workflows are complete. The next phase is the existing cross-profile ROM/stdio/persistence/speech/display/serial/audio gate matrix.
- Next exact action: recover the already-recorded cross-profile matrix and identify its first unchecked gate before running or editing anything.

### 2026-07-20: Cross-profile regression matrix recovered; BSP and BSL pass

- The current automated matrix already covers all six model-owned command-loop addresses, keyboard transactions, port ownership, state formats, isolated serial round trips, display frame callbacks, SSI-263 capture/text, and PCM audio. The live phase therefore reuses the previously recorded supplied-ROM invocations rather than defining a new protocol.
- All six supplied packages remain present at their recorded paths.
- BSP live gate: supplied `bspeng.bns`, model `bsp`, canonical no-newline `a`, 30,000,000 cycles, exit `0`, retained real speech, final PC `D656`, MMU `34/00/C6`.
- BSL live gate: supplied `bsleng.bns`, model `bsl`, canonical no-newline `a`, 20,000,000 cycles, exit `0`, final PC `D656`, MMU `34/00/C6`. The zero retained frame under ordinary `a` is expected; this gate's live authority is CSI/O handshaking and command-loop progress, while BSL frame content remains covered by its device/frame tests.
- No source changes were made during these gates.
- Next exact action: run the recorded BL2 JSONL power-on `b` gate at 30,000,000 cycles and require its established nonempty 18-cell frame plus final PC `1DB8`.

### 2026-07-20: BL2 and BL4 pass; combined TNS run rejected

- BL2 exact structured gate passed: accepted power-on chord `0x03`, emitted the established nonempty 18-cell frame `[9,149,9,141,8,16,29,8,212,144,1,24,28,17,12,152,0,0]`, returned `keyboard ready`, exited `0`, and ended halted at PC `1DB8`, MMU `34/12/C6`.
- BL4 exact raw-stdio gate passed: canonical no-newline power-on `b`, nonempty 40-cell frame beginning `09 95 09 8D 08 10 1D 08`, exit `0`, halted PC `1FC7`, MMU `34/30/C6`.
- A TNS run incorrectly combined the previously separate `A1?` and grave/tilde live gates into one five-character 30,000,000-cycle run. All five main scans were accepted (`94`, `8B`, `CA`, `B9`, `B9`) and the process exited `0`, but the cycle bound ended at PC `0B21` before the final `keyboard ready`.
- That combined run is rejected as evidence because it changed the recorded timing contract; it is not treated as a product failure or a passing TNS gate.
- Next exact action: rerun the two recorded TNS live cases separately at their established 30,000,000-cycle bound: `A1?`, then grave/tilde. Each must return to `keyboard ready` and final PC `D65C`.

### 2026-07-20: Cross-profile live matrix passes

- TNS `A1?` exact gate passed separately: accepted main scans `94`, `8B`, and `CA`, returned `keyboard ready`, exited `0`, and ended at PC `D65C`, MMU `34/00/C6`.
- TNS grave/tilde exact gate passed separately: accepted main scan `B9` for both source-defined modifier sequences, returned `keyboard ready`, exited `0`, and ended at PC `D65C`, MMU `34/00/C6`.
- Current live profile results are therefore: BSP `D656` with real speech; BS2 full YMODEM dictionary import/use/exact persistence/restart; BSL `D656` with CSI/O display handshake; BL2 `1DB8` with exact nonempty 18-cell frame; BL4 `1FC7` with nonempty 40-cell frame; TNS `D65C` with complete printable scan/modifier paths and real speech.
- The same turn's full suite (`213 passed`, one known invalid legacy-DSP failure) covers the remaining matrix authorities: model state formats and rejection, raw and JSONL binary serial isolation, display callbacks, SSI-263 retained/live text, and product PCM synthesis.
- No product source changed during the live matrix. The rejected combined TNS run produced no durable artifact.
- Active plan status: cross-profile gate phase is complete. The final unchecked phase is the requirement-by-requirement audit against current product code and current live evidence.
- Next exact action: recover the objective's recorded requirement list and map each item to its current owner and authority; identify any first concrete missing boundary before declaring completion.

### 2026-07-20: Final requirement audit complete

- Objective audited: operate every supplied English firmware package as a software-only device, use standard input/output for human and machine interaction, provide software SSI-263 audio, preserve device state, and support the supplied firmware-visible files/programs.
- Firmware/package loading: `BNS.load_rom()` extracts update packages by header rather than extension. Current live gates pass BSP, BS2, BSL, BL2, BL4, and TNS from their supplied packages.
- Hardware profiles: current `BNS` owners and automated authorities cover each profile's linked command-loop/input addresses, SSI-263 base, keyboard device, display type or deliberate absence, memory/flash capacity, RTC/clock PIC, power/status/watchdog, and bank latches.
- Standard input: legacy raw keyboard/serial routing remains tested; JSONL stdio multiplexes keyboard text/raw chords and binary ASCI0/ASCI1 data. Live gates cover BSP/BSL Braille input, BS2 cold-reset/file-manager/YMODEM input, BL2/BL4 power-on Braille modes, and the complete printable TNS scan/modifier path.
- Standard output: raw serial output and JSONL binary serial events are tested; live SSI-263 phoneme events and retained/streamed text are tested; BSL/BL2/BL4 complete display frames are emitted through JSONL and the display CLI, while BSP/BS2/TNS correctly have no built-in display surface.
- Persistence: current state formats preserve shadow RAM and the model-owned flash capacity and reject wrong/unknown formats. Live authorities cover exact BS2 files/resources and external programs across restart plus live BL4 4 MiB save/reload; the CLI uses the same `Memory` owner for every profile.
- Firmware filesystem/workflows: live authorities cover create/write/read/save/reopen/delete; exact BSNAME import/entry/persisted re-entry; exact Calsort program plus message lookup; profile Help import/rename/full-content use/restart; and exact `spell.dic` import/use/restart. Calsort, message, and dictionary payloads are byte-identical across the supplied profiles; Help files are profile-specific but use the same proven firmware file/YMODEM path.
- Auxiliary inventory contains no `.ima` file. The supplied assets are six Help files, six identical dictionaries, six identical Calsort programs/messages, and three identical BSNAME programs.
- Software audio: `BNS(audio=True)` directly selects `SSI263PCMSynth`; focused authorities prove register mirroring, captured SSI-263 PCM selection, amplitude/silence, host-player queuing, and direct runtime ownership. The backend explicitly and honestly remains approximate: the available fixed captures cannot reproduce undocumented articulation, inflection, rate, duration, or filter-frequency effects. Exact die-ROM coefficient recovery remains externally blocked on unavailable higher-resolution/delayered imagery and is a separate fidelity workstream, not an unimplemented working-system I/O boundary.
- Current gates: focused dictionary/driver `6 passed`; full repository `213 passed, 1 failed`; six supplied-profile live matrix passes. The only failure is the pre-existing invalid legacy `qns/synth/dsp.py` duration assertion, outside the product PCM path and overlapping preserved user synth work.
- Git ledger: the final product commit is `e588017`; recent auxiliary commits are `25bd0b1`, `6408149`, and `e588017`. No uncommitted product slice remains. Only preserved user-owned tracked files, this unstaged handoff, and unrelated untracked research/assets are dirty.
- Completion decision: the software-only BNS objective and its ordered implementation plan are complete. Remaining exact SSI-263 timbre/parameter fidelity is explicitly separate and externally evidence-blocked; it is not silently represented as complete.

### 2026-07-20: Prior completion decision reopened; legacy DSP failure was real

- The active goal's strict audit invalidated the prior completion decision because it relied on indirect evidence for broad claims and accepted a red repository authority without inspecting its current owner.
- The user-facing `--audio` path was run directly with supplied BSP firmware: the host `sounddevice` stream opened, firmware produced 116 phonemes, the process exited `0`, and the ROM returned to PC `D656`, MMU `34/00/C6`.
- Current `qns/synth/dsp.py::time_stretch()` publicly documents and implements duration modes but had an unconditional early `return samples.copy()` that made its complete implementation unreachable. The failing test was therefore valid; calling it an invalid legacy assertion was wrong.
- Removed only that obsolete early return. The existing duration authority changed from red to green; all `20` synth tests pass and Ruff passes on `qns/synth/dsp.py`.
- Active source slice is exactly `qns/synth/dsp.py`. Preserved user-owned `qns/synth/__init__.py`, `qns/synth/ssi263_synth.py`, and their untracked formant/research files remain untouched and unstaged.
- Next exact action: run the full repository suite. If green, inspect/stage/commit only `qns/synth/dsp.py` before continuing the strict completion audit.

### 2026-07-20: DSP duration slice committed; strict audit remains active

- The full repository suite now passes: `214 passed in 11.15s`.
- Restored the tracked file's CRLF line endings after the narrow edit and verified that the final diff removed only the obsolete three-line early-return block.
- Inspected and staged only `qns/synth/dsp.py`; commit `a39cf91` (`Restore SSI-263 duration processing`) closes that source slice.
- No uncommitted product slice remains. `CLAUDE.md`, `qns/synth/__init__.py`, `qns/synth/ssi263_synth.py`, this handoff, and unrelated untracked research/assets remain unstaged and untouched by the commit.
- The earlier broad completion claim is not automatically restored by the green suite. The active final audit must still decide whether the direct evidence establishes the requested whole-system behavior for every supplied ROM/profile and its applicable auxiliary assets, rather than inferring that from BS2 plus shared code.
- Next exact action: map every explicit user requirement to a direct current authority, and run the first genuinely missing authority if the map exposes one.

### 2026-07-20: Root-level `.ima` inventory corrected

- The earlier statement that the supplied auxiliary inventory contains no `.ima` file was too broad. It is true only of `roms/NFB99`; the user-owned untracked `aicom/` research directory contains seven `.ima` files.
- Those files are 720 KiB or 1.44 MiB FAT12 DOS disk images for Aicom Accent/Messenger PCMCIA products. Their embedded documentation identifies a separate Messenger-IC card, DOS/OS2 device drivers, PCMCIA Socket Services/Card Services, and Aicom installation utilities; the accompanying board photographs are labeled `AICOM ... MESSENGER-IC`.
- They are therefore not BNS ROM packages or BNS firmware-filesystem payloads. They remain relevant research for historical speech hardware, but supporting them would mean emulating a separate PCMCIA product and is not part of making the supplied Blazie ROM profiles work through QNS standard I/O.
- No file under `aicom/` was modified. The strict BNS audit continues with the corrected scope: the six Blazie English firmware packages and the profile-matched Help/dictionary/program/resource files under `roms/NFB99`.

### 2026-07-20: Strict working-system audit closed with explicit evidence boundaries

- **Supplied firmware operation is direct, not inferred.** BSP, BS2, BSL, BL2, BL4, and TNS each passed a live run of its supplied English update package under its own model. The gates exercised real firmware keyboard acceptance and speech; BSL/BL2/BL4 additionally exercised their actual display transports and frame widths.
- **Standard I/O is direct.** Raw standard input supports firmware-paced keyboard input and either ASCI channel; raw standard output supports either ASCI channel. JSONL standard I/O multiplexes keyboard text/raw chords, arbitrary binary ASCI0/ASCI1 data, SSI-263 phoneme events, complete Braille display frames, PC watches, graceful stop, and the terminal exited event. The shipped subprocess driver directly proves binary serial round trips and graceful state persistence.
- **Persistent device state is direct at each distinct storage boundary.** BSP shadow-RAM state passes the shipped CLI round trip; BS2 2 MiB flash passes exact files/programs and restart; BL4 4 MiB flash passes save/reload; wrong sizes and unknown formats are rejected. BL2 uses the same directly tested 2 MiB BSNEW memory owner as BS2, while BSL and TNS use the same directly tested shadow-RAM owner as BSP; this is shared implementation ownership, not a claim that every firmware menu was replayed redundantly.
- **The supplied firmware-visible asset mechanism is direct.** Real BS2 firmware received exact files through ASCI probe handling and YMODEM over JSONL stdio, then used and persisted BSNAME, Calsort plus `calsort.msg`, the profile Help file, and `spell.dic` across fresh-process restarts. The Calsort/message/dictionary payloads are byte-identical across their profile directories. The English builds compile the same `FILEP.C`, `BSSPELL.C`, and `BSPROCES.ASM` owners; per-profile Help text differs, but it travels through the same host serial mechanism. This establishes that QNS exposes the required device boundary; it does not claim that every alternative firmware UI choreography was separately replayed.
- **Software speech is direct and honestly bounded.** Every live firmware gate emits retained/streamed SSI-263 phonemes; `--audio` opened the host audio stream and played the product `SSI263PCMSynth` path from supplied BSP firmware. All 64 code slots have software samples, while names, IPA, and example words are available on standard output. The fixed captured PCM is a working approximate SSI-263 backend, not exact analog/die-level parameter fidelity.
- **Testing and accountability are current.** Hypothesis is installed and used for generated native/serial authorities; the reusable subprocess, BS2 lifecycle, YMODEM, timeout-context, PC-watch, and causal ASCI diagnostics are under focused tests. The full repository gate is green at `214 passed`. The last source slice is commit `a39cf91`; no uncommitted product slice remains and user-owned tracked/untracked work remains unstaged.
- **Scope correction for Aicom images.** The root-level Aicom FAT12 images are separate DOS/OS2 PCMCIA product media, not Blazie BNS ROM/filesystem assets. Emulating Messenger-IC would be a new product objective and is not silently counted as either implemented or missing from QNS.
- Completion decision: the requested software-only Braille 'N Speak system is working for the supplied Blazie firmware profiles through standard I/O, persistent state, displays where present, and software speech. Exact SSI-263 physical fidelity and Aicom Messenger-IC emulation remain separate possible projects, not hidden qualifications on this result.

### 2026-07-20: English text-output investigation active

- New requested capability: emit actual English text for firmware speech, rather than only SSI-263 codes, names, IPA, examples, or approximate audio.
- Current runtime finding: `SSI263._speak_phoneme()` is the exact observer boundary for final chip events, but inverse phoneme recognition would be ambiguous and would lose dynamic firmware text.
- Source finding: the English firmware stores messages as ordinary NUL-terminated ASCII in `BSMESENG.C`; runtime speech can also come from filenames, editor buffers, dates, and external programs, so a fixed known-phrase dictionary is not a complete solution.
- Current function trace: `BSSPEECH.ASM::_say` receives the exact source-string address, `_get_msg` copies that ASCII into `SPBUF`, and `MSPEAK` begins the existing ASCII-to-phoneme path. This exposes exact English before translation and is the preferred authority if it can be observed consistently in each linked profile.
- Reverse-engineering findings are being recorded function-by-function in the required unstaged `NOTES.md`. No product source has been edited; the pre-existing user-owned tracked and untracked files remain untouched.
- Current blocker: linked `_say`/`SPBUF` addresses and boundary coverage across the six supplied English packages have not yet been established, and direct `SAY` is not yet proven to cover every text-speaking path.
- Next exact action: finish tracing `_say` through `MSPEAK`, document that function, then recover the linked observation address or a source-independent SPBUF write boundary before defining tests or implementation.

### 2026-07-20: Exact pre-translation English boundary proven

- `BSSPEECH.ASM::MSPEAK` handles fixed/dynamic messages already copied into `SPBUF`.
- `BSSPEECH.ASM::TALKIT` handles editor/document speech and copies the selected runtime text into the same `SPBUF`, stopping at carriage return or the firmware's 255-byte speech chunk boundary.
- Both paths join at `MFULL3`, where `HL=SPBUF`, `BC` is the exact character count, and `_SPMAIN` is called to translate ASCII into phonemes. Observing this call therefore provides actual firmware English for prompts, filenames, dynamic buffers, and document text without inverse-phoneme guessing.
- QNS already exposes live `HL` and `BC` through `Z180.get_reg`; its existing PC watch does not retain those registers or the buffer. No product edit has started.
- The local firmware-source tree has no linker map/symbol/list artifact. `_SPMAIN` is implemented by `SPTST.C`, and the call is issued from `BSSPEECH.ASM`; linked call-site recovery must come from the supplied ROMs or a current executable trace.
- Current blocker: the six linked English package call sites and the logical-to-physical buffer read at that instant are not yet proven.
- Next exact action: document `SPTST.C::spmain`, then locate the `_SPMAIN` call site in one supplied ROM using the source-defined instruction neighborhood and verify the live `HL`/`BC` buffer contents before generalizing to profile-linked addresses.

### 2026-07-20: First linked English boundaries recovered

- `SPTST.C::spmain` confirms that `_SPMAIN` consumes the common ASCII speech buffer and produces the double-buffered phoneme stream; there is no additional English source after this boundary.
- The source-defined `MFULL3` byte neighborhood occurs uniquely in BSP at `0xBC98`: `SPBUF=0xD657`, `_SPMAIN` call site `0xBCA8`, `_SPMAIN=0x5915`, followed by `SPON=0x0814`.
- The matching BS2 boundary is `SPBUF=0xD658`, `_SPMAIN` call site `0xBCA7`, `_SPMAIN=0x58FD`, followed by `SPON=0x0871`.
- The matching TNS boundary is `SPBUF=0xD65D`, `_SPMAIN` call site `0xAD7E`, `_SPMAIN=0x58E5`, followed by `SPON=0x08EC`.
- The same short signature correctly does not match BSL, BL2, or BL4 because their `B_LITE`/`B_LITE_40` builds include the source-defined Braille display and speech-enable instructions between buffer setup and `_SPMAIN`.
- No product source has been edited. `NOTES.md` and this handoff remain unstaged.
- Current blocker: none for the three recovered profiles; the Braille Lite signature and live `HL`/`BC` buffer authority remain.
- Next exact action: derive the literal Braille Lite `MFULL3` signature from the source block, recover BSL/BL2/BL4 call sites, then live-verify one captured buffer before opening tests.

### 2026-07-20: All six linked English boundaries recovered

- The Braille Lite source-defined sequence is present uniquely in each remaining ROM. It adds `_TNSBM` speech-enable testing before the H-chord-save call and `_SPMAIN`.
- BSL: `SPBUF=0xD657`, `_SPMAIN` call site `0xAD9A`, `_SPMAIN=0x57BA`, followed by `SPON=0x0896`.
- BL2: `SPBUF=0xD658`, `_SPMAIN` call site `0xBC61`, `_SPMAIN=0x57A6`, followed by `SPON=0x08E0`.
- BL4: `SPBUF=0xD65E`, `_SPMAIN` call site `0xAD95`, `_SPMAIN=0x579E`, followed by `SPON=0x0917`.
- Together with the prior BSP/BS2/TNS findings, all six supplied English packages now have exact call sites grounded in the same source instruction sequence and strengthened by the immediately following linked `SPON` call.
- No implementation slice is open. The current worktree changes from this request are only unstaged investigation notes.
- Current blocker: no live authority yet proves that observing the call instruction through QNS exposes unchanged `HL`, `BC`, and ASCII buffer bytes.
- Next exact action: run BSP until the exact `0xBCA8` call instruction, capture live `HL`/`BC`, translate `HL` through the current MMU, and compare those bytes with the subsequent SSI-263 speech.

### 2026-07-20: English output contract established red

- The implementation contract is now tested across all six exact linked call-site/SPBUF pairs. It requires one English callback event containing `BC` bytes read from the high-common `HL=SPBUF` buffer and suppresses duplicate observation of the same instruction fetch.
- CLI authorities require `--speech english` to retain and join firmware text chunks and `--speech-stream english` to emit each chunk before `run()` returns.
- The structured stdio authority requires a `{"device":"speech","text":"..."}` event while retaining the existing per-phoneme speech events.
- Focused result is the expected red state: `10 failed`. Six fail because `BNS.__init__` has no `english_callback`; the unrelated-instruction test fails at the same absent contract; JSONL has no callback; and both CLI tests fail because `english` is not an accepted choice. No different failure was exposed.
- Active source slice currently changes only `tests/test_bns.py` and `tests/test_ssi263.py`; investigation records remain unstaged and outside the commit slice.
- Current blocker: none.
- Next exact action: implement the callback, exact linked boundary table, same-instruction deduplication, high-common address read, and CLI/JSONL wiring only in `qns/bns.py`, then rerun the exact focused authority.

### 2026-07-20: First live hook premise rejected and corrected

- Implemented the narrow tested surface in `qns/bns.py`: optional English callback, six exact linked boundaries, high-common MMU buffer reads, same-fetch deduplication, `--speech english`, `--speech-stream english`, and JSONL speech text events.
- The first supplied BSP live run produced 116 phonemes but no English event. That run is rejected; focused synthetic tests alone did not establish the real callback phase.
- The existing native PC watch then proved the linked call site is correct: BSP entered `0xBCA8` at cycle `1,443,916` with `CBAR=C6`.
- Proven cause: during opcode fetch, the Python memory callback cannot rely on `cpu.instruction_pc` already equaling the instruction being fetched. The callback's own physical `addr` is the exact fetch surface; at these bank-zero linked sites it equals the recovered call site.
- Corrected only that predicate from `instruction_pc == call_site` to `addr == call_site`, while retaining exact `HL==SPBUF`, `1 <= BC <= 255`, common-page, MMU, and same-cycle guards. The focused authority returns green at `10 passed`.
- Active slice is `qns/bns.py`, `tests/test_bns.py`, and `tests/test_ssi263.py`. Investigation notes remain unstaged; user-owned synth/research files remain untouched.
- Current blocker: the corrected hook has not yet passed the supplied-ROM live gate.
- Next exact action: rerun supplied BSP with `--speech-stream english`; require real English chunks before accepting the hook, then test JSONL and at least one differently linked profile.

### 2026-07-20: Second live hook premise rejected; CPU MMU is authoritative

- Moving capture to the source-defined instruction immediately after `LD HL,SPBUF` correctly exposed live BSP `HL=0xD657` and `BC=0x0029`, before the later H-chord-save call clobbers those registers. All six model boundaries were moved to the equivalent point.
- The next BSP run still emitted no English. A second exact-boundary diagnostic proved why: the `Memory` object's cached MMU fields remained reset at `CBR=00/CBAR=F0`, while the executing native CPU's already-proven state is `CBR=34/CBAR=C6`.
- Z180 internal MMU register writes are owned by the CPU and do not traverse QNS's external I/O-bus setters. Therefore `Memory.cbr/cbar` are not a live translation authority; using them was wrong.
- Removed the diagnostic and changed the capture mapping to use `cpu.cbr` and `cpu.cbar`. The synthetic boundary CPUs now expose those exact authoritative values.
- Neither failed live attempt is accepted as English-output evidence. The implementation slice remains uncommitted.
- Current blocker: none; the CPU-MMU correction has not yet been rerun through focused and live authorities.
- Next exact action: rerun the ten focused tests, then the supplied BSP live stream. Accept only actual English text emitted before its corresponding phonemes.

### 2026-07-20: BSP/JSONL pass; BS2 exposes segmented-length defect

- Focused English authorities pass `10 passed` after switching address translation to `cpu.cbr/cbar`.
- Supplied BSP live gate now passes: `--speech-stream english` emits `Braille 'n Speak ready`, `help`, `1`, and `page`; the same run emits 116 phonemes, returns to `D656`, and retains MMU `34/00/C6`.
- BSP structured stdio directly emits `{"device":"speech","text":"Braille 'n Speak ready"}` before the corresponding non-pause phonemes, while preserving all per-phoneme events and terminal system event.
- Differently linked BSL also reaches its recovered capture site and emits text chunks (`h`, `1`, `p`) while returning to `D656`; this proves the table is not BSP-only.
- The BS2 normal-boot gate is not accepted: it emitted only `initialize fla`, while its 84 phonemes are the already-established full `Initialize flash system. Enter Y or N.` question.
- This proves `BC` is not universally the full final-buffer length. The `_say_part`/message-assembly path can retain a segment count while `SPBUF` contains a longer NUL-terminated utterance. Exact English must follow the buffer's source-defined NUL terminator, not truncate to `BC`.
- Current blocker: the full BS2 SPBUF bytes at the capture point have not yet been observed, so the NUL-termination correction is not yet implemented.
- Next exact action: instrument only BS2's exact capture fetch to report `BC` and the first NUL-terminated SPBUF bytes; if the complete question is present, replace the length assumption with the source-defined 255-byte NUL bound and add a regression before rerunning live gates.

### 2026-07-20: Complete NUL-terminated English utterances pass live

- Exact BS2 diagnostic showed `BC=0x0E` while SPBUF contained `initialize flash system? enter y or n ?\0`. This directly confirms that `_say_part` leaves a segment count but assembles the complete utterance in the source-defined NUL-terminated buffer.
- Strengthened the six-profile boundary authority so `BC=4` while the buffer contains `enter file command\0`; the old implementation failed all six by emitting only `ente`.
- Removed the diagnostic. Production now uses `BC` only as the source-defined nonempty/bounded boundary guard and reads at most the 256-byte SPBUF through its NUL terminator. It emits nothing if no terminator exists within that fixed buffer.
- Focused English authorities pass `10 passed`.
- Corrected supplied BS2 live gate passes: exact English output is `initialize flash system? enter y or n ?`; the same process emits 84 phonemes, halts at `1BDA`, and reports MMU `34/1E/C6`.
- Accepted live coverage now includes BSP retained/streamed text, BSP JSONL ordering before phonemes, BSL's separately linked boundary, and BS2's assembled multi-part prompt.
- Active source slice remains exactly `qns/bns.py`, `tests/test_bns.py`, and `tests/test_ssi263.py`. No diagnostic print remains. Notes and user-owned files remain unstaged.
- Current blocker: none.
- Next exact action: run Ruff and the complete BNS/SSI263/stdio focused modules, then the full repository suite. After each pass, reread this plan before diff/commit closure.

### 2026-07-20: English slice passes complete authorities

- The complete focused modules pass: `123 passed` across `tests/test_bns.py`, `tests/test_ssi263.py`, `tests/test_stdio.py`, and `tests/test_stdio_process.py`.
- Scoped Ruff passes for `qns/bns.py`, `tests/test_bns.py`, and `tests/test_ssi263.py` with `All checks passed!`.
- The full repository suite passes `223 passed in 11.44s`.
- The reverse-engineering task review in `NOTES.md` is complete, and its stale intermediate premises were corrected to the final capture-boundary, CPU-MMU, and NUL-terminated-buffer authorities.
- `git diff --check` passes for the exact active slice: `qns/bns.py`, `tests/test_bns.py`, and `tests/test_ssi263.py`.
- Line-ending inspection reports mixed baseline and worktree endings in `qns/bns.py` and `tests/test_bns.py`; the next closure check is limited to distinguishing semantic changes from touched-hunk line-ending churn before staging.
- Investigation records and this handoff remain unstaged. User-owned synth and research files remain untouched.
- Current blocker: none.
- Next exact action: reconcile only misleading test naming and any proven touched-hunk line-ending churn, rerun the authorities affected by that cleanup, then stage and commit exactly the three active-slice files.

### 2026-07-20: English slice ready for Git closure

- Renamed the test parameter from misleading `call_site` to exact `capture_site`, removed its unused synthetic instruction PC, and removed the test write to the non-authoritative `Memory` MMU cache.
- The post-cleanup focused authority passes `123 passed in 5.05s`; scoped Ruff remains clean.
- The post-cleanup full repository authority passes `223 passed in 11.27s`.
- Branch is `master`. The semantic diff is exactly the intended three files and reports 200 insertions and 11 deletions when end-of-line-only differences are ignored.
- `git diff --check` is clean. Inspection confirms the mixed-ending baseline caused only eight touched-line representations; there is no whole-file line-ending rewrite to reconcile.
- No implementation or verification task remains unchecked. Investigation records and this handoff remain unstaged, and all unrelated user-owned work remains outside the slice.
- Current blocker: none.
- Next exact action: stage exactly `qns/bns.py`, `tests/test_bns.py`, and `tests/test_ssi263.py`; inspect the cached diff and status; commit the kept slice.

### 2026-07-20: Exact firmware English speech committed

- Commit `82e82ca` (`Emit exact firmware English speech`) contains exactly `qns/bns.py`, `tests/test_bns.py`, and `tests/test_ssi263.py`.
- Final authorities are `123 passed` for the focused BNS/SSI263/stdio modules, scoped Ruff clean, and `223 passed` for the full repository suite.
- Supplied-ROM gates remain accepted: BSP emits `Braille 'n Speak ready`; BSL reaches its separately linked capture boundary; BS2 emits the complete `initialize flash system? enter y or n ?`; BSP JSONL emits the English text event before the corresponding phoneme events.
- English output is exact pre-translation firmware text from the bounded NUL-terminated SPBUF. Direct chip sounds that never pass through that firmware buffer intentionally emit no invented English.
- This handoff and `NOTES.md` remain unstaged as required. The status after commit contains only pre-existing notes, synth/research work, ROMs, and other untracked user artifacts; none entered the commit.
- Current blocker: none. The requested English-output slice is complete.
- Next exact action: none for this slice.

### 2026-07-20: Newly supplied updater corpus inventory started

- User direction is to support all additional old-version updaters now present under `roms`; this is the active full objective.
- The newly visible corpus is under `roms\NFB99` and contains product trees `BL2ENG`, `BL4ENG`, `BS2ENG`, `BSLENG`, `BSPENG`, and `TNSENG`, with updater/readme assets including `update97.txt`, `update98.txt`, and `update99.txt`. Five trees contain `.bns` firmware/update packages; `TNSENG` contains `tnseng.tns` rather than a `.bns` image.
- Existing code already recognizes BNS update packages at firmware offset `0x3000`, but that does not yet prove that every newly supplied old updater version has been extracted or runs under its correct hardware profile.
- Branch is `master`, 40 commits ahead of `origin/master`. The worktree contains pre-existing user-owned tracked synth/notes changes and extensive untracked artifacts including the whole `roms` tree; none has been modified, staged, or committed for this objective.
- Current blocker: the complete old-version updater payload inventory and the repository's exact established extraction/runtime workflow have not yet been derived from the current artifacts, so no source slice is authorized yet.
- Next exact action: inspect the updater text/package structure and current extraction/runtime owners, enumerate every distinct embedded updater version, and identify the exact per-artifact run gate before opening the first implementation slice.

### 2026-07-20: Six system updater packages and extraction contract proven

- The complete system-updater set is the six package files larger than 250,000 bytes: `bspeng.bns`, `bs2eng.bns`, `bsleng.bns`, `bl2eng.bns`, `bl4eng.bns`, and `tnseng.tns`. Each has the same `BNS` package magic at bytes 2 through 4 and a distinct SHA-256 hash.
- Smaller `bsname.bns` and `calsort.bns` files are supplied external programs, not system firmware updaters; repeated copies are byte-identical. They remain outside this extraction inventory.
- The root `roms\bspeng.bns` is byte-identical to `roms\NFB99\BSPENG\bspeng.bns`, so it is not a seventh updater.
- The established current workflow in `prompts\load-all-rom-banks.md`, `tools\extract_firmware.py`, and `reports\load-all-rom-banks-report.md` extracts from exact package offset `0x3000`, truncates or pads to four 64 KiB banks, and writes `roms\extracted\<stem>_full.bin`. `qns.bns` explicitly accepts 256 KiB pre-extracted images.
- Existing extracted artifacts cover only BSP: `bspeng_full.bin` is the current four-bank output, and the older `bspeng.bin` is the obsolete single-bank extraction retained from the preceding workflow stage.
- Current blocker: none. The exact mutation is now bounded to generating the five missing four-bank images plus deterministically regenerating BSP through the same command, followed by one correct-profile runtime gate per extracted image.
- Next exact action: run `tools\extract_firmware.py` once for each of the six proven updater packages, then verify output size/content against the package extraction contract before any runtime run.

### 2026-07-20: Updater target correction

- The user corrected the target: this request concerns the new `.exe` updater files, not the existing `.bns`/`.tns` packages under `roms\NFB99`.
- The preceding NFB99 extraction direction was wrong and is abandoned. No further NFB99 extraction or runtime work is authorized by this request.
- One wrong command targeting `bl2eng.bns` was interrupted before its result was returned. Whether it created `roms\extracted\bl2eng_full.bin` is not yet known; inspect only and do not delete or alter it without user direction.
- Current blocker: none. The correct updater executable set must be inventoried from the new `.exe` files and processed through the executable extraction/runtime contract.
- Next exact action: inventory the new `.exe` files, their formats, timestamps, and hashes; locate the existing executable extraction owner; then extract and run each executable updater only.

### 2026-07-20: Executable container recovery in progress

- The correct corpus is 11 distinct updater executables in `reports`: `M20_V45.exe`, `M40_V45.exe`, `m20.exe`, `m40.exe`, `tlt.exe`, `tns.exe`, `blt18.exe`, `blt40.exe`, `blt2000.exe`, `bns640.exe`, and `bns2000.exe`.
- 7-Zip reads the inspected files without executing them. `M20_V45.exe`, `M40_V45.exe`, `m20.exe`, and `bns2000.exe` are x86 WinZip self-extracting PE/ZIP containers; `blt18.exe` is an older direct ZIP self-extractor.
- Proven system payloads are `M20ENU-U.BNS` (481,798 bytes), `M40ENU-U.BNS` (481,798 bytes), `BLM20ENU.BNS` (371,795 bytes), `BS2ENG.BNS` (274,218 bytes), and `BSLENG.BNS` (274,374 bytes). Smaller bundled `.bns` members are external applications and are not firmware updater targets.
- The RE protocol requires each recovered executable boundary to be documented in `NOTES.md` before inspecting the next one; those entries are current.
- The interrupted wrong NFB99 command created `roms\extracted\bl2eng_full.bin`. It remains untouched and outside the corrected task pending user direction.
- Current blocker: none. Six executable manifests remain uninspected, followed by payload extraction and format/runtime mapping.
- Next exact action: list `m40.exe`, record its system payload in `NOTES.md`, and continue one executable at a time through the remaining corpus.

### 2026-07-20: All executable system payloads identified

- The complete mapping is now proven by read-only 7-Zip manifests and recorded in `NOTES.md`: `M20_V45 -> M20ENU-U.BNS`, `M40_V45 -> M40ENU-U.BNS`, `m20 -> BLM20ENU.BNS`, `m40 -> BLM40ENU.BNS`, `tlt -> TLTENU.BNS`, `tns -> TNSENG.TNS`, `blt18 -> BSLENG.BNS`, `blt40 -> BL4ENG.BNS`, `blt2000 -> BL2ENG.BNS`, `bns640 -> BSPENG.BNS`, and `bns2000 -> BS2ENG.BNS`.
- All 11 containers can be read by 7-Zip without executing the Windows updater. Ten are WinZip self-extracting PE files; `blt18.exe` is an older direct ZIP self-extractor with a 23,102-byte stub.
- The six classic payloads are later 2003 builds of the already modeled BSP/BS2/BSL/BL2/BL4/TNS families. The five Millennium/Tiny Lite payloads are structurally larger and require format and hardware-profile proof before any existing model may be assigned.
- No correct updater payload has been extracted yet. No QNS source slice is open. The only generated file remains the out-of-scope interrupted `bl2eng_full.bin`, preserved unchanged.
- Current blocker: none.
- Next exact action: extract each of the 11 named system payload members into a dedicated executable-updater corpus, verify its archive CRC/size/header, and document the exact package/firmware boundary before attempting runtime.

### 2026-07-20: Executable payload extraction underway

- Provenance-preserving output folders are `roms\<executable-stem>` so distinct old updater revisions and the case-insensitive `BSPENG.BNS` collision remain separated.
- `M20_V45.exe`, `M40_V45.exe`, and `m20.exe` have been extracted and individually verified against their archive-manifest size plus a recorded SHA-256/header in `NOTES.md`.
- All three Millennium payloads begin with `18 18 BNS`, contain header fields through offset `0x19`, and begin executable-looking Z180 bytes at offset `0x1A`. This contradicts blindly applying the classic `0x3000` extraction rule; no loader change has been made.
- `m40.exe` has just extracted `BLM40ENU.BNS` to `roms\m40` at the manifested 371,794-byte size, but its hash/header verification and `NOTES.md` entry have not yet been performed.
- Current blocker: none. Seven executable payloads remain unextracted after `m40` verification.
- Next exact action: verify and document `roms\m40\BLM40ENU.BNS`, then continue extraction one executable at a time.

### 2026-07-20: Seven payloads fully extracted and verified

- Fully extracted, size/hash/header verified, and documented in `NOTES.md`: `M20_V45`, `M40_V45`, `m20`, `m40`, `tlt`, `tns`, and `blt18` (seven total).
- The five Millennium/Tiny Lite packages inspected so far share `18 18 BNS`, a 26-byte header, and executable-looking bytes at offset `0x1A`; this is not the classic `0x3000` container contract.
- The 2003 TNS and BSL packages share the classic `18 0C BNS` updater-program header and are distinct revisions from their NFB99 counterparts.
- `blt40.exe` has just extracted `BL4ENG.BNS` to `roms\blt40` at the manifested 274,355-byte size, but hash/header verification and its `NOTES.md` entry remain next.
- No QNS source change is open. Runtime/model mapping has not begun because extraction is not complete.
- Current blocker: none. Three executable payloads remain after completing `blt40` verification: `blt2000`, `bns640`, and `bns2000`.
- Next exact action: verify and document `roms\blt40\BL4ENG.BNS`, then extract and verify the remaining three payloads one at a time.

### 2026-07-20: All 11 executable updater payloads extracted

- Every named system payload is now extracted under `roms\<executable-stem>` and individually verified for manifested size, SHA-256, and leading package bytes. `NOTES.md` contains one extraction record per executable as required by the RE protocol.
- The complete classic runtime family is `bns640/BSPENG.BNS -> bsp`, `bns2000/BS2ENG.BNS -> bs2`, `blt18/BSLENG.BNS -> bsl`, `blt2000/BL2ENG.BNS -> bl2`, `blt40/BL4ENG.BNS -> bl4`, and `tns/TNSENG.TNS -> tns`.
- Those six 2003 packages retain the established classic updater-program shape and are 21, 41, or 64 bytes larger than their corresponding NFB99 packages. They are distinct revisions, not copies.
- The five Millennium/Tiny Lite payloads (`M20_V45`, `M40_V45`, `m20`, `m40`, `tlt`) share a different `18 18 BNS` header and begin executable-looking bytes at offset `0x1A`; blindly stripping `0x3000` would be an unsupported substitution.
- No QNS source slice is open. Runtime verification has not started.
- Current blocker: none for the classic family; the Millennium/Tiny Lite package/hardware contract remains to be recovered after the classic runtime gates.
- Next exact action: run each of the six classic 2003 payloads through its existing exact hardware profile with a bounded cycle/stat/speech gate, document each result, and correct only proven old-revision divergences.

### 2026-07-20: All six classic 2003 updater revisions execute

- `bns640/BSPENG.BNS --model bsp`: 20,000,000 cycles, 116 phonemes, PC `D656`, MMU `34/00/C6`.
- `bns2000/BS2ENG.BNS --model bs2`: 20,000,000 cycles, 88 phonemes, stable initialization halt at PC `1BF1`, MMU `34/24/C6`.
- `blt18/BSLENG.BNS --model bsl`: 20,000,000 cycles, seven pause phonemes, display-handshake/command region PC `D656`, MMU `34/00/C6`.
- `blt2000/BL2ENG.BNS --model bl2`: 20,000,000 cycles, 10 phonemes, stable initialization halt at PC `1DE6`, MMU `34/30/C6`.
- `blt40/BL4ENG.BNS --model bl4`: 20,000,000 cycles, 10 phonemes, stable initialization halt at PC `1FE8`, MMU `34/2A/C6`.
- `tns/TNSENG.TNS --model tns`: 20,000,000 cycles, 118 phonemes, PC `D65C`, MMU `34/00/C6`.
- Every run used the direct extracted executable payload; QNS recognized the classic package and stripped the exact `0x3000` prefix. No illegal opcode, reset loop, loader error, or unsupported peripheral blocked execution.
- Exact-English observers remain silent because their linked addresses are for the later NFB99 images. That is a revision-specific instrumentation gap, not evidence that the classic images fail to run.
- No classic-family source change is required for bounded execution. Full BL2/BL4 cold-dialogue advancement remains available through their existing power-on-input path but was not substituted for the loader/profile gate.
- Current blocker: none. The remaining unsupported scope is exactly the five Millennium/Tiny Lite payloads.
- Next exact action: establish the `18 18 BNS` package layout and raw firmware mapping from the five extracted images before selecting or adding any hardware profile.

### 2026-07-20: Millennium updater executable contract entered

- Strings in `M20ENU-U.BNS` explicitly identify it as the Millennium 20 version 4.50 updater and contain the validation, side A/B selection, flash-update, and warm-reset workflow. `BLM20ENU.BNS` identifies the earlier Millennium 20 update; `TLTENU.BNS` identifies Type Lite. Normal product strings follow updater-specific strings in each payload.
- `C:\Users\Q\src\bns` contains the classic product sources but no Millennium 20/40 or Type Lite build/project, so it cannot supply the missing package or hardware contract.
- The `18 18` header's initial JR lands exactly at file offset `0x1A`, where Z180 code begins. Treating the file as classic firmware at `0x3000` is disproven; the updater itself must reveal the embedded ROM boundary and programming algorithm.
- The Ghidra MCP correctly rejected direct raw `.BNS` import because no loader identifies the format. A lossless Intel HEX representation was created in the OS temp directory with file offset zero mapped to `0x0FE6`, making file offset `0x1A` land at logical address `0x1000` as required by the updater entrypoint. It is queued for Ghidra analysis; no repository artifact or source file was added.
- Current blocker: the queued Ghidra import has not yet appeared as an analyzed project binary, so no updater function has been decompiled or documented.
- Next exact action: wait for/import the Intel HEX analysis, verify the entrypoint bytes at `0x1000`, decompile the first flash/update owner, and document it in `NOTES.md` before following its next callee.

### 2026-07-20: Ghidra address-space correction

- The MCP background import never produced a program. Headless Ghidra with the explicit `z180:LE:16:default` processor then rejected the full Intel HEX for the correct reason: the 481,798-byte updater spans multiple physical banks, while the processor program space is 16-bit and the linear representation wrapped/overwrote addresses.
- The failed full import produced no analyzed program and no decompilation evidence.
- A corrected temporary front-bank image now contains exactly the first 61,466 file bytes, the maximum non-wrapping window when file offset zero maps to logical `0x0FE6`. Its Intel HEX representation therefore maps the updater entry at file offset `0x1A` to logical `0x1000` and ends at `0xFFFF` without overlap.
- The temporary decompile script and headless project are outside the repository. No QNS source or extracted updater artifact changed.
- Current blocker: none; the corrected front-bank image has not yet been imported or decompiled.
- Next exact action: import the corrected front-bank HEX into the temporary Z180 Ghidra project, verify `0x1000`, decompile the updater entry, and immediately document that function in `NOTES.md`.

### 2026-07-20: Millennium banked source reader recovered

- Corrected Z180 headless analysis now succeeds. `NOTES.md` documents the wrapper entry at `0x1000`, normal updater workflow at `0x208B`, and source-byte owner at `0x1F27` before following each next function as required by the RE protocol.
- The updater is an external banked program: entry sets `CBAR=0x41`, preserves BBR/CBR context, initializes runtime state, and dispatches to the normal workflow at `0x208B`.
- The normal workflow performs identity/destructive-update prompts, validation, side selection, device preparation, erase/program/verify loops, and restart/error handling. It seeds its source from globals `0x3E74`, `0x3E76`, and `0x3E78`.
- Exact `0x1F27` behavior is: set `CBR` from the high byte of the source bank word, then return the byte at logical `0xF000 | 12-bit-offset`. The caller increments the bank on 4 KiB rollover. This proves the embedded image is a contiguous banked source sequence, not a classic fixed-offset block and not decoded by the byte reader.
- Current blocker: the initializer/xrefs that assign the source tuple have not yet been recovered, so the exact updater-file offset and image length remain unknown.
- Next exact action: list all references to `0x3E74`, `0x3E76`, and `0x3E78`, decompile the function that initializes them, and document the exact tuple before extracting any Millennium ROM bytes.

### 2026-07-20: Source builder corrects Millennium boundary premise

- Ghidra xrefs show only reads of the source tuple; its naive mapped bytes are `0xFF`. The tuple is supplied by the external-program load/runtime contract rather than a literal updater initializer.
- The exact contract is present in `C:\Users\Q\src\bns\update\BEUPDATE.C` and `BUPDATE.C`. `BEUPDATE` copies the updater program, pads to the configured 4 KiB-aligned `IMAGE_OFFSET`, appends raw firmware unchanged, then writes the firmware's 32-bit little-endian length and 16-bit CRC in the six bytes immediately before the image.
- `BUPDATE` asks the host API for the physical address corresponding to logical `IMAGE_OFFSET + 0x1000`, reads length/CRC at `image-6`, validates every appended byte, and programs those bytes verbatim.
- Every supplied update project after the recorded April 1999 change defines `IMAGE_OFFSET=0x3000`. The Millennium header's additional 12 bytes belong to the external updater program after the standard 14-byte header; they do not move the appended image.
- Therefore the earlier claim that Millennium/Tiny Lite could not use `0x3000` was wrong. Existing QNS extraction may already be correct, but it remains unproven until each file's own `0x2FFA` length/CRC metadata matches its appended bytes.
- Current blocker: none.
- Next exact action: inspect and validate the six-byte metadata plus CRC for all five Millennium/Tiny Lite payloads; only then run the appended firmware and determine missing hardware profiles.

### 2026-07-20: Four Millennium image boundaries proven

- A temporary diagnostic implements the exact `BEUPDATE.C::crc_byte` algorithm and scans only source-required 4 KiB-aligned candidates whose preceding 32-bit length equals the remaining file size.
- `M20ENU-U.BNS`: unique `IMAGE_OFFSET=0x8000`, length 449,030, stored/recomputed CRC `D09A`.
- `M40ENU-U.BNS`: unique `IMAGE_OFFSET=0x8000`, length 449,030, stored/recomputed CRC `A03E`.
- `BLM20ENU.BNS`: unique `IMAGE_OFFSET=0x7000`, length 343,123, stored/recomputed CRC `5E56`.
- `BLM40ENU.BNS`: unique `IMAGE_OFFSET=0x7000`, length 343,122, stored/recomputed CRC `4394`.
- These results prove QNS's fixed `0x3000` extraction is wrong for all four Millennium packages. They also prove the appended images are raw, intact, and distinct.
- No product source change is open. Type Lite remains the only unscanned variable-offset payload.
- Current blocker: none.
- Next exact action: run the same exact length/CRC candidate authority on `TLTENU.BNS`, document its boundary, then design one loader correction that follows package metadata rather than product-name special cases.

### 2026-07-20: All five variable updater boundaries proven

- `TLTENU.BNS` has the same independently validated contract: unique `IMAGE_OFFSET=0x7000`, length 342,832, stored/recomputed CRC `CCAA`.
- The five remaining executable payloads therefore divide exactly into `0x8000` (`M20_V45`, `M40_V45`) and `0x7000` (`m20`, `m40`, `tlt`) packages. The boundary is package metadata, not a product-name convention.
- The same diagnostic reproduces the classic contract for both an NFB99 BSP package and the newly extracted `bns640/BSPENG.BNS`: unique `IMAGE_OFFSET=0x3000`, with matching stored/recomputed CRCs `2BAF` and `5DA7` respectively.
- QNS source and tests are clean for the loader slice. The tracked handoff remains intentionally unstaged; extracted updater artifacts remain untracked.
- Current blocker: none.
- Next exact action: replace the loader's fixed `0x3000` strip with exact length/CRC metadata discovery, add direct authorities for `0x3000`, `0x7000`, and `0x8000`, run the loader tests, and either commit the kept slice or restore it before any hardware-profile work.

### 2026-07-20: Metadata-driven loader slice passes its targeted gate

- `qns/bns.py::BNS.load_rom` now scans only 4 KiB-aligned candidates, requires the preceding little-endian length to equal the exact remaining package size, and accepts only the unique candidate whose stored CRC matches the exact `BEUPDATE.C::crc_byte` calculation.
- The fixed `0x3000` strip and 256 KiB truncation are removed. `Memory.load_rom` already extends its bytearray when an appended firmware image exceeds its initial 256 KiB allocation, so no memory interface, adapter, or model-name exception was introduced.
- `tests/test_bns.py` now supplies direct synthetic authorities for `0x3000`, `0x7000`, and `0x8000`, using a 262,295-byte firmware image so the old truncation would fail. A corrupted CRC is explicitly rejected instead of loading updater code as ROM.
- Targeted gate: `uv run pytest tests/test_bns.py -k "load_rom"` passed all 4 selected tests in 0.90 seconds.
- The shipped module entrypoint is confirmed as `uv run python -m qns.bns ROM --model ... --cycles N --stats`; its current model choices remain `bsp`, `bs2`, `bsl`, `bl2`, `bl4`, and `tns`.
- Current blocker: none. The source slice is uncommitted and must be validated against the five real packages plus the repository test/lint gate before it may be kept.
- Next exact action: invoke the current CLI against each real variable-offset package for a minimal bounded load, verify the reported offsets and full firmware sizes, then run the repository tests/lint and commit only `qns/bns.py` plus `tests/test_bns.py` if all gates pass.

### 2026-07-20: Loader slice validated and staged exactly

- Direct one-cycle CLI loads now report `0x8000` and 449,030-byte ROMs for both `M20_V45/M20ENU-U.BNS` and `M40_V45/M40ENU-U.BNS`.
- Direct one-cycle CLI loads report `0x7000` and complete 343,123-byte, 343,122-byte, and 342,832-byte ROMs for `m20/BLM20ENU.BNS`, `m40/BLM40ENU.BNS`, and `tlt/TLTENU.BNS` respectively.
- Each run began at physical ROM byte zero, executed one instruction without a loader exception, and showed a backing ROM length equal to the full appended image. These are loader authorities only; the temporary default `bsp` profile is not a claimed hardware assignment.
- Full gate: `uv run pytest` passed all 227 tests in 11.49 seconds. `uv run ruff check qns\\bns.py tests\\test_bns.py` passed. `git diff --check` passed.
- Exactly `qns/bns.py` and `tests/test_bns.py` are staged. `notes-software-bns.md`, `NOTES.md`, and the extracted `roms/` corpus are not staged.
- Current blocker: none.
- Next exact action: commit the staged loader slice, then begin a fresh clean source slice to derive the actual Millennium 20/40 and Type Lite hardware profiles from their running firmware behavior.

### 2026-07-20: Loader committed; Millennium 20 hardware blocker isolated

- Loader support was committed as `e4e0741` (`Support variable-offset BNS update packages`). The new hardware-profile slice began with clean `qns/bns.py` and `tests/test_bns.py`; the handoff/corpus remain unstaged.
- `M20_V45/M20ENU-U.BNS` executes one million cycles without an illegal opcode or reset, reaching PC `5FBD` with MMU `77/00/C7`, but produces no speech.
- At 20 million cycles it remains active near PC `5FCC`, has performed 1,046,191 memory writes, still has zero phonemes, and retains MMU `77/00/C7`. This is a live wait/spin state under the temporary default `bsp` profile, not a successful Millennium hardware assignment.
- Early external writes are `80=01`, `80=39`, and `88=80`; later repeated `F0/F1` accesses dominate. A short default-profile trace alone does not establish which are Z180-internal versus board peripherals.
- Requesting `--display` with the default `bsp` profile correctly fails because BSP has no built-in display. That failed command is evidence of the missing profile and was not treated as a runtime gate.
- Current blocker: the condition polled by the firmware loop around logical PC `5FCC` is not yet identified, so assigning an existing keyboard/display/speech profile would be unsupported.
- Next exact action: map the first 64 KiB of the validated M20 firmware into temporary Z180 analysis, decompile the function containing `5FCC`, document that function in `NOTES.md`, and use its actual I/O dependency to define the first required Millennium peripheral behavior.

### 2026-07-20: Millennium 20 trace and decompile setup narrowed

- A complete one-million-cycle I/O trace was written only to the OS temp directory. The exact distinct firmware-visible ports are `80`, `88`, `F0`, `F1`, and `F2`; no SSI-263 access occurs under the default profile.
- Early writes are `80=01`, `80=39`, `88=80`. The active runtime region then repeatedly writes zero to `F0` and `F1`; `F2` is initialized to `01`. This makes the `F0`-family owner, not a guessed display or keyboard class, the next decision-changing target.
- The validated `0x8000` package boundary was used to extract exactly the first 65,536 firmware bytes to `C:\Users\Q\AppData\Local\Temp\m20-v45-front.bin`. The extraction script and image are outside the repository.
- A temporary Ghidra script is ready to decompile the analyzed function containing logical PC `5FCC`. The initial headless invocation exited 1 before import because `C:\Users\Q\AppData\Local\Temp\qns-millennium-ghidra` did not exist; it produced no program and no decompilation evidence.
- Current blocker: the temporary Ghidra project parent directory must exist before the exact import can run.
- Next exact action: create that one OS-temp directory, rerun the same Z180 raw-binary import/decompile at `5FCC`, and document the recovered function in `NOTES.md` before following any callee or changing QNS.

### 2026-07-20: Millennium 20 reset/context owners recovered

- The corrected temporary Ghidra import succeeded. The frequently sampled function at `0x5FA0` is a BBR bank-switch/runtime return helper, not a peripheral wait loop; `NOTES.md` contains the required function record.
- The first `F0/F1` owner at `0x013C` is a context switch: it saves CBAR/CBR/BBR/stack state, installs MMU `77/xx/C7`, and restores a two-byte context-extension word through `F0/F1` on return. It does not poll those ports.
- The reset vector jumps to `0x0314`, which initializes Z180 core state, writes `01` and `39` to port `80`, writes `80` to port `88`, delays, writes `00/00/01` to `F0/F1/F2`, installs `BBR=00`, `CBAR=C7`, `CBR=77`, and transfers through the bank thunk toward `0x0372`.
- The M20 image contains literal SSI-263 writes at port `90`, but a 20-million-cycle run under the existing BL4 `0x90` mapping still produced zero phonemes and an untouched 40-cell display. Therefore speech-port placement alone does not establish a BL4-derived Millennium profile.
- Current blocker: the first post-context initialization branch after reset has not been recovered, so the actual missing read/interrupt dependency remains unknown.
- Next exact action: decompile the post-context target at logical `0x0372`, document it in `NOTES.md`, and follow only its first decision-changing initialization dependency.

### 2026-07-20: Board-ID branch rejected; full I/O address is next

- Exact bytes correct an isolated Ghidra mis-decompilation: `0x0372` is inside the continuing initialization routine, not a new tail call. It initializes services, reads port `F8`, compares with `40`, and records one of exactly two board-ID classes.
- Temporary runs registered exact `F8` reads of `00` (below `40`) and `40` (at/above `40`) under the proven `0x90` SSI mapping. Both reached the same `0x5FCC` runtime region after 20 million cycles with zero phonemes. The board-ID branch is not the missing startup dependency at that gate.
- Extending the `F8=40` run to 100 million cycles still produced zero phonemes and sampled the same `0x5FBD` bank-switch helper. This is persistent runtime mis-mapping, not merely slower initialization of the larger ROM.
- Z80 `OUT (n),A` places `A` in both the data byte and the high byte of the 16-bit I/O address. The decompiled context restore uses that behavior with the two-byte runtime word at `D02D` while targeting low ports `F0/F1`; preserving only an 8-bit port would erase a context selector that can explain the repeated bank-switch execution.
- Current blocker: it is not yet verified whether the CPU-to-IOBus path retains or discards the high eight address bits.
- Next exact action: inspect the current CPU callback and `IOBus` ownership of port width, then compare it with the exact Millennium `OUT (n),A` semantics before changing any source.

### 2026-07-20: Extended-memory selector ownership proven

- `Z180` forwards an `offs_t` port to QNS, but `IOBus.read/write` immediately mask it to eight bits. For Millennium this is not independently fatal because `OUT (n),A` also passes the selector byte as data; a low-port `F0` or `F1` handler could retain it. No such handler currently exists.
- Freedom Scientific's April 2002 M20/M40 user manual states the machine has approximately 2 MiB RAM and 12 MiB read-only flash. That 14 MiB total necessarily exceeds the Z180's native 1 MiB physical address space and independently supports the recovered external paging behavior.
- Function `0x52E4` writes selector word `0030` through `F0/F1`, then reads logical `D435`, and restores selector zero before returning. The first suspected callee `0x3D7D` is only a byte-comparison helper; `NOTES.md` corrects that false lead.
- The selector changes which storage backs the same logical `D435` address. With no handler, QNS reads ordinary zero-filled RAM there instead of page `0030`, contaminating startup state and explaining persistent context switching.
- Current blocker: the exact sequence of selector values and the page granularity/backing split are not yet measured from execution, so a 14 MiB array or guessed shift is not authorized.
- Next exact action: instrument the existing CPU callbacks outside the repository to retain/log exact `F0/F1/F2` values during M20 execution, then derive the minimal mapping experiment from values the firmware actually uses.

### 2026-07-20: Native RAM ceiling is the first Millennium blocker

- A 20-million-cycle selector trace shows only two states: reset `00/00/00`, then `00/00/01`. The firmware never reaches selector `0030` before the persistent runtime loop. Therefore the missing extended-page handler is required later but is not the first startup blocker; the earlier handoff inference is corrected.
- With `CBR=77` and `CBAR=C7`, the Z180 translates common runtime records such as logical `D024` above physical address `0x80000`. QNS's default RAM is exactly 512 KiB, and `Memory.write` silently ignores every address at or above that boundary.
- The observed 1,046,191 firmware write callbacks therefore include dropped context records. The bank/runtime helper keeps revisiting them because its stack and scheduler state cannot persist.
- Freedom Scientific's exact hardware authority is approximately 2 MiB RAM. This is the first capacity experiment authorized by both the manual and the failing physical boundary; no source change is open.
- Current blocker: it remains to prove that 2 MiB RAM allows initialization to advance and to observe the next real selector/peripheral dependency.
- Next exact action: run M20 with only the backing RAM expanded to the documented 2 MiB, retain the selector trace, and compare PC/speech/page transitions at the same 20-million-cycle gate.

### 2026-07-20: RAM fix exposes a later explicit reset path

- Expanding only RAM to the documented 2 MiB stops the dropped-context loop, reducing writes from 1,046,191 to 7,710, but the firmware then resets 50 times in 20 million cycles (50 writes each of `80=01`, `80=39`, and `88=80`; final PC `0340`).
- Each boot attempt reaches writes `E0=FD` and selector `F6:F5=0100` before resetting. Decompilation proves `0x3B69` reads and `0x3C06` writes through logical window `7000-7FFF`, with external address `(F6:F5 << 12) | offset`.
- A temporary exact 14 MiB backing model now maps CPU physical `7E000-7EFFF` to that 4 KiB window, provides 2 MiB zero-filled RAM plus 12 MiB `FF` flash, and retains selector `0100`. The 20-million-cycle result remains the same 50 resets, so the first selected RAM page's contents/aliasing do not cause this reset.
- The paging contract remains required for complete hardware support, but it is not sufficient to pass startup. No QNS source slice is open.
- Current blocker: the firmware branch that jumps back to the reset vector after its first `E0`/page-window work is not identified.
- Next exact action: list exact analyzed code references to reset address `0000`, then decompile and document the executed reset caller before changing any product source.

### 2026-07-20: Executed reset is an indirect task-runtime return

- Static xrefs find only the image entry and a conditional NMI call to reset, but a 200-instruction execution ring proves the observed resets do not traverse NMI.
- The first actual predecessor path loops through `9112-912F`, then executes `8FF7`, `8FFA`, `8FFD`, `9000`, `8FED`, and finally `0000`. A later boot attempt follows a distinct indirect path through `CD2D/CD2F` before zero.
- Function `0x8FD6` invokes runtime helper `0x43E0`, copies word `D056` into its caller record, and transfers through the bank/runtime thunk using `D056-80` plus a stack argument. Zero is an invalid indirect return/task target, not an explicit reset instruction.
- The isolated `0x9112` fragment operates on runtime record `D3BA` and routes toward thunk target `96AA`. Exact bytes around `90F0-916F` contain calls, comparison/status branches, and stack-record operations but no I/O read or write; a missing peripheral event is not yet proven.
- Current blocker: the call that initializes/returns the invalid task continuation has not been identified; guessing an external timer would be unsupported.
- Next exact action: recover the containing routine's start/backedge and decompile its first returning callee over `D3BA`, documenting each recovered owner in `NOTES.md` before following the next.

### 2026-07-20: Front-bank reset decompilation invalidated

- The executed-PC trace now retains MMU state and shows `BBR=28`, `CBR=77`, `CBAR=C7` throughout the apparent `8FED/9112` path.
- Logical addresses `7000-BFFF` are therefore fetched from physical firmware offsets `2F000-33FFF`. In particular, logical `8FD6` is physical `30FD6`, and logical `9112` is physical `31112`.
- The earlier Ghidra decompilations used raw front-bank offsets `8FD6` and `9112`; they analyzed unrelated code. Their claims about a task-exit function and record `D3BA` are withdrawn and corrected in `NOTES.md`.
- The execution-backed facts that remain are only the logical PC sequence, its MMU state, and the eventual transfer to zero. No reset owner, timer dependency, or task record is yet proven.
- Current blocker: Ghidra does not yet have the executed BBR bank mapped into its logical address range.
- Next exact action: build a temporary 64 KiB logical image with raw `00000-06FFF` at logical `0000-6FFF` and physical `2F000-33FFF` at logical `7000-BFFF`, then decompile the actual executed owners at logical `8FED` and `9112`, documenting each before proceeding.

### 2026-07-20: Correct bank proves deliberate memory-test reboot

- The temporary BBR-aware image maps physical firmware `2F000-33FFF` into logical `7000-BFFF`. Actual logical `8FD0` invokes a memory initializer/test with selector `0100`, count `0100`, and pattern `BBBB`; chooses result A/B; finalizes; then unconditionally disables interrupts and jumps to reset initializer `0314`.
- This first reboot is deliberate first-boot memory setup, not task corruption or NMI. The prior `8FD6`/`9112` front-bank claims remain withdrawn.
- A callback trace after `F6:F5=0100` shows the actual selected data write at native Z180 physical `E4000` while `BBR=DD`. The earlier fixed `7E000-7EFFF` diagnostic intercepted the wrong physical page and did not emulate the real access.
- The executed bank code later uses logical `9112` with `BBR=28`, confirming that page extension cannot blindly replace every bank-area instruction fetch. The mapping must preserve ROM instruction fetch while extending the firmware's selected data access.
- Current blocker: the exact combination of `F5/F6` and the native 20-bit physical address, including whether instruction/data cycles are distinguished, is not yet proven. The observed `F6=1` plus native `E4000` strongly targets documented RAM address `1E4000`, but that remains a hypothesis until tested against the intentional `BBBB` memory pattern and reboot outcome.
- Next exact action: extend only non-instruction memory accesses by the observed `F6` high address bits in the temporary diagnostic, retain ROM instruction fetches, and verify whether the first reboot's `BBBB` test persists and stops repeating before any source edit.
# 2026-07-20 M20/M40/Tiny Lite updater checkpoint

- All 11 new updater EXE payloads are extracted under `roms/`; the six classic
  payloads run under existing profiles.
- Commit `e4e0741` adds the verified variable-offset, source-length/CRC package
  loader; its full gate was 227 passing tests plus Ruff.
- M20 V4.5 requires 2 MiB RAM and an F6:F5-selected 4 KiB window at logical
  `0x7000-0x7FFF`. Its effective address is
  `(F6:F5 << 12) | (logical_address & 0x0FFF)`; the Z180 bank translation must
  not be retained in the external address.
- A 20M-cycle temporary run with that exact mapping writes F6/F5 only five
  times, proving the first-boot memory test completes. The run then enters a
  separate repeated reset path (49 later resets, no speech yet).
- A compact 5M-cycle trace found 11 identical later reset tails ending through
  logical PCs `0x917B...0x918B`, then `0xCD2D`, `0xCD2F`, and reset `0x0000`.
- Current blocker: the banked owner of the dominant later reset tail has not yet
  been decompiled, so its missing hardware prerequisite is unknown.
- Next action: resolve the live BBR mapping for the dominant `0x917B-0x918B`
  tail, decompile that exact routine, document it in `NOTES.md`, then test only
  the hardware behavior it proves.
# 2026-07-20 post-refactor review checkpoint

- Review mode is read-only; no source modifications are authorized.
- `master` currently matches `origin/master`.
- The only modified tracked path is this required uncommitted checkpoint note.
- The remaining untracked files are the existing local corpus and investigation
  artifacts; they are outside the review mutation scope.
- No blocker is known yet.
- Next action: inspect recent commits to identify the exact refactor boundary,
  then review its changed code and tests for concrete regressions.

## Review findings after inspection

- The refactor boundary is eight commits, `3a941c6` through `835ec35`, after
  `5fe0978`.
- `uv run pytest tests/` passes all 222 tests in 11.97 seconds.
- The current architecture has one profile table, one `IOBus`, extracted device
  owners, an isolated loader, an isolated CLI, and no surviving `qns/io.py`.
- `uv run ruff check .` fails with 83 findings. Much of the output is generated
  SC-01 table line length, but `qns/bns.py` has unsorted imports plus unused
  `nullcontext` and `redirect_stdout` imports, and multiple newly tracked tools
  also have ordinary lint failures.
- Current blocker: none; the lint failures still need comparison with the
  pre-refactor baseline before attributing them to this refactor.
- Next action: run Ruff against the pre-refactor tree or inspect commit-local
  diffs, then continue call-site and runtime smoke review for concrete behavior
  regressions.

## Active lint-fix slice after user cleanup

- The user's further cleanup left all tracked source clean before this slice;
  only this required checkpoint note remained modified.
- Current-tree Ruff started with 82 errors. `ruff --fix` resolved 13 mechanical
  import/type/f-string findings.
- Added a narrow `E501` exemption to the generated one-record-per-line SC-01 ROM
  table, moved the two late `test_bns.py` imports, and wrapped the decoder's
  table header.
- No blocker is present.
- Next action: wrap the remaining `extract_phonemes.py`,
  `phoneme_mapping.py`, and `rom_analyzer.py` lines; rerun Ruff; then run the
  full test suite and commit only this lint-fix slice.

### Validation checkpoint

- `uv run ruff check .` now passes with no findings.
- `uv run pytest tests/` passes all 229 tests in 11.64 seconds.
- The reviewed diff contains only import ordering, modern union annotations,
  plain-string cleanup, line wrapping, and the narrow generated-table `E501`
  exemption.
- No blocker is present.
- Next action: smoke the touched tool entrypoints without regenerating tracked
  artifacts, then stage the exact lint-fix paths (excluding this note), commit,
  and verify final status.

## Calculator keyboard-input investigation

- Scope is read-only: demonstrate the firmware calculator through the real
  emulator input path and diagnose any keyboard translation problem; do not
  change code.
- Expected user sequence: O chord, `c`, expression `1+2+3`, then E chord or
  dots 4-6; Enter/Return translation must also be investigated.
- The RE protocol is active. Each decompiled firmware function must be recorded
  in `NOTES.md` immediately before following another function.
- Current blocker: the exact current chord map, CLI input mode, calculator
  prompt timing, and firmware Enter action have not yet been verified.
- Next action: inspect the current input driver, tests, and CLI contract to
  derive the literal executable sequence before running a ROM.

### Live calculator result

- Lowercase host `o` maps to ordinary text chord `0x15`; firmware tries to
  insert it into the startup help file and says `file is write protected`.
- The already-proven command constants are `O_CHORD=0x55` and
  `E_CHORD=0x51`. Uppercase host `O` maps to `0x55`; firmware accepts it and
  says `option`.
- Sending lowercase `c` only after the next ready event maps to `0x09`;
  firmware accepts it and says `calculator ready`.
- After calculator entry, the driver never emits another keyboard-ready event.
  A queued `1` remains unaccepted for 30 seconds. Stopping after more than
  12 billion emulated cycles reports final PC `0x1418`.
- Current blocker: `ChordInputDriver` only starts input at its discovered main
  command-loop timer boundary or a stable halted CPU. The calculator waits at a
  different live boundary near PC `0x1418`, not yet identified in source.
- Next action: map BSP linked PC `0x1418` to the exact calculator/input function,
  document that function in `NOTES.md`, then use existing read-only mechanisms
  to determine whether the full calculation can be demonstrated without code.

### Calculator line-reader source trace

- `CALC.C::calc()` owns calculator mode: it says `calculator ready`, sets
  `numlock` and `calcflg`, and repeatedly calls `glin(cobuf, 99)` before
  dispatching the returned command through `glincg`.
- `BSPARMS.C::glin()` is a wrapper over `get_line()`. The collector repeatedly
  waits in `keybd()`, appends non-chord characters to its buffer, and completes
  the line when `keybd()` returns either `ECHORD` or `CR` under the ordinary
  calculator state.
- This establishes that the stall after `calculator ready` is before expression
  collection, inside or immediately around the firmware `keybd()` wait—not in
  calculation parsing or evaluation.
- Current blocker: linked PC `0x1418` has not yet been mapped to the exact
  `keybd()` wait instruction, and the source constants still need to distinguish
  the physical dots-4-6 chord from the ASCII/control encoding currently chosen
  for host Enter/Return.
- Next action: record the completed `glin/get_line` read in `NOTES.md`, then
  inspect the exact chord constants and the `BSKEY.ASM` `keybd()` owner.

### Physical keyboard wait identified

- `BSKEY.ASM::_keybd` calls `KEYIN`, which in the ordinary non-macro BSP path
  calls `_get_key` to remove a physical key from the shared queue.
- `_get_key` checks `queue_count`; while empty it executes `HALT`, calls
  `bg_task`, and loops. When a key is present it removes the queued integer,
  returns the raw low byte in `A`, and returns the complete key value in `HL`.
- Firmware constants prove `ECHORD=0x151` and `C46=CR=0x168`, corresponding to
  raw bytes `0x51` and `0x68`. Current host Enter/Return emits raw `0x8D`, so
  Return translation is independently wrong even once pacing is repaired.
- Current blocker: the calculator is using the same HALT-based `_get_key` wait
  as the top-level input path, but QNS does not recognize it as stable at live
  PC `0x1418`. The exact stability predicate and changing observation that
  prevents readiness still need to be identified.
- Next action: document `_get_key` in `NOTES.md`, map `0x1418` to its wait loop,
  and inspect QNS's stable-key-wait state inputs without modifying code.

### QNS stable-wait predicate

- `BNS.run()` executes the CPU in 1,000-cycle chunks. After each chunk it
  considers a key-wait sample only when `cpu.halted` is true and the SSI-263
  has no pending IRQ.
- Readiness requires two consecutive samples with exactly the same tuple
  `(cpu.pc, len(phoneme_log))`. `ChordInputDriver` otherwise relies on the
  top-level STARTA command-loop timer write, which calculator `glin()` does not
  perform.
- This means a real firmware `_get_key` HALT can remain invisible if periodic
  interrupt/background work prevents two adjacent 1,000-cycle samples from
  landing on the same halted PC, even though the firmware repeatedly returns
  to that wait.
- Current blocker: this sampling explanation is a source-supported hypothesis;
  linked PC `0x1418` and the native execute/HALT behavior still need direct
  confirmation before it is called the cause.
- Next action: inspect the native execution wrapper and use existing PC-watch
  or trace facilities to confirm the calculator wait's repeated HALT/interrupt
  pattern, without changing code.

### Exact prequeued calculator demonstration

- A fresh live BSP run received the literal host sequence `Oc1+2+3E` as one
  already-queued JSONL keyboard event after startup readiness.
- QNS accepted exactly `O` (`0x55`) and `c` (`0x09`). Firmware spoke `option`
  and then `calculator ready`. None of the already-queued `1+2+3E` values was
  accepted or pressed before the run was stopped at 753,584,000 cycles.
- Therefore the failure is not caused by an external client waiting for another
  `keyboard ready` event; the driver's internal start predicate blocks the
  remaining queue after calculator entry.
- The stopped run's final PC was `0x25E0`, while the prior one-at-a-time run
  ended at `0x1418`. A final PC snapshot is not a stable identification of the
  calculator wait. ROM `0x1418` is not HALT; the ROM's sole literal `ED 76`
  occurs at `0x141E`.
- Current blocker: the existing CLI exposes only an accepted event, not the
  sampled `cpu.halted` / SSI IRQ / candidate state that rejects calculator
  readiness, so the precise failing term is not yet directly observed.
- Next action: use only existing watch/trace surfaces to determine whether a
  repeated firmware location can identify queue-empty readiness; then report
  the demonstrated behavior and no-code diagnosis.

### Linked NFB99 wait behavior

- After a fresh `Oc` run reached and finished speaking `calculator ready`, the
  existing JSONL PC watch was armed on the linked ROM's sole literal HALT at
  `0x141E`.
- No PC-watch hit occurred during the following 437,934,000 cycles. The run
  remained in calculator input and still emitted no keyboard readiness.
- This corrects the source-tree hypothesis: although the available later
  `BSKEY.ASM::_get_key` includes a HALT-based queue wait, this linked NFB99
  calculator path does not reach that HALT while waiting. Its observed PCs are
  consistent with active polling, so QNS's stable-halt fallback cannot start
  calculator characters.
- The source still establishes the calculator's semantic contract, but the
  binary is the runtime authority for its wait behavior.
- Current blocker: without code changes, QNS has no general firmware
  key-consumption/readiness boundary outside the top-level STARTA write, so the
  expression cannot be delivered through the public emulator path.
- Next action: report the exact demonstrated sequence, the two independent
  keyboard defects, and the later implementation targets; do not code yet.

## Calculator and general nested-input implementation

- The user's implementation authorization broadens the fix to the actual
  defect surface: every firmware input reader outside the top-level STARTA
  command-loop epoch, not a calculator-specific exception.
- `ChordInputDriver` now uses the discovered command-loop/stable-wait signal
  only to establish initial keyboard availability after boot. Thereafter the
  existing physical handshake—press, firmware `_IIB` acceptance, release, and
  firmware `_IIB` clear—paces every queued key in any firmware context.
- Classic BNS host `\n` and `\r` now translate to physical C46 raw `0x68`.
  TNS retains its separate source-defined QWERTY scan mapping.
- The phase test now queues two keys and makes the fake CPU cease satisfying
  the readiness heuristic after initial activation; both keys still complete
  through the firmware buffer phases.
- Targeted gate: 7 relevant tests passed in 0.54 seconds.
- Current blocker: none.
- Next action: run the exact live BSP calculator sequence through E chord and
  host Return, then run Ruff and the full test suite before committing only the
  source and test slice; keep both investigation notes unstaged.

### First pacing attempt rejected by live firmware

- `Oc1+2+3E` reached eight successive `_IIB` accepted events with the initial
  enablement latch, but firmware spoke no result. A later E chord also produced
  no result. The attempt allowed hardware transfer to outrun application key
  consumption and is not a valid fix.
- `BSKEY.ASM::_put_key` establishes the missing distinction: the ISR increments
  `queue_count` when it transfers a key into the firmware queue; `_get_key`
  decrements it only when the active application reader consumes that key.
- The correct general pacing authority is therefore an empty firmware key
  queue after the prior `_IIB` hardware handshake, not a calculator boundary
  and not permanent enablement alone.
- The `_put_key` signature is unique in each NFB99 bank-zero link. Recovered
  logical `queue_count` addresses are BSP `0xDA32`, BS2 `0xDA33`, BSL `0xDA34`,
  BL2 `0xDA35`, BL4 `0xDA3B`, and TNS `0xDA38`; their runtime physical addresses
  use the same discovered common-area mapping as `_IIB`.
- Current blocker: none; the first code revision must be replaced within the
  same uncommitted slice and revalidated live.
- Next action: extend the existing input-boundary discovery with the unique
  `_put_key` queue-count operand, require queue emptiness before each subsequent
  chord, update exact tests, then repeat the calculator demonstration.

### Queue-empty pacing alone rejected

- Boundary discovery now recovers `queue_count`, and the targeted test proves a
  second key is withheld while the prior key remains queued. Nine focused tests
  pass.
- The repeated live `Oc1+2+3E` run still accepted all chords but spoke no
  result. Queue emptiness occurs when `_get_key` pops the current key, before
  its caller finishes processing that key and reaches the next input request.
- Therefore `_IIB` acceptance plus queue emptiness prevents hardware overrun
  but still allows semantic typeahead to outrun mode transitions.
- The general readiness owner is the shared `_get_key` empty-wait entry: it is
  reached only when the active calculator/menu/editor caller has finished prior
  processing and is actively requesting another key.
- Current blocker: the linked empty-wait instruction and its unique discovery
  signature have not yet been recovered from all supplied firmware links.
- Next action: recover and document the linked `_get_key` empty-wait signature,
  replace the permanent-enable/queue-only start condition with epochs from that
  exact application wait, then repeat targeted and live gates.

### Exact application-wait boundary implemented

- The earlier `ED 76` HALT identification was wrong; Z80 HALT is byte `0x76`.
  Linked BSP `_get_key` is uniquely `0x1AF2`, reads empty `queue_count` at
  `0x1AF5`, and halts at `0x1AFE`. `NOTES.md` now contains the correction.
- Unique NFB99 `_get_key` wait-read PCs are BSP `0x1AF5`, BS2 `0x1BD3`, BSL
  `0x1CF9`, BL2 `0x1DB4`, BL4 `0x1FC0`, and TNS `0x1E16`.
- TNS `get_brl()` also consumes scans through shared `get_key()`, so this is a
  general cross-family application-read boundary.
- `InputBoundary` discovery now requires and reports the linked `_put_key`
  queue operand plus the `_get_key` empty-wait instruction. `BNS._mem_read`
  counts exact empty-wait epochs, and `ChordInputDriver` starts one chord per
  new epoch after confirming the queue remains empty.
- The prior sampled stable-HALT and STARTA-based next-key gates have been
  removed from the normal driver path; hardware press/accept/release remains
  unchanged.
- Current blocker: the revised unit tests and live calculator gates have not
  yet run against this exact-wait implementation.
- Next action: update the phase fake to emit exact wait reads, run focused
  discovery/driver tests, then run `Oc1+2+3E` live before any commit.

### Two exact application-read epochs

- The first exact-wait live startup emitted no keyboard readiness because the
  top-level editor does not call blocking `_get_key`; STARTA polls the queue and
  opens its own linked command-loop epoch.
- The general firmware contract therefore has exactly two observed owners:
  linked STARTA for top-level editor commands and linked `_get_key` empty reads
  for calculator, menus, prompts, TNS `get_brl()`, and other nested readers.
- `ChordInputDriver` now starts one key when either exact counter advances and
  records both counters at that start. The sampled-HALT heuristic remains
  deleted. `_IIB` and queue-empty checks still guard the physical transfer.
- Tests retain one top-level STARTA-driven BSL case and use `_get_key` epochs for
  the two-key nested phase case and TNS modifier case.
- Current blocker: this combined exact-epoch revision has not yet passed its
  targeted tests or the calculator live gate.
- Next action: run the focused gate, then rerun the literal BSP calculation.

### Causal readiness ordering

- A pre-armed native PC watch proved linked BSP `_get_key` reaches `0x1AF5`.
  The callback must use its physical fetch address because `instruction_pc` can
  lag inside memory callbacks, as already proven for English capture.
- The same run showed stale STARTA epochs can accumulate while a chord is still
  moving through the ISR. Reusing one after `_IIB` acceptance allowed `c` to
  outrun O-chord processing and produced `file is write protected`.
- STARTA and `_get_key` readiness now share one monotonically ordered epoch.
  A nonzero `_IIB` write records the epoch at firmware acceptance. The next key
  requires an epoch strictly after both that acceptance and the last epoch used
  to start a key.
- This preserves exact top-level and nested owners while enforcing causal
  ordering across the ISR handshake; no timing delay or feature-specific gate
  has been introduced.
- Current blocker: the ordered-epoch revision has not yet passed tests or the
  live calculator proof.
- Next action: extend the phase test to include a stale epoch before `_IIB`
  acceptance, run focused tests, then rerun `Oc1+2+3E`.

### Linked calculator uses another queue reader

- Qualifying STARTA at the event itself with `queue_count == 0` fixed causal
  O-to-c ordering: live firmware now finishes speaking `option` before it
  accepts `c`, then speaks `calculator ready`.
- The first expression digit still does not start. This disproves the remaining
  assumption that this NFB99 calculator line reader reaches the same linked
  `_get_key` empty wait used by the option prompt.
- The later source tree's `glin -> keybd -> KEYIN -> _get_key` contract is not
  the exact linked calculator implementation for this package. Earlier varied
  final PCs (`0x1418`, `0x25E0`, and others) are consistent with another
  polling/editor owner.
- Current blocker: the actual linked calculator queue-read PC is not yet known.
- Next action: temporarily log unique instruction PCs that read the already
  discovered physical queue-count byte while it is empty, enter calculator,
  identify and document the actual shared input owner, remove the diagnostic,
  and generalize readiness to that owner rather than the calculator feature.

### Linked calculator bypasses both recovered firmware queue bytes

- Live BSP tracing across O, the option prompt, c, and `calculator ready`
  found no calculator read of either `queue_count` (`0x41A32`) or `_IIB`
  (`0x4327C`). The recovered `_get_key` wait at `0x1AF5` belongs to the option
  prompt in this path, not to the linked calculator line editor.
- The calculator continues emitting its idle/error speech after announcing
  readiness, so it remains active while the host driver waits. The remaining
  candidate is direct keyboard-port polling in the linked calculator/editor.
- Next action: temporarily log unique CPU PCs reading the BSP keyboard port,
  identify the empty polling reader reached after calculator entry, and use
  that proven shared input owner rather than adding a calculator-specific gate.

### Calculator input is interrupt-driven, not pre-key port polling

- Temporary unique-PC tracing of BSP keyboard port `0x40` found only boot
  probes (`0x03CB`, `0x03D2`, `0x05B8`, `0x05BE`) and ISR reads for O-chord
  (`0x0A87`, `0x0A99`). No keyboard-port read occurred after the firmware
  announced `calculator ready`.
- This rules out a zero-value calculator polling read as a readiness event.
  The linked calculator can instead be waiting interrupt-first: no queue or
  port read needs to occur until QNS presents the next physical chord.
- Current blocker: queue-empty alone releases the next chord too early during
  the c-to-calculator transition, while requiring another observed read event
  deadlocks an interrupt-driven consumer.
- Next action: inspect the exact CPU halt/state transition around calculator
  entry and compare it with the option prompt. Determine whether an actual
  post-dispatch HALT epoch is the general input-ready boundary, without using a
  sampled delay or recognizing the calculator feature.

### First character transitions the calculator into the shared wait

- Sampled HALT tracing found option-prompt `_get_key` HALT `0x1AFC`, but no new
  HALT PC after calculator entry. Re-arming the native watch for `0x1AFC` only
  after c was accepted produced `watch-armed` and no hit during the next ten
  seconds, confirming this was not hidden by unique-PC suppression.
- Under diagnostic-only readiness bypass, a separately presented `1` completed
  the ISR handshake. The eventual final PC was `0x1AFC`; subsequent expression
  input therefore returns to the ordinary shared `_get_key` wait.
- Current blocker: no pre-key queue, port, or HALT event marks readiness for the
  first character after calculator entry. Queue-empty alone can present it
  before calculator initialization consumes/clears pending input.
- Next action: disassemble the linked path following the `calculator ready`
  message and recover the exact interrupt-first boundary that accepts the
  initial character. Determine whether it is a reusable external-program input
  boundary before changing the runtime contract.

### Loader freezes banked input data at the top-level mapping

- `find_input_boundary()` recovers logical `_IIB`, `queue_count`, and STARTA
  timer operands, then converts all three to physical addresses with the
  hard-coded `_COMMON_AREA_CBR = 0x34`. Only `_get_key` and STARTA instruction
  PCs remain logical.
- Z180 callbacks receive translated physical addresses, while external
  applications may change MMU registers. The frozen queue address can therefore
  cease to observe the same logical firmware variable during calculator code.
- Current blocker: the live CBR/BBR/CBAR values at calculator entry and at the
  first post-entry key have not yet been captured, so the banked-address
  hypothesis is not proven.
- Next action: capture the live MMU mapping at the `calculator ready` English
  boundary and on the first digit ISR/queue access, then compare translated
  logical addresses before changing discovery or runtime ownership.

### Application consumption, not ISR acceptance, owns host input

- Live MMU capture falsified the frozen-address hypothesis: `CBR=0x34` and
  `CBAR=0xC6` remain stable at calculator entry; only external-program `BBR`
  changes, while `queue_count` is in common area.
- Logging repeated nonzero queue reads showed c and delayed digit 1 are both
  consumed by the shared `_get_key` path at `0x1AF5` / `0x1B03`. The earlier
  apparent absence was only unique-PC suppression.
- Root cause: QNS reports and forgets a host character when the hardware ISR
  clears `_IIB`. That proves insertion into the firmware queue, not application
  consumption. During c-to-calculator initialization, firmware can clear an
  already queued first digit before `_get_key` consumes it.
- Next action: retain one logical host character after its physical handshake
  until a nonzero `_get_key` observation proves consumption. If queue insertion
  occurred but the queue returns to zero without that proof, retry the same
  physical chord. Keep the initial STARTA readiness boundary for boot, apply
  the consumption rule to classic and TNS input, and add a discard/retry test.

### Live calculator and Return gates pass with consumption ownership

- Runtime now records queue-insertion and `_get_key`-consumption epochs. The
  driver retains one logical host character through its physical handshake,
  reports acceptance only after `_get_key` sees a nonzero queue, and repeats
  the physical chord if firmware clears an inserted key without consuming it.
- A single JSONL event containing `Oc1+2+3E` was consumed in exact order by
  linked BSP firmware and produced English speech text `6`.
- In the same live calculator, `4+5\n` wrote raw chord `0x68`, emitted accepted
  chord `104`, and produced English speech text `9`. This proves host Return is
  translated to firmware C46/CR rather than inverse-table raw `0x8D`.
- Current state: the live defect is solved. Focused test fixtures still model
  queue changes with direct memory writes, so six tests fail because they never
  invoke the new insertion/consumption callbacks.
- Next action: remove temporary queue/port/HALT/MMU diagnostics, update fixture
  CPUs to call `_mem_write` for queue insertion and `_mem_read` with nonzero
  queue for consumption, add an explicit clear-without-consume retry case, then
  run focused and full gates.

### Diagnostics removed and focused gates pass

- Temporary queue-read, port-read, HALT, MMU, and trace-mode readiness bypass
  diagnostics have all been removed from production code.
- The phase fixture now proves a queued character cleared without `_get_key`
  consumption is physically retried, then accepted once consumed, before the
  next host character starts. It passes for BSP, BS2, BSL, BL2, and BL4.
- TNS modifier fixtures now model queue insertion and shared `_get_key`
  consumption; JSONL routing and BSL STARTA tests use the same contract.
- Focused result: `12 passed, 91 deselected`. Loader invalidation now also
  covers a missing `_get_key` wait signature.
- Current blocker: lint and the full test suite have not yet been run after the
  final cleanup.
- Next action: run `uv run ruff check .`, then `uv run pytest tests/`; inspect
  and fix any failures before reviewing the exact staged diff.

### Full gates and commit scope

- `uv run ruff check .` passes.
- `uv run pytest tests/` passes all 251 tests in 13.04 seconds.
- `git diff --check` passes. The intended source/test slice is limited to
  `qns/bns.py`, `qns/input_driver.py`, `qns/loader.py`, `tests/test_bns.py`, and
  `tests/test_loader.py`.
- The worktree also contains user-owned tracked cleanup in docs/external-tool
  paths and many untracked ROM, EXE, research, and generated artifacts. None is
  part of this slice; notes remain uncommitted as required.
- Current blocker: none. One read-only compatibility check remains before
  staging: ensure boundary discovery still succeeds on each of the six classic
  2003 updater payloads, whose linked addresses may differ from NFB99.
- Next action: run each classic payload for one cycle with its exact existing
  model and confirm the CLI reports buffer, queue, wait PC, and timer; then
  rerun the final focused/full authority only if code changes are required.

### Classic 2003 compatibility and final gates

- One-cycle loads with exact models discovered complete input boundaries for
  all six classic 2003 payloads: BSP queue/wait `0x41A7F/0x1B06`, BS2
  `0x41A80/0x1BEA`, BSL `0x41A81/0x1D21`, BL2 `0x41A82/0x1DE2`, BL4
  `0x41A8A/0x1FE1`, and TNS `0x41A85/0x1E32`. Every command exited 0.
- After deleting the unused wait counter and adding missing-wait signature
  invalidation, final `uv run ruff check .` passes and the full suite again
  passes all 251 tests in 13.03 seconds.
- Current blocker: none. The live calculator, Return translation, focused
  contract, full suite, lint, and cross-revision discovery gates are green.
- Next action: stage only the five intended source/test files, inspect the
  staged patch and staged name list, commit the kept slice, and verify that
  notes, ROMs, EXEs, and unrelated tracked cleanup remain unstaged.

### Staged patch reviewed

- The staged name list is exactly the intended five paths: `qns/bns.py`,
  `qns/input_driver.py`, `qns/loader.py`, `tests/test_bns.py`, and
  `tests/test_loader.py`.
- `git diff --cached --check` passes. The staged patch was reviewed with
  end-of-line-only differences ignored because `qns/bns.py` and
  `tests/test_bns.py` already have mixed line endings in the index.
- The patch contains only linked queue/wait discovery, causal
  insertion/consumption epochs, retry of an unconsumed cleared key, classic
  Return-to-C46 translation, and their authorities. No diagnostic trace or
  calculator-specific branch remains.
- Notes, ROMs, EXEs, unrelated docs/tools/tests cleanup, and all untracked
  research/generated artifacts remain unstaged.
- Current blocker: none. Next action: commit the staged kept slice, then inspect
  the commit name list and worktree status to verify scope.

### Keyboard input fix committed

- Commit `23a629654e5e6e6560abdbe644983f4cfdcdcd8a` (`Fix firmware-paced
  keyboard input`) contains exactly the five reviewed source/test paths.
- Post-commit status has no staged paths. The remaining tracked modifications
  are user-owned notes/docs/external-program cleanup; untracked research,
  generated files, ROMs, and updater EXEs remain untouched.
- `git ls-files -- roms reports/*.exe` produced no output, confirming neither
  ROMs nor updater executables are tracked by this commit or the current index.
- Final outcome: live calculator `Oc1+2+3E -> 6`, live host Return
  `4+5\n -> accepted 0x68 -> 9`, Ruff clean, 251 tests passed, and all six
  classic 2003 links discovered complete input boundaries.
- No blocker remains. Pause after reporting so the user can continue cleanup.

## 2026-07-20 flash-support investigation

- Current implementation supports BSNEW flash for the `bs2` profile: the
  profile allocates 2 MiB, port `0xE0` selects/enables 512 KiB flash pages,
  and `Memory` implements AMD byte-program, sector-erase, and chip-erase
  command sequences.
- Version-2 `--state` files include both nonvolatile RAM and flash bytes, so
  flash persists only when the CLI is given a state path.
- The reported command does not select `--model bs2`; the CLI default is
  `bsp`, whose profile allocates zero flash. It also omits `--state`, so even
  correctly selected BS2 flash would not survive process exit.
- Focused current authorities pass: three flash mapping/program/erase/state
  tests, two BS2 wiring tests, and the persisted-program restart test (6
  passed in 0.59 seconds).
- Current blocker: none for answering whether support exists. The exact
  reported invocation does not activate or persist that support.
- Next action: report the required `--model bs2 --state <path>` correction and
  clearly distinguish implemented flash support from the behavior of the
  supplied command.
