# Task: Connect SSI-263 INT1 to CPU

## Context

QNS is a Braille 'N Speak emulator. The SSI-263 speech chip uses INT1 to signal when it's ready for the next phoneme. Currently:

1. `ssi263.py` has `set_irq_callback()` method (already added)
2. `ssi263.py` calls the callback in `_speak_phoneme()` (already added)
3. BUT: `bns.py` never connects the SSI-263 to the CPU's INT1

The keyboard is already connected as a pattern:
```python
self.keyboard.set_irq_callback(self._make_irq_callback(2, "keyboard"))
```

## Objective

Connect SSI-263's IRQ callback to CPU INT1 in `bns.py`, using the existing `_make_irq_callback()` wrapper for tracing.

## Files to Read
- `qns/bns.py` - see keyboard connection pattern at line ~95
- `qns/ssi263.py` - see `set_irq_callback()` method

## Files to Modify
- `qns/bns.py` - add SSI-263 INT1 connection

## Implementation

In `BNS.__init__()`, after keyboard connection (around line 95), add:
```python
# Connect SSI-263 speech interrupt (INT1) to CPU
self.ssi263.set_irq_callback(self._make_irq_callback(1, "ssi263"))
```

## Test Command
```bash
uv run python -m qns.bns --trace-interrupts --cycles 1000000 roms/NFB99/BSPENG/bspeng.bns 2>&1 | grep -E "(IRQ|SSI263)" | head -30
```

Expected: Should see `[IRQ] INT1 ASSERT from ssi263` lines mixed with phoneme output.

## Output
Write findings/status to `./reports/connect-ssi263-int1-report.md`

## CRITICAL: File Modified Error Workaround

If Edit/Write fails with "file unexpectedly modified":
1. Read the file again with Read tool
2. Retry the Edit
3. Try path formats: `./relative`, `C:/forward/slashes`, `C:\back\slashes`
4. NEVER use cat, sed, echo - always Read/Edit/Write
5. If all formats fail, STOP and report - do not use bash workarounds

## CRITICAL: Parallel Swarm Awareness

You may be running alongside other agents in parallel.
- NEVER use git restore, git checkout, git reset, git clean
- If you mess up a file beyond repair: STOP, write what happened to your report, exit
