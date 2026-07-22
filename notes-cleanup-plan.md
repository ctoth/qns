# Whole-app cleanup/modularization plan — 2026-07-20

## FOLLOW-UP (2026-07-20 evening): english-boundary discovery

Q request: replace profile-hardcoded english_capture_addr/spbuf with
load-time signature discovery so --speech english works on all classic
revisions (2003 TNS was silent — different link).

Findings so far (all from actual package bytes via qns.loader):
- Verified NFB99 sites: LD HL,SPBUF prologue identical across all 6;
  BSP-family shape: prologue + speech-enable test + CALL,CALL.
  NFB99 BL shape: prologue + display test + speech-enable + CALL,CALL.
- 2003 BL links REORDERED the conditionals: prologue + speech-enable +
  display test + CALL,CALL,CALL (verified bytes blt18/blt2000/blt40;
  blt40 2003 spbuf is 0xD65F vs NFB99 0xD65E — proves discovery needed).
- Discovery results: all 6 NFB99 == proven values; 2003 bsp 0xBC6F/D657,
  bs2 0xBC70/D658, tns 0xBB99/D65D unique; 2003 BLs matched after adding
  third signature (pending re-verify).
- Q mid-turn feedback: express signatures as SEMANTIC instructions, not
  hex byte strings — DONE: _Insn dataclass (mnemonic, opcode, operand
  wildcards), named instructions, composed sequences.
- DONE since: _find_signature takes _Insn sequences (semantic, per Q);
  discovery re-verified on all 12 packages (6 NFB99 exact match to
  proven values; 2003: bsp 0xBC6F/D657, bs2 0xBC70/D658, bsl 0xBC26/
  D657, bl2 0xBC21/D658, bl4 0xADD1/D65F, tns 0xBB99/D65D — all unique).
  BNS wired: _english_boundary discovered in load_rom (with print),
  _mem_read uses it; profile english_capture_addr/spbuf fields DELETED.
  Tests: new tests/test_loader.py (3 shapes, ambiguity->None,
  absent->None, high-bank ignored); test_bns capture test now loads
  synthetic signature ROMs through real discovery. Suite: 228 passed.
- English discovery COMMITTED 87ac512: e2e proven (2003 TNS streams
  "Type 'n Speak ready/help/1/page", 2003 BSP retained english works,
  NFB99 regression clean), 228 tests, gates zero-hit.

## FOLLOW-UP 2: input-boundary discovery (Q: "Do it. and commit and push")

- Two new semantic signatures, both verified UNIQUE in all 12 packages
  with NFB99 extractions exactly matching the proven profile values:
  - STARTA: XOR A; LD (nn),A; LD HL,timer; LD (HL),0; CALL — timer =
    LD HL operand, write-PC = LD (HL),0 address.
  - Chord accept (keyboard ISR tail): LD A,7DH; JR; LD (IIB),A; XOR A;
    LD (nn),A; JR — IIB = first LD (nn),A operand.
  - 2003 values differ from NFB99 (e.g. 2003 BSP IIB 0xF0D4 vs 0xF27C;
    2003 BL4 timer 0xD65B) — hardcoding was wrong for them.
  - Physical = (CBR 0x34 << 12) + logical; CBR=34 proven in every
    NOTES runtime record incl. all 2003 runs.
- Q mid-turn: "you can also decompile things when you need to" —
  acknowledged; byte-level sufficed here, Ghidra is the escalation if
  a future revision breaks a signature.
- DONE: loader.py InputBoundary + find_input_boundary (+_sequence_offset
  helper, semantic offsets); bns.py wired (discover+print in load_rom,
  _mem_write guard, run() disables keyboard input with message when
  non-tns boundary missing, power-on-input raises); input_driver
  _input_buffer uses bns._input_boundary.
- DONE: profile input fields deleted; test_bns rewired to test-local
  INPUT_BOUNDARIES table + bns._input_boundary installs (9 sites);
  authority test replaced by loader round-trip tests; test_loader has
  make_input_boundary_image + 2 tests. Suite 229 passed.
- E2E PROVEN (quoted): `printf 'h' | ... --input keyboard
  --speech-stream english` on NFB99 BSP AND 2003 bns640 BSP both print
  "Chord acceptance boundary: ..." (2003 buffer 0x430D4 vs NFB99
  0x4327C) then identical dialogue: ready/help/1/page then "file is
  write protected" in response to the chord — 2003 chord handshake
  works end-to-end.
