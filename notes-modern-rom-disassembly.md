# Modern ROM annotated disassembly investigation

Status: read-only feasibility investigation complete, 2026-07-21. This
task note is intentionally uncommitted.

## User target

Determine which current artifacts should become the modern annotated firmware
source for the Braille 'n Speak 2000 and Type 'n Speak, whether a simple
compile/decompile/byte-exact round trip is practical, and the overall effort.

## Current repository state

- Branch is `master`, tracking `origin/master`.
- The worktree was already dirty before this investigation, including tracked
  changes to `NOTES.md`, `notes-software-bns.md`, emulator modules, and tests,
  plus many untracked research artifacts and ROMs.
- This investigation has not changed source code, ROMs, tests, or Git state.

## Verified local artifacts

- `C:\Users\Q\src\bns\bsp` is not merely an annotated disassembly. It is a
  large mixed C/Z180 assembly source tree with linker scripts, make/project
  files, headers, language data, and build scripts. Source timestamps extend
  through May 2001; `BS.ASM` was last modified 2001-05-01 and
  `BSPROCES.ASM` 2001-05-03.
- The historical build names Softools `sc180`, `slink`, `sc180.lib`, Blazie
  startup/API objects, and a post-link finalizer. Those historical tools are
  not present in the source archive.
- The repository already pins z88dk 2.4 and has proved it for Z180 external
  programs, but that toolchain targets add-on `.bns` applications at logical
  `0x1000`; it does not yet rebuild firmware ROMs.
- Existing `tools/rom_analyzer.py disasm` is explicitly a hex dump rather than
  an actual disassembler.

## Firmware generations verified with the current loader/analyzer

All four packages below contain a uniquely validated firmware image at package
offset `0x3000`:

| Product | Package | Package date | Package bytes | Firmware bytes | Reset jump |
|---|---|---:|---:|---:|---:|
| BNS 2000 | `roms/NFB99/BS2ENG/bs2eng.bns` | legacy 1999 corpus | 274,177 | 261,889 | `0x032F` |
| BNS 2000 | `roms/bns2000/BS2ENG.BNS` | 2003-06-24 | 274,218 | 261,930 | `0x0332` |
| TNS | `roms/NFB99/TNSENG/tnseng.tns` | legacy 1999 corpus | 273,970 | 261,682 | `0x0339` |
| TNS | `roms/tns/TNSENG.TNS` | 2003-06-24 | 273,991 | 261,703 | `0x033C` |

The 2003 BNS 2000 and TNS packages are distinct, slightly newer links than the
1999 images and are the current candidate targets. Later 2004 M20/M40 images
exist but are different Millennium products, not replacements for either
requested target.

## Observations that affect the approach

- The 2001 source tree supports multiple products through conditional builds,
  so it can supply authoritative names, structure, comments, data types, and
  hardware ownership for both targets.
- The 2003 links have moved addresses and small size changes. Directly treating
  the 2001 source as byte-identical to either 2003 ROM would be false.
- A byte-exact round trip requires preserving code/data boundaries, bank and
  linker layout, instruction encodings, padding, generated tables, and package
  length/CRC metadata. A conventional linear disassembly cannot safely infer
  all of those boundaries on its own.
- The existing emulator loader already provides an authority for extracting
  and validating the update-package boundary and CRC. It should be reused as
  evidence for any eventual ROM packaging gate.

### Measured cross-revision similarity

The current extractor produced four padded 256 KiB images under ignored
`.toolchain/analysis`. SHA-256 values are:

- BS2 1999: `4989dd9445e36fadf0a97757e26673b7bb6950053f036f408b488819668bd282`
- BS2 2003: `3186152b0a55719450a072c89acdf8baa182d85d0fb981bb1a4e17aaaa71f594`
- TNS 1999: `761a965af76f1a1ed07c849eeada67c62997ff8b31e24554868e694f8c03b30f`
- TNS 2003: `d0bb8002c81c384842db69d124d2b183cbf8ee0b7bffea59a6b0b444a1b2b00a`

A bounded block-membership probe compared each non-overlapping chunk in the
older image with every byte-aligned window in the newer image. This is not a
semantic diff and repetitive padding can inflate it, but it establishes that
the newer images are not old images with a tiny same-address patch:

