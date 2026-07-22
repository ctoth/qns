# English speech-output investigation

## Objective

Produce actual English text from the SSI-263 phoneme stream emitted by the supplied Blazie firmware, without replacing the firmware or routing its text through an unrelated TTS system.

## Investigation tasks

1. Identify the exact runtime owner that receives firmware SSI-263 phoneme writes.
2. Identify the firmware/source representation that maps English messages to those phoneme sequences.
3. Determine how word, phrase, and utterance boundaries can be recognized from the runtime stream.
4. Define the smallest product output contract that can emit English without inventing words for unknown sequences.

## Findings

### `qns.ssi263.SSI263._speak_phoneme`

`SSI263.write()` reduces each firmware duration/phoneme register write to its low six-bit phoneme code and calls `_speak_phoneme()` whenever the chip is awake. `_speak_phoneme()` is the exact runtime event owner: it appends the code to `phoneme_log`, invokes the existing `(code, name)` callback, marks the chip busy, and schedules the completion interrupt. Therefore English recognition belongs as an observer of this event stream; it must not alter SSI-263 timing, interrupt scheduling, or the audio synthesizer.

This answers investigation task 1.

### `BSMESENG.C` English message objects

The authoritative English firmware source stores user-facing messages as ordinary NUL-terminated ASCII arrays, for example `say_spellcomplete[] = "done"`, rather than as precompiled SSI-263 byte strings. The English project includes `BSMESENG.C`, `BSPROCES.ASM`, `BSSPELL.C`, and `FILEP.C`; hardware variants are conditional builds of these common owners. Consequently a fixed dictionary of known startup phrases would be incomplete: the firmware can also speak filenames, editor text, and other runtime strings through its ASCII-to-phoneme translator.

This partially answers investigation task 2 and rules out a static phrase-only recognizer as the general English output owner.

### `BSSPEECH.ASM::_say` and `_get_msg`

The C-callable `_say` entry receives the source string in `DE`, preserves registers, enables display mirroring on Braille Lite builds, and calls `_get_msg`. `_get_msg` copies the NUL-terminated message—whether from ordinary RAM/low ROM or banked message ROM—into the common `SPBUF` ASCII buffer, returning its length. `_say` then calls `MSPEAK`, which owns the existing translation/speech pipeline. This is exact pre-translation English, including dynamically assembled buffers, and is more authoritative than reconstructing words from the final six-bit phonemes.

The remaining task-2 question is whether all speech-producing paths pass through `SPBUF`/`MSPEAK` or whether cursor/document speech has a separate entry that must be observed too.

### `BSSPEECH.ASM::MSPEAK`, `TALKIT`, and `MFULL3`

`MSPEAK` handles prompt/message strings already copied into `SPBUF`. `TALKIT` handles editor/document speech: it reads the active text through `ISA`/`ISB`, copies up to a carriage return or 255 characters into the same `SPBUF`, and then joins `MFULL3`. At `MFULL3`, `HL` is set to `SPBUF`, the text is saved for H-chord replay/display behavior, and `_SPMAIN` translates that ASCII into phonemes. Later live evidence proves `BC` can retain only the latest appended segment length and that the H-chord save call clobbers both register pairs before `_SPMAIN`.

Therefore `MFULL3` is the common source-independent path for both fixed messages and dynamic document text. The exact observation point is the instruction immediately after `LD HL,SPBUF`, before H-chord saving; the exact utterance is the fixed buffer's NUL-terminated content, not `BC` bytes. This preserves the existing translator, SSI-263 stream, timing, display mirroring, and audio.

This completes investigation task 2.

### `qns.cpu.Z180.get_reg` and existing PC watch

The existing CPU wrapper already exposes the live `BC` and `HL` register pairs through `get_reg(Z180.BC)` and `get_reg(Z180.HL)`. Its existing native PC watch records only hit count, cycle, and `CBAR`; it does not retain the text registers or bytes. A new generic decoder interface is unnecessary. The narrow implementation observes the existing execution/memory callback at each linked post-`LD HL,SPBUF` capture site.

### `SPTST.C::spmain`

`spmain()` is the firmware's language translator. For the English build it consumes the common text buffer prepared by `MSPEAK`/`TALKIT`, applies number and pronunciation processing, and produces the double-buffered phoneme stream later sent by the SSI-263 interrupt routine. It does not own an additional English source: its input is precisely the pre-translation `SPBUF` already identified at the call site.

This confirms that capturing the call input does not bypass later speech behavior and completes the functional trace from ASCII message/document text to final SSI-263 events.

### BSP linked `_SPMAIN` call site

The source-defined `MFULL3` instruction neighborhood occurs exactly once in supplied `bspeng.bns` at logical `0xBC98`: `LD HL,D657; XOR A; LD B,A; LD A,C; OR A; JR Z,...; LD A,(...); OR A; CALL Z,...; CALL 5915; CALL 0814`. Thus `SPBUF=0xD657`, the `_SPMAIN` call instruction is `0xBCA8`, and linked `_SPMAIN=0x5915` for BSP English. The next call target `0x0814` matches source-defined `SPON`, strengthening the identification.

The later live trace confirms this code identification but rejects the call instruction as the register-capture point; BSP capture occurs earlier at `0xBC9B`.

### BS2 and TNS linked `_SPMAIN` call sites

The same unique `MFULL3` signature identifies BS2 `SPBUF=0xD658`, call site `0xBCA7`, `_SPMAIN=0x58FD`, and following `SPON=0x0871`; it identifies TNS `SPBUF=0xD65D`, call site `0xAD7E`, `_SPMAIN=0x58E5`, and following `SPON=0x08EC`.

The signature does not match BSL/BL2/BL4 because the source conditionally inserts Braille-display and speech-enable instructions before `_SPMAIN`; those builds require their literal longer conditional signature rather than a guessed address offset.

### Braille Lite linked `_SPMAIN` call sites

The literal conditional sequence uniquely identifies all remaining builds:

- BSL: `SPBUF=0xD657`, call site `0xAD9A`, `_SPMAIN=0x57BA`, `SPON=0x0896`.
- BL2: `SPBUF=0xD658`, call site `0xBC61`, `_SPMAIN=0x57A6`, `SPON=0x08E0`.
- BL4: `SPBUF=0xD65E`, call site `0xAD95`, `_SPMAIN=0x579E`, `SPON=0x0917`.

All six English profile addresses are now recovered from their actual supplied packages. Live register/buffer capture remains required before this becomes a product contract.

### Live BSP observation boundary

The native PC watch proves BSP enters `_SPMAIN` call site `0xBCA8` at cycle `1,443,916` with `CBAR=C6`. A first implementation using `cpu.instruction_pc` inside the Python memory-read callback emitted nothing despite 116 subsequent phonemes; that premise is false because the callback occurs during opcode fetch before that getter reflects the fetched instruction. The callback's physical `addr` does equal the bank-zero linked call site. Using `addr`, then validating exact `HL=SPBUF`, bounded `BC`, and the high-common MMU page, is the proven narrow capture predicate.

The H-chord-save call between `MFULL3` and `_SPMAIN` clobbers `HL/BC`; live BSP shows `HL=D657, BC=0029` immediately after `LD HL,SPBUF`, then `HL=D8B1, BC=FFFF` at the `_SPMAIN` call. The capture sites are therefore BSP `BC9B`, BS2 `BC9A`, BSL `AD86`, BL2 `BC4D`, BL4 `AD81`, and TNS `AD71`.

A second live diagnostic proved that the CPU's internal MMU state, not `Memory.cbr/cbar`, is authoritative: the latter remained `00/F0` while native execution was at `34/C6`. Logical SPBUF translation must use `cpu.cbr` and `cpu.cbar`.

### Utterance boundary and output contract

BS2 proves `BC` can describe only the most recently appended `_say_part` segment: live `BC=0x0E` accompanied the complete `initialize flash system? enter y or n ?\0` SPBUF. The actual firmware utterance boundary is the NUL written within the fixed 256-byte SPBUF. Reading through that terminator yields the complete text; a 256-byte scan bound prevents reading adjacent state, and absence of a terminator yields no event.

The product contract is therefore one text event per completed SPBUF translation, observed at the post-`LD HL,SPBUF` capture site, with exact ASCII decoded using replacement only for non-ASCII bytes. Raw CLI supports retained and streaming `english`; structured stdio emits `{"device":"speech","text":"..."}` before the corresponding phoneme events. Unknown/direct phoneme-only sounds produce no invented English.

This answers investigation tasks 3 and 4.

## Phase review