- REMAINING: search gate, commit, check remote + push.
- Blocker: none.

## STATUS of main cleanup: COMPLETE (all 8 slices committed on master)

3a941c6 baseline adoption · c458368 synth/chip decode · fd39317 devices
package · ae81ce5 hardware profiles · f1433f3 input driver · adb13c6
loader · a8e95da CLI split · 835ec35 tools triage + CLAUDE.md.
Cleanup slices net: 27 files, +3787/-3953 (excluding baseline adoption).
Final gates: 222 tests green after every slice; 20M-cycle bspeng.bns
e2e speaks the boot message after every code slice; all search gates
zero-hit; `python -m qns.bns --help` works; rewired tools smoke-tested
against the real package. Working tree clean for qns/tests/tools +
CLAUDE.md. Bug fixed en route: formant inflection I11 loss (0x007 mask),
regression-tested in tests/test_ssi263.py.

State: survey COMPLETE (all of qns/ read: bns, io, cpu, ssi263, memory, stdio,
synth/* incl. formant, sc01_rom, sc02_to_sc01, phonemes head; usage verified by
grep). Plan delivered to Q, awaiting go-ahead. No code touched. No blockers.

## Verified findings

- Register decode duplicated 3x: ssi263.py chip + synth/ssi263_synth.py +
  synth/ssi263_pcm.py each decode the same 5 registers with own State class.
  Chip forwards RAW byte to synth which re-decodes.
- BUG: ssi263_synth.py:105 write_inflect masks `& 0x007` (drops I11);
  ssi263_pcm.py:65 uses correct `& 0x807`.
- ssi263_synth.py:239-242: amplitude 0->15 HACK + debug print in production.
- dsp.py: only tests import it (grep-verified). pitch_shift has unreachable
  code after early return; apply_filter is a stub.
- Phoneme metadata 3 owners: ssi263.py::PHONEMES, sc02_to_sc01.py::SC02_PHONEMES,
  sc01_rom.py (SC-01 side).
- bns.py hardcodes SSI263PCMSynth; formant backend only used by tests/tools.
- bns.py god object: ~20 scattered `if model ==`, 6 parallel model dicts,
  ~250-line inline chord state machine in run(), tracing in mem-write callback,
  package parsing inline in load_rom, 260-line main() with duplicated
  speech formatting (--speech vs --speech-stream).
- io.py: 8 unrelated device classes in one file.
- Loader: NOTES.md proves Millennium packages use IMAGE_OFFSET 0x7000/0x8000
  w/ length+CRC metadata; hardcoded 0x3000 must become discovered boundary.
- UNTRACKED production files: qns/synth/formant.py, sc01_rom.py, sc02_to_sc01.py.

## Plan slices (execution order)

0. Baseline: commit untracked production surfaces, pytest green recorded.
1. Synth: chip owns register decode once; SpeechBackend protocol; delete dup
   State classes/write_* mirrors/dsp.py/HACK/print; consolidate phoneme
   metadata; fix 0x007 mask; selectable backend (--synth pcm|formant).
2. Devices: split io.py -> qns/devices/ package.
3. Model profiles: per-model hardware-profile dataclass replaces dicts+branches.
4. Input driver: extract chord state machine from run().
5. Loader: qns/loader.py, classic 0x3000 + proven length/CRC aligned scan.
6. CLI: split main(); one speech-formatting function.
7. Tools triage: keep harness/verify tools, archive one-off scripts.

Gates: pytest (test_bs2_* = end-to-end firmware speech), per-slice search gates
(no write_durphon outside chip, no `if model ==` in BNS, no SSI263PCMState),
atomic commit per slice, record in docs/cleanup-log.md.

## Execution log

- Slice 1 COMMITTED c458368 (13 files, +1647/-1697): chip sole decoder,
  SpeechBackend protocol, dsp.py deleted, metadata consolidated, I11 bug
  fixed+regression-tested, --synth pcm|formant. Gates: 222 tests green,
  search gates zero-hit, 20M-cycle bspeng run speaks boot message.
- Slice 2 COMMITTED fd39317: qns/devices/ package (8 modules), io.py
  deleted, test_io.py renamed test_devices.py. 222 tests green, gates zero.
- Slice 3 COMMITTED ae81ce5: profiles table drives wiring; tests read
  PROFILES authority; gates clean; e2e speaks. 15 self.model refs remain,
  all input-machine (slice 4 scope).
- Slice 4 COMMITTED f1433f3: ChordInputDriver extracted; run() keeps only
  stdin plumbing + tick(); importers updated to public names; 222 green,
  gates clean, e2e speaks.
- Slice 5 COMMITTED adb13c6: qns/loader.py owns firmware extraction
  (FirmwareImage w/ kind+provenance, boundary discovery, BEUPDATE CRC);
  load_rom slimmed to load+report. 222 green, e2e speaks.
- Slice 6 COMMITTED a8e95da: qns/cli.py owns argparse main (+shared
  _format_phoneme, PROFILES-derived --model choices); bns.py keeps
  __main__ shim so `python -m qns.bns` works; bns.py 1413->814 lines.
  222 green, e2e speaks, --help parses.
- Slice 7 IN PROGRESS (tools triage): extract_firmware.py REWRITTEN as
  thin CLI over qns.loader (old one hardcoded 0x3000, wrong for
  Millennium). rom_analyzer.py: local load_firmware now delegates to
  qns.loader; its info command still references deleted IMAGE_OFFSET at
  lines 75-76 — fixing to use FirmwareImage provenance. Then: commit
  decode_sc01_rom.py + trace_bs2_folder_trap.py as-is, update CLAUDE.md
  structure section (devices/, profiles, loader, cli, input_driver,
  --synth flag), final pytest + e2e, final commit + summary to Q.
- Slice 6 details (done): move main()/argparse from bns.py to
  qns/cli.py; unify --speech/--speech-stream formatting into one
  function; keep `python -m qns.bns` working (bns.py __main__ delegates);
  tests import `main as bns_main` from qns.bns in test_bns/test_ssi263 —
  update those imports to qns.cli. Then slice 7 tools triage + CLAUDE.md
  structure refresh + final full-matrix e2e.
- Slice 4 details (done): qns/input_driver.py written —
  public ASCII_TO_BNS_KEY/keyboard_input_chord/tns_input_scan tables +
  ChordInputDriver (power-on hold, tick = advance_phase + start_next,
  same phase semantics incl. same-tick accept-then-dequeue).
  bns.py: tables/helpers deleted, import added; _read_stdin_character
  and _COMBYT_PHYSICAL intentionally stay in bns (tests monkeypatch
  qns.bns._read_stdin_character; COMBYT used by _mem_write counter).
  REMAINING: replace run() machine body (lines ~640-930: power-on block
  uses driver.hold_power_on_chord, loop tick), update importers of
  _ASCII_TO_BNS_KEY etc. (test_bns, test_bs2_external_program,
  test_bs2_help, tools/verify_bs2_dictionary, tools/verify_bs2_help),
  pytest + e2e + commit.
- Slice 3 progress 2: bns.py fully converted to profile fields (init,
  _mem_read english capture, _mem_write timer, _setup_io family branches,
  parallel port handlers via profile.parallel_port_base + isinstance
  display check, run() keyboard_input_buffer, main display None-checks,
  stale model docstring fixed). tests hasattr->is None applied. CURRENT
  BLOCKER: pytest collection error in test_bns.py after sed — inspecting
  now (likely sed collateral or import error).
- Slice 3 IN PROGRESS (model profiles): qns/profiles.py written — frozen
  HardwareProfile dataclass + PROFILES table for all 6 models (wiring,
  peripherals flags, firmware addresses from the four old parallel dicts).
  bns.py partially converted: dicts deleted, __init__ peripheral block now
  profile-driven, display is now an always-set attr (None when absent).
  REMAINING refs to fix (per pyright): _ENGLISH_SPEECH_BOUNDARY in
  _mem_read (~327), _command_loop_timer_* in _mem_write (~365),
  _keyboard_input_buffer_physical in run (~910); _setup_io family branches;
  _read/_write_parallel_port (bsnew check, display isinstance);
  main() hasattr(bns,"display") x2 -> is not None; tests test_bns.py
  347/698 hasattr -> is None. Then pytest + e2e + commit.
- Slice 2 details (done): qns/devices/ package written —
  __init__ (exports), bus.py (IOBus, typed handlers), gas_gauge.py,
  clock_pic.py, rtc.py, keyboard.py (BrailleKeyboard+TNSKeyboard, typed
  IRQ callback), display.py (both displays), watchdog.py. Code moved
  verbatim except type hints. Unused-param pyright hints are handler
  signature requirements (port/value), expected. NEXT: update importers
  (qns/bns.py line 13 block, tests/test_io.py line 8), git rm qns/io.py,
  run pytest + end-to-end, commit slice 2.
- Blocker: none.

- Q approved: "drive to completion". Working on master, committing per slice.
- Slice 0 DONE: baseline 227 tests green; commit 3a941c6 adopts formant.py,
  sc01_rom.py, sc02_to_sc01.py + modified __init__/ssi263_synth as tracked.
- Slice 1 IN PROGRESS (synth consolidation):
  - qns/ssi263.py REWRITTEN: chip is sole register decoder; decoded fields
    (phoneme/duration/inflection/rate/articulation/amplitude/filter_freq/
    control); frozen SSI263State snapshot; SpeechBackend Protocol
    (start/stop/play(state)); irq_pending + irq_enabled properties;
    _speak_phoneme calls backend.play(snapshot); deleted MODE_*/CONTROL_BIT
    consts, current_phoneme, _reset, raw register attrs.
  - ssi263_pcm.py REWRITTEN: no state mirror, play(state)+speak_phoneme,
    get_phoneme_audio(phoneme, amplitude).
  - ssi263_synth.py REWRITTEN: formant backend, no mirror/HACK/print; kept
    standalone knobs (amplitude/inflection attrs, set_pitch/set_volume,
    speak_phoneme(s), wait_until_done); deleted set_speed (dead), deleted
    SSI263_TO_SC01 alias (use SC02_TO_SC01).
  - synth/__init__.py: exports FormantSynth, SSI263PCMSynth, SSI263Synth.
  - dsp.py DELETED (git rm). sc02_to_sc01.py: SC02_PHONEMES dict deleted.
  - PENDING (current diagnostics confirm): fix sc02_to_sc01 helper functions
    still referencing SC02_PHONEMES -> use qns.ssi263.PHONEMES; update
    bns.py (_pending_irq_cycle -> irq_pending, --synth backend selection);
    tools/bs2_harness.py (4 private pokes), tools/phoneme_mapping.py +
    tools/test_phonemes.py (alias + state pokes); rewrite tests
    (test_synth.py dsp/state sections, test_ssi263_pcm.py mirror tests,
    add chip decode + I11-preservation regression test); run pytest.
- Blocker: none.
- Slice 1 progress 3: tools updated (bs2_harness irq_pending; phoneme_mapping
  deduped hand-copied name list + stale MAME note; test_phonemes new API).
  Tests rewritten: test_synth.py (dsp tests gone, chip-driven integration),
  test_ssi263_pcm.py (mirror tests gone), test_ssi263.py (+decode test,
  +I11 regression, +snapshot-to-backend test). First pytest: 221 passed,
  1 failed — MY new amplitude test assumed FormantSynth was stateless; it
  is stateful across phonemes (observed: second render differs). Fix: render
  each amplitude on a fresh backend. No production defect indicated.
- Slice 1 progress 2: sc02_to_sc01 helpers now use qns.ssi263.PHONEMES;
  bns.py updated (--synth pcm|formant, synth_backend param, irq_pending).
  Pyright noise in bns.py is pre-existing union-type issues (keyboard/display
  variants), deferred to profiles slice. bs2_harness.py sites read: 4 pokes
  at _pending_irq_cycle (112/118/124/139/144) — 124 wants the cycle VALUE for
  an error message; will use irq_pending for booleans and drop the value from
  the message (or keep private read? No — extend property set: keep message
  via irq_pending only). phoneme_mapping.py duplicates SSI263_NAMES list
  (redundant with PHONEMES — has a transcription error at 0x10 "W" vs "AW")
  and imports the deleted SSI263_TO_SC01 alias; will rewrite imports to
  SC02_TO_SC01 and derive names from PHONEMES. Next: edit bs2_harness,
  phoneme_mapping, test_phonemes, then rewrite tests and run pytest.