| Pair | Same-address bytes | 16-byte old chunks found anywhere | 64-byte old chunks found anywhere | 256-byte old chunks found anywhere |
|---|---:|---:|---:|---:|
| BS2 1999 -> BS2 2003 | 9.13% | 33.23% | 25.63% | 21.68% |
| TNS 1999 -> TNS 2003 | 6.78% | 31.45% | 23.73% | 19.73% |
| BS2 2003 -> TNS 2003 | 7.16% | 36.60% | 26.03% | 22.75% |

Bank 0 has the best source-bearing similarity (about 31.5% of 64-byte chunks
for both cross-revision comparisons). Middle banks are much lower; bank 3 has
large shared/padded or table regions. Annotation transfer therefore needs
function/data matching and verification, not address translation.

The first diagnostic used byte-level `difflib.SequenceMatcher`; it was stopped
after repeated long polls because repetitive ROM data made it computationally
disproportionate. No result from that attempt is being used. It was replaced
by the linear-size window-membership probe above.

### Surviving build/layout facts

- `BE_ENG.PRJ` explicitly defines separate English models for `BS2ENG`
  (`BSNEW=1`) and `TNSENG` (`TNS=1`) and enumerates the mixed assembly/C object
  set.
- The project/link configuration preserves segments through physical
  `0x03FFFF`, BSS at logical `0xC000`/physical `0x040000`, message data near
  physical `0x03B000`, folders at physical `0x043E48`, and help near
  `0x03FA40`.
- Project references to `Sc180.lib`, `Scbcd.lib`, and `Scblazie.lib` are not
  satisfied by the archive: its `LIB` directory contains only `BSEQUATS.LIB`
  and `BSPORTS.LIB`.
- The locally pinned z88dk installation contains both `z88dk-dis.exe` and
  `z88dk-z80asm.exe`, with explicit `-mz180`/`-m=z180` support. A sample
  disassembly correctly decoded Z180 `OUT0` and `IN0` instructions, but linear
  decoding also interpreted copyright text and vector/data words as code.
  It therefore needs an externally maintained code/data map.

### Local round-trip qualification

A 72-byte confirmed-code range at BS2 2003 physical offsets `0x00B8..0x00FF`
was disassembled and reassembled with the pinned z88dk 2.4 tools. It includes
Z180 `IN0`/`OUT0`, `LD I,A`, absolute memory operands, and five relative
branches.

- The raw `z88dk-dis` text did **not** assemble directly: it prints relative
  branch targets as absolute numeric addresses, while standalone
  `z88dk-z80asm` treated those numeric `JR` operands as displacements and
  rejected them as out of range.
- Replacing those five destinations with one explicit local label made the
  branch encodings correct.
- The first selected disassembly range ended in the middle of a four-byte
  instruction, so `z88dk-dis` displayed a zero for the missing final operand
  byte. Extending the range to the instruction boundary recovered the actual
  `LD SP,($D41D)` operand.
- With both corrections, the assembled 72 bytes are byte-for-byte identical
  to the 2003 firmware range. This proves the core encoder/decoder can preserve
  representative Z180 code; it also proves that a direct shell pipeline would
  be unsound.

### Ghidra qualification and bank model

- Installed Ghidra is 12.0.3 (2026-02-10) and ships native
  `z180:LE:16:default` and Z182 SLEIGH languages, not merely generic Z80.
- Headless raw import and auto-analysis of the complete BS2 2003 64 KiB bank 0
  succeeded under `z180:LE:16:default` in about three analysis seconds.
- Ghidra is therefore suitable for interactive disassembly, cross-references,
  function recovery, types, and decompilation. It is not the canonical
  reassembly format: the firmware is a 256 KiB physical image executed through
  a 16-bit Z180 MMU, so later physical banks need explicit overlay/logical-map
  treatment instead of one flat 16-bit program.

The source itself confirms the bank complication: it uses Softools banked-code
runtime symbols and dynamically programs CBAR/CBR/BBR. The surviving project
places banked code through physical `0x03FFFF`, but execution operands remain
16-bit logical addresses under changing maps.

### Archive-manifest check