1. Runtime phoneme owner — answered by `qns.ssi263.SSI263._speak_phoneme`: “`_speak_phoneme()` is the exact runtime event owner: it appends the code to `phoneme_log`, invokes the existing `(code, name)` callback, marks the chip busy, and schedules the completion interrupt.”
2. English-to-phoneme representation — answered by `BSMESENG.C English message objects` and `BSSPEECH.ASM::MSPEAK, TALKIT, and MFULL3`: “The authoritative English firmware source stores user-facing messages as ordinary NUL-terminated ASCII arrays” and “`MFULL3` is the common source-independent path for both fixed messages and dynamic document text.”
3. Utterance boundary — answered by `Utterance boundary and output contract`: “The actual firmware utterance boundary is the NUL written within the fixed 256-byte SPBUF.”
4. Smallest non-inventing output contract — answered by `Utterance boundary and output contract`: “Unknown/direct phoneme-only sounds produce no invented English.”

Every investigation task has a documented answer. The reverse-engineering phase is complete.
## 2026-07-20 legacy updater executable extraction

### Corpus and container boundary

The active corpus is the 11 updater executables in `reports`: `M20_V45.exe`,
`M40_V45.exe`, `m20.exe`, `m40.exe`, `tlt.exe`, `tns.exe`, `blt18.exe`,
`blt40.exe`, `blt2000.exe`, `bns640.exe`, and `bns2000.exe`. All are distinct
by SHA-256.

`7z l -slt` proves that `M20_V45.exe`, `m20.exe`, and `bns2000.exe` are x86
WinZip self-extracting PE files with an embedded ZIP payload beginning after the
61,440-byte executable image. `blt18.exe` is an older ZIP self-extractor with a
23,102-byte stub that 7-Zip can read directly despite not accepting the stub as
a PE archive. Running the executables is unnecessary for extraction.

The embedded system updater payloads proven so far are:

- `M20_V45.exe` -> `M20ENU-U.BNS`, 481,798 bytes, modified 2004-04-08.
- `M40_V45.exe` -> `M40ENU-U.BNS`, 481,798 bytes, modified 2004-04-08.
- `m20.exe` -> `BLM20ENU.BNS`, 371,795 bytes, modified 2003-01-23.
- `m40.exe` -> `BLM40ENU.BNS`, 371,794 bytes, modified 2003-01-23.
- `tlt.exe` -> `TLTENU.BNS`, 371,504 bytes, modified 2003-01-23.
- `tns.exe` -> `TNSENG.TNS`, 273,991 bytes, modified 2003-06-24.
- `bns2000.exe` -> `BS2ENG.BNS`, 274,218 bytes, modified 2003-06-24.
- `bns640.exe` -> `BSPENG.BNS`, 274,215 bytes, modified 2003-06-24.
- `blt18.exe` -> `BSLENG.BNS`, 274,374 bytes, modified 2003-08-29.
- `blt40.exe` -> `BL4ENG.BNS`, 274,355 bytes, modified 2003-06-24.
- `blt2000.exe` -> `BL2ENG.BNS`, 274,362 bytes, modified 2003-06-24.

The other `.bns` members in these executables are external programs, not the
system updater: their names and sizes identify utilities such as `doc2txt`,
`email`, `mailer`, `bsname`, and games. The system updater is the product-named
payload accompanied by its product help/update documentation.

Current unknowns are the exact embedded updater names in the remaining seven
executables, whether the two Millennium `.BNS` formats retain the established
`BNS`/`0x3000` firmware boundary, and which existing or new QNS profile each
requires. The next action is to list one remaining executable at a time and
append its exact system payload here before extraction.

### M20_V45 extraction

`7z x reports\M20_V45.exe M20ENU-U.BNS -oroms\M20_V45` extracts exactly the
manifested 481,798-byte payload without executing the updater. The extracted
SHA-256 is `FAFDB088C3222937F1B44736627A43FEA22C277CC8CAB1869A83D670F10E9A60`.
Its first bytes are `18 18 42 4E 53 00 ...`, preserving the BNS package magic,
but Z180-looking code begins at file offset `0x1A`; this is not evidence for the
classic fixed `0x3000` firmware boundary. The exact Millennium package layout
must be established before loading or stripping it.

### M40_V45 extraction

`M40ENU-U.BNS` extracts to `roms\M40_V45` at the exact manifested 481,798-byte
size with SHA-256
`DC50BB3D871E6C33562F29B94734351588B668F2D7CAC045D2BA5BD2531AB1CC`.
It has the same `18 18 BNS` header and code-at-`0x1A` shape as M20_V45, while
remaining byte-distinct. The shared Millennium package boundary is therefore a
two-product observation, not yet a loader rule.

### m20 extraction

`BLM20ENU.BNS` extracts to `roms\m20` at 371,795 bytes with SHA-256
`E56B86456B1CFB894B950AF0784B446C6F88BAF54E143130FAE28C3F2A0DB6FD`.
It also begins `18 18 BNS`, has zero-filled header bytes through `0x19`, and
begins executable-looking Z180 bytes at `0x1A`. This independently confirms the
same package shape in the earlier 2003 Millennium generation.

### m40 extraction

`BLM40ENU.BNS` extracts to `roms\m40` at 371,794 bytes with SHA-256
`DAAFE2F9DADEC4B201FA2AA2BA7AD9330FDCDF207D6079A26AE4E17506BA1E15`.
Its header and offset-`0x1A` code shape match `BLM20ENU.BNS`; the two payloads
remain byte-distinct and preserve their 20-cell versus 40-cell provenance.

### tlt extraction

`TLTENU.BNS` extracts to `roms\tlt` at 371,504 bytes with SHA-256
`1CBDC50519CCC7DFA2F8C5F1206AD44FC9EA108F7B1F4B4FEFCFBC610015531C`.
It shares the Millennium `18 18 BNS` header and offset-`0x1A` code boundary,
while its header addresses and body are distinct from both Millennium Braille
Lite payloads.

### tns extraction

`TNSENG.TNS` extracts to `roms\tns` at 273,991 bytes with SHA-256
`FBCBEF25734BEDE87B36C4A2E0EF7B22D7E9884C91ED7D7C950982B31336F946`.
It begins `18 0C BNS` and then updater-program bytes, matching the classic TNS
package shape rather than the Millennium offset-`0x1A` firmware shape. It is 21
bytes larger than the NFB99 TNS package and must be treated as a distinct 2003
revision.

### blt18 extraction

`BSLENG.BNS` extracts to `roms\blt18` at 274,374 bytes with SHA-256
`D6474F946263C14D4977277B9078448825174DBDE527ABE374767BF69A2316F9`.
It begins `18 0C BNS` and updater-program bytes, the classic package shape. It
is 64 bytes larger than the NFB99 BSL package and remains a distinct revision.

### blt40 extraction

`BL4ENG.BNS` extracts to `roms\blt40` at 274,355 bytes with SHA-256
`8AA2A3E8AE7C59893FA57F7B9D92C8DA8C9D2A3699EF4CC526606633B95C6E52`.
It has the classic `18 0C BNS` updater-program header and is 64 bytes larger
than the NFB99 BL4 package.

### blt2000 extraction

`BL2ENG.BNS` extracts to `roms\blt2000` at 274,362 bytes with SHA-256
`A55455EBB8CCC1A9720150C53823AC484FD9AA7926B43079BF5D6EA7F2BF6002`.
It has the classic `18 0C BNS` updater-program header and is 64 bytes larger
than the NFB99 BL2 package.

### bns640 extraction

`BSPENG.BNS` extracts to `roms\bns640` at 274,215 bytes with SHA-256
`FF0738FE2B041FC6846F316E6EBE2B1FD67F10BDB99827DFBF1EA2887D14D41C`.
It has the classic `18 0C BNS` updater-program header and is 41 bytes larger
than the NFB99 BSP package.

### bns2000 extraction

`BS2ENG.BNS` extracts to `roms\bns2000` at 274,218 bytes with SHA-256
`9EE0AF633BEB744C3905E9E3A940C13873FA05FAAEE5EE6442F2F96CFC1D004D`.
It has the classic `18 0C BNS` updater-program header and is 41 bytes larger
than the NFB99 BS2 package.

All 11 executable system payloads are now extracted, size-verified, hashed, and
documented. Five Millennium/Tiny Lite payloads require a new proven package and
hardware contract; six classic 2003 revisions can next be checked through their
existing `tns`, `bsl`, `bl4`, `bl2`, `bsp`, and `bs2` profiles.

### bns640 BSP runtime

