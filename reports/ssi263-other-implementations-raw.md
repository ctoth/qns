# SSI-263 Other Implementations - Raw Findings

Scout Agent Report - 2026-01-10

---

## 1. AppleWin (Primary Reference)

**Repository:** https://github.com/AppleWin/AppleWin

**Source Files:**
- `source/SSI263.cpp` - Main implementation (~1200 lines)
- `source/SSI263.h` - Header with class definition
- `source/SSI263Phonemes.h` - Phoneme PCM data (~1.1MB, 156,566 samples)

**Language:** C++

**License:** GPL v2

**Approach:** PCM Sample Playback
- Uses pre-recorded phoneme samples (NOT formant synthesis)
- 62 phonemes stored as signed 16-bit PCM at 22050 Hz
- Samples extracted from real SSI-263 hardware
- Phoneme data structure: offset + length into sample array

**Audio Generation:**
- DirectSound ring buffer for playback
- Real-time amplitude modulation based on register values
- Duration control via DUR bits (stretch/compress playback)
- No actual filter frequency emulation
- No rate/inflection emulation

**Register Emulation:**
- REG0: Duration/Phoneme (DURPHON)
- REG1: Inflection
- REG2: Rate/Inflection (RATEINF)
- REG3: Control/Articulation/Amplitude (CTTRAMP)
- REG4: Filter Frequency (FILFREQ)

**Timing/Interrupt Handling:**
- Phoneme complete triggers IRQ
- CTL bit controls power-down mode
- D7 pin reflects A/!R status
- Supports both Mockingboard and Phasor modes
- 6522 VIA integration for interrupt routing