The four dated source ZIP manifests were searched for `.obj`, `.bin`, map,
symbol, listing, executable, and library artifacts. There is no hidden
firmware build, object corpus, linker map, or symbol file. The only relevant
binaries are `BSEQUATS.LIB`, `BSPORTS.LIB`, and the updater-builder
`BEUPDATE.EXE`; the proprietary compiler/runtime/Blazie libraries remain
absent. This closes the easiest possible source-to-symbol recovery path.

### Primary tool documentation checked

- z88dk's official current documentation describes `z88dk-dis` as supporting
  Z180 and accepting a z80asm map file for symbols; its documented interface
  does not provide code/data control ranges or promise assembler-ready output.
- z88dk 2.4 is the current pinned release and explicitly adds local-label
  support to z80asm.
- SkoolKit 10.0 provides a strong model for a durable annotated disassembly:
  control files distinguish code, byte data, text, words, and unused regions;
  annotations can produce both browsable HTML and assembler-facing source;
  execution maps can improve code/data classification.
- SkoolKit's documented processor and simulator surface is Z80/Spectrum, with
  warnings that variant opcode sequences may not reassemble to original bytes.
  No documented Z180 extended-opcode mode was found. It is therefore useful as
  a design reference, not a drop-in decoder for this firmware.

## Residual implementation questions

No external blocker prevents the recommended first milestone. Implementation
would still need to establish:

1. how much of each 2003 image can be aligned to the 2001 source/link structure;
2. which modern disassembler/assembler pair can express all Z180 encodings and
   reproduce arbitrary bytes without hidden normalization;
3. whether bank boundaries and relocation/layout facts can be recovered from
   surviving linker inputs or must be represented in a generated manifest;
4. whether a first byte-exact round trip can be demonstrated without claiming
   semantic annotation completeness.

Question 2 is partially answered: pinned z88dk is viable underneath a
control-map exporter, but the full instruction corpus and ambiguous/alternate
encodings still need an automated whole-image byte gate. Question 4 is also
partially answered: exact byte preservation is easy for data and demonstrated
for representative code, while correct full-image classification remains the
hard part.

The ignored diagnostic directory was initially missing, so the first extraction
failed before writing a file. After creating that exact directory, the same
extractor command succeeded for all four packages. This was a procedure error,
not a ROM/tool failure.

## Recommendation

### Targets

Start with exactly two independently round-tripped targets:

1. `roms/bns2000/BS2ENG.BNS`, the 2003-06-24 Braille 'n Speak 2000 package
   from the 2002 Summer Notetaker Update. Package SHA-256 is
   `9EE0AF633BEB744C3905E9E3A940C13873FA05FAAEE5EE6442F2F96CFC1D004D`;
   extracted/padded ROM SHA-256 is
   `3186152B0A55719450A072C89ACDF8BAA182D85D0FB981BB1A4E17AAAA71F594`.
2. `roms/tns/TNSENG.TNS`, the corresponding 2003-06-24 Type 'n Speak
   package. Package SHA-256 is
   `FBCBEF25734BEDE87B36C4A2E0EF7B22D7E9884C91ED7D7C950982B31336F946`;
   extracted/padded ROM SHA-256 is
   `D0BB8002C81C384842DB69D124D2B183CBF8EE0B7BFFEA59A6B0B444A1B2B00A`.

These are the newest supplied classic-platform revisions for the two requested
products and both already execute under their exact QNS hardware profiles.
The 2004 M20/M40 payloads are newer in date but belong to the different
Millennium hardware/package family. BNS 640 and Braille Lite variants should
be later targets, not silently folded into either first target.

### Canonical architecture

Use three distinct authorities rather than asking one tool to do incompatible
jobs:

1. **Immutable input authority:** original updater package plus recorded
   package/image sizes, extraction offset, CRC, padding rule, and hashes.
2. **Version-controlled annotation/layout authority:** one target directory
   per ROM containing physical-bank layout, logical MMU view(s), code/data/text/
   word/fill ranges, symbols, comments, and provenance back to surviving source
   files. This should be a small text control format inspired by SkoolKit; it
   must be the durable source, not a Ghidra project database.
3. **Generated views:** Ghidra imports/overlays for interactive analysis,
   readable annotated assembly/HTML, and strict z88dk assembly used only for
   rebuilding.

