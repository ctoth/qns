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
