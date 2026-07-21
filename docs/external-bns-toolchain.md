# Building external `.bns` programs for Blazie note takers

Status: active implementation plan and verified format specification,
2026-07-20. Phase 1 is complete: a clean checkout installs the pinned Z180
backend and reproduces the exact smoke artifact. The repository can import and
execute supplied external programs, but it cannot yet package and run a newly
built external program. Commands marked **planned** do not exist yet.

## Goal

Given Z180 assembly or C source, produce a deterministic external-program
`.bns` file, transfer it through an unmodified Blazie firmware file-transfer
path, execute it at logical address `0x1000`, use the firmware API, and return
cleanly to the note taker.

The initial target is the July 1999 English Braille 'n Speak 2000 firmware
already exercised by QNS (`roms/NFB99/BS2ENG/bs2eng.bns`). A different physical
model or firmware revision is a new target and must pass the same gates before
being called supported.

```text
assembly or C
    -> Z180 compiler/assembler/linker
    -> flat image plus link symbols
    -> BNS header finalizer and inspector
    -> external-program .bns
    -> real-ROM QNS YMODEM/import/launch gate
    -> physical note-taker YMODEM/import/launch gate
```

## Do not confuse the two `.bns` formats

Blazie used `.bns` for at least two different things:

- An **external program** is a small relocatable application with `BNS\0` in
  its header. The firmware maps it at logical `0x1000` and exposes services
  through `RST 38h`.
- A **firmware update package** contains an updater followed by a large firmware
  image, length, and CRC at a model/build-specific `IMAGE_OFFSET`. That is the
  format handled by `qns/loader.py`; it is not the format described here.

This toolchain must reject a firmware update package when asked to inspect an
external program.

## Verified external-program format

`C:\Users\Q\src\bns\bsp\PROGHDR.ASM` defines the header and
`C:\Users\Q\src\bns\bsp\BS.ASM::_execute_program` defines validation and
launch. The supplied `BSNAME.BNS` and `CALSORT.BNS` files confirm the layout.
All multi-byte integers are little-endian.

| File offset | Size | Meaning |
|---:|---:|---|
| `0x00` | 2 | Z180 `JR` from file start to the entry point at offset `0x0E` |
| `0x02` | 4 | `BNS\0` application identifier |
| `0x06` | 2 | `code_size`, the number of bytes checked by the program CRC |
| `0x08` | 2 | `program_length`, from offset `0x0E` through the byte before the final marker |
| `0x0A` | 2 | CRC of `code_size` bytes beginning at offset `0x0E` |
| `0x0C` | 2 | Initial logical stack pointer |
| `0x0E` | variable | Entry code, linked to logical address `0x100E` |
| last byte | 1 | `0xAA` end marker |

The file-size invariant is:

```text
file_size = program_length + 15
```

The launcher uses `program_length`, rounded to 4 KiB pages, to construct the
application MMU map. A length that overflows the ordinary calculation gets the
full 60 KiB application map. The first toolchain target must remain below that
boundary; large-program behavior is a separate gate.

Use `BNS\0` for the portable application identifier. TNS/Tiny Lite firmware
also accepts `TNS\0`, but `BNS\0` is accepted by the source-defined TNS path and
is present in the supplied TNS copy of `CALSORT.BNS`.

### CRC algorithm

The launcher seeds the CRC with zero and applies this operation to each byte of
the code range:

```text
carry = bit 15 of crc
crc = (crc << 1) & 0xffff
crc.low = (crc.low + byte) & 0xff
if carry:
    crc.low ^= 0x97
    crc.high ^= 0xa0
```

Only `file[0x0E : 0x0E + code_size]` is covered. The historical format keeps
writable data, BSS, stack, and the final marker outside this range. The modern
link layout must preserve that boundary; treating the entire file as code would
make an application that stores state in its data area fail its next CRC check.

### Confirmed sample headers

| File | File size | Code size | Program length | CRC | Stack |
|---|---:|---:|---:|---:|---:|
| `BSNAME.BNS` | 25,108 | `0x1AEF` | `0x6205` | `0x6E8A` | `0x7213` |
| `CALSORT.BNS` | 17,092 | `0x2EDE` | `0x42B5` | `0x0F57` | `0x52C3` |