The generated assembly must use real instructions only for confirmed code.
Data, padding, unresolved regions, ambiguous instruction encodings, compiler
tables, and any bytes whose mnemonic normalizes differently must remain exact
byte directives until classified. Relative branches must be emitted as labels,
not copied from `z88dk-dis`'s numeric output.

Build each 64 KiB physical bank independently with pinned
`z88dk-z80asm -m=z180_strict -no-synth`, join the four bank outputs, trim only
the loader-proven package padding, and require the extracted-image SHA-256.
The strict assembler mode reproduced the qualified 72-byte sample with the
same SHA-256 as non-strict mode. Rebuild the package by preserving its updater
prefix and applying the existing source-backed length/CRC algorithm, then
require the original package SHA-256 for an unchanged round trip.

Expose only three user workflows after the format exists:

```text
uv run <rom-tool> decompile bs2-2003
uv run <rom-tool> build bs2-2003
uv run <rom-tool> verify bs2-2003
```

The same commands must work for `tns-2003`. `verify` must check bank outputs,
firmware length/hash, package CRC/hash, and a bounded QNS boot/runtime gate.
Generating source is not success unless the unchanged image is byte-exact.

### How to use the surviving source

Treat the May 2001 mixed C/assembly tree as the annotation oracle, not as the
canonical build input. Transfer names/comments only when a binary signature,
call graph, referenced string/table, or runtime trace verifies the match. Keep
provenance per symbol so a later reviewer can distinguish original-source
names, high-confidence transferred names, and newly inferred names.

The current Softools vendor still sells SC180-WIN and publishes a 30-day demo,
so that toolchain may be useful for studying ABI/code-generation and parsing
the old project. It cannot be assumed to reproduce these ROMs: the vendor says
the Windows compiler generates 10-20% less code than the older DOS version;
the custom Blazie libraries are absent; and the target binaries postdate the
source snapshot by about two years.

### Runtime-guided recovery with z-core and QNS

This materially improves the proposal. `../z-core` Phase 7 is already more
than a CPU implementation that could someday be instrumented:

- Its instruction trace records `(cycle, logical PC, physical PC, fetched
  bytes, length)` at instruction entry. The physical PC is the Z180 MMU result,
  and the byte array contains the bytes actually fetched without adding bus
  reads.
- Its event stream records logical PC plus physical address for watched memory
  accesses and ROM writes, logical PC plus port for I/O, and cycle/source/vector
  for IRQ acknowledgement; traps carry their logical PC and fetched opcode.
- Its disassembler uses the same seven-page opcode tables as execution and is
  total over arbitrary bytes, emitting `DB` for undefined or truncated forms.
- Its verification record ties opcode, MMU, interrupt, I/O-register, timer,
  serial, DMA, and timing behavior to exact sections of Zilog UM0050. The
  manual can therefore establish architecture facts rather than merely suggest
  interpretations.

QNS contributes the other half: model-specific banking and ports plus
observable firmware meaning. Its profiles and devices identify keyboards,
displays, speech, serial channels, flash, RTC, PIC, gauge, and power latches.
Its existing end-to-end harnesses already exercise BS2 initialization, the
command loop, help, dictionary, editor/external-program handling, file menus,
YMODEM, persistence/restart, PC-disk transfers, speech, and display output.
TNS has proven keyboard/PIC, modifier, port-ownership, command-loop, and speech
boundaries, but substantially fewer full product workflows than BS2.

The supplied July 1999 firmware help files are unusually useful scenario
catalogs. BS2 has 26 named functional sections and TNS has 27, covering writing
and reading, line editing, menus, find/global search, macros, speech, files and
folders, status/parameter/option menus, transfer protocols, printing, datebook,
phone book, formatter, spellcheck, calculator, stopwatch, disk, and other
functions. BS2 and TNS describe almost the same firmware capabilities through
different keyboard command surfaces. They predate the 2003 target images, so
they establish a common baseline rather than an exact complete specification;
the 2000 source change logs, 2003 ROM strings/menus, update documentation, and
runtime observation must identify the later delta.

The combined discovery loop should be:

1. Drive one deterministic user/manual scenario in QNS.
2. Capture executed physical instruction ranges and edges, logical-to-physical
   mappings/MMU changes, interrupts, I/O, selected data accesses, speech,
   display, serial, and other host-observable events.