The extracted 2003 `BSPENG.BNS` runs unchanged with `--model bsp`. QNS strips
the established `0x3000` updater prefix, loads 261,927 firmware bytes, executes
20,000,000 cycles, produces 116 phonemes, reaches PC `D656`, and has live MMU
`CBR=34 BBR=00 CBAR=C6`. Exact-English output is empty because the current
observation address belongs to the later NFB99 link; that is a revision-specific
instrumentation gap, not a boot failure.

### bns2000 BS2 runtime

The extracted 2003 `BS2ENG.BNS` runs unchanged with `--model bs2`. QNS strips
the `0x3000` prefix, loads 261,930 firmware bytes, executes 20,000,000 cycles,
produces 88 phonemes, and halts in its initialization dialogue at PC `1BF1`
with MMU `34/24/C6`. This differs from the later NFB99 linked prompt address
and again leaves the exact-English observer silent, but establishes executable
firmware progress through speech to a stable firmware wait.

### blt18 BSL runtime

The extracted 2003 `BSLENG.BNS` runs unchanged with `--model bsl`. The loader
extracts 262,086 bytes at `0x3000`; after 20,000,000 cycles the firmware has
completed its CSI/O Braille-display handshake and reached PC `D656` with MMU
`34/00/C6`. It retains seven pause phonemes, matching the display-oriented BSL
startup contract. The later-link exact-English observer does not fire.

### blt2000 BL2 runtime

The extracted 2003 `BL2ENG.BNS` runs with `--model bl2`. The loader extracts
262,074 bytes at `0x3000`; after 20,000,000 cycles it has produced 10 phonemes
and is halted at PC `1DE6` with MMU `34/30/C6`, an initialization wait rather
than an illegal-opcode or reset failure. Full cold-start advancement still
requires the profile's existing power-on-input dialogue gate; this bounded run
establishes loader/CPU/peripheral compatibility only.

### blt40 BL4 runtime

The extracted 2003 `BL4ENG.BNS` runs with `--model bl4`. The loader extracts
262,067 bytes at `0x3000`; after 20,000,000 cycles it has produced 10 phonemes
and is halted at PC `1FE8` with MMU `34/2A/C6`. Like BL2, this is the expected
class of cold initialization wait and requires the existing power-on-input path
for full dialogue advancement; there is no illegal opcode or reset loop.

### tns 2003 runtime

The extracted 2003 `TNSENG.TNS` runs unchanged with `--model tns`. The loader
extracts 261,703 bytes at `0x3000`; after 20,000,000 cycles it has produced 118
phonemes and reached its command-loop region at PC `D65C` with MMU `34/00/C6`.
The later-link exact-English observer does not fire, but the firmware is live
and executing through the modeled Type 'n Speak hardware profile.

The six classic 2003 executable-updater payloads now all load and execute under
their exact existing profiles. BSP, BSL, and TNS reach command-loop regions;
BS2, BL2, and BL4 reach stable spoken initialization waits. No classic-family
source change is required for bounded execution. Revision-specific linked
instrumentation and full prompt-driven cold-start completion are separate from
the loader/profile compatibility established here.

### Millennium updater entry at logical 0x1000

Headless Ghidra imported the first non-wrapping logical bank as Z180 with file
offset zero mapped to `0x0FE6`; the `18 18` header JR therefore lands exactly at
logical `0x1000`. Decompilation proves this is an external updater-program
entrypoint, not a ROM reset image.

The entry disables interrupts, establishes stack `0x4398`, sets `CBAR=0x41`,
preserves the active `BBR`, makes `CBR` follow that bank, initializes local
runtime/relocation state around `0x3D8B..0x3D91`, and later restores/changes CBR
through a bank table. It calls runtime owners at `0x3B98` and `0x3D11`, then
dispatches to `0x11AB` when byte `0x3E16` equals one or to `0x208B` otherwise.
This banked external-program setup contradicts treating bytes after `0x1A` as a
bootable ROM beginning.

Ghidra warnings about missing low-memory callees are expected because this
temporary image contains the updater and its high logical bank, not the host
Millennium ROM API below `0x0FE6`. The next function is `0x208B`, the normal
entry dispatch selected by this wrapper; it must be documented before following
its update/flash callees.

### Millennium normal updater workflow at 0x208B

The `0x208B` decompile is partially noisy because Ghidra follows banked data as
code after an overlapping instruction near `0x213F`. The coherent updater
control flow is nevertheless explicit and string-backed:

1. It presents the Millennium 20 identity, eligibility, destructive-update,
   side A/B/both, and confirmation prompts.
2. It announces validation, enters a DI-protected device phase through
   `0x3374`/`0x3378`, and calls `0x318B` with the three-word source tuple at
   globals `0x3E74`, `0x3E76`, and `0x3E78`.
3. It compares the validation result against global `0x3E7C`, records selected
   side/state in `0x3E80..0x3E85`, and follows error or continue prompts.
4. The accepted path prepares the selected side through `0x24D7`, `0x2CC0`,
   `0x2F14`, and `0x2FD0`, validates through `0x30A1`, then enters the actual
   erase/program/verify phase.
5. The byte-copy loops obtain source bytes through `0x1F27` using a banked
   address that increments across 64 KiB boundaries. One path emits bytes
   through `0x32C1` between device-entry `0x3381` and device-exit `0x338A`.
   A second path stages blocks around `0x3E9B`/`0x3EAB`.
6. Completion reaches `0x3357`/`0x3349`; earlier error/abort paths speak the
   validation failure or restart guidance.

This proves the embedded image is addressed by a banked source tuple rather
than a fixed file offset. The next function is `0x1F27`, because its mapping
from the tuple/incrementing logical address to a payload byte can recover the
physical embedded-firmware boundary without guessing.

### Banked source-byte owner at 0x1F27

`0x1F27` is exact and small:

```c
CBR = high_byte(source_bank_word);
return memory[0xF000 | (offset_high << 8) | offset_low];
```

With the updater's established `CBAR=0x41`, this selects a 4 KiB physical
source window through CBR and reads one byte at its 12-bit offset. The caller at
`0x208B` increments the offset and increments the bank word on 4 KiB rollover.
The embedded image is therefore stored as a contiguous sequence described by
an initial `(offset, bank, length/checksum)` tuple, not compressed or decoded by
this read owner.

The next decision-relevant target is the initialization/xrefs for globals
`0x3E74`, `0x3E76`, and `0x3E78`, because those values seed the source tuple and
will convert the banked physical location into the exact updater-file offset.

### Source tuple ownership narrows to the BNS loader

Ghidra finds only reads of `0x3E74`, `0x3E76`, and `0x3E78`: one set in the
main workflow and repeated sets in `0x22F3`. There are no direct updater-code
writes to any tuple word. The bytes at the naive linear file mapping for those
logical addresses are all `0xFF`, confirming that these globals are not static
initialized data at that file offset.

The tuple is therefore populated indirectly by the external-program loading or
runtime contract (or an indirect library call), not by a literal initializer in
the updater. The exact next authority is the classic BNS external-program
loader/parser in the supplied source, because its handling of the extended
`18 18 BNS` header and appended banked data can map these runtime globals back
to file offsets without inventing a format.

### Source-defined update package boundary corrects the earlier premise

`C:\Users\Q\src\bns\update\BEUPDATE.C` is the authoritative package builder.
It parses the standard first 14 header bytes (`JR`, ID, code size, program
length, program CRC, stack), copies the external updater program, pads the
output to the configured 4 KiB-aligned `IMAGE_OFFSET`, appends the raw firmware
unchanged, then writes the firmware's 32-bit little-endian length and 16-bit CRC
into the six bytes immediately preceding `IMAGE_OFFSET`.

The 26-byte Millennium entry layout does not change that outer package format:
its extra 12 bytes are part of the updater program copied after the standard
14-byte header. The entry at `0x1A` proves how that updater runs, not where the
appended firmware begins. All supplied update projects after the recorded April
1999 change define `IMAGE_OFFSET=0x3000`; the builder rejects an updater program
that would overlap it.

`BUPDATE.C` independently consumes the same contract: it asks the host API for
the physical address corresponding to logical `IMAGE_OFFSET + 0x1000`, reads
the image length/CRC at `image-6`, validates every appended byte, and programs
the image verbatim. Thus the previous claim that the Millennium packages could
not use `0x3000` was wrong. The next check is the five files' own six-byte
metadata at `0x2FFA`; only matching length/CRC evidence authorizes extraction
through the existing loader.

### M20_V45 rejects 0x3000 and defines the candidate test