The format inspector must reproduce these values and CRCs before it is trusted
to create a file.

## Runtime contract

The application is not a bare-metal program. The firmware remains the owner of
the machine while the application runs.

- Do not change the MMU.
- Do not access model-specific hardware directly; use the firmware API.
- Do not leave interrupts disabled.
- Keep the stack at logical `0x1000` or above.
- Exit by returning from `main`, or by invoking API function zero exactly as the
  startup code does.
- Keep mutable state outside the CRC-covered code section.

The firmware API entry is `RST 38h`. On entry, `A` is the function number and
`HL`, `DE`, and `BC` carry the three 16-bit argument words. Results return in
those registers. Two calls are sufficient for the first assembly program:

| Function | `A` | Input | Purpose |
|---|---:|---|---|
| `API_EXIT` | 0 | `HL=0` | Terminate normally |
| `API_SAY_WAIT` | 2 | `HL=logical address of NUL-terminated text` | Speak up to 80 characters and wait |

The historical `BNSAPI.H` describes many more calls, but its missing
`bsapi.lib` was compiled for the Softools C ABI. It is evidence for the API,
not a library that a modern compiler can link unchanged.

## Historical toolchain

The original source names this build stack:

- Softools `sc180` C compiler and assembler
- Softools `slink` linker
- `sc180.lib` C runtime
- Blazie `proghdr` startup object
- Blazie `bsapi.lib` API wrappers
- a post-link program that writes lengths and CRCs

Its linker layout placed code at logical `0x1000` while emitting it at file
offset zero, placed `proghdr` first, followed it with application objects, and
grouped `const`, `data`, `bss`, `bssz`, `stack`, and `end` after code.

That stack is not currently reproducible here: the compiler, assembler,
linker, runtime library, API library, and general post-link finalizer are not
installed or present in the local source archives. It remains a useful
historical cross-check, not the primary implementation path. If those binaries
are later recovered legally, reproduce them in an isolated DOS environment and
compare output; do not make them an undeclared prerequisite of the modern
build.

## Selected modern backend

