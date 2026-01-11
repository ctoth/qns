# SSI-263 Our Implementation Analysis Report

## Overview

This report documents our current SSI-263 speech synthesizer implementation in `qns/synth/`. The implementation produces audio but reportedly sounds "terrifying and alien" - garbled with wrong timing.

## File Structure

```
qns/synth/
  __init__.py          - Module exports (SSI263State, SSI263Synth)
  ssi263_synth.py      - Main synthesizer class (234 lines)
  phonemes.py          - Phoneme sample data (~878KB, auto-generated)
  dsp.py               - Audio DSP functions (123 lines)
  player.py            - Real-time audio output (113 lines)

qns/
  ssi263.py            - Chip register emulation (326 lines)
```

---

## 1. Phoneme Data (`phonemes.py`)

### Source
- Auto-generated from AppleWin's `SSI263Phonemes.h` via `tools/extract_phonemes.py`
- Sample rate: **22050 Hz**
- Total samples: **156,566** 16-bit signed samples
- Number of phonemes: **62** (NOT 64 - two are missing!)

### Data Structure
```python
PHONEME_INFO: list[tuple[int, int]]  # (offset, length) pairs
PHONEME_DATA: np.ndarray             # int16 samples
```

### Sample Lengths
Analyzing `PHONEME_INFO`:
- Most phonemes: ~1280-1370 samples (~58-62ms at 22050Hz)
- Shortest: phonemes 35-39 have 440-506 samples (~20-23ms)
- These short phonemes (35-39) are likely plosives/stops

### CRITICAL ISSUE: Phoneme Count Mismatch
Our data has **62 phonemes** but SSI-263 has **64 phoneme codes** (0-63).

Looking at AppleWin's `Play()` function:
```cpp
if (nPhoneme == 1)
    nPhoneme = 2;   // Missing this sample, so map to phoneme-2

if (nPhoneme == 0)
    bPause = true;
else
    nPhoneme-=2;    // Missing phoneme-1
```

This reveals:
- **Phoneme 0** = Pause (silence)
- **Phoneme 1** = Missing, maps to phoneme 2
- **Phonemes 2-63** map to data indices 0-61

**Our implementation does NOT handle this offset!** We directly use phoneme codes as array indices.

---

## 2. DSP Pipeline (`dsp.py`)

### Pipeline Order in `get_phoneme_audio()`:
```python
samples = get_phoneme_samples(phoneme)
samples = apply_amplitude(samples, amplitude)      # 1. Volume scaling
samples = apply_filter(samples, filter_freq)       # 2. Filter (placeholder)
samples = time_stretch(samples, rate, duration)    # 3. Duration adjustment
samples = pitch_shift(samples, inflection)         # 4. Pitch modification
return (samples / 32768.0).astype(np.float32)      # 5. Normalize to float
```

### `apply_amplitude(samples, amplitude)`
- Input: `amplitude` 4-bit (0-15)
- Linear scaling: `samples * (amplitude / 15.0)`
- `amplitude=0` returns silence
- **Seems correct**

### `apply_filter(samples, filter_freq)`
- Input: `filter_freq` 8-bit (0-255)
- **NOT IMPLEMENTED** - just returns copy of input
- `filter_freq=0xFF` returns silence (matches AppleWin)
- Comment: "filter implementation TBD"

**ISSUE**: No actual filtering is performed. The SSI-263 filter controls formant resonance.

### `time_stretch(samples, rate, duration)`
- Input: `rate` 4-bit (0-15), `duration` 2-bit (0-3)
- Duration modes:
  - DUR=0,1: No averaging, return original
  - DUR=2: Average 2 samples (output length halved)
  - DUR=3: Average 4 samples (output length quartered)
- **Rate parameter is IGNORED!**

**CRITICAL ISSUE**: The `rate` parameter is not used at all! Looking at AppleWin:
```cpp
// phonemeDuration_ms = (((16-rate)*4096)/1023) * (4-dur_mode)
```
Rate affects how long a phoneme plays. Our implementation ignores this entirely.

### `pitch_shift(samples, inflection)`
- Input: `inflection` 12-bit (0-4095)
- `ratio = 1.0 + (inflection - 2048) / 4096.0`
- Uses linear interpolation resampling
- Range: ~0.5x to ~1.5x pitch (2048 = neutral)