Current-file inspection shows `M20ENU-U.BNS[0x2FFA:0x3000]` is entirely `FF`,
so it contains neither a 32-bit image length nor a 16-bit CRC at that boundary.
The `0x3000` assumption is therefore false for this Millennium build. The local
projects establish the builder algorithm but are not the missing Millennium
project that selected its `IMAGE_OFFSET`.

The builder requires `IMAGE_OFFSET` to be 4 KiB aligned. A candidate is exact
only when its preceding four bytes equal `file_size - candidate` and the
preceding CRC equals `BEUPDATE.C::crc_byte` over every byte from the candidate
to EOF. Scanning only those source-defined candidates will recover the boundary
without guessing from strings or reset-looking bytes.

### M20_V45 exact embedded image boundary

The source-defined aligned scan yields exactly one length candidate:
`IMAGE_OFFSET=0x8000`, appended length 449,030 bytes. Its stored CRC is `D09A`;
recomputing `BEUPDATE.C::crc_byte` over all 449,030 appended bytes also yields
`D09A`. This is an exact boundary proof for `M20ENU-U.BNS`, not a signature
heuristic. The current QNS fixed-`0x3000` loader extracts the wrong bytes for
this package.

### M40_V45 exact embedded image boundary

`M40ENU-U.BNS` independently has the single exact candidate
`IMAGE_OFFSET=0x8000`, appended length 449,030 bytes, stored CRC `A03E`, and
recomputed CRC `A03E`. M20_V45 and M40_V45 therefore share the same version
4.50 package layout while preserving distinct raw images.

### m20 exact embedded image boundary

`BLM20ENU.BNS` has the single exact candidate `IMAGE_OFFSET=0x7000`, appended
length 343,123 bytes, stored CRC `5E56`, and recomputed CRC `5E56`. The earlier
2003 Millennium updater uses a 28 KiB updater prefix rather than version 4.50's
32 KiB prefix.

### m40 exact embedded image boundary

`BLM40ENU.BNS` has the single exact candidate `IMAGE_OFFSET=0x7000`, appended
length 343,122 bytes, stored CRC `4394`, and recomputed CRC `4394`. It shares
the earlier Millennium layout with `BLM20ENU.BNS`; the one-byte length
difference and distinct CRC preserve the separate 40-cell image.

### tlt exact embedded image boundary

`TLTENU.BNS` has the single exact candidate `IMAGE_OFFSET=0x7000`, appended
length 342,832 bytes, stored CRC `CCAA`, and recomputed CRC `CCAA`. All five
Millennium/Tiny Lite boundaries are now proven from their own length/CRC
metadata. A correct loader must discover this contract (`0x7000` or `0x8000`)
rather than keep the classic hard-coded `0x3000` offset or branch on filenames.

### Millennium 20 sampled runtime owner at 0x5FA0

The validated M20_V45 image's first 64 KiB was mapped directly at logical zero
in a temporary Z180 Ghidra project. The function containing the repeatedly
sampled PCs `0x5FBD`/`0x5FCC` begins at `0x5FA0`. Its decompilation does not
poll a peripheral: it compares a requested bank byte with the Z180 `BBR`, and
when they differ it saves the old BBR plus a return tuple through the stack
record rooted at `0xC000`, advances that record by three bytes, and installs
the requested BBR.

The high frequency of samples in this helper therefore reflects the firmware's
bank-switching runtime, not a wait condition and not evidence for any existing
hardware profile. The immediate hardware target remains the independently
observed repeated writes to external ports `0xF0` and `0xF1` (with `0xF2`
initialized to `0x01`). The next function to recover is an actual owner of an
`OUT0` instruction targeting that port family.

### Millennium 20 context switch owner at 0x013C

The first executed `0xF0`/`0xF1` owner begins at `0x013C`. It is a runtime
context switch, not a display protocol. It disables interrupts, writes zero to
both ports, installs `CBAR=0xC7` and `CBR=0x77`, saves the previous CBAR/CBR/BBR
and stack context under the `0xD024` runtime record, and selects `IL=0x40`.
On the return path it restores the saved MMU/interrupt context and writes the
two bytes of runtime word `0xD02D` back through ports `0xF0` and `0xF1`.

This matches the observed steady MMU state and explains why those two writes
dominate the trace: they are context-extension state, not a polled peripheral.
Ignoring their write-only state does not itself explain the lack of speech.
The same analyzed image contains literal speech writes to port `0x90` at
`0x1E2B` and `0x1E89`, while the temporary BSP profile maps SSI-263 at `0xC0`.
The next bounded experiment is therefore the existing BL4/TNS-class `0x90`
speech mapping, without yet claiming their keyboard/display maps for M20.

## 2026-07-20 whole-app cleanup survey (in progress)

Goal: plan a beautification/DRY/modularization pass over the whole program.
Read so far: bns.py (1413), io.py (719), cpu.py (372), ssi263.py (339),
memory.py (242), stdio.py (115), synth/{__init__,ssi263_synth,ssi263_pcm,
dsp,player}. Remaining: synth/formant.py, sc01_rom.py, sc02_to_sc01.py,
phonemes.py head, tools/ + tests skim.

Observed problems (candidate plan items, not yet verified complete):

1. `BNS.__init__`/`run()` god-object: model-conditional wiring (`if model ==`
   scattered ~20x), keyboard input state machine (~250 lines of phase strings
   "down"/"up"/"tns-shift-down"...) inline in `run()`, plus tracing, stdio,
   power latches all in one class. Candidate: per-model hardware profile
   objects/dataclass registry (ports, latches, display, addresses tables
   `_KEYBOARD_INPUT_BUFFER_PHYSICAL` etc. currently 6 parallel dicts keyed by
   model), and an InputDriver class owning the chord state machine.
2. Two synth backends (`SSI263Synth` formant, `SSI263PCMSynth` PCM) duplicate
   the register-mirror protocol (write_durphon/inflect/rateinf/ctrlamp/filter,
   state dataclass, play-on-CTL-drop) with subtle differences (inflection
   masks 0x007 vs 0x807 — possible bug in formant version). Candidate: shared
   register-decode base or protocol + backend hook; fix mask discrepancy.
3. Dead/vestigial surfaces: `dsp.py` (pitch_shift has `return` before dead
   code, filter TBD) apparently unused by PCM path; `SSI263Synth` debug print
   `[SYNTH] _play_current_phoneme` and amplitude=15 HACK; `ssi263.py` has its
   own PHONEMES table while synth/ has phoneme data — duplication to check.
4. `bns.py` `main()` mixes CLI parsing, callback plumbing, output formatting
   (~260 lines). Candidate: split CLI into own module; speech formatting
   (codes/names/ipa/examples) duplicated between --speech and --speech-stream.
5. Loader logic (BNS package CRC scan) inline in `BNS.load_rom`; NOTES above
   prove Millennium packages need a discovered IMAGE_OFFSET contract — loader
   should become its own module with the source-defined boundary scan.
6. cpu.py `CFFI_AVAILABLE` stub dual-path on every method — candidate: drop
   stub or isolate. asci_debug_state 60-line dict literal duplicated.
7. io.py holds 8 unrelated device classes in one file — candidate split into
   devices/ package.

Blocker: none. Next: read formant.py, sc01_rom.py, sc02_to_sc01.py, skim
tools/tests, then write the plan.

### Millennium 20 reset owner at 0x0314

The reset vector at `0x0001` jumps directly to `0x0314`. This function selects
interrupt mode 1; clears Z180 refresh, timer, interrupt/trap, and DMA state;
writes `01` then `39` to port `0x80`; clears `CCR`; and writes `80` to port
`0x88`. After a fixed delay it installs `IL=0x20`, writes `00/00/01` to ports
`0xF0/0xF1/0xF2`, sets `BBR=0`, `CBAR=0xC7`, and `CBR=0x77`, initializes the
runtime context pointer at `0xC000`, then transfers through the bank-switch
thunk with return target `0x0372`.

This proves all five observed ports are deliberate reset/context latches. It
does not show a read dependency that the current emulator must satisfy. The
next boot-stage authority is the post-context target at `0x0372`; it precedes
any firmware speech and can identify the first actual initialization branch.

### Millennium 20 post-reset target at 0x0372

The first isolated decompilation at `0x0372` was wrong about a tail-transfer:
it created an artificial function in the middle of the real post-reset routine
and misidentified the ordinary `CALL 0x6EF0` as the bank thunk. Exact bytes
show the containing routine begins no later than `0x036F`: `CALL 0x6EEA`,
`LD (0xD006),HL`, `CALL 0x6EF0`, followed by initialization of `0xD614` and
an input from port `0xF8`.

