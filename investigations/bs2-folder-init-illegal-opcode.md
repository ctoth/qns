# Investigation: BS2 flash initialization illegal opcode

## Facts (verified)

- `bs2eng.bns` accepts two prompt-paced lowercase `y` responses and advances through flash initialization with the active 2 MiB flash slice.
- The earlier no-flash implementation could not advance through that initialization.
- A prompt-paced trace delivered only the two flash-initialization confirmations. The native Z180 core then reported `Z180 'z180' ill. opcode $d1 $11` before any third key was sent, and firmware restarted its initialization speech.
- The exact file-manager gate is uppercase terminal `O` (raw `0x55`, firmware `OCHORD`) followed by lowercase `f`, ending in the spoken `enter file command` prompt.
- The file-manager gate has not been reached.
- The eventual stack word `00 C3` is deliberately created at logical PC `01B1` by `DD E5` (`PUSH IX`) with `IX=C300` and `SP=0000`; the subsequent `RET` at `01F8` therefore transfers to an intentional RAM entry point rather than a corrupted return address.

## Theories (plausible)

1. The BS2 flash window or page selection is wrong, so flash initialization reads or executes incorrect bytes.
2. A DMA or flash-command path corrupts RAM or control-flow state during flash initialization.
3. The flash mapping is correct, but the Z180 core mishandles a valid instruction path first exercised during flash initialization.

## Tests Run