3. Correlate the event sequence with the product manual's named operation.
4. Promote executed bytes to confirmed code and instruction boundaries;
   transfer names from the 2001 source only where signatures, calls, strings,
   tables, or observed behavior agree.
5. Feed new entry points into static traversal and Ghidra, regenerate assembly,
   and require the unchanged-ROM zero-diff gate.

Coverage must be aggregated by physical PC, not logical PC: Z180 MMU banking
can make the same logical address name different ROM bytes. Runtime mapping is
especially authoritative for bank-switch stubs, interrupt handlers, RAM-loaded
code, overlays, and instruction boundaries. It is not an authority that an
unexecuted byte is data. Error paths, optional peripherals, locale/update code,
rare interrupts, and undiscovered menu operations still require static
cross-reference work, source/revision matching, and additional scenarios.

This is not available inside QNS today. QNS still wraps the older CFFI core and
has selected watches rather than the full z-core trace. The controlling z-core
plan puts the Python binding and QNS migration in Phase 8; P8.1 is currently
blocked on the exact Python representation of `set_ext_mapper`. Once that
decision and migration land, no new CPU decoder or trace engine should be
invented for this ROM project.

### Difficulty and effort bands

The task has one easy layer and two hard layers:

| Deliverable | Difficulty | Evidence-based single-engineer band |
|---|---|---:|
| Hash-pinned extraction, four-bank byte source, strict reassembly, package rebuild, and QNS verification | Moderate | 3-7 working days; plausibly 2-5 after z-core/QNS migration |
| Bank/MMU-aware structural disassembly for both targets, with reset/vectors, confirmed code/data boundaries, useful labels, HTML/ASM generation, continuous zero-diff gate, and scripted execution maps | Hard | about 1-3 weeks after z-core/QNS migration; 3-6 weeks without it |
| Broad source-assisted and scenario-assisted annotation of major firmware subsystems and data, sufficient for productive modification | Very hard | about 1-3 months |
| Near-exhaustive semantic annotation or maintainable C-like reconstruction of most firmware | Research project | 4-9+ months |

These are not generic ROM estimates. They reflect two 256 KiB images; only
about 20-26% long-block similarity across nearby revisions; a 245,638-code-line
multi-product source corpus; no objects/maps/exact compiler or custom libraries;
and a bank-0 Ghidra trial that auto-defined only 9,980 instruction bytes plus
1,211 data bytes out of 65,536, despite finding 167 functions. The improved
bands assume z-core is migrated into QNS and manual-derived deterministic
scenarios are recorded. The estimates remain broad because scenario coverage
has not yet been measured against either complete ROM.

The practical first milestone is therefore **mechanically exact, structurally
honest, partially annotated**, not “fully decompiled.” That milestone is quite
achievable. A high-quality full annotation is the expensive part.

## Investigation completion check

1. **What is the existing annotation/source?** Answered in “Verified local
   artifacts”: it is a May 2001 mixed C/Z180 source tree, not merely one
   annotated disassembly.
2. **Which modern ROMs should be targeted?** Answered in “Targets”: the exact
   2003 BS2 and TNS packages, with package and extracted hashes.
3. **Can they compile/decompile/round-trip simply?** Answered in “Canonical
   architecture” and “Local round-trip qualification”: yes mechanically, with
   a bank-aware control format and generated strict assembly; no as a direct
   `z88dk-dis | z80asm` pipe or C decompile/recompile.
4. **What do other programs and emulators contribute?** External programs
   validate the separate application format and firmware API. z-core provides
   manual-backed physical execution tracing and decoding; QNS supplies hardware
   meaning and controllable product workflows. None replaces firmware
   annotation, and unexecuted bytes remain unclassified.
5. **Overall difficulty?** Answered in “Difficulty and effort bands,” separated
   by exact deliverable so a passing byte gate cannot be mistaken for semantic
   completion.

## Next action

Answer the user's runtime-guidance question, then decide whether the next
authorized artifact is (a) a detailed scenario/coverage plan only or (b) the
ROM round-trip implementation after the existing z-core Phase 8 migration is
unblocked and completed. Do not build a parallel trace adapter in QNS.