The durable conclusion from the earlier fragment is therefore only the store
to `0xD006`; its claimed control flow is withdrawn. The next authority is a
fresh containing-function analysis beginning at `0x036F`, because the input
from `0xF8` is the first post-reset read that can change an initialization
decision.

Fresh analysis at `0x036F` identifies only the call stub to `0x6EEA`; Ghidra's
non-return inference is what prevents it from joining the following bytes into
the real initialization routine. The literal bytes remain authoritative:
execution continues at `0x0372`, initializes several runtime services, reads
port `0xF8`, compares it with `0x40`, and stores zero at `0xD60B` for values
below `0x40` or one for values at/above `0x40`. The current unmapped-port value
`0xFF` therefore selects the latter class. A bounded two-class experiment on
this exact read can determine whether the missing startup behavior depends on
the board-identification input without inventing intermediate port values.

### Millennium 20 paged-memory client at 0x52E4

The function containing `OUT0` instructions at `0x5395`/`0x5398` begins at
`0x52E4`. It performs allocation/record initialization, then writes `0x30` to
port `0xF0` and zero to `0xF1`, calls memory owner `0x3D7D` twice, and on its
exit path restores both paging ports to zero before transferring through the
runtime thunk. A separate failure path transfers with page/context data from a
record rooted at `0xD435`.

This proves `F0/F1` are active memory-page selectors: the firmware brackets
memory-owner calls with a nonzero 16-bit page value and restores page zero
afterward. QNS currently has no handlers for either selector, so all such
logical windows alias page zero.

The first follow-up premise about callee `0x3D7D` was wrong: its exact
decompilation is only a signed/unsigned byte comparison helper (it returns
either `param1-param2` or the shared sign bit). It supplies no accessed memory
range and cannot establish page granularity. The next page owner is the
separate `OUT0 F0/F1` pair at `0x543F`/`0x5442`, which must be decompiled and
documented independently.

### Millennium 20 0x7000 page-window reader at 0x3B69

The first executed `F5/F6` owner begins at `0x3B69`. For an ordinary page
number (bit 15 clear), it writes the page's high byte to `F6` and low byte to
`F5`, then reads logical address `0x7000 | (offset & 0x0FFF)`. Bit 15 selects a
separate path through `0x52E4`. This is an exact 4 KiB page-window contract:
selector `0x0100`, observed immediately before each reset, maps the `0x7000`
window to external byte address `0x100000 | offset`.

The official 2 MiB RAM plus 12 MiB flash layout occupies page numbers
`0x0000` through `0x0DFF` at this granularity. QNS currently ignores `F5/F6`,
so every selected page aliases the Z180-translated native address instead.
The next owner is the analogous function containing the second executed
`F6/F5` pair at `0x3C08`, needed to establish write semantics before a mapping
experiment.

### Millennium 20 0x7000 page-window writer at 0x3C06

The second executed owner begins at `0x3C06`. It writes a 16-bit page number's
high byte to `F6` and low byte to `F5`, then stores its byte argument at logical
`0x7000 | (offset & 0x0FFF)`. Together with reader `0x3B69`, this proves a
bijective 4 KiB read/write window. Under the reset MMU (`CBR=0x77`,
`CBAR=0xC7`), logical `0x7000-0x7FFF` reaches the CPU callback as physical
`0x7E000-0x7EFFF`; QNS must replace that native page with selected external
address `(F6:F5 << 12) | offset` for Millennium hardware.

The first executed selector is `0x0100`, which targets external RAM offset
`0x100000` inside the documented 2 MiB RAM. A minimal runtime experiment can
therefore implement this exact window and RAM capacity without yet inventing
flash programming behavior.

The exact experiment must discard the Z180 bank translation after recognizing
the live logical `0x7000-0x7FFF` window. The callback's native address is only
used to recover the low 12-bit window offset; the effective external address is
`(F6:F5 << 12) | offset`. Preserving the translated bank base incorrectly maps
selector `0x0100` to `0x1E4000` instead of `0x100000`.

With 2 MiB RAM and that exact mapping, a 20,000,000-cycle M20 V4.5 run writes
F6/F5 only five times and then never re-enters the page-window test, whereas it
continues through 49 later deliberate resets. This proves the first-boot memory
test completes; the remaining reset loop has a different owner and is the next
runtime target.

### Millennium 20 reset-vector reference at NMI 0x0066

Static xrefs to reset address `0x0000` find only the image entry point and a
conditional call from the NMI vector at `0x0066`. The NMI handler conditionally
invokes reset, conditionally dispatches `RST7`, saves runtime state, checks a
stack boundary near `0xFFF5`, and routes through scheduler helpers before
returning.

This does not prove the observed resets enter through NMI: QNS does not yet
report the last executed PCs, and an indirect return/call to zero would not
appear in static xrefs. The next authority must be a bounded executed-PC trace
capturing the immediate predecessor of the second reset-vector fetch. Static
xrefs alone cannot choose the reset cause.

### Millennium 20 executed reset transfer at 0x8FD6

An instruction-PC ring proves the first reset does not traverse NMI. After a
loop at logical `0x9112-0x912F`, execution reaches logical `0x8FF7`, `0x8FFA`,
`0x8FFD`, `0x9000`, `0x8FED`, then transfers to zero. The durable control-flow
observation ends there.

The first decompilation of `0x8FD6` was wrong because it used front-bank bytes.
The executed path has `BBR=0x28` and `CBAR=0xC7`, so logical bank-area address
`0x8FD6` fetches firmware physical offset `0x30FD6`. Raw offset `0x8FD6` is a
different bank and its function says nothing about this reset. A BBR-aware
logical image must be built before the executed owner can be decompiled.

The corrected BBR-aware image maps physical `0x2F000-0x33FFF` into logical
`0x7000-0xBFFF`. In that image, executed logical `0x8FED` is a real reset stub:
it disables maskable interrupts and transfers to reset initializer `0x0314`.
Thus the recurring boot is now proven to be a deliberate call/jump into a
banked reset routine, not a bad return to address zero. The next authority is
the actual BBR-aware code around `0x8FF7-0x9000` that precedes entry to this
stub in the execution ring.

The containing routine actually begins at logical `0x8FD0`. It invokes
`0x3C2C` with page `0x0100`, length/count `0x0100`, and pattern `0xBBBB`; calls
`0x90E1`; selects result marker `A` or `B`; invokes finalizer `0x8FF0`; then
unconditionally disables interrupts and resets through `0x0314`. The first
reset is therefore an intentional memory-initialization/test reboot.

One experimental assumption remains invalidated: logical `0x7000-0xBFFF` is
the Z180 bank area under `CBAR=0xC7`, so the CPU callback address for the page
window depends on live `BBR`, not fixed `CBR=0x77`. The temporary fixed
`0x7E000` interception may not have handled the `0x0100` test at all. The exact
callback address immediately after the executed `F5/F6` writes must be logged
before evaluating the page model.

### Millennium 20 pre-exit fragment at 0x9112

The isolated front-bank fragment previously documented here was also wrong.
With executed `BBR=0x28`, logical `0x9112` fetches firmware physical offset
`0x31112`; the raw bytes shown at offset `0x9112` and their apparent operations
on record `0xD3BA` are unrelated. No conclusion about the loop's hardware or
runtime ownership survives. The next authority is the exact physical
`0x2F000-0x33FFF` bank mapped into logical `0x7000-0xBFFF`.
# BSP calculator input investigation

`APHHELP.C` defines calculator entry as O chord followed by `c`, execution as
E chord, and exit as Z chord. Its arithmetic entry table defines plus as dots
3-4-6. The current host mapping produces the corresponding raw values:
`o=0x15`, `c=0x09`, `1=0x02`, `+=0x2C`, `2=0x06`, `3=0x12`, and `e=0x11`.
Both host newline and carriage return instead map to firmware chord `0x8D`;
raw dots 4-6 / C46 is `0x68`, so neither is the documented calculator execute
key.

In a live NFB99 BSP JSONL run, firmware reached `Braille 'n Speak ready` and
emitted `keyboard ready`. Sending batched text `oc1+2+3e` produced accepted
chords `0x15,0x09,0x02,0x2C,0x06,0x2C,0x12,0x11`, proving translation and the
press/release handshake for every character. It did not enter the calculator:
after the first digit and after each subsequent chord, firmware spoke `file is
write protected`. This isolates that run's first failure to using lowercase
host `o` (`0x15`) instead of the literal O chord (`0x55`), not to the physical
press/release handshake.

### BSP `calc()` calculator owner