| Test | Hypothesis | Result | Rules Out | Supports |
|------|------------|--------|-----------|----------|
| Live flash initialization with prompt-paced `y`, `y` | Missing flash model blocked initialization | Firmware spoke the flash-initialized sequence and advanced | Flash still being wholly absent | The flash model is materially active |
| Prompt-paced trace with exactly two lowercase `y` responses | Determine whether the trap precedes the folder response | Native core reported the illegal opcode before any third key was sent | Folder response causing the earlier trap | The failure is inside the affirmative flash-initialization path |
| Two-key-armed Python trace matching `DD D1` or `FD D1` | Existing `run(1)` calls expose the failing pre-instruction boundary | Native core trapped after about 45 seconds of one-cycle calls, but the Python pre-call ring never saw either prefix pair | The current Python wrapper being a sufficient instruction-boundary trace | Either one execute call crosses the trap or the Python fetch reconstruction differs from the native core |
| Watch native `ITC.TRAP` transition after each one-cycle execute call | Interrupt dispatch changes the instruction PC after Python's pre-call observation | Trap captured at logical `C37B`, physical `4037B`, with mapped bytes `FD 00`; no third key | The logged `D1 11` being the fetched instruction and the execute wrapper running multiple ordinary instructions | Control flow entered data-like RAM bytes during flash initialization |
| Stop on first observed entry into logical `C300..C3FF` | A bad return or missing RAM code causes the later sequential trap | `RET` at `01F8` popped `C300` from physical stack `43FFE`; `SP` changed from `FFFE` to `0000`; physical `40300` was zero-filled | A direct jump from flash code into the middle of `40371` data | Either `C300` is a legitimate return into RAM that was never populated, or the saved return address is wrong |
| Capture mapped `C2E0..C31F` at the `RET` into `C300` | A valid `CALL` at `C2FD` produced return address `C300` | All 64 mapped bytes were zero | `C300` being a normal call return from code immediately below it | The stack word was produced by an interrupt push or another invalid control-flow path |
| Stop on first post-confirmation write to physical `43FFE..43FFF` | The bad stack word is created by a push | PC `D67D` executed `LD (HL),A` with `SP=D3FE`, writing `43FFF=00` | The first write being stack activity | Firmware clears this address before a later operation writes the `C3` high byte |
| Stop when a later instruction writes `43FFF=C3` | The eventual `00 C3` word is a corrupted return address | At logical PC `01B1`, `DD E5` (`PUSH IX`) with `IX=C300` and `SP=0000` wrote `43FFE=00`, `43FFF=C3`; afterward `SP=FFFE` | Accidental stack corruption producing the `C300` transfer | Firmware deliberately installs `C300` as the continuation, but its target RAM is not populated |
| Inspect package bytes for logical `01B1..01F8` | The routine at `01B1` is responsible for populating `C300` | It saves registers, calls `5F7B`, restores registers and `SP`, enables interrupts, then returns | `01B1..01F8` itself being the missing code-copy routine | `C300` must already be a valid continuation before this context handler runs |
| Inspect native Z180 DMA channel-0 modes | Repeated writes to physical `4215C` prove a broken destination counter | `DMODE=20/24` intentionally keeps `DAR0` fixed; `00/04/08` increment it and `10/14/18` decrement it | Repetition alone proving incorrect DMA behavior | Live `DMODE`, source, destination, count, and target-region writes are required to judge the transfer |
| Trace physical `40300..403FF` writes and stop before `01B1` | The entire `C300` continuation was never populated | Firmware made 66 writes only to `40371..4037B`; final bytes there were `6F F0 36 01 00 08 1E 02 00 55 FD`; `40300..40370` remained zero. DMA snapshot: `SAR0=44080 DAR0=4254A BCR0=0000 DSTAT=31 DMODE=02 DCNTL=1C` | The exact trap bytes at `4037B` being uninitialized RAM | Execution is entering a deliberately constructed data structure; the causal fault precedes the context handler and its return |
| Print the instruction-boundary ring at the first post-confirmation `01B1` entry | The first `01B1` entry captures the `C300` continuation | The CPU was already executing zeros at logical `DA99..DAB8`, physical `41A99..41AB8`; a maskable interrupt pushed return `DAB9` at physical stack `43FFE`, vectored through `0038` and `012B`, then reached `01B1` with `IX=FFFF` | The first post-confirmation interrupt being the later `C300` instance or causing the initial bad control transfer | The generic interrupt handler is operating after control flow has already entered zero RAM; the first sustained zero-run transition is the earlier cause |
| Stop at the first 16 consecutive zero opcodes after confirmation | The first zero run begins at the original bad control transfer | The run began at logical `D690`, but preceding execution had already entered ASCII data at `D658` (`70 61 67 65 ...`, including `Braille 'n Speak two thousand ready`). An interrupt epilogue at `0E04..0E05` executed `EI; RET` with stack top `58 D6` and next word `86 0A`, returning to `D658` | `D690` being the initial invalid target | The first entry into the high RAM/data area occurs earlier; later interrupts preserve and return to already-invalid PCs |
| Stop at the first post-confirmation PC `>= C000` | Any high PC is an invalid control transfer into data | Low firmware at `0A83` executed `CD 55 D6` (`CALL D655`). The target bytes are `ED 76 C9 70 61 67 65 20`: Z180 `SLP`, `RET`, then the `page...` string. Later invalid execution starts at `D658`, exactly one byte after the `RET` | `D655` itself being an invalid call target | The emulator's sleep/wake continuation skips the required `RET` at `D657` and resumes in the following string |

## Current Best Theory

The root cause is the Z180 `SLP` continuation path. Firmware deliberately calls a three-byte RAM routine at `D655`: `ED 76` (`SLP`) followed by `C9` (`RET`). After wake-up, correct execution must resume at `D657`, execute the `RET`, and return to the caller at `0A86`. Instead, observed invalid execution begins at `D658`, the first byte of the adjacent `page...` string. All later high-RAM walks, interrupts, and the eventual `FD 00` trap follow from this one-byte overshoot.

## Open Questions

- Where does the native core implement `ED 76` (`SLP`), and what PC value does it retain while sleeping?
- Does the Python/native wake bridge increment PC as if HALT left it on the opcode even though `SLP` has already advanced past both bytes?
- What focused test reproduces `CALL; SLP; RET` and proves wake-up resumes at the `RET` rather than the following byte?

## Next Action

Inspect the native `ED 76` implementation and the Python/native sleep wake-up bridge. Then add a focused `CALL; SLP; RET` regression test and correct the continuation semantics at their owning boundary before rerunning the live BS2 initialization.
