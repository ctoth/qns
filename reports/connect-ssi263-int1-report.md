# Task Report: Connect SSI-263 INT1 to CPU

## Summary

Successfully connected the SSI-263 speech chip's IRQ to the CPU's INT1 line in the BNS emulator.

## What Was Done

### File Modified

**`C:\Users\Q\code\qns\qns\bns.py`** (lines 97-98)

Added the following after the keyboard INT2 connection:

```python
# Connect SSI-263 speech interrupt (INT1) to CPU
self.ssi263.set_irq_callback(self._make_irq_callback(1, "ssi263"))
```

### Context

The pattern follows the existing keyboard connection:
- Keyboard uses INT2: `self.keyboard.set_irq_callback(self._make_irq_callback(2, "keyboard"))`
- SSI-263 now uses INT1: `self.ssi263.set_irq_callback(self._make_irq_callback(1, "ssi263"))`

## Verification

Ran the test command:
```bash
uv run python -m qns.bns --trace-interrupts --cycles 1000000 roms/NFB99/BSPENG/bspeng.bns 2>&1 | grep -E "(IRQ|SSI263)" | head -30
```

Output confirmed the connection works:
```
[SSI263] Phoneme: 0x00 PA (pause)
[IRQ] INT1 ASSERT from ssi263 (cycle ~0)
[SSI263] Phoneme: 0x00 PA (pause)
```

The `[IRQ] INT1 ASSERT from ssi263` message confirms:
1. The SSI-263 is calling the IRQ callback when a phoneme completes
2. The callback correctly signals INT1 to the CPU
3. The tracing identifies the source as "ssi263"

## Technical Details

### How It Works

1. `ssi263.py` has a `set_irq_callback()` method that stores a callback function
2. When `_speak_phoneme()` completes, it calls `self._irq_callback(1)` to assert INT1
3. The `_make_irq_callback()` wrapper in `bns.py` creates a callback that:
   - Logs the IRQ event when `--trace-interrupts` is enabled
   - Calls `self.cpu.set_irq(line, state)` to signal the CPU

### Interrupt Mapping

| Source      | INT Line | Purpose                          |
|-------------|----------|----------------------------------|
| Keyboard    | INT2     | Key press notification           |
| SSI-263     | INT1     | Ready for next phoneme           |
| (Reserved)  | INT0     | (Not currently used)             |

## Status

**COMPLETE** - The SSI-263 speech chip is now properly connected to the CPU's INT1 interrupt line.