`CALC.C::calc()` speaks `calculator ready`, sets both `numlock` and `calcflg`,
then loops forever around `glin(cobuf, 99)`. `glin` returns the terminating
chord through global `glincg`. Z chord exits; E chord, equals chord, the advance
bar, C46, and the TNS F1/arrow variants all call `compute()` on `cobuf`. On a
successful expression, `compute()` formats the value into `obuf`, copies it to
the insert buffer and clipboard, and speaks the numeric result before `calc()`
returns to `glin`. Thus BSP calculator execute is source-defined as E chord
`0x51`; C46 is also accepted by the calculator but is distinct from the current
host Return mapping. The next owner is `glin`/`get_line` and its line-editor
keypress wait, which determines why QNS will not present queued calculator
input.

### BSP `glin()` / `get_line()` input collector

`BSPARMS.C::glin(sptr, lim)` calls `get_line(sptr, lim, 0)`. `get_line()`
initializes the destination and waits on `glincg = keybd()` until the input
length reaches the supplied limit. A non-chord return is appended to the text
buffer. Chord returns instead drive editing and command behavior: C25 spells
the current character, C chord speaks the buffer, X chord arms control input,
B chord backspaces, and zero chord clears outside calculator mode.

The ordinary line-completion condition is `(glincg == CR && !(stat4 & 0x10))
|| glincg == ECHORD`; either return leaves the terminating value in `glincg`
for `calc()` to dispatch. Therefore calculator expression text is collected as
ordinary characters and E chord or the firmware `CR` value terminates the
line. The live stall occurs before any expression character reaches this
collector, at the `keybd()` wait or its hardware-facing caller. The next owner
to inspect is the exact `keybd()` implementation and its chord/CR constants.

### BSP `BSKEY.ASM::_keybd` keyboard owner

`_keybd` clears the Braille-key speech flag and calls `KEYIN`, the blocking
hardware-facing keyboard entry routine. It stores the returned raw byte in
`bkey`. For BSP, raw bit 6 distinguishes a chord from ordinary text. Ordinary
keys pass through `braasc`, are lowercased when alphabetic, may be spoken, and
return as an ASCII value. Chords bypass `braasc`; except for U and Q chord's
immediate mode handling, they return with the chord marker set in the integer
result and retain their raw low byte.

The calculator therefore blocks inside `KEYIN` while waiting for each physical
keypress; `get_line()` itself does not poll a separate editor or timer. The
source constants make the Enter contract exact: `ECHORD=0x151`, while both
`C46` and calculator `CR` are `0x168`, so their raw keyboard bytes are `0x51`
and `0x68`. QNS currently maps host `\n` and `\r` through the ASCII table to raw
`0x8D`; that cannot produce calculator Return/C46. The remaining runtime
question is which `KEYIN` wait/boundary corresponds to linked PC `0x1418` and
why the driver recognizes the top-level `KEYIN` caller but not this one.

### BSP `BSKEY.ASM::KEYIN` input multiplexer

`KEYIN` first consumes a running macro when one is active, including macro
pause, speech, and nested-macro commands. With no available macro key, BSP's
`KEYINM` calls `_get_key` to unbuffer one physical keyboard value. It then
handles E-chord macro unpause, one-hand decoding, macro recording, and the
special macro-control chords before returning the valid raw byte in `A`.

Calculator mode does not select a different input collector: it reaches the
same `KEYIN -> _get_key` path as the top-level command loop. The difference is
call context and timing. QNS's readiness heuristic keys off the separately
discovered top-level STARTA timer write or a stable halted CPU, neither of which
is guaranteed while `get_line -> keybd -> KEYIN -> _get_key` is polling in the
calculator. The next source owner is `_get_key`, whose wait behavior must be
matched to linked PC `0x1418` before deciding what a valid readiness signal is.

### BSP `BSKEY.ASM::_get_key` queue wait

`_get_key` tests the shared `queue_count`. While the queue is empty it loads
the background timer, executes `HALT`, calls `bg_task`, and loops to test the
queue again. Once an interrupt has buffered a key, it disables interrupts,
decrements the count, removes the two-byte key value at `queue_out`, advances
and wraps the queue pointer, returns the low raw byte in `A` and the full value
in `HL`, then reenables interrupts.

This disproves the tentative distinction that calculator input waits at a
different kind of active boundary. The same firmware `_get_key` loop contains
the same explicit `HALT` used by any caller. QNS's stable-halt readiness
predicate nevertheless rejects the live calculator wait at PC `0x1418`, so
the remaining defect lies in what QNS includes in its definition of a stable
wait (or in how it samples that state), not in calculator firmware bypassing
the halted queue wait.

### Linked NFB99 calculator wait correction

The earlier linked-HALT conclusion was wrong because the ROM search treated
`ED 76` as HALT. Z80 HALT is the single-byte opcode `76`. The exact linked BSP
`_get_key` sequence occurs uniquely at `0x1AF2`: `LD HL,DA32; LD A,(HL); OR A;
JR NZ; LD A,(D653); HALT; CALL 132F; JR 1AF2`. Its queue-count read begins at
`0x1AF5`, and its real HALT is at `0x1AFE`.

The calculator does use the shared `_get_key` empty-wait loop. QNS still cannot
use sampled stable HALT as a complete input boundary because periodic wakeups
can move the sampled PC between host chunks. The exact `0x1AF5` queue-count
read is the general readiness epoch: when that instruction observes an empty
queue, the active calculator/menu/editor caller is requesting its next key.
This is independent of the host Return defect, where `\n` and `\r` map through
the ASCII inverse table to raw `0x8D` instead of calculator C46/CR raw `0x68`.

### BSP `BSKEY.ASM::_put_key` / firmware queue ownership

The keyboard ISR does not hand a chord directly to `keybd()`. `_put_key`
increments one-byte `queue_count` and appends the two-byte key value at
`queue_in`; `_get_key` later decrements `queue_count` when an application input
reader removes that key at `queue_out`. The queue holds 64 entries on BSPLUS.

This distinguishes the two acknowledgements that the first implementation
incorrectly treated as equivalent. `_IIB` clearing proves only that hardware
transfer into the firmware queue completed. `queue_count` returning to zero
proves the application removed the key. A general input driver can safely keep
at most one firmware key queued: after initial boot readiness, start another
host chord only when `_IIB` is clear and linked `queue_count` is zero. That
contract applies to calculator, menus, editors, and other `keybd()` callers
without recognizing each caller separately.

### TNS `TNSKBX.C::get_brl()` input owner

TNS `KEYIN` calls `get_brl()` instead of using the raw classic chord directly,
but `get_brl()` obtains each PC keyboard scan through the same `get_key()`
firmware queue consumer. It then decodes modifier flags, filters key-up and
typematic codes, converts the scan to Braille, and returns the decoded command.

Therefore the linked `_get_key` empty-wait read is the common application-level
readiness authority for TNS as well as the classic BNS family. No TNS-specific
readiness adapter or calculator exception is required; the hardware-specific
press/release sequence remains in `ChordInputDriver`, while the next-key epoch
comes from the shared firmware queue consumer.

### Linked BSP calculator bypasses both recovered queue bytes

A live BSP run traced unique CPU reads of `queue_count` (`0x41A32`) through
O-chord, the option prompt, `c`, and `calculator ready`. The option prompt
reached the recovered `_get_key` wait at `0x1AF5`; no new queue-count reader
appeared after calculator entry. This disproves the conclusion above that the
linked NFB99 calculator uses that `_get_key` loop; the later source tree is not
an exact description of this linked calculator implementation.

A second live BSP run traced `_IIB` (`0x4327C`) through the same sequence. The
ISR wrote and cleared O (`0x55`) and c (`0x09`), but the calculator made no CPU
read of `_IIB` after announcing readiness. Its repeated idle/error speech while
no digit is sent confirms the calculator remains active. The remaining input
candidate is direct polling of the physical keyboard port by the linked
calculator/editor path; its exact reader PC must be recovered before changing
the readiness contract.

### Interrupt-first calculator input and physical queue addressing

Unique-PC keyboard-port tracing found no calculator polling read after
`calculator ready`; the only post-boot port reads were ISR reads for a presented
chord. Sampled HALT tracing likewise found the option prompt's `_get_key` HALT
at `0x1AFC`, but no calculator HALT. The calculator therefore waits
interrupt-first rather than announcing readiness through a pre-key queue,
port, or HALT observation.

With the readiness guard bypassed only in diagnostic trace mode, presenting
digit `1` after `calculator ready` completed the normal hardware ISR handshake
(`_IIB` received `0x02` and cleared), yet produced no CPU read at physical
`queue_count` address `0x41A32`. Since an external application can alter Z180
bank mapping while retaining the firmware's logical queue contract, the next
question is whether input-boundary discovery incorrectly froze a banked
physical queue address that is only valid in the top-level firmware mapping.

