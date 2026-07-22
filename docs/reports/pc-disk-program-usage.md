# PC Disk ownership, usage, and discovery failure

## Question

Is PC Disk a Braille 'n Speak external program, and why does the current
`--pc-disk-dir` feature report `storage device missing` from the documented UI?

## Facts

### PC Disk is not a guest external program

- The supplied July 1999 firmware help, `roms/NFB99/BS2ENG/bs2eng.hlp`, places
  PC Disk under the built-in `Disk Drive Functions`. It says S-chord activates
  the disk drive and that most of those commands may also be used with PC Disk.
  Only after successful activation does `d` mean disk directory; outside that
  mode, the file menu documents lowercase `d` as delete.
- The matching firmware source implements S-chord at
  `C:/Users/Q/src/bns/bsp/BSPROCES.ASM:5079-5221`. It calls
  `disk_upload_download(-1)` before reading and dispatching the disk subcommand.
  No `.bns` external-program loader is involved.
- The supplied NFB99 BS2 distribution contains external programs
  `bsname.bns` and `calsort.bns`, but no PC Disk `.bns` image.

PC Disk is the external peer side of a built-in firmware client: historically,
PC-side software made a serial-connected computer act as storage for the
notetaker. A historical description likewise characterizes PC Disk as allowing
an MS-DOS or Windows-compatible computer to serve as a disk unit for Braille 'n
Speak or Braille Lite:
<https://www.revistacomunicar.com/pdf/comunicar17.pdf>.

### PC Disk and WinDisk are different directions

- The older PC Disk surface lets the notetaker initiate directory, load, save,
  delete, and path-management commands against the external peer.
- WinDisk is a later host-side Windows integration. The official Freedom
  Scientific page restricts it to notetakers purchased after July 2000 or
  running a post-July-2000 update:
  <https://support.freedomscientific.com/Downloads/NoteTaker/NoteTaker>.
- The official Type Lite guide describes WinDisk as Windows Explorer browsing
  and copying the notetaker's own RAM/flash files, the reverse presentation
  direction from PC Disk:
  <https://www.freedomscientific.com/Content/Documents/Manuals/Legacy/Type_LiteDocs/Type_Lite_User_Guide.pdf>.
- The user's NFB99 ROM is dated July 1999, so WinDisk is not the relevant path.

### Firmware channel ownership

- `disk_upload_download` loops from transfer channel 1 to channel 0 in
  `C:/Users/Q/src/bns/bsp/FILETRAN.C:197-236`.
- After a successful S-chord probe, `BSPROCES.ASM:5091-5100` explicitly tests
  `ser_chan`: zero is described as `pcdisk`; nonzero is the Disk Drive port.
- `BSSERIAL.ASM:144-156` sends through ASCI0 when `ser_chan == 0` and ASCI1
  otherwise.
- QNS currently exposes `PCDisk` only on ASCI0 in `qns/bns.py:557-577`. That
  channel choice matches the source-defined PC Disk identity.

## Reproduction

The user's command was replayed with the same ROM and fresh emulator memory:

```powershell
uv run -m qns.cli --model bs2 --input keyboard --speech-stream english `
  --pc-disk-dir .\ roms\NFB99\BS2ENG\bs2eng.bns
```

After answering both flash-initialization prompts with lowercase `y`, S-chord
spoke `storage device missing` exactly as reported. Repeating the path through
structured stdio exposed the serial event stream:

1. S-chord was accepted as raw chord `0x4e`.
2. ASCI1 transmitted one byte, ENQ (`0x05`, JSONL base64 `BQ==`).
3. No ASCI0 transmit event occurred.
4. Firmware spoke `storage device missing`.

The emulated PC Disk therefore received no request. Its ACK/capability response
was not involved in this failure.

## Root cause

The feature was validated against the wrong lifecycle/path. The earlier bounded
run used a recorded BS2 lifecycle state and a file-transfer path that eventually
reached ASCI0. It did not execute S-chord from the user's fresh ROM-only launch.

The existing `investigations/bs2-state-lifecycle.md` already proves that this
BS2 startup family can leave ASCI0 transmitter enable clear when the persistent
communication byte (`COMBYT`) was never established by the real cold-reset
lifecycle. That is exactly what the new live trace shows: the channel-1 Disk
Drive probe transmits, while the source-defined channel-0 PC Disk fallback does
not.

Moving PC Disk to ASCI1 would hide the symptom by impersonating the physical
Disk Drive port and would contradict the firmware's explicit channel ownership.

## Open product decision

The implementation needs an explicit fresh-start contract before it is changed:

1. Require users to initialize and persist the real guest lifecycle state before
   using `--pc-disk-dir`; or
2. Make `--pc-disk-dir` usable from a fresh ROM-only launch while preserving the
   source-defined ASCI0 ownership.

Whichever contract is selected, the acceptance gate must start from that exact
launch shape, activate S-chord in the real ROM, then exercise directory, load,
and save against actual host files. Direct `PCDisk.transmit()` tests and a
boot-time probe are not sufficient.