**Known Limitations (from Issue #175):**
- "SSI263 emulation is very basic: there is no attempt to emulate rate, inflection or filters"
- Rate, inflection, articulation registers are stored but NOT applied to audio
- Filter frequency register NOT functional

**SC-01 to SSI-263 Translation:**
- Contains 64-entry `m_Votrax2SSI263[]` table
- Maps SC-01 phonemes to closest SSI-263 equivalent
- Used for backwards compatibility with SC-01 games

**Chip Variants Supported:**
- SSI263Empty (no chip)
- SSI263P (original, has reset bug)
- SSI263AP (bugfix version, default)

---

## 2. MAME Votrax SC-01/SC-02 Emulation

**Repository:** https://github.com/mamedev/mame

**Source Files:**
- `src/devices/sound/votrax.cpp`
- `src/devices/sound/votrax.h`

**Language:** C++

**License:** BSD-3-Clause (MAME license)

**Approach:** True Formant Synthesis (for SC-01)
- Mathematical simulation of analog circuit
- Based on reverse-engineering die photographs (SC-01A decap)
- Digital section: "pretty much perfect"
- Analog section: "still some issues, plosives don't sound quite right"

**Technical Details from votrax.cpp:**
- Uses 4 formant filters (F1, F2, F3, F4)
- F2 splits into voice and noise paths
- Noise shaper filter for fricatives
- Glottal pulse generation from stored waveform
- Real-time sample calculation at 16kHz

**Filter Implementation:**
- F1, F2, F3 variable formant filters
- F4 fixed frequency filter
- Output filter for final shaping
- Known bug: "Die bug there: fc should be updated, not va"
- Noise filter documented as "numerically unstable"

**SSI-263 Status in MAME:**
- Pull Request #11915 added SSI-263 skeleton device
- Uses `ssi263hle` device (High-Level Emulation)
- Currently remaps SC-02 phonemes onto SC-01's phoneme set
- Described as "temporary" and "placeholder"

**Update History:**
- MAME 0.181: Initial Votrax SC-01 emulation debut
- MAME 0.225: Adjusted SC-01 pitch and closure
- MAME 0.226: Adjusted SC-01 filters

---

## 3. Hardware Replacement Modules

### SC-01 Emulator by The Geek Pub / ReactiveMicro

**Product URLs:**
- https://www.thegeekpub.com/product/sc-01-speech-chip-emulator-votrax/
- https://www.reactivemicro.com/product/sc-01-emulator-sound-and-speech-replacement-module/

**Approach:**
- Physical drop-in replacement for SC-01 socket
- STM32 microcontroller emulation
- Based on MAME emulator code
- "No recorded sounds; phonemes are recreated by a sound engine"

**Technical Notes:**
- Supports variable clock frequencies for pitch control
- V1.1+ enabled variable clock by default
- "Code is based on MAME's SC-01 emulation, which is still a work in progress, and not 100% accurate"

**Use Cases:**
- Arcade game restoration (Q*bert, Gorf, Wizard of Wor)
- Apple Mockingboard restoration
- Atari Alien Voice Box

---

## 4. Arduino/Hardware Projects

### SSI-263 via Nanpy on Arduino

**Source:** https://gist.github.com/deladriere/8878702

**Blog Post:** https://www.polaxis.be/2014/02/ssi-263-text-to-speech-in-python-via-nanpy-on-the-arduino/

**Language:** Python (with Arduino hardware)

**Approach:** Direct hardware control
- Controls actual SSI-263 chip via Arduino pins
- NOT emulation - drives real hardware
- Uses ATtiny45 for clock generation (1-2 MHz)

**Text-to-Speech Pipeline:**
1. NLTK CMU Dictionary lookup for word -> ARPAbet
2. ARPAbet -> SSI-263 phoneme code mapping
3. Serial command to Arduino
4. Arduino writes to SSI-263 registers

**Pin Configuration:**
- Pins 2-13 for data/register bus
- Pin 13 for R/W strobe
- Pin 15 for acknowledge/request

**Reference Material:**
- Steve Ciarcia's "Build a Third-Generation Phonetic Speech Synthesizer", Byte magazine, March 1984, p28

---

## 5. BNS (Braille 'n Speak) Emulators

### emubns

**Website:** https://emubns.sourceforge.net/

**Source:** `svn://svn.code.sf.net/p/emubns/code/`

**Language:** C

**Author:** Mateusz Viste (2020-2024)

**Approach:** Protocol Emulation Only
- Does NOT emulate SSI-263 chip
- Emulates BNS serial communication protocol
- Pipes text to external TTS (espeak-ng, Piper, etc.)
- Listens on TCP port 7333

**Use Case:**
- Running DOS screen readers (PROVOX, ASAP, JAWS) in emulators
- Requires QEMU or VirtualBox serial port redirect

**Note:** The original BNS hardware used an SSI-263 for speech synthesis, but emubns bypasses this entirely.

### vbns-eSpeak

**Repository:** https://github.com/sukiletxe/vbns-eSpeak

**Language:** Unknown

**Authors:** Tyler Spivey (original), Sukil Etxenike (modifications)

**Approach:** Same as emubns
- Uses eSpeak as output backend
- Protocol-level emulation only

### Rasp 'n Speak

**Forum Thread:** https://www.vogons.org/viewtopic.php?t=103744

**Approach:**
- Raspberry Pi running emubns
- USB-to-Serial connection to actual DOS PC
- Physical hardware replacement for BNS device

---

## 6. Other Apple II Emulators

### KEGS / GSplus

**KEGS:** https://kegs.sourceforge.net/

**GSplus:** https://apple2.gs/plus/

**SSI-263 Status:** NOT SUPPORTED
- Mockingboard emulation limited to AY-3-8913 sound chips only
- "just for the AY8913 sound chip, not for the SC01 speech chip"
- GSplus inherits this limitation from KEGS base

### Virtual II (Mac)

**Website:** https://virtualii.com/

**SSI-263 Status:** UNCLEAR / LIKELY NOT SUPPORTED
- Mockingboard support described as "two sound chips that together can produce 6 simultaneous sounds"
- No explicit SSI-263 mention found
- AppleWin described as having "Mockingboard (with speech, unlike most emulators)"

### microM8

**Website:** https://paleotronic.com/software/microm8/

**Language:** Go

**SSI-263 Status:** UNCLEAR
- "6-channel Mockingboard sound card emulation"
- No explicit SSI-263/speech mention found
- Focus is on "upcycling" features (3D graphics, etc.)

---

## 7. Testing Tools

### mb-audit

**Repository:** https://github.com/tomcw/mb-audit

**Author:** tomcw (Tom Charlesworth, AppleWin developer)

**Purpose:** Comprehensive Mockingboard/Phasor test suite

**SSI-263 Tests:**
- Single and dual SSI-263 configurations
- "Classic Adventure" phrase timing test
- SSI263P vs SSI263AP detection
- Willy Byte false-read bug test
- Phasor native mode SSI263 interface

**Hardware Tested:**
- ReactiveMicro Mockingboard-C
- Applied Engineering Phasor

### play-sc01-using-ssi263

**Repository:** https://github.com/tomcw/play-sc01-using-ssi263

**Author:** tomcw

**Purpose:** Play SC-01 phonemes on SSI-263 hardware

**Technical Notes:**
- Dumps SC-01 phonemes from games
- Uses AppleWin's 64-entry translation table
- On-the-fly translation in interrupt handler
- Games tested: The Spy Strikes Back, Crime Wave, Crypt of Medea, Berzap!

---

## 8. Documentation & Datasheets

### Available Documents (ReactiveMicro)

**URL:** https://downloads.reactivemicro.com/Apple%20II%20Items/Hardware/SC-02-aka-SSI-263/Datasheet/

**Files:**
- SC-02 Data Sheet.jpg (218K)
- SSI-263A Data Sheet.pdf (412K)
- SSI-263A Data Sheet v2.pdf (1.4M)
- SSI-263A Programming Guide.pdf (1.5M)

### Internet Archive

**URL:** https://archive.org/details/ssi-263-a

**Content:** SSI 263A Phoneme Speech Synthesizer manual (1985)

### Visual6502 Die Shots

**URL:** http://www.visual6502.org/images/pages/Silicon_Systems_SSI_263P_die_shots.html

**Note:** Certificate expired at time of check

### Patents

From redcedar.com research:
- US 3,908,085 - Voice Synthesizer (Gagnon, 1975)
- US 3,836,717 - Speech Synthesizer Responsive to Digital Command Input (Gagnon, 1974)
- US 4,128,737 - Voice Synthesizer (Dorais/Votrax, 1978)
- US 4,130,730 - 64 phonemes, 12 parameters
- US 4,264,783 - 64 phonemes, digital interpolation
- US 4,433,210 - SC-01 prototype

---

## 9. Related Speech Chips

### Votrax SC-01 / SC-01A

**Phonemes:** 64
**Synthesis:** Analog formant
**Intonation Levels:** 4

**Relationship to SSI-263:**
- SSI-263 is essentially SC-02 (successor to SC-01)
- Silicon Systems marketed it as SSI-263P
- Different phoneme set than SC-01
- Additional control registers

### SP0256-AL2 (General Instrument)

**Used by:** Amstrad SSA-1 (NOT SSI-263)
**Clock:** 3.12 MHz (SSA-1) or 4 MHz (dk'tronics)
**Port:** 0xFBEE

**Note:** Speak&SID uses SpeakJet to emulate SSA-1, not SSI-263

### SpeakJet

**Used by:** Speak&SID for Amstrad CPC
**Controller:** ATMega 8535 @ 16 MHz
**Not SSI-263 compatible**

### DECtalk

**Talker/80 Project:** Emulates SC-01 via DECtalk
**Fidelity:** "80% faithful" - sounds different from real chip

---

## 10. Chip Variants and Compatibility

### SSI-263P
- Original version
- Has reset bug in Phasor mode
- Made from ~1982

### SSI-263AP
- Bugfix version
- Manufactured 1985-1995
- Also labeled: Arctic 263, 78A263A-P, TDK/SSI-78A263 A/P

### Compatible Labels
- Votrax SC-02
- Arctic-02
- SSI-263P
- SSI-263AP
- 78A263A-P

---

## 11. Technical Specifications (from various sources)

### Core Specs
- Phonemes: 64 (different set from SC-01)
- Clock: 1-2 MHz typical
- Sample Rate: 22050 Hz (AppleWin)
- Synthesis: Analog formant (original), PCM samples (emulation)

### Registers (5 total)
| Reg | Name | Function |
|-----|------|----------|
| 0 | DURPHON | Duration (2 bits) + Phoneme (6 bits) |
| 1 | INFLECT | Inflection I10..I3 |
| 2 | RATEINF | Rate (4 bits) + Inflection I2..I0 |
| 3 | CTTRAMP | Control + Articulation + Amplitude |
| 4 | FILFREQ | Filter Frequency |

### Duration Modes
- 0x00: IRQ disabled (retains previous mode)
- 0x40: Frame immediate inflection
- 0x80: Phoneme immediate inflection
- 0xC0: Phoneme transitioned inflection

### Control Bit (CTL)
- CTL=1: Power-down/standby mode
- CTL=0: Active mode, plays phoneme
- CTL transition H->L: Sets device mode and starts phoneme

---

## 12. Key Implementation Insights

### AppleWin Approach (PCM Samples)
**Pros:**
- Authentic sound from real hardware samples
- Simple implementation
- Reliable audio quality

**Cons:**
- No dynamic parameter control (rate, inflection, filter)
- Large data file (~1MB samples)
- Cannot synthesize new sounds

### MAME Approach (Formant Synthesis)
**Pros:**
- True chip simulation
- Dynamic parameter control possible
- Smaller code size

**Cons:**
- Complex mathematics
- Analog section accuracy issues
- "Plosives don't sound quite right"
- Numerically unstable filters

### BNS Emulators Approach (TTS Backend)
**Pros:**
- Uses modern high-quality TTS
- Flexible backend options
- Understandable speech

**Cons:**
- Sounds nothing like original SSI-263
- No vintage character
- Protocol emulation only

---

## 13. URLs Referenced

### Primary Implementations
- https://github.com/AppleWin/AppleWin
- https://github.com/mamedev/mame/blob/master/src/devices/sound/votrax.cpp

### Testing/Utilities
- https://github.com/tomcw/mb-audit
- https://github.com/tomcw/play-sc01-using-ssi263

### Hardware Projects
- https://gist.github.com/deladriere/8878702
- https://www.polaxis.be/2014/02/ssi-263-text-to-speech-in-python-via-nanpy-on-the-arduino/
- https://www.thegeekpub.com/product/sc-01-speech-chip-emulator-votrax/
- https://www.reactivemicro.com/product/sc-01-emulator-sound-and-speech-replacement-module/

### BNS Emulators
- https://emubns.sourceforge.net/
- https://github.com/sukiletxe/vbns-eSpeak

### Documentation
- https://downloads.reactivemicro.com/Apple%20II%20Items/Hardware/SC-02-aka-SSI-263/Datasheet/
- https://archive.org/details/ssi-263-a
- https://vocal-synthesis.fandom.com/wiki/Votrax_SC-02

### Emulator Comparisons
- https://juiced.gs/emulators/ (2024 Emulation Evaluation)
- https://wiki.reactivemicro.com/Mockingboard

---

## Summary of Findings

| Implementation | Approach | SSI-263 Support | Quality |
|---------------|----------|-----------------|---------|
| AppleWin | PCM Samples | Full registers, partial DSP | Good (no rate/filter) |
| MAME | Formant Synthesis | SC-01 full, SSI-263 HLE | WIP |
| KEGS/GSplus | N/A | None | N/A |
| Virtual II | Unknown | Likely None | N/A |
| microM8 | Unknown | Unknown | N/A |
| emubns | Protocol Only | None (uses TTS) | N/A |
| STM32 Board | MAME-based | SC-01 only | Good |
| Arduino Projects | Real Hardware | N/A (not emulation) | N/A |

**Primary finding:** AppleWin is the only comprehensive SSI-263 emulation implementation. MAME has formant synthesis for SC-01 but only placeholder HLE for SSI-263. All other Apple II emulators lack SSI-263 support entirely.