Live MMU capture falsified that physical-queue hypothesis. Top-level and
`calculator ready` speech both use `CBR=0x34`, `CBAR=0xC6`; the external
application changes `BBR` (`0x12` around c, `0x18` around digit 1), but the
linked `queue_count` logical address is in the common area selected by CBR.
Physical `0x41A32` therefore remains the correct queue address. The apparent
absence of a digit read can instead be an artifact of unique-PC suppression:
if the calculator later reuses `_get_key` at `0x1AF5`, that PC was already
logged during the option prompt. Repeated nonzero queue reads must be logged to
recover the actual first-digit consumption order.

Repeated nonzero tracing proved both c and digit 1 are consumed by the same
linked `_get_key` path at `0x1AF5` / `0x1B03`. The actual ownership boundary is
therefore application consumption, not ISR acceptance: `_IIB` clearing only
proves the chord entered firmware, and calculator initialization can clear an
already queued first digit before `_get_key` reads it.

The general fix retains one logical host character until `_get_key` observes a
nonzero queue. If firmware inserted the character but returns the queue to zero
without that observation, the driver repeats the same physical chord. A live
single-event `Oc1+2+3E` run then produced `6`. A second expression, `4+5\n`,
wrote and accepted raw chord `0x68` (decimal 104) and produced `9`, proving host
Return maps to firmware C46/CR rather than raw inverse-table `0x8D`.

## WinDisk / PC serial filesystem protocol recovery

### `WDComm.dll::CWDComm::getWhoWhat` identity exchange

The original WinDisk 2001 installer was recovered from the archived DB
Techies distribution. Its `WDComm.dll` is 49,152 bytes with SHA-256
`9DF35738FF28C211039DD152881CD030F4DC71C22CA7B869E678872740ECAF62`.
The DLL retains Microsoft C++ export names for its protocol owners.

`CWDComm::getWhoWhat` is exported at RVA `0x4980` (loaded address
`0x10004980`). It initializes the serial line when necessary, then repeatedly
sends the exact three-byte request `05 04 57` and waits up to one second for
an exact two-byte reply. Byte zero is accepted only in the inclusive range
`1..11` and becomes the notetaker device type. Byte one is accepted only in
the inclusive range `1..5` and becomes the notetaker baud-rate code; the
function converts that code to the host communication driver's baud enums.
Only a valid device type, valid baud code, and supported converted baud mark
the connection identified. The outer attempt window is five seconds.

The request therefore reads as an ENQ-prefixed WinDisk identity operation:
`ENQ (0x05), EOT/function introducer (0x04), 'W' (0x57)`. The two-byte reply
is binary metadata, not a pathname or text response. This proves the exact
WinDisk discovery boundary but does not yet prove any folder or file command
grammar. The next protocol-owning function to recover is the exported
`CWDComm::enumFolder`, which must reveal the first directory request and its
record framing.

### `WDComm.dll::CWDComm::enumFolder` directory exchange

`CWDComm::enumFolder` is exported at RVA `0x2F30` (loaded address
`0x10002F30`). Its string parameter is copied into the object's command
buffer, followed by one carriage return. The function sends the exact
three-byte operation prefix `05 04 46` and then sends the path bytes plus the
carriage return; it does not send the trailing NUL. Thus the directory
request grammar is `ENQ, EOT/function introducer, 'F', path, CR`.

The first reply field is exactly two bytes and is interpreted as a
little-endian unsigned entry count. A zero count is a successful empty
directory. For each nonzero entry the function reads exactly 31 bytes. The
record layout recovered from the local stack offsets is:

- bytes `0..20`: NUL-terminated filename field;
- byte `21`: file type, treated as invalid when greater than `3`;
- bytes `22..25`: four-byte size field, reordered into a host 32-bit value;
- bytes `26..30`: five one-byte date/time components passed to
  `buildSystemTime`.

The name, type, size, and converted timestamp are appended to WinDisk's item
vector. A missing 31-byte record ends the serial line and returns `-41`.
Invalid record metadata changes the object's per-item status but does not by
itself change the fixed record length.

After the two-byte count and after every 31-byte record, `enumFolder` calls
`CWDComm::nextFunctionCharSend`. A return of `2` retries the same record index;
a return of `3` ends the serial line and returns `-42`; a return of `1`
continues. The exact control bytes are not inferred here. The next
protocol-owning function to recover is `nextFunctionCharSend`, because its
control exchange is part of the directory framing.

### `WDComm.dll::CWDComm::nextFunctionCharSend` record control

`CWDComm::nextFunctionCharSend` is exported at RVA `0x4F70` (loaded address
`0x10004F70`). It maps the object's current record status directly to one
single-byte host-to-notetaker control character:

- status/return `1`: send ASCII `C` (`0x43`) to continue;
- status/return `2`: send ASCII `R` (`0x52`) to retry the current record;
- status/return `3`: send ASCII `X` (`0x58`) to cancel.

Any other status sends nothing and returns `-65`. The helper contains no
receive operation. This completes the unresolved `enumFolder` control
framing: WinDisk acknowledges the count and each fixed 31-byte directory
record with `C`, requests retransmission with `R`, or aborts with `X`.

The next protocol-owning function to recover is `CWDComm::receiveFile`, which
must establish whether and how a selected notetaker file becomes an ordinary
host file.

### `WDComm.dll::CWDComm::receiveFile` guest-to-host file transfer

`CWDComm::receiveFile` is exported at RVA `0x3710` (loaded address
`0x10003710`) and accepts two strings. The first is copied into the remote
command buffer and carriage-return terminated; the second is retained as the
ordinary host destination pathname.

After the identity exchange when needed, the function sends exact operation
prefix `05 04 53`, then `remote path, CR`, then one additional NUL byte. It
configures the bundled `XYDRV32` transfer driver, starts that driver in receive
mode, and writes the transferred body to the retained host pathname. The file
body is therefore carried by the X/YMODEM driver rather than by WinDisk's
31-byte directory-record framing. The function restores the serial-line mode
after the transfer and returns the transfer driver's result; serial property
setup failure returns `-64`.

This proves that one notetaker file can be materialized as a normal host file,
but it does not yet prove the reverse host-to-notetaker operation. The next
protocol-owning function to recover is `CWDComm::sendFile`.

### `WDComm.dll::CWDComm::sendFile` host-to-guest file transfer

`CWDComm::sendFile` is exported at RVA `0x38F0` (loaded address
`0x100038F0`) and accepts two strings. The first is retained as the ordinary
host source pathname. The second becomes the remote destination path and is
carriage-return terminated.

After the identity exchange when needed, the function sends exact operation
prefix `05 04 52`, then `remote path, CR`. It requires exactly one reply byte
within five seconds, and that byte must be `0x05`; a missing byte returns
`-41`, while any value other than `0x05` returns `-42`. After the readiness
byte it configures the bundled `XYDRV32` transfer driver, starts that driver in
transmit mode, and sends the retained host file. Serial property setup failure
returns `-64`.

WinDisk therefore supports both directions using normal host pathnames:
directory metadata through its custom fixed-record exchange, and file bodies
through X/YMODEM. This still does not make a host directory directly visible
inside the notetaker's ordinary file menu; it proves a host program can
enumerate the guest filesystem and copy files in either direction while the
firmware is in WinDisk mode.

The remaining architectural decision is whether WinDisk mode can satisfy the
requested `--state-dir` semantics or whether the emulator must instead expose
a host directory to the firmware as its older external PC Disk device. These
are directionally different protocols and must not be conflated.

### `BS2ENG::upload_download` external Disk Drive owner

The NFB99 BS2 bank-one image is mapped at its linked logical base `0x4000`.
The routine before the external-disk owner returns at `0x60DD`; the owner
begins at `0x60DE`, allocates `0x8c` bytes of compiler stack frame, and returns
at `0x677B`. This exact boundary contains the previously observed disk probe
near `0x671F` and replaces the earlier unresolved entry-point estimate.

This is the combined upload/download owner rather than a one-byte serial
primitive. Its high-level branches choose ordinary serial transfer or the
external Disk Drive path, choose transfer direction/mode, and dispatch to the
corresponding block-transfer helpers. The disk path contains literal command
bytes `Y` (`0x59`), `S` (`0x53`), and `R` (`0x52`). The observed branches are:

- one direction sends `Y`, then `S`, then bytes from the firmware buffer at
  `0xD9BC` through the shared single-byte sender at `0x22CF`, and terminates
  the string with carriage return;
