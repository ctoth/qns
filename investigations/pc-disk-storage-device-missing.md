# Investigation: PC Disk reports storage device missing

## Facts (verified)

- The BS2 firmware reaches its UI when launched with `--pc-disk-dir`, but selecting PC Disk reports `storage device missing` - evidence: user ran `uv run -m qns.cli --model bs2 --input keyboard --speech-stream english --pc-disk-dir .\ roms\NFB99\BS2ENG\bs2eng.bns`.
- The intended PC Disk implementation is attached to ASCI channel 0 - evidence: commit `3d41e8f`.
- Unit tests exercise the implemented protocol directly, not the complete firmware discovery transaction - evidence: `tests/test_pc_disk.py`.
- The supplied July 1999 help says S-chord activates the built-in Disk Drive function and that most Disk Drive commands also work with PC Disk - evidence: `roms/NFB99/BS2ENG/bs2eng.hlp`.
- PC Disk is not a guest external `.bns` program. The firmware's S-chord owner calls `disk_upload_download(-1)` before reading a disk subcommand - evidence: `C:/Users/Q/src/bns/bsp/BSPROCES.ASM:5079-5100`.
- Firmware source tries transfer channels 1 then 0; a successful channel 0 probe is explicitly described as talking to `pcdisk` - evidence: `C:/Users/Q/src/bns/bsp/FILETRAN.C:197-236` and `C:/Users/Q/src/bns/bsp/BSPROCES.ASM:5091-5100`.
- Replaying the user's fresh launch, answering both flash-initialization prompts with lowercase `y`, and sending S-chord produces exactly one serial event, ASCI1 `ENQ` (`BQ==`), followed by `storage device missing`. No ASCI0 byte is transmitted.
- QNS currently offers the PC Disk peer only to ASCI0 - evidence: `qns/bns.py:557-577`.

## Theories (plausible)

1. Fresh startup has not initialized the firmware's channel-0 communication state, so the S-chord fallback cannot transmit to PC Disk; this predicts ASCI1 ENQ followed by no ASCI0 transmit and the missing-device message.
2. The PC Disk discovery response bytes or their ordering are wrong; this predicts ASCI0 traffic reaches `PCDisk`, but the firmware rejects the reply before issuing a file command.
3. The response timing/readiness integration with the emulated ASCI is wrong; this predicts the right bytes are queued but are not delivered under the UART status/interrupt conditions expected by firmware.

## Tests Run

| Test | Hypothesis | Result | Rules Out | Supports |
|------|------------|--------|-----------|----------|
| Read supplied BS2 help | PC Disk requires a guest external program | S-chord is documented as the built-in Disk Drive activation; most commands also work with PC Disk | Guest `.bns` program ownership | Built-in firmware client plus external peer |
| Read recovered `BSPROCES.ASM` and `FILETRAN.C` | PC Disk should be attached to ASCI1 | Firmware probes 1 then 0 and explicitly labels successful channel 0 as `pcdisk` | ASCI1-only PC Disk attachment | Existing ASCI0 device ownership |
| Replay fresh launch through JSONL and press S-chord | ASCI0 reaches the emulated peer but rejects its reply | Only ASCI1 transmits ENQ; no ASCI0 transmit occurs before the error | Bad PC Disk ACK/capability as the immediate failure | Missing channel-0 firmware/UART initialization |

## Current Best Theory

The user's invocation starts with fresh emulator memory and does not take the full cold-reset/persistent-state lifecycle that initializes the firmware's channel-0 communication state. S-chord probes the physical Disk Drive on channel 1, then the intended PC Disk on channel 0, but the channel-0 ENQ does not transmit. The emulated peer therefore receives nothing and cannot be discovered. This explains the complete live trace and is consistent with the earlier `COMBYT`/ASCI0 lifecycle investigation.

## Open Questions

- Should `--pc-disk-dir` require a correctly initialized persistent guest state, or should QNS make the PC Disk attachment usable during a fresh launch without a separate lifecycle procedure?
- After fixing or satisfying channel-0 initialization, does the full S-chord directory/load/save UI pass against real host files?

## Next Action

Do not change the protocol or move PC Disk to ASCI1. First choose the intended fresh-start contract, then require an end-to-end real-ROM S-chord directory/load/save test using the user's launch shape.