The first backend is **z88dk 2.4**. Its official Windows archive is pinned in
`toolchain/z88dk.lock` by URL, byte size, and SHA-256. The local installer
verifies those facts before extracting it into ignored `.toolchain/`; it does
not alter global `PATH` or install outside the repository cache. See the
[z88dk 2.4 release](https://github.com/z88dk/z88dk/releases/tag/v2.4) and
[zcc custom configuration documentation](https://www.z88dk.org/wiki/doku.php?id=zcc).

The locally installed tools identify themselves as z88dk build
`v23854-4d530b6eb7-20251002` and zsdcc `4.5.0 #15242`. Their actual help
surfaces establish these flags:

| Tool | Help command | Flags used by this plan |
|---|---|---|
| `zcc.exe` | `zcc -h` | `-mz180`, `-m`/`-gen-map-file`, `-s`, `--list`, `-g` |
| `z88dk-zsdcc.exe` | `z88dk-zsdcc --help` | `-mz180`, `-S`, segment-placement flags |
| `z88dk-z80asm.exe` | `z88dk-z80asm -h` | `-mz180`, `-b`, `-o`, `-l`, `-m`, `-s`, `-g` |

These commands have run successfully on this host:

```powershell
& .\toolchain\setup-z88dk.ps1
uv run pytest tests/test_bns_external.py -v
uv run ruff check tests/test_bns_external.py
```

The pinned release archive SHA-256 is
`26d9880ee2e43077808ac86a4b6247a81f5dadc30563ca7cedc58bc4fb5ccb57`.
The assembler smoke fixture contains `MLT BC`; in Z180 mode it emits exactly
`ED 4C`, whose SHA-256 is
`88506b69237ce638a5a69f79b7a97e82fa23c5a4137f25fc1170723afffab3ec`.
The committed Phase 1 snapshot was also tested from a detached clean checkout.
It downloaded and installed the pinned archive, created a fresh `uv`
environment, passed the smoke test, and reproduced the same smoke-output
SHA-256. This closes the Phase 1 clean-checkout gate.

## Repository artifacts the plan must create

These are the required artifacts, not suggestions to replace with nearby
files:

| Path | Purpose |
|---|---|
| `toolchain/z88dk.lock` | Exact release URL, version, and SHA-256 |
| `toolchain/setup-z88dk.ps1` | Idempotent install into ignored `.toolchain/` |
| `toolchain/bns.cfg` | z88dk target/link configuration for logical `0x1000` |
| `toolchain/teraterm.lock` | Exact portable Tera Term release URL and SHA-256 |
| `toolchain/setup-teraterm.ps1` | Idempotent install into ignored `.toolchain/` |
| `sdk/bns_crt0.asm` | Header placeholder, stack setup, C entry, API exit |
| `sdk/bns_api.asm` | Compiler-ABI shims that marshal calls to `RST 38h` |
| `sdk/include/bns_api.h` | Only the API calls whose wrappers have tests |
| `tools/bns_external.py` | `pack` and `inspect` operations for this format |
| `examples/hello-asm/` | Smallest assembly program: speak and exit |
| `examples/hello-c/` | Smallest C program using the tested API wrapper |
| `tests/test_bns_external.py` | Header, CRC, rejection, and fixture authority |
| `docs/external-bns-toolchain.md` | This plan and, later, the verified user guide |

Do not copy the historical copyrighted headers or libraries into the
repository until redistribution rights are established. The modern header and
shims should encode the measured ABI facts needed by the supported calls.

## Ordered implementation plan

Each phase ends in a committed kept slice or a complete Git restore before the
next phase begins.

### Phase 1: pin and qualify the backend

Implementation status: complete. All four tasks pass on the current host, and
the committed Phase 1 snapshot passes the clean-checkout reproduction gate.

1. Create `toolchain/z88dk.lock` for official z88dk 2.4 Windows binaries,
   including SHA-256.
2. Create `toolchain/setup-z88dk.ps1`; it must refuse a checksum mismatch and
   must not alter global `PATH` or install outside `.toolchain/`.
3. Record the actual v2.4 Z180 assembler/compiler/linker flags from their local
   `--help` output.
4. Assemble a fixture containing Z180 `MLT BC` and have a repository test
   require its documented two-byte encoding `ED 4C`.

Gate: a clean checkout can install the pinned backend and reproduce the exact
smoke-test hash. If this fails, stop and choose another backend explicitly;
do not imitate a successful z88dk setup with hand-written bytes.

### Phase 2: implement the format authority

1. Implement `inspect` first. It parses the table above, checks the identifier,
   bounds, `file_size == program_length + 15`, final `0xAA`, stack range, and
   CRC.
2. Require it to validate the supplied `BSNAME.BNS` and `CALSORT.BNS` when those
   local research fixtures are available.
3. Implement `pack` over a linked raw image plus link symbols for code end,
   program end, and stack. It fills the four header words and CRC; it must not
   guess section boundaries from byte patterns.
4. Reinspect the emitted output and fail the build if any invariant differs.

The link symbols are part of the interface and must be named
`__bns_entry`, `__bns_code_end`, `__bns_end_marker`, and `__bns_stack_top`.
The packer derives `code_size` from the first two, `program_length` from
`__bns_end_marker - __bns_entry`, and the stack word from
`__bns_stack_top`. The marker symbol must identify the final `0xAA` byte.

Gate: fixture CRCs are exactly `0x6E8A` and `0x0F57`; corrupting any covered
code byte is rejected; corrupting header bounds or the end marker is rejected;
two clean builds are byte-identical.

### Phase 3: build the assembly walking skeleton

1. Write `sdk/bns_crt0.asm` with the 14-byte header, entry at logical `0x100E`,
   a stack outside the CRC-covered code section, and normal `API_EXIT`.
2. Write `examples/hello-asm` to call `API_SAY_WAIT` through `RST 38h`, say a
   unique short phrase, and exit.
3. Link it through `toolchain/bns.cfg`; use exported link symbols as packer
   inputs.
4. Inspect the resulting `.bns` and its generated assembler listing. Require
   entry at logical `0x100E`, the source-defined section boundaries, and the
   `RST 38h` API calls.

Gate: the result is structurally valid, enters at `0x1000`, speaks the expected
phrase, exits, and the firmware accepts another key afterward.

### Phase 4: add the minimal C SDK

1. Confirm the selected z88dk compiler's actual calling convention from its
   generated assembly.
2. Implement only `bns_exit()` and `bns_say_wait()` shims first.
3. Add C prototypes whose pointer and integer widths are asserted at compile
   time.
4. Build `examples/hello-c` with no implicit host I/O or target-specific z88dk
   console runtime.
5. Compare the wrapper's generated assembly listing with the firmware register
   contract.

Gate: the C example passes the same emulator and physical-device behavior as
the assembly example. Passing compilation alone is not an ABI gate.

### Phase 5: make QNS the repeatable integration gate

The existing command is:

```powershell
uv run python tools/verify_bs2_external_program.py --help
```

It can import an arbitrary program through real-ROM YMODEM and prove its
program-length-derived `CBAR` at PC `0x1000`. Its speech assertions are
currently named only for `bsname.bns` and `calsort.bns`, so the tool must be
extended to accept an explicit expected speech marker and to prove return to
the firmware command loop.

The final integration command will use a disposable state path, the exact
BS2ENG ROM, the built program, and the stdio process boundary. The command must
be copied into this section only after it has run successfully; until then it
is not part of the user quick start.

Gate: real firmware completes serial probes, imports the exact output bytes,
launches at `0x1000` with the header-derived map, observes the example's unique
behavior, and regains its command loop after exit.

### Phase 6: validate on physical hardware

Before the first run, record the unit model, firmware revision, available RAM,
serial parameters, and a backup. Use the assembly example first because it has
the smallest runtime surface. Load it into RAM, not flash.

Use the portable x64 build of [Tera Term 5.6.1](https://github.com/TeraTermProject/teraterm/releases/tag/v5.6.1)
as the first Windows transfer authority. Pin `teraterm-5.6.1-x64.zip` with the
publisher-provided SHA-256
`4cd4a75dc6614c7be8e19955fadadd4ceb0fc4c7ad4475913e2deecb37cbc656` in
`toolchain/teraterm.lock`. Tera Term's documented
[`ymodemsend`](https://teratermproject.github.io/manual/5/en/macro/command/ymodemsend.html)
operation reports success or failure and preserves the transmitted file size.

The July 1999 Blazie instructions give this transfer sequence:

1. Run **planned** `toolchain/setup-teraterm.ps1`, open its repository-local
   `ttermpro.exe`, select the unit's COM port, and configure both ends for
   9600 baud, 8 data bits, no parity, one stop bit, and no flow control.
2. On the note taker, enter the file menu, then T-chord.
3. Enter `r` to receive and `y` for YMODEM.
4. In Tera Term select **File > Transfer > YMODEM > Send**, choose the `.bns`
   file, and require transfer success. Do not create a destination file on the
   note taker first.
5. Press E-chord/Enter on the note taker to begin transfer and require its
   completion message.
6. Launch from the option menu with O-chord, `x`, the program's base name, and
   E-chord/Enter. An alternative is to select it in the file menu and press
   X-chord.
7. Require the unique spoken phrase, normal return, a working firmware key
   command afterward, and the same result on a second launch.

Gate: two consecutive launches work without reset, file damage, unexpected
power behavior, or changed serial settings. Only then run the C example. Flash
execution and additional hardware models are later, independent gates.

## Intended quick start after the plan is complete

This section deliberately contains no fictional build command. It is complete
only when a clean checkout has executed, in order:

1. repository-local toolchain setup;
2. assembly and C builds;
3. format inspection;
4. QNS real-ROM integration;
5. the physical transfer/run procedure above.

The exact successful commands and expected output must replace this paragraph
during Phase 6. Until that happens, the truthful current answer is: the file
format and launch path are known, but the build toolchain is not yet complete.

## Completion definition

This toolchain is complete only when all of the following are true:

- a clean checkout obtains a checksum-pinned compiler toolchain without global
  host changes;
- both example sources reproducibly build into structurally valid `.bns`
  files;
- all emitted header fields come from linker facts rather than guessed offsets;
- the tested API wrappers match the firmware register ABI;
- QNS imports, launches, observes, and returns through unmodified BS2 firmware;
- a recorded physical BS2 unit passes transfer and two-launch validation; and
- this document contains the exact commands that produced those results.