- the other direction sends `Y`, then `R` before entering its selected
  transfer helper;
- a final disk exchange at `0x671F..0x676A` uses literals `0x05`, `Y`, and `E`,
  retries the exchange twice while the resulting status is `0xFF`, and reports
  a remaining nonzero status through the firmware error path;
- the common tail restores transfer/serial state, conditionally restores the
  active channel, and returns at `0x677B`.

The function also confirms that the firmware treats the Disk Drive as an
active command/transfer peer, not as WinDisk's host-side view of guest files.
However, Ghidra's decompilation does not preserve enough Z80 calling detail to
label the `0x230F` operations around literals `0x05` and `E` as sends,
receives, or expected-value reads. Assigning those meanings here would be an
inference rather than recovered protocol.

The next protocol-owning function to recover is therefore the bank-zero helper
at logical `0x230F`. It must be documented before following another callee or
claiming the complete external-disk probe grammar.

### `BS2ENG::ftran_send_wt` send-and-receive wrapper

The bank-zero helper at logical `0x230F` spans `0x230F..0x2321`. It first
calls the single-byte sender at `0x22CF`, passing through its caller's byte.
If that sender returns with a nonzero condition, `0x230F` returns immediately.
Otherwise it passes the address of status byte `0xDDC3` to helper `0x2322`.
If `0xDDC3` remains zero, it returns the `0x2322` result; if the status byte is
nonzero, it returns `0xFFFF`.

The matching labels and comments in `BSSERIAL.ASM` identify `0x230F` as
`ftran_send_wt(ch)`, documented there as sending a character and waiting for
an acknowledgement. They identify `0x2322` as `ftran_recv(char *error)`: it
waits for a buffered inbound character, returns that byte when successful,
sets the pointed status to `1` on timeout or `2` on abort, and returns `-1` on
either error. The timeout is controlled by `ftran_timeout` in tenths of a
second.

This makes the external disk discovery grammar exact. `disk_upload_download`
tries serial port 1 and then port 0. On each port it sets a three-tick receive
timeout and repeatedly sends `ENQ` (`0x05`) while the peer replies `?`
(`0x3F`). A reply other than `ACK` (`0x06`) rejects that port. After `ACK`, it
sends ASCII `C` and expects ASCII `1` or `3`; `3` advertises the drive's
38,400-baud capability, while either accepted value establishes YMODEM-capable
disk service. The special old-drive test accepts the drive after sending `C`
without validating that capability reply.

The next protocol-owning surface to recover is the disk-specific branch of
`upload_download`: the command/path bytes sent after successful discovery and
before its YMODEM transfer.

### `BS2ENG::upload_download` external-disk transfer grammar

The matching `FILETRAN.C` makes both transfer directions exact. A successful
disk discovery has already selected `ser_chan` and established whether the
drive supports the higher baud rate. Every disk transfer then begins another
`ftran_send_wt(ENQ)` and requires `ACK`.

Saving notetaker files to the external disk proceeds as:

1. send `ENQ` and receive `ACK`;
2. send ASCII `Y`, then ASCII `R` (the disk is told to receive);
3. wait five ticks and, when advertised, switch the selected serial channel to
   the drive's higher speed;
4. transmit the selected notetaker file set as a YMODEM batch.

Loading files from the external disk proceeds as:

1. send `ENQ` and receive `ACK`;
2. send ASCII `Y`, then ASCII `S` (the disk is told to send);
3. send the requested name or wildcard pathname as raw bytes followed by
   carriage return, with no trailing NUL;
4. wait five ticks and, when advertised, switch to the higher speed;
5. receive a YMODEM batch into the notetaker filesystem.

After either direction, firmware returns the UART to the discovery speed,
waits 500 ticks for PC Disk recovery, and queries the operation result by
sending `ENQ`, then `Y`, then `E` with send-and-receive on `E`. Reply `0`
means success. Reply `0xFF` is retried once; any remaining nonzero reply is
passed to the firmware's disk-error reporter.

This is already sufficient for a host service to back the notetaker's load and
save operations with ordinary host files: match the discovery handshake,
interpret `Y R` as an inbound YMODEM batch, interpret `Y S pathname CR` as an
outbound YMODEM batch selected from the host tree, and answer the subsequent
`Y E` status query. It does not yet establish the separate directory and file
management commands exposed by the Disk Drive menu.

The next protocol-owning surface to recover is the source owner for Disk Drive
directory enumeration and its associated path-management commands.

### `BS2ENG::savef` / `enqack` PC Disk command grammar

The ordinary Disk Drive menu is implemented by `savef` and `enqack` in
`BSTXT.C`, separately from the newer YMODEM transfer branch. `enqack(command)`
emits this request:

`ENQ (0x05), command byte, name/path bytes, CR (0x0D)`

The name/path field is omitted only for format command `F`. On the PC Disk
channel, firmware temporarily disables receive interrupts after ENQ, waits for
the acknowledgement, consumes the acknowledgement from the UART, restores
receive interrupts, and then emits the command frame. On the other disk
channel it waits for the normal receive path to place `ACK` in `istat`.

The recovered command mapping is:

- `d name-or-pattern CR`: directory listing. The firmware deliberately uses
  lowercase `d` so the initial acknowledgement is not inserted into the open
  clipboard; it then changes its local state to uppercase `D` and receives the
  listing as text into that clipboard.
- `L name CR`: load a text file from disk into the current notetaker file.
- `S name CR`: save the current file; `T name CR` is also used for text-output
  and for the Braille/no-formatting menu aliases.
- `K name-or-pattern CR`: delete file(s); `X name CR`: remove directory;
  `M name CR`: create directory.
- `H path CR`: change directory (`C` in the user menu is normalized to this
  command); `V label CR`: write volume label.
- `F CR`: format, with no name/path bytes; `U name CR`: disk update/revision
  operation.
- resume does not create a new ENQ frame: it changes local receive state and
  sends XON.

Directory and load replies use the firmware's text-receive path rather than
the 31-byte WinDisk records. Directory output is placed in the clipboard and
is expected to terminate with Ctrl-Z (`0x1A`). Save/text-output sends file data
and then Ctrl-Z. File-management commands wait for a status/error byte; the
known error alphabet is `#`, `!`, `&`, `%`, `"`, `$`, `+`, `-`, `/`, and `?`,
with Ctrl-Z treated as successful completion where applicable.

This establishes that the old PC Disk interface is a real remote filesystem
API: it carries path-aware directory, load/save, delete, change-directory,
mkdir/rmdir, format, and label operations. The remaining detail needed for a
faithful host-directory backend is the receive ISR's exact acknowledgement,
data, and completion handling for the `d` and `L` replies.

The next protocol-owning function to recover is the Disk Drive receive handler
that dispatches bytes according to `sflag` and writes `istat`/`dskcnt`.

### `BS2ENG::DISKIN` and channel-zero receive completion

The external Disk Drive ISR `DISKIN` reads each inbound byte, handles XON/XOFF,
and always stores the latest byte in `istat` while a storage command is active.
Only local receive states `D` (directory) and `$` (load/resume) append inbound
bytes to the current notetaker file. The directory command opens the clipboard
before entering state `D`; load uses the current destination file. `dskcnt`
saturates at three bytes and is used as the firmware's minimum evidence that a
data-producing disk operation actually ran.

The PC Disk path on serial channel zero uses the ordinary serial receive ISR.
That ISR likewise stores every received byte in `istat`, queues the byte, and
increments `dskcnt` up to three. `gettxt` drains the queue through `ser_task`
into the open file. For a directory, Ctrl-Z is both queued into the clipboard
and recognized by the waiting loop as the explicit end marker; for a load, the
receiver changes its local state to `$` and finishes after the serial stream
becomes idle. XON and XOFF control paused transfers rather than becoming file
data.

The command acknowledgement and result rules are therefore:

- the peer answers the initial ENQ with ACK before the command/path frame;
- `d` returns a textual listing terminated by Ctrl-Z;
- `L` returns file text, with idle time delimiting completion and XON/XOFF
  available for flow control;
- `S`/`T` receive file text from the notetaker until its Ctrl-Z terminator;
- metadata/mutation commands report a one-byte error/status when needed, using
  the error alphabet already listed; lack of an error byte through the bounded
  wait is treated as success for `H`, `K`, `M`, `V`, and `X`.

This completes the protocol surface needed for the architectural decision. A
QNS serial peer can expose a rooted host directory as the firmware's PC Disk:
the firmware already supplies paths and filesystem commands, and the emulator
only needs to translate those requests inside the configured root, stream text
or YMODEM file bodies, and emit the legacy acknowledgement/completion bytes.
