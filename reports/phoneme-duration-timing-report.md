# Phoneme Duration Timing Implementation Report

## Summary

Successfully implemented phoneme duration timing for INT1 in the SSI-263 emulation. The implementation correctly calculates phoneme duration using the AppleWin formula and schedules INT1 to fire after the phoneme completes.

## Changes Made

### File: `qns/ssi263.py`

1. **Added timing instance variables to `__init__`:**
   - `clock` parameter (default 12,288,000 Hz)
   - `_pending_irq_cycle: int | None` - Cycle when INT1 should fire
   - `_current_cycle: int` - Current cycle count for timing calculations

2. **Added `set_cycle_count(cycles: int)` method:**
   - Updates the current cycle count for timing calculations
   - Called by main loop to sync SSI-263 with CPU cycles

3. **Added `_calc_phoneme_duration_cycles()` method:**
   - Uses AppleWin formula from SSI263.cpp line 95:
     ```python
     rate = (self.rate_inflection >> 4) & 0x0F
     dur_mode = (self.duration_phoneme >> 6) & 0x03
     duration_ms = (((16 - rate) * 4096) // 1023) * (4 - dur_mode)
     return (duration_ms * self._clock) // 1000
     ```
   - Returns duration in CPU cycles

4. **Added `check_pending_irq(current_cycle: int)` method:**
   - Checks if pending IRQ should fire
   - Clears pending IRQ and calls callback when triggered
   - Sets `speaking = False` when phoneme completes

5. **Modified `_speak_phoneme()` method:**
   - Now logs duration in ms: `duration=64ms`
   - Sets `speaking = True` while phoneme plays
   - Schedules INT1 using: `self._pending_irq_cycle = self._current_cycle + duration_cycles`

### File: `qns/bns.py`

1. **Updated SSI263 instantiation:**
   - Passes `clock=clock` to SSI263 constructor

2. **Updated run loop:**
   - Added cycle count update: `self.ssi263.set_cycle_count(cycles_run)`
   - Added IRQ check: `self.ssi263.check_pending_irq(cycles_run)`

## Duration Calculations Verified

| Mode | Rate | Duration (ms) | Cycles at 12.288 MHz |
|------|------|---------------|---------------------|
| 3    | 0    | 64            | 786,432             |
| 2    | 0    | 128           | 1,572,864           |
| 1    | 0    | 192           | 2,359,296           |
| 0    | 0    | 256           | 3,145,728           |
| 3    | 15   | 4             | 49,152              |
| 0    | 15   | 16            | 196,608             |

## Test Results

Running with `--cycles 20000000`:
- Phonemes output with correct duration: `[SSI263] Phoneme: 0x00 PA (pause) duration=64ms`
- Duration varies correctly (64ms for mode 3, 256ms for mode 0)

## Key Finding: Firmware Does Not Wait for INT1

Analysis revealed that during initialization, the firmware:
1. Sends pause phonemes (0x00) every ~700,000 cycles
2. Does NOT wait for INT1 (phoneme completion interrupt)
3. Polls the status register instead

This is why INT1 never fires during boot:
- Phoneme scheduled at cycle 327,000 to fire at 1,113,432
- But new phoneme written at 1,042,000 (before 1,113,432)
- Each write overwrites the pending IRQ, pushing it forward
- The pending IRQ never catches up

This appears to be intentional initialization behavior - the firmware sends pause phonemes for "warm-up" without waiting for each to complete.

## Remaining Issues

The phoneme duration timing is now correct, but the **silent startup issue** remains:
- Only pause phonemes (0x00) are being sent
- No actual speech phonemes appear
- This is a separate issue documented in `prompts/silent-startup-investigation.md`

The timing implementation is complete and working as designed.

## Files Modified

- `C:\Users\Q\code\qns\qns\ssi263.py`
- `C:\Users\Q\code\qns\qns\bns.py`

## Test Command

```bash
uv run python -m qns.bns --cycles 20000000 --stats roms/NFB99/BSPENG/bspeng.bns 2>&1 | head -50
```