**POTENTIAL ISSUE**: The formula may not match actual SSI-263 behavior. AppleWin doesn't seem to use inflection for pitch in the main playback loop - it's more complex.

---

## 3. Audio Player (`player.py`)

### Implementation
- Uses `sounddevice` library with callback-based streaming
- Sample rate: 22050 Hz
- Channels: 1 (mono)
- Block size: 512 samples (~23ms)
- Uses a queue + buffer system for continuous playback

### Callback Flow
```python
def _audio_callback(self, outdata, frames, time_info, status):
    # Fill buffer from queue
    while len(self._buffer) < frames:
        chunk = self._queue.get_nowait()  # Get queued samples
        self._buffer = np.concatenate([self._buffer, chunk])

    # Output samples
    if len(self._buffer) >= frames:
        outdata[:, 0] = self._buffer[:frames]
        self._buffer = self._buffer[frames:]
```

### Potential Issues
1. **No crossfading between phonemes** - may cause clicks/pops at boundaries
2. **Queue-based system** - phonemes may pile up or have gaps
3. **No timing synchronization** with CPU cycles
4. **concatenate() in callback** - may cause audio glitches due to allocation

---

## 4. Synthesizer Core (`ssi263_synth.py`)

### State Management (`SSI263State`)
```python
@dataclass
class SSI263State:
    phoneme: int = 0          # 6-bit (0-63)
    duration: int = 3         # 2-bit (0-3)  <- DEFAULT IS 3, NOT 0!
    inflection: int = 0       # 12-bit (0-4095)  <- DEFAULT IS 0, NOT 2048!
    rate: int = 0             # 4-bit (0-15)
    articulation: int = 0     # 3-bit (0-7)
    amplitude: int = 15       # 4-bit (0-15)
    filter_freq: int = 0      # 8-bit (0-255)
    control: bool = True      # CTL bit
```

**ISSUES**:
1. `duration=3` default means maximum sample averaging (4x) - audio will be very short
2. `inflection=0` default means maximum pitch DOWN shift (not neutral at 2048)
3. No `articulation` parameter usage anywhere!

### Register Write Methods

#### `write_durphon(value)`
```python
self.state.duration = (value >> 6) & 0x03
self.state.phoneme = value & 0x3F
if not self.state.control:
    self._play_current_phoneme()
```
- Correct bit extraction
- Plays phoneme if CTL=0 (correct)

#### `write_inflect(value)`
```python
# I10:I3 (8 bits)
self.state.inflection = (self.state.inflection & 0x007) | (value << 3)
```
- Sets bits I10:I3 correctly

#### `write_rateinf(value)`
```python
self.state.rate = (value >> 4) & 0x0F
i11 = (value >> 3) & 0x01
i2_0 = value & 0x07
self.state.inflection = (i11 << 11) | (self.state.inflection & 0x7F8) | i2_0
```
- Rate extraction correct
- Inflection bit assembly looks correct

#### `write_ctrlamp(value)`
```python
old_control = self.state.control
self.state.control = bool(value & 0x80)
self.state.articulation = (value >> 4) & 0x07
self.state.amplitude = value & 0x0F

# CTL transition 1->0 wakes up and plays phoneme
if old_control and not self.state.control:
    self._play_current_phoneme()
```
- Correct CTL wake-up behavior
- **Articulation extracted but never used!**

### HACK in `_play_current_phoneme()`
```python
# HACK: Force amplitude to 15 if it's 0 (workaround for VOLUME bug)
if self.state.amplitude == 0:
    self.state.amplitude = 15
```
This override might be hiding a real issue - why is amplitude 0?

---

## 5. Chip Emulation (`ssi263.py`)

### Dual Phoneme Tracking
The chip emulation (`SSI263` class) and synth (`SSI263Synth` class) BOTH track phoneme playback:

In `SSI263._speak_phoneme()`:
```python
self.speaking = True
if self.irq_enabled and self._irq_callback:
    self._pending_irq_cycle = self._current_cycle + duration_cycles
```

But it also forwards to synth:
```python
if self._synth:
    self._synth.write_durphon(value)
```

**This creates confusion** - the chip tracks timing for IRQ, but the synth tracks audio playback separately. They may get out of sync.

### Duration Calculation
```python
def _calc_phoneme_duration_cycles(self) -> int:
    rate = (self.rate_inflection >> 4) & 0x0F
    dur_mode = (self.duration_phoneme >> 6) & 0x03
    duration_ms = (((16 - rate) * 4096) // 1023) * (4 - dur_mode)
    return (duration_ms * self._clock) // 1000
```

