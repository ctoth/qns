# MAME SSI-263 Implementation - Raw Scout Findings

## Overview

MAME's SSI-263 implementation is called `ssi263hle_device` (High-Level Emulation). The implementation is explicitly described as temporary and incomplete, using the Votrax SC-01A as a workaround.

### Developer Note from Source

> "NOTE: This is completely wrong, and exists only to have working audio in Thayer's Quest, which would not otherwise be playable due to relying on speech output for important gameplay cues."

## Source File Locations

- **Header**: `src/devices/sound/ssi263hle.h`
- **Implementation**: `src/devices/sound/ssi263hle.cpp`
- **Votrax backend**: `src/devices/sound/votrax.cpp` and `votrax.h`
- **Driver example**: `src/mame/misc/thayers.cpp` (Thayer's Quest)

GitHub URLs:
- https://github.com/mamedev/mame/blob/master/src/devices/sound/ssi263hle.h
- https://github.com/mamedev/mame/blob/master/src/devices/sound/ssi263hle.cpp
- https://github.com/mamedev/mame/blob/master/src/devices/sound/votrax.cpp
- https://github.com/mamedev/mame/blob/master/src/devices/sound/votrax.h

## SSI263HLE Class Structure

```cpp
class ssi263hle_device : public device_t, public device_mixer_interface
{
public:
    static constexpr feature_type imperfect_features() { return feature::SOUND; }

    ssi263hle_device(const machine_config &mconfig, const char *tag, device_t *owner, u32 clock = 0);

    void map(address_map &map) ATTR_COLD;
    auto ar_callback() { return m_ar_cb.bind(); }

protected:
    virtual void device_start() override ATTR_COLD;
    virtual void device_reset() override ATTR_COLD;
    virtual void device_add_mconfig(machine_config &config) override ATTR_COLD;

private:
    required_device<votrax_sc01_device> m_votrax;

    TIMER_CALLBACK_MEMBER(phoneme_tick);

    void duration_phoneme_w(u8 data);
    void inflection_w(u8 data);
    void rate_inflection_w(u8 data);
    void control_articulation_amplitude_w(u8 data);
    void filter_frequency_w(u8 data);
    u8 status_r();

    void votrax_request(int state);

    devcb_write_line m_ar_cb;
    emu_timer *m_phoneme_timer = nullptr;

    u8 m_duration;
    u8 m_phoneme;
    u16 m_inflection;
    u8 m_rate;
    u8 m_articulation;
    bool m_control;
    u8 m_amplitude;
    u8 m_filter;
    u8 m_mode;
    u8 m_data_request;

    u8 m_votrax_fifo[1024];
    u32 m_votrax_fifo_wr;
    u32 m_votrax_fifo_rd;
    u32 m_votrax_fifo_cnt;
};
```

## Register Map (SSI263HLE)

| Address | Read | Write |
|---------|------|-------|
| 0x00 | Status | Duration-Phoneme |
| 0x01 | Status | Inflection |
| 0x02 | Status | Rate-Inflection |
| 0x03 | Status | Control-Articulation-Amplitude |
| 0x04-0x07 | Status | Filter-Frequency |

## Phoneme Name Table (64 entries)

From ssi263hle.cpp - names for debugging:
```
"PA", "E", "E1", "Y", "YI", "AY", "IE", "I",
"A", "AI", "EH", "EH1", "AE", "AE1", "AH", "AH1",
"AW", "AW1", "OU", "OO", "IU", "IU1", "U", "U1",
"UH", "UH1", "UH2", "UH3", "ER", "R", "R1", "R2",
"L", "L1", "LF", "W", "B", "D", "KV", "P",
"T", "K", "HV", "HVC", "HF", "HFC", "HN", "Z",
"S", "J", "SCH", "V", "F", "THV", "TH", "M",
"N", "NG", ":A", ":OH", ":U", ":UH", "E2", "LB"
```

## SSI-263 to SC-01A Phoneme Mapping Table

The `PHONEMES_TO_SC01` conversion table maps SSI-263 phoneme codes (0-63) to Votrax SC-01A equivalents:
```cpp
static const u8 PHONEMES_TO_SC01[64] = {
    // PA->PA0, E->E, E1->E1, Y->Y1, etc.
    // 64-byte array mapping each SSI-263 phoneme to closest SC-01A equivalent
};
```

## Timing Calculations

Frame time calculation from ssi263hle.cpp:
```cpp
frame_time_us = (4096 * (16 - rate)) / 2
phoneme_duration = frame_time_us * (4 - duration)
```

Where:
- `rate` = bits 7:4 of rate/inflection register (0-15)
- `duration` = bits 7:6 of duration/phoneme register (0-3)

## How MAME Generates Audio

MAME's SSI263HLE does NOT directly generate audio samples. Instead:

1. SSI263 phoneme codes are translated to SC-01A phoneme codes
2. Translated phonemes are queued in a 1024-byte FIFO
3. The Votrax SC-01A device generates the actual audio
4. Votrax uses formant synthesis (not PCM samples)

## Votrax SC-01A Implementation (The Real Audio Engine)

### Architecture

The Votrax SC-01A implementation uses analog formant synthesis based on die imaging reverse engineering. Key quote:

> "MAME 0.181 marks the debut of Votrax SC-01 emulation in MAME, based on reverse-engineering die photographs. The digital section should be pretty much perfect, although there are still some issues in the analog section (plosives don't sound quite right)."

### Signal Path in analog_calc()

1. **Glottal Source**: Pick up pitch wave from `s_glottal_wave` lookup (9-sample table, values -4/7 to 7/7)
2. **Voice Amplitude**: Multiply by `m_filt_va / 15.0`
3. **F1 Filter**: Apply first formant filter using `apply_filter()` with `m_f1_a` and `m_f1_b` coefficients
4. **F2 Voice Filter**: Apply second formant filter (voice half)
5. **Noise Path**: Parallel processing with noise shaper
6. **F2 Noise**: Second formant for noise component
7. **Mixing**: Combine F2 voice and F2 noise outputs
8. **F3, F4 Filters**: Apply third and fourth formant filters
9. **Glottal Closure**: Multiply by closure amplitude (inverted 3-bit value)
10. **Output Lowpass**: Fixed lowpass filter, scaled to 0.35

### Filter Implementation

- Uses bilinear transform digital filters derived from analog circuit analysis
- Switched-capacitor design (capacitor ratios determine filter response)
- Four main formant filters (F1-F4) built via `build_standard_filter()`
- Pre-warping frequency: `sqrt(|k0*k1-k2|) / (2*pi*k2)`

### ROM Parameters Per Phoneme

Each of the 64 phonemes has ROM data encoding:
- `m_rom_duration` - Duration in 5KHz units (7 bits)
- `m_rom_vd`, `m_rom_cld` - Voice and closure delays (4 bits each)
- `m_rom_fa`, `m_rom_fc`, `m_rom_va` - Noise volume, noise freq cutoff, voice volume (4 bits each)
- `m_rom_f1`, `m_rom_f2`, `m_rom_f2q`, `m_rom_f3` - Formant frequencies and Q (4 bits each, f2 is 5 bits)
- `m_rom_closure` - Closure bit (true = silence at cld)
- `m_rom_pause` - Pause marker for PA0/PA1 phones

### Sample Generation Rate

- Main clock divides into control clock (`/36`) and sample clock (`/18`)
- Audio stream at `m_sclock = mainclock / 18.0`
- Internal chip updates at `m_cclock = mainclock / 36.0`

### Parameter Interpolation

Formant parameters interpolate toward ROM targets:
```cpp
reg = reg - (reg >> 3) + (target << 1)
```
Provides smooth 1/8-step transitions. Pause phones freeze formant updates unless voice/noise amplitudes reach zero.

### Timing Details

- Phone tick counter increments per sample
- Comparator fires when `phonetick == (duration << 2) | 1`
- Interpolation cycle every ~208Hz
- Parameter updates every ~625Hz

## Thayer's Quest Driver Configuration

```cpp
SSI263HLE(config, m_ssi, 860000);  // 860 kHz clock

// Audio routing
m_ssi->add_route(ALL_OUTPUTS, *this, 1.0);  // stereo at 1.0 gain

// Interrupt callback
m_ssi->ar_callback().set(FUNC(thayers_state::ssi_data_request_w));

// I/O mapping (0x00-0x07)
map(0x00, 0x07).m(m_ssi, FUNC(ssi263hle_device::map));
```

## Key Differences from QNS Implementation

| Aspect | MAME | QNS |
|--------|------|-----|
| Audio Source | Formant synthesis via Votrax | PCM samples from AppleWin |
| Phoneme Handling | Translates to SC-01A | Direct playback |
| Sample Rate | Derived from clock | Fixed 22050 Hz |
| Filter | 4-stage IIR formant filters | Pass-through (TBD) |
| Timing | Timer-based with frame/phoneme modes | Duration formula |

## Historical Notes

### SC-01 to SSI-263 Relationship

- SC-01A was enhanced to become the SC-02 (SSI-263)
- SSI-263 is "quite an upgrade from the SC-01; it has many more control registers"
- "Has the same analog formant synthesis core as the SC-01"
- Compatible ICs: Votrax SC-02, TDK/SSI-78A263 A/P, Artic 263

### MAME Version History

- MAME 0.181: Debut of Votrax SC-01 emulation based on die photographs
- MAME 0.225: Adjusted pitch and closure
- MAME 0.226: Adjusted filters
- Game status: `MACHINE_IMPERFECT_SOUND` (known incomplete)

## Complete SSI-263 Phoneme Table (from Programming Guide)

| Hex | Symbol | Example | Hex | Symbol | Example |
|-----|--------|---------|-----|--------|---------|
| 00 | PA | pause | 20 | L | Lift |
| 01 | E | MEET | 21 | L1 | pLay |
| 02 | E1 | bIt | 22 | LF | faLL |
| 03 | Y | Yet | 23 | W | Water |
| 04 | YI | babY | 24 | B | Bag |
| 05 | AY | bAIt | 25 | D | paiD |
| 06 | IE | anY | 26 | KV | sKy |
| 07 | I | sIx | 27 | P | Pen |
| 08 | A | mAde | 28 | T | TarT |
| 09 | A1 | cAre | 29 | K | Kit |
| 0A | EH | nEst | 2A | HV | aHead |
| 0B | EH1 | bElt | 2B | HVC | aHead |
| 0C | AE | dAd | 2C | HF | Heart |
| 0D | AE1 | After | 2D | HFC | Heart |
| 0E | AH | gOt | 2E | HN | Horse |
| 0F | AH1 | fAther | 2F | Z | Zero |
| 10 | AW | Office | 30 | S | Same |
| 11 | AW1 | stOre | 31 | J | aZure |
| 12 | OU | bOAt | 32 | SCH | SHip |
| 13 | OO | lOOk | 33 | V | Very |
| 14 | IU | yOU | 34 | F | Four |
| 15 | IU1 | cOUld | 35 | THV | THere |
| 16 | U | tUne | 36 | TH | wiTH |
| 17 | U1 | cartOOn | 37 | M | More |
| 18 | UH | wOnder | 38 | N | Nine |
| 19 | UH1 | lOve | 39 | NG | siNG |
| 1A | UH2 | whAt | 3A | :A | German a |
| 1B | UH3 | nUt | 3B | :OH | French o |
| 1C | ER | bIRd | 3C | :U | German u |
| 1D | R | Roof | 3D | :UH | French u |
| 1E | R1 | Rug | 3E | E2 | German i |
| 1F | R2 | German R | 3F | LB | LuBe |

## SSI-263 Register Details (from Datasheet)

### Register 0: Duration/Phoneme
- Bits 7-6: Duration mode (DR1, DR0)
  - 00: IRQ disabled
  - 01: Frame immediate inflection
  - 10: Phoneme immediate inflection
  - 11: Phoneme transitioned inflection
- Bits 5-0: Phoneme code (0-63)

### Register 1: Inflection
- Bits 7-0: I10:I3 of 12-bit inflection

### Register 2: Rate/Inflection
- Bits 7-4: Rate (0-15, 0=slowest, 15=fastest)
- Bit 3: I11 (MSB of inflection)
- Bits 2-0: I2:I0 (LSB of inflection)

### Register 3: Control/Articulation/Amplitude
- Bit 7: CTL (1=standby/power-down, 0=active)
- Bits 6-4: Articulation (0-7)
- Bits 3-0: Amplitude (0-15, 0=silent, 15=loudest)

### Register 4: Filter Frequency
- Bits 7-0: Filter frequency (0-255)

## CTL Bit and Timing Modes

The CTL bit (bit 7 of register 3) selects between frame and phoneme timing modes:
- CTL=1: Standby/power-down mode
- CTL=0: Active mode

Combined with duration bits determines:
- Frame timing mode
- Phoneme timing mode
- Transitioned vs immediate inflection

## AppleWin Implementation Notes (for comparison)

AppleWin uses PCM samples extracted from the chip, not formant synthesis:
- Sample rate: 22050 Hz
- 62 phoneme samples (phonemes 2-63, phoneme 0=pause, 1 maps to 2)
- Each sample ~1300-1700 samples long (~60-77ms)
- DirectSound ring-buffer for playback
- Duration mode affects sample averaging

## Sources

### Primary Sources
- [MAME GitHub Repository](https://github.com/mamedev/mame)
- [ssi263hle.h](https://github.com/mamedev/mame/blob/master/src/devices/sound/ssi263hle.h)
- [votrax.cpp](https://github.com/mamedev/mame/blob/master/src/devices/sound/votrax.cpp)
- [thayers.cpp](https://github.com/mamedev/mame/blob/master/src/mame/misc/thayers.cpp)

### Datasheets and Documentation
- [SSI-263A Data Sheet (Archive.org)](https://archive.org/details/ssi-263-a)
- [SSI-263A Programming Guide (Archive.org)](https://archive.org/stream/SSI-263A_Programming_Guide/SSI-263A_Programming_Guide_djvu.txt)
- [Votrax SC-02/SSI-263A Data Sheet 1985](https://archive.org/details/bitsavers_federalScrI263APhonemeSpeechSynthesizerDataSheet19_1827998)
- [SC-01A Speech Synthesizer Info](https://www.redcedar.com/sc01.htm)

### Related Projects
- [AppleWin GitHub](https://github.com/AppleWin/AppleWin)
- [Votrax SC-01 Phoneme Table (Vocal Synthesis Wiki)](https://vocal-synthesis.fandom.com/wiki/Votrax_SC-01/Phoneme_table)

### Forum Discussions
- [Mockingboard: Playing SC-01 speech on SSI263](https://groups.google.com/g/comp.sys.apple2.programmer/c/F3JfFVOR6pc)
- [MAME 0.181 Votrax announcement](https://forums.bannister.org/ubbthreads.php?ubb=showflat&Number=108273)

## Raw Notes

- MAME SSI263HLE is marked `MACHINE_IMPERFECT_SOUND`
- The real SC-01/SSI-263 uses analog formant synthesis
- PCM sample approach (like AppleWin/QNS) bypasses the analog synthesis entirely
- MAME's Votrax has known issues with plosives
- The 12-bit inflection is "tuned to an even tempered scale with microtones"
- Glissando effects possible via inflection-rate control
- Holding phonemes: frame timing mode + max duration + min rate
