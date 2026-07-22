# Task: Implement Phoneme Duration Timing for INT1

## Context

The BNS emulator's SSI-263 speech chip needs proper timing:
- Currently INT1 is disabled (fixed boot issue)
- But speech doesn't work because INT1 is needed to trigger the ISR for next phoneme
- Real hardware triggers INT1 AFTER phoneme finishes playing, based on duration

From AppleWin SSI263.cpp (line 95):
```cpp
int phonemeDuration_ms = (((16-(ssi2>>4))*4096)/1023) * (4-(ssi0>>6));
```

Where:
- ssi2 = rate_inflection register (bits 7:4 = rate, 0=fastest, 15=slowest)
- ssi0 = duration_phoneme register (bits 7:6 = duration mode)

At 12.288 MHz clock: 1 ms = 12,288 cycles

## Objective

Implement phoneme duration timing in SSI-263 so INT1 triggers after the phoneme finishes.

## Files to Read
- `qns/ssi263.py` - SSI-263 emulation
- `qns/bns.py` - main emulator, has run loop

## Files to Modify
- `qns/ssi263.py` - add duration calculation and pending interrupt
- `qns/bns.py` - check for pending SSI-263 interrupt in run loop

## Implementation

### In ssi263.py:

1. Add instance variables:
```python
self._pending_irq_cycle = None  # Cycle when INT1 should fire
self._clock = 12_288_000  # CPU clock for timing
```

2. Add method to calculate phoneme duration:
```python
def _calc_phoneme_duration_cycles(self) -> int:
    """Calculate phoneme duration in CPU cycles."""
    rate = (self.rate_inflection >> 4) & 0x0F
    dur_mode = (self.duration_phoneme >> 6) & 0x03
    duration_ms = (((16 - rate) * 4096) // 1023) * (4 - dur_mode)
    return (duration_ms * self._clock) // 1000
```

3. In `_speak_phoneme()`, instead of immediate INT1:
```python
if self.irq_enabled and self._irq_callback:
    duration = self._calc_phoneme_duration_cycles()
    self._pending_irq_cycle = current_cycle + duration
```

4. Add method to check pending interrupt:
```python
def check_pending_irq(self, current_cycle: int) -> None:
    """Check if pending IRQ should fire. Call from main loop."""
    if self._pending_irq_cycle is not None and current_cycle >= self._pending_irq_cycle:
        self._pending_irq_cycle = None
        if self._irq_callback:
            self._irq_callback(1)  # Assert INT1
```

### In bns.py:

1. Pass cycle count to `_speak_phoneme()` or add a `set_cycle_count()` method

2. In run loop, call `self.ssi263.check_pending_irq(cycles_run)` periodically

## Test Command
```bash
uv run python -m qns.bns --cycles 20000000 --stats roms/NFB99/BSPENG/bspeng.bns 2>&1 | grep -E "(SSI263|Phonemes|PC:)" | head -50
```

Expected: Should see non-pause phonemes (not just 0x00) as speech ISR runs.

## Output
Write findings/status to `./reports/phoneme-duration-timing-report.md`

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