This matches AppleWin's formula! But our DSP `time_stretch()` doesn't use this at all.

---

## 6. Critical Issues Summary

### 1. Phoneme Index Offset (HIGH)
- SSI-263 phoneme 0 = pause
- SSI-263 phoneme 1 = missing, should map to 2
- SSI-263 phonemes 2-63 map to our data indices 0-61
- **We don't do this mapping!**

### 2. Rate Parameter Ignored (HIGH)
- `rate` (0-15) affects phoneme playback duration
- Our `time_stretch()` completely ignores it
- This affects timing of all speech

### 3. Duration Mode Behavior (HIGH)
- Our implementation averages samples (shortens output)
- AppleWin uses averaging but within a different flow
- DUR=1 special case: skip every 4th sample (we don't do this!)

### 4. No Phoneme Repeat/Loop (HIGH)
- Real SSI-263 repeats phoneme until new one is sent or CTL=1
- Our implementation plays phoneme once and stops
- AppleWin has `RepeatPhoneme()` function

### 5. Articulation Unused (MEDIUM)
- Articulation is extracted from registers but never applied
- SSI-263 articulation affects consonant/vowel transitions

### 6. Filter Unimplemented (MEDIUM)
- Filter frequency parameter is not applied
- Only 0xFF (silence) is handled

### 7. Inflection/Pitch May Be Wrong (MEDIUM)
- Our formula: `ratio = 1.0 + (inflection - 2048) / 4096.0`
- Need to verify this matches actual SSI-263 behavior

### 8. Default State Issues (MEDIUM)
- `duration=3` default causes 4x sample averaging
- `inflection=0` default causes pitch down shift

### 9. Audio Pipeline Issues (LOW-MEDIUM)
- No crossfading between phonemes
- No synchronization with CPU timing
- Memory allocation in audio callback

---

## 7. Comparison with AppleWin

| Feature | AppleWin | Our Implementation |
|---------|----------|-------------------|
| Phoneme offset (0,1 mapping) | Yes | **No** |
| Rate parameter | Used for timing | **Ignored** |
| Duration averaging | With DUR=1 skip | **No skip mode** |
| Phoneme repeat | Yes (`RepeatPhoneme()`) | **No** |
| IRQ generation | Cycle-accurate | Chip-level only |
| Articulation | Not clear | **Unused** |
| Filter | Not clear | **Placeholder** |
| Ring buffer | DirectSound | Queue-based |

---

## 8. Questions Needing Answers

1. What is the actual SSI-263 behavior for articulation parameter?
2. How does the real filter work - is it a formant filter?
3. Is inflection pitch linear or logarithmic?
4. Should phonemes crossfade or have hard transitions?
5. Why was the amplitude=0 hack added? What causes zero amplitude?
6. Is the phoneme data from AppleWin accurate to real hardware?

---

## 9. Recommended Investigation Order

1. **Fix phoneme index offset** - This is likely causing completely wrong sounds
2. **Implement rate parameter** - Affects all timing
3. **Add DUR=1 skip mode** - Matches AppleWin behavior
4. **Implement phoneme repeat** - Required for continuous speech
5. **Fix default state values** - Duration=0, Inflection=2048
6. **Investigate amplitude=0 hack** - May indicate register ordering issue
7. **Add crossfading** - Improve audio quality
8. **Implement articulation** - Once basics work

---

## Appendix A: File Hashes and Sizes

| File | Size | Purpose |
|------|------|---------|
| `__init__.py` | 189B | Exports |
| `ssi263_synth.py` | 7.4KB | Main synth |
| `phonemes.py` | ~878KB | Sample data |
| `dsp.py` | 3.0KB | DSP functions |
| `player.py` | 2.8KB | Audio output |
| `ssi263.py` | 10KB | Chip emulation |

## Appendix B: Phoneme Duration Examples

At 22050 Hz with no rate adjustment:
- Phoneme 0 (index -2): 1328 samples = 60.2ms
- Phoneme 34 (index 32): 506 samples = 22.9ms
- Average phoneme: ~1300 samples = 59ms

With DUR=3 (4x averaging): ~15ms per phoneme
With DUR=0 (no averaging): ~60ms per phoneme
