# Task: Fix SSI-263 INT1 Timing

## Context

The BNS emulator is stuck in early boot because SSI-263 triggers INT1 immediately when a phoneme is written. Real hardware has phoneme duration - the interrupt fires AFTER the phoneme finishes playing.

Current behavior:
1. Firmware writes phoneme to SSI-263
2. We immediately set `speaking = False` and trigger INT1
3. CPU jumps to ISR before even finishing the boot delay loop
4. Boot never completes

Expected behavior:
1. Firmware writes phoneme to SSI-263
2. SSI-263 "plays" the phoneme (takes time based on duration register)
3. When done, SSI-263 signals ready (A/R line low)
4. If interrupts enabled, this triggers INT1

## Objective

Fix the INT1 timing in `ssi263.py` so boot can complete. For now, the simplest fix is to NOT trigger INT1 immediately - remove the call to `_irq_callback(1)` in `_speak_phoneme()`.

This will let the firmware run in polling mode (checking status register) until we implement proper phoneme duration timing.

## Files to Read
- `qns/ssi263.py` - SSI-263 emulation, see `_speak_phoneme()` method around line 226

## Files to Modify
- `qns/ssi263.py` - comment out or remove the INT1 trigger in `_speak_phoneme()`

## Implementation

In `_speak_phoneme()`, comment out the INT1 trigger:
```python
# TODO: Implement proper phoneme duration timing before triggering INT1
# For now, don't trigger immediately - let firmware poll status register
# if self.irq_enabled and self._irq_callback:
#     self._irq_callback(1)  # Assert INT1
```

## Test Command
```bash
uv run python -m qns.bns --cycles 5000000 --stats roms/NFB99/BSPENG/bspeng.bns 2>&1 | tail -15
```

Expected: PC should advance past 0x033C to the main loop (around 0x0A30). Should see different phonemes, not just 0x00.

## Output
Write findings/status to `./reports/fix-ssi263-int1-timing-report.md`

## CRITICAL: File Modified Error Workaround

If Edit/Write fails with "file unexpectedly modified":
1. Read the file again with Read tool
2. Retry the Edit
3. Try path formats: `./relative`, `C:/forward/slashes`, `C:\back\slashes`
4. NEVER use cat, sed, echo - always Read/Edit/Write
5. If all formats fail, STOP and report

## CRITICAL: Parallel Swarm Awareness

You may be running alongside other agents in parallel.
- NEVER use git restore, git checkout, git reset, git clean
- If you mess up a file beyond repair: STOP, write what happened to your report, exit
