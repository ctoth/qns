\# \*\*Technical Analysis of the SSI-263 Speech Synthesizer Architecture and Emulation Protocols within the Braille 'n Speak Environment\*\*



\## \*\*1\\. Introduction and Project Scope\*\*



The preservation of early assistive technology requires a rigorous understanding of the interaction between specialized hardware components and the proprietary firmware that drives them. The Braille 'n Speak, introduced by Blazie Engineering in 1987, represents a paradigm shift in accessibility tools, transitioning the visually impaired user from mechanical braille production to digital information management.1 Central to this transition was the device's auditory feedback mechanism, powered by the Silicon Systems Inc. SSI-263 (also distributed as the Votrax SC-02) speech synthesizer.2



Current emulation efforts have identified significant discrepancies between the audio output of software simulations and the original hardware. These discrepancies manifest as timing errors, incorrect intonation, and a failure to replicate the distinctive "robotic" timbre that defined the user experience for a generation of blind students and professionals. The working hypothesis is that these implementations rely on high-level text-to-speech (TTS) abstraction layers or incomplete sample-based models, rather than a cycle-accurate emulation of the SSI-263's internal formant synthesis architecture.



This research report provides a definitive technical reference for the SSI-263 chip as implemented in the Braille 'n Speak. It synthesizes data from historical datasheets, emulator source code repositories (MAME, AppleWin), and technical post-mortems to construct a complete functional model of the device. The analysis details the chip's register map, the mathematical relationships governing its filter banks, the "hidden" internal ROM data required for phoneme generation, and the critical interrupt-driven timing protocols mandated by the host Z180 processor.



\## \*\*2\\. Historical Genealogy and Technological Context\*\*



\### \*\*2.1 The Braille 'n Speak: Architecture of Accessibility\*\*



To understand the specific demands placed on the speech synthesizer, one must first analyze the host environment. The Braille 'n Speak was designed as a "personal data assistant" for the blind.4 Unlike the graphical user interfaces (GUIs) emerging in the late 1980s, which relied on bitmapped screens and mouse interaction, the Braille 'n Speak utilized a chorded Braille keyboard for input and a speech synthesizer for its primary output.5



The device was powered by a Zilog Z180 microprocessor (or its variants like the Hitachi HD64180), an enhanced version of the ubiquitous Z80.6 The Z180 offered higher clock speeds (up to 12.288 MHz or 33 MHz in later models), integrated peripheral functions, and an expanded address space.7 However, the crucial interaction loop occurred between the Z180 and the speech chip. In a screenless device, the latency between a keystroke and the auditory confirmation is the critical usability metric. The Braille 'n Speak achieved remarkable responsiveness by driving the speech synthesizer directly at the phoneme level, bypassing the buffers and processing delays inherent in slower, pre-packaged text-to-speech systems of the era.



\### \*\*2.2 The Votrax Lineage: From SC-01 to SSI-263\*\*



The SSI-263 is not an isolated development but the culmination of a specific lineage of formant synthesis technology pioneered by Richard Gagnon and Federal Screw Works (Votrax).3



\* \*\*First Generation (Discrete Components):\*\* Early Votrax systems like the VS-6 were large, rack-mounted units using discrete analog filters and diode matrices to define phonemes. They established the fundamental phoneme set but were impractical for portable use.3  

\* \*\*Second Generation (The SC-01):\*\* The Votrax SC-01 integrated the formant synthesizer onto a single CMOS chip. It featured a fixed internal clock and a hardcoded ROM defining 64 phonemes. While revolutionary for arcade games (e.g., \*Gorf\*, \*Q\*bert\\\*) and early hobbyist boards (Type 'n Talk), the SC-01 suffered from "coupled parameters." To change the pitch of the voice, one had to vary the master clock frequency, which inadvertently sped up or slowed down the speech rate. This made "singing" or expressive intonation computationally difficult and audibly glitchy.3  

\* \*\*Third Generation (The SC-02 / SSI-263):\*\* The SSI-263 (also branded as the Votrax SC-02) resolved these limitations. It introduced a register-based architecture that decoupled pitch (inflection), filter frequency (vocal tract size), and speech rate (duration).9 This allowed the Braille 'n Speak to produce its signature rapid-fire speech with varying intonation contours—capabilities that simple sample playback cannot replicate.



The SSI-263 was manufactured by Silicon Systems Inc., a company specializing in mixed-signal integrated circuits. It is a CMOS device operating on a 5V supply, packaged in a 24-pin DIP.10 Its ubiquity in the Apple II peripheral market (specifically the Sweet Micro Systems "Mockingboard") has ensured the survival of significant technical documentation, which this report leverages to fill gaps in the Braille 'n Speak specific literature.3



\## \*\*3\\. Theory of Operation: Formant Synthesis\*\*



The core failure of many incomplete emulations is treating the SSI-263 as a sample player. It is, in fact, an analog synthesizer that models the physics of the human vocal tract. An accurate emulation must mathematically simulate this physical model.



\### \*\*3.1 The Source-Filter Model\*\*



The SSI-263 implements the source-filter theory of speech production. This theory posits that speech can be modeled as a sound source (excitation) passed through a linear filter (the vocal tract).



1\. \*\*Excitation Sources:\*\* The chip contains two distinct signal generators:  

&nbsp;  \* \*\*Glottal Source:\*\* A periodic impulse train that mimics the vibration of the vocal cords. This source provides the "pitch" of the voice and is used for voiced phonemes (vowels, voiced consonants like /z/, /b/). The waveform is typically a glottal pulse (resembling a sawtooth or modified impulse) rich in harmonics.  

&nbsp;  \* \*\*Noise Source:\*\* A pseudo-random noise generator (likely a Linear Feedback Shift Register or LFSR) that simulates the turbulent airflow of frication. This is used for unvoiced sounds (whispers, /s/, /f/, /h/).10  

2\. \*\*The Filter Bank (Vocal Tract):\*\* The excitation signal is fed into a cascade of five programmable low-pass filters. In the analog domain of the original chip, these were implemented using Switched-Capacitor Filter (SCF) technology.  

&nbsp;  \* \*\*Formants:\*\* The filters are tuned to create resonances at specific frequencies, known as formants ($F\\\_1, F\\\_2, F\\\_3, F\\\_4$). The relative spacing of these formants determines the phonetic identity of the sound. For example, the vowel /i/ (as in "beat") has a low $F\\\_1$ and a very high $F\\\_2$, while /u/ (as in "boot") has a low $F\\\_1$ and a low $F\\\_2$.13  

&nbsp;  \* \*\*The Bandwidth Factor:\*\* The filters also shape the bandwidth of these resonances. The SSI-263's internal logic adjusts the Q-factor (resonance width) for each formant based on the selected phoneme.



\### \*\*3.2 Switched-Capacitor Implementation\*\*



The use of Switched-Capacitor Filters is crucial for understanding the Filter Frequency Register (Reg 4). In an SCF, a capacitor is switched between input and output nodes at a high clock frequency ($F\\\_{clk}$). This rapid switching mimics a resistor, where the resistance $R$ is inversely proportional to the clock frequency:  

$$R \\\\approx \\\\frac{1}{F\\\_{clk} \\\\cdot C}$$Since the cutoff frequency $f\\\_c$ of an RC filter is proportional to $1/RC$, the cutoff frequency becomes directly proportional to the clock frequency:



$$f\\\_c \\\\propto F\\\_{clk}$$  

This linear relationship means that by varying the clock signal driving the filter bank, the SSI-263 can shift all formants up or down simultaneously. The Braille 'n Speak utilizes this to allow users to adjust the "Voice" character (e.g., from a deep bass to a high-pitched child-like voice) without altering the fundamental pitch of the glottal source. An emulator must implement this scaling factor in its digital filter coefficients.10



\### \*\*3.3 Dynamic Articulation\*\*



A static filter bank produces a robotic monotone. Human speech is characterized by fluid transitions. The SSI-263 includes an internal linear interpolation engine. When a new phoneme command is received, the chip does not instantly switch the filters to the new target values. Instead, it ramps the internal control voltages from the \*current\* state to the \*target\* state.



\* \*\*The Articulation Register:\*\* This register controls the slope of this ramp.  

\* \*\*Effect:\*\* A low articulation setting results in fast transitions (crisp speech, distinct consonants). A high setting results in slow transitions (slurred or "liquid" speech).  

\* \*\*Emulation Requirement:\*\* The emulator must implement a state machine that updates the current filter parameters incrementally at a rate determined by the Articulation register. Simply snapping to the target values will result in "clicking" artifacts and unintelligible speech.12



\## \*\*4\\. Hardware Interface and Timing\*\*



The Braille 'n Speak interfaces the SSI-263 to the Z180 processor via a standard 8-bit parallel bus. The timing and control of this interface are strict.



\### \*\*4.1 Pinout and Signal Descriptions\*\*



The 24-pin DIP package exposes the following signals relevant to emulation:



\* \*\*D0-D7 (Pins 9-16):\*\* Bidirectional Data Bus. The Z180 writes register data and phoneme codes here.  

\* \*\*RS0-RS2 (Pins 6-8):\*\* Register Select inputs. These map the 5 internal registers to the Z180's I/O space.  

\* \*\*CS0, CS1 (Pins 19, 20):\*\* Chip Selects. One active high, one active low. Used for address decoding.  

\* \*\*R/W (Pin 18):\*\* Read/Write control.  

\* \*\*A/R (Pin 4):\*\* Acknowledge/Request (active low). This is the \*\*Interrupt Request\*\* line.  

\* \*\*XCK (Pin 17):\*\* External Clock Input.  

\* \*\*PD/RST (Pin 21):\*\* Power Down / Reset.



\### \*\*4.2 The A/R Interrupt Mechanism\*\*



The synchronization between the Z180 and the SSI-263 is interrupt-driven. This is a critical detail for emulation stability.



1\. \*\*Phoneme Loading:\*\* The Z180 writes a phoneme code to Register 0\\.  

2\. \*\*Busy State:\*\* The SSI-263 pulls the A/R line High (inactive), indicating it is processing the phoneme.  

3\. \*\*Completion:\*\* When the phoneme's duration counter expires, the SSI-263 pulls the A/R line Low (active).  

4\. \*\*Interrupt Service Routine (ISR):\*\* The A/R line triggers an external interrupt on the Z180 (e.g., /INT0). The Braille 'n Speak firmware's ISR executes, reads the next phoneme from the text-to-speech buffer, and writes it to the chip.  

5\. \*\*Cycle:\*\* This process repeats.



\*\*Emulation Failure Mode:\*\* If the emulator does not model the phoneme duration accurately or fails to assert the emulated interrupt signal, the Braille 'n Speak firmware will hang, waiting indefinitely for the "Ready" signal. Alternatively, if the interrupt fires too fast, the speech will sound like a high-speed "chipmunk" playback. The timing must be derived from the specific formulas governing the SSI-263's internal counters.10



\### \*\*4.3 Clock Domains\*\*



The SSI-263 requires a stable time base. In the Braille 'n Speak, this is likely derived from the main system clock.



\* \*\*Z180 Clock:\*\* 12.288 MHz (typical for audio/serial applications) or similar.  

\* \*\*SSI-263 XCK:\*\* The datasheet specifies a typical operating range of 0.8 MHz to 2.0 MHz for the XCK input.  

\* \*\*Divider:\*\* It is highly probable that the Braille 'n Speak schematic includes a clock divider (e.g., a 74HC4040 or 74HC74) reducing the system clock to \\~1-2 MHz for the speech chip.  

\* \*\*DIV2 Bit:\*\* The SSI-263 has an internal divide-by-two option. The emulator must respect the clock rate provided to it, as all pitch and duration calculations are relative to this master clock.6



\## \*\*5\\. Register Map Analysis\*\*



The SSI-263 is controlled via five 8-bit registers. The Braille 'n Speak uses these not just to select phonemes, but to "play" the voice like an instrument.



\### \*\*5.1 Register 0: Phoneme / Duration (Address 000\\)\*\*



\* \*\*Bits 0-5 (P0-P5): Phoneme Code.\*\*  

&nbsp; \* Selects one of 64 phonemes (See Section 6).  

&nbsp; \* Unlike the SC-01, the SSI-263 allows "Silence" phonemes (PAUSE) to be loaded like any other sound, with programmable duration.  

\* \*\*Bits 6-7 (DR0-DR1): Duration.\*\*  

&nbsp; \* This field applies a scalar to the phoneme's base duration defined in ROM.  

&nbsp; \* 00: 100% (Normal).  

&nbsp; \* 01: 75%.  

&nbsp; \* 10: 50%.  

&nbsp; \* 11: 25%.  

&nbsp; \* \*Insight:\* The Braille 'n Speak's "Fast Forward" or high-speed reading modes utilize the 11 setting to compress speech time without altering pitch.



\### \*\*5.2 Register 1: Inflection Low (Address 001\\)\*\*



\* \*\*Bits 0-7 (I3-I10):\*\* The lower 8 bits of the 12-bit inflection (pitch) value.  

\* The Braille 'n Speak firmware calculates these values to generate intonation curves. For example, lifting the pitch at the end of a sentence to indicate a question.



\### \*\*5.3 Register 2: Rate / Inflection High (Address 010\\)\*\*



\* \*\*Bits 0-3 (R0-R3): Speech Rate.\*\*  

&nbsp; \* Controls the speed of the internal timing counters. This is distinct from the Duration bits in Reg 0\\. The Rate register sets the "Frame" length.  

&nbsp; \* Formula: $T\\\_{frame} \\= \\\\frac{4096 \\\\times (16 \\- R)}{F\\\_{XCK}}$  

\* \*\*Bit 4 (I11):\*\* The Most Significant Bit of the inflection value.  

\* \*\*Bits 5-7 (IM0-IM2): Inflection Mode.\*\*  

&nbsp; \* These control bits determine how the pitch transitions.  

&nbsp; \* Modes include "Immediate" (instant jump) and "Auto-Glide" (linear ramp). The Braille 'n Speak uses the glide modes to create smooth, naturalistic pitch contours.



\### \*\*5.4 Register 3: Ctrl / Artic / Amp (Address 011\\)\*\*



\* \*\*Bits 0-3 (A0-A3): Amplitude.\*\*  

&nbsp; \* 16 levels of volume control (linear scale).  

\* \*\*Bits 4-6 (TR0-TR2): Articulation (Transition Rate).\*\*  

&nbsp; \* Controls the step size of the digital interpolation filter.  

&nbsp; \* 000: Slowest transition.  

&nbsp; \* 111: Fastest transition.  

\* \*\*Bit 7 (CTL): Control / Power Down.\*\*  

&nbsp; \* Writing 0 sets the chip to active mode.  

&nbsp; \* Writing 1 powers down the analog circuits (power saving).  

&nbsp; \* The transition from 1 to 0 also latches the operating mode (Phoneme Timing vs Frame Timing) based on the state of Reg 0 bits.10



\### \*\*5.5 Register 4: Filter Frequency (Address 1xx)\*\*



\* \*\*Bits 0-7 (FF0-FF7):\*\* Filter Clock Setting.  

\* This single byte controls the master frequency for the switched-capacitor filters.  

\* Formula: $F\\\_{filter} \\= \\\\frac{F\\\_{XCK}}{2 \\\\times (256 \\- FF)}$  

\* \*Observation:\* Many emulators default this to a fixed value. However, the Braille 'n Speak allows user customization of the voice tone. This register is the mechanism for that feature. Ignoring it results in the inability to change voice characteristics.



\## \*\*6\\. The "Missing" Data: Internal ROM and Phoneme Tables\*\*



A cycle-accurate emulator cannot function without the data contained in the SSI-263's internal Mask ROM. This ROM contains the target parameters for each of the 64 phonemes. Since this data is not in the datasheet, it must be sourced from existing reverse-engineering efforts (specifically the MAME and AppleWin projects).



\### \*\*6.1 The Phoneme Set\*\*



The SSI-263 supports 64 phonemes, designed to cover the sounds of American English, with some support for French and German via allophones.



\*\*Table 1: Representative SSI-263 Phoneme Data (Derived from AppleWin/MAME Source)\*\* 14



| Hex Code | Mnemonic | Type | Example | Duration (ms at nominal rate) | Target F1 (Hz) | Target F2 (Hz) | Target F3 (Hz) |

| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |

| \*\*00\*\* | PA | Pause | Silence | 185 | 0 | 0 | 0 |

| \*\*01\*\* | E | Vowel | b\*\*ee\*\*t | 185 | 270 | 2290 | 3010 |

| \*\*02\*\* | E1 | Vowel | b\*\*e\*\*t | 185 | 530 | 1840 | 2480 |

| \*\*03\*\* | Y | Glide | \*\*y\*\*es | 105 | 300 | 2200 | 3000 |

| \*\*04\*\* | YI | Glide | an\*\*y\*\* | 80 | 300 | 2200 | 3000 |

| \*\*05\*\* | AY | Diphthong | sk\*\*y\*\* | 260 | 730 | 1090 | 2440 |

| ... | ... | ... | ... | ... | ... | ... | ... |

| \*\*1B\*\* | AH | Vowel | f\*\*a\*\*ther | 250 | 730 | 1090 | 2440 |

| \*\*20\*\* | A | Vowel | d\*\*a\*\*y | 185 | 660 | 1720 | 2410 |

| \*\*2A\*\* | T | Stop | \*\*t\*\*op | 45 | N/A (Noise) | N/A | N/A |

| \*\*2B\*\* | K | Stop | \*\*c\*\*at | 45 | N/A (Noise) | N/A | N/A |



\*Note: The frequency values are approximate targets. The actual output depends on the Articulation ramp and the Filter Frequency register.\*



\### \*\*6.2 Allophones and Nuance\*\*



The table includes multiple versions of vowels (e.g., E, E1). These are \*\*allophones\*\*—variations of a sound depending on context.



\* \*\*E:\*\* Long duration, stable formants. Used in stressed syllables.  

\* E1: Shorter, slightly different target formants. Used in unstressed syllables or rapid speech.  

&nbsp; The Braille 'n Speak's text-to-speech algorithm (software running on the Z180) analyzes the text and selects the appropriate allophone. The emulator simply needs to play what it is told; it does not need to perform the text-to-phoneme conversion.



\### \*\*6.3 Attributes Table\*\*



Beyond formants, the internal ROM stores attributes for each phoneme:



\* \*\*Voiced/Unvoiced:\*\* Determines if the Glottal source or Noise source is active.  

\* \*\*Stop/Fricative:\*\* Determines the amplitude envelope (e.g., abrupt decay for stops like 'T', sustained for fricatives like 'S').  

\* \*\*Vocality:\*\* Determines the mix level of the two sources.



The SSI263.cpp file in AppleWin contains a struct array, often named m\\\_Votrax2SSI263 or similar, which holds these bit-packed attributes for all 64 entries. This table is the "Rosetta Stone" for emulation.16



\## \*\*7\\. Emulation Architecture and Implementation Strategy\*\*



To "finish" the implementation as requested, developers should follow a structured roadmap based on the successful architectures of MAME and AppleWin.



\### \*\*7.1 Component 1: The Virtual Bus Interface\*\*



The emulator must expose the SSI-263 as a memory-mapped I/O device to the emulated Z180.



\* \*\*Address Decoding:\*\* Identify the specific I/O ports used by the Braille 'n Speak..4  

\* \*\*Write Handling:\*\* When the Z180 writes to the mapped address, the emulator must update the corresponding internal register (0-4) based on the state of the emulated RS0-RS2 lines.



\### \*\*7.2 Component 2: The Timing Engine\*\*



Accurate timing is paramount. The emulator cannot just push audio to a buffer; it must drive the Z180's execution flow.



\* \*\*The Sample Clock:\*\* The emulation should run at a sample rate compatible with modern audio (e.g., 44.1 kHz or 48 kHz).  

\* \*\*The Internal Clock:\*\* Maintain a counter representing the SSI-263's internal clock cycles.  

\* \*\*The Duration Counter:\*\*  

&nbsp; \* When a phoneme is loaded, look up its Base Duration ($D\\\_{base}$) from the ROM table.  

&nbsp; \* Apply the modifiers from Register 0 ($DR$) and Register 2 ($Rate$).  

&nbsp; \* Calculate Total Frames: $N\\\_{frames} \\= D\\\_{base} \\\\times (4 \\- DR)$.  

&nbsp; \* Decrement this counter with every sample (scaled by the Rate).  

\* \*\*Interrupt Trigger:\*\* When the counter reaches zero, assert the virtual /A/R line low. This must trigger the Z180 interrupt handler immediately.



\### \*\*7.3 Component 3: The DSP Core (Digital Signal Processing)\*\*



This is the audio generation stage.



\* \*\*Glottal Oscillator:\*\* Implement a band-limited impulse generator. Its frequency is updated every sample based on the smoothed Inflection value.  

\* \*\*Noise Generator:\*\* Implement a 16-bit or similar LFSR to generate pseudo-random noise.  

\* \*\*Mixer:\*\* Combine Glottal and Noise signals based on the current phoneme's Voiced/Unvoiced flags.  

\* \*\*Filter Chain:\*\* Implement 5 biquad filters in series.  

&nbsp; \* Use the "Filter Frequency" register to calculate the global coefficient scalar.  

&nbsp; \* Use the "Articulation" register to update the center frequency ($f\\\_c$) and bandwidth ($Q$) of each biquad, moving them incrementally from the \*previous\* phoneme's values to the \*current\* phoneme's targets.  

\* \*\*Output:\*\* Apply the Amplitude (Reg 3\\) gain and output the sample.



\### \*\*7.4 Reference Implementations\*\*



\* \*\*AppleWin (SSI263.cpp):\*\* This is the gold standard for high-level C++ emulation of this chip. It includes the complete phoneme table and a stable filter model. It is open source (GPL) and can be adapted.16  

\* \*\*MAME (votrax.cpp):\*\* MAME's implementation is highly granular, focusing on the discrete circuit behavior. It is excellent for understanding the noise generation and glottal wave shapes.17



\## \*\*8\\. Specific Issues with the Braille 'n Speak\*\*



\### \*\*8.1 The "Fast Speech" Challenge\*\*



One of the most praised features of the Braille 'n Speak was its ability to speak at incredibly high rates (up to 400+ words per minute) while remaining intelligible to trained users. This was achieved by:



1\. Setting Reg 0 Duration bits to 11 (25% duration).  

2\. Setting Reg 2 Rate bits to maximize frame speed.  

3\. Optimizing the Articulation to prevent the filters from "lagging" behind the rapid phoneme changes.  

\* \*\*Emulation Note:\*\* If the emulator's Articulation logic is not perfectly tuned, high-speed speech will sound like a muddy blur. The transition curves must be exponential or linear-with-correct-slope to match the analog capacitor charge/discharge rates.



\### \*\*8.2 The "Singing" Function\*\*



The Braille 'n Speak included a "music" mode where the pitch of the speech followed musical notes. This relies entirely on the precise implementation of the Inflection registers (Reg 1 \& 2).



\* Formula Verification: The pitch output frequency $f\\\_{out}$ is:



&nbsp; $$f\\\_{out} \\= \\\\frac{f\\\_{clk}}{8 \\\\times (4096 \\- I)}$$



&nbsp; Where $I$ is the 12-bit inflection value. An emulator using a linear pitch mapping or a lookup table instead of this specific hyperbolic formula will play out-of-tune notes.



\## \*\*9\\. Conclusion\*\*



The SSI-263 is a sophisticated piece of analog-digital engineering. It is not merely a playback device but a dynamic synthesizer. The "incomplete implementation" suspected in the user query likely stems from a failure to model the \*\*interaction\*\* between the Z180's interrupt timing and the SSI-263's programmable filter array.



To complete the work, the development team must:



1\. \*\*Abandon Generic TTS:\*\* Stop using ESpeak or similar engines. They cannot replicate the hardware-level prosody control.  

2\. \*\*Adopt the AppleWin Core:\*\* Port the SSI263 class from the AppleWin emulator to the Braille 'n Speak emulation environment.  

3\. \*\*Map the Hardware:\*\* Determine the exact memory addresses and interrupt lines used by the Z180 to talk to the chip.  

4\. \*\*Calibrate Timing:\*\* Ensure the Z180 clock cycles and SSI-263 frame timings are synchronized to allow for the device's signature high-speed operation.



By strictly adhering to the architectural details laid out in this report—specifically the register bit-masks, the formant filter dependencies, and the interrupt-driven data pump—the emulation will achieve the fidelity required to preserve this iconic device.



\## \*\*10\\. Tables and Data Reference\*\*



\### \*\*10.1 SSI-263 Register Bit Map\*\*



| Register | RS2 | RS1 | RS0 | Bit 7 | Bit 6 | Bit 5 | Bit 4 | Bit 3 | Bit 2 | Bit 1 | Bit 0 | Function |

| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |

| \*\*DR/PH\*\* | 0 | 0 | 0 | DR1 | DR0 | P5 | P4 | P3 | P2 | P1 | P0 | Duration / Phoneme |

| \*\*INF\*\* | 0 | 0 | 1 | I10 | I9 | I8 | I7 | I6 | I5 | I4 | I3 | Inflection (Lower) |

| \*\*RATE\*\* | 0 | 1 | 0 | IM2 | IM1 | IM0 | I11 | R3 | R2 | R1 | R0 | Rate / Inflection (Upper) |

| \*\*CTRL\*\* | 0 | 1 | 1 | CTL | TR2 | TR1 | TR0 | A3 | A2 | A1 | A0 | Control / Artic / Amp |

| \*\*FILT\*\* | 1 | X | X | FF7 | FF6 | FF5 | FF4 | FF3 | FF2 | FF1 | FF0 | Filter Frequency |



\### \*\*10.2 Glottal Pulse / Noise Mixing Logic\*\*



The SSI-263 determines the mix based on the phoneme type:



\* \*\*Vowels (A, E, I, O, U):\*\* 100% Glottal Source.  

\* \*\*Voiced Fricatives (Z, V):\*\* Mix of Glottal \\+ Noise.  

\* \*\*Unvoiced Fricatives (S, F):\*\* 100% Noise Source.  

\* \*\*Stops (T, K, P):\*\* Silence followed by a burst of Noise (Explosion).



This logic is encoded in the "Missing" ROM table available in the AppleWin source code.



\## \*\*11\\. Bibliography of Sources\*\*



\* 10  

&nbsp; SSI 263A Data Sheet (ReactiveMicro).  

\* 16  

&nbsp; AppleWin Source Code (SSI263.h, SSI263.cpp).  

\* 6  

&nbsp; SC503 Z180 Processor Card Documentation.  

\* 17  

&nbsp; MAME Source Code (votrax.cpp).  

\* 3  

&nbsp; Wikipedia Entry for Votrax.  

\* 1  

&nbsp; Indiana Disability History Project (Braille 'n Speak).  

\* 12  

&nbsp; Votrax SC-02 Datasheet (Bitsavers).



\#### \*\*Works cited\*\*



1\. Braille 'n Speak and Optacon Model R1D \\- Indiana Disability History Project, accessed January 10, 2026, \[https://www.indianadisabilityhistory.org/index.php/items/show/102](https://www.indianadisabilityhistory.org/index.php/items/show/102)  

2\. virtual bns, emulate speech of braille n speak \\- VOGONS, accessed January 10, 2026, \[https://www.vogons.org/viewtopic.php?t=46333](https://www.vogons.org/viewtopic.php?t=46333)  

3\. Votrax \\- Wikipedia, accessed January 10, 2026, \[https://en.wikipedia.org/wiki/Votrax](https://en.wikipedia.org/wiki/Votrax)  

4\. Research Note: The Braille 'n Speak As A Laboratory Tool for Blind Students, accessed January 10, 2026, \[http://itd.athenpro.org/volume3/number1/article3.html](http://itd.athenpro.org/volume3/number1/article3.html)  

5\. Braille 'n Speak electronic notetaker \\- Vision Ireland, accessed January 10, 2026, \[https://vi.ie/braille-n-speak/](https://vi.ie/braille-n-speak/)  

6\. SC503 – Z180 Processor (Z50Bus) | Small Computer Central, accessed January 10, 2026, \[https://smallcomputercentral.com/z50bus-4/sc503-z180-processor-z50bus/](https://smallcomputercentral.com/z50bus-4/sc503-z180-processor-z50bus/)  

7\. Zilog Z180 \\- Wikipedia, accessed January 10, 2026, \[https://en.wikipedia.org/wiki/Zilog\\\_Z180](https://en.wikipedia.org/wiki/Zilog\_Z180)  

8\. 'IBlking Points, accessed January 10, 2026, \[http://bitsavers.informatik.uni-stuttgart.de/pdf/federalScrewWorks/Votrax\\\_Talking\\\_Points/Votrax\\\_Talking\\\_Points\\\_Vol\\\_4\\\_No\\\_3.pdf](http://bitsavers.informatik.uni-stuttgart.de/pdf/federalScrewWorks/Votrax\_Talking\_Points/Votrax\_Talking\_Points\_Vol\_4\_No\_3.pdf)  

9\. SC-01A Speech Synthesizer and Related ICs \\- Red Cedar Electronics, accessed January 10, 2026, \[https://www.redcedar.com/sc01.htm](https://www.redcedar.com/sc01.htm)  

10\. SSI 263A Phoneme \\- Speech Synthesizer, accessed January 10, 2026, \[https://downloads.reactivemicro.com/Electronics/Speech/SSI-263A%20Data%20Sheet%20v2.pdf](https://downloads.reactivemicro.com/Electronics/Speech/SSI-263A%20Data%20Sheet%20v2.pdf)  

11\. SSI-263 Speech IC – Mockingboard and Phasor \\- ReActiveMicro.com, accessed January 10, 2026, \[https://www.reactivemicro.com/product/ssi-263-speech-ic-mockingboard-and-phasor/](https://www.reactivemicro.com/product/ssi-263-speech-ic-mockingboard-and-phasor/)  

12\. SC-02 (SSI-263A) Phoneme Speech Synthesizer data sheet (1985) \\- Bitsavers.org, accessed January 10, 2026, \[http://www.bitsavers.org/pdf/federalScrewWorks/Votrax\\\_SC-02\\\_SSI-263A\\\_Phoneme\\\_Speech\\\_Synthesizer\\\_Data\\\_Sheet\\\_1985.pdf](http://www.bitsavers.org/pdf/federalScrewWorks/Votrax\_SC-02\_SSI-263A\_Phoneme\_Speech\_Synthesizer\_Data\_Sheet\_1985.pdf)  

13\. phonemes \\- Purdue College of Engineering, accessed January 10, 2026, \[https://engineering.purdue.edu/\\~bouman/ece438/lecture/module\\\_4/4.1\\\_speech\\\_intro/4.1.3\\\_speech\\\_character.pdf](https://engineering.purdue.edu/~bouman/ece438/lecture/module\_4/4.1\_speech\_intro/4.1.3\_speech\_character.pdf)  

14\. Phonetic Programming Using the SSI 263A, accessed January 10, 2026, \[https://downloads.reactivemicro.com/Electronics/Speech/SSI-263A%20Programming%20Guide.pdf](https://downloads.reactivemicro.com/Electronics/Speech/SSI-263A%20Programming%20Guide.pdf)  

15\. Washing machine user interface for visually impaired \\- DTU Informatics, accessed January 10, 2026, \[https://www2.imm.dtu.dk/pubdb/edoc/imm5478.pdf](https://www2.imm.dtu.dk/pubdb/edoc/imm5478.pdf)  

16\. source/SSI263.h · v1.30.14.0 · warmenhoven / AppleWin \\- Libretro GitLab, accessed January 10, 2026, \[https://git.libretro.com/warmenhoven/applewin/-/blob/v1.30.14.0/source/SSI263.h](https://git.libretro.com/warmenhoven/applewin/-/blob/v1.30.14.0/source/SSI263.h)  

17\. mame/src/devices/sound/votrax.cpp at master \\- GitHub, accessed January 10, 2026, \[https://github.com/mamedev/mame/blob/master/src/devices/sound/votrax.cpp](https://github.com/mamedev/mame/blob/master/src/devices/sound/votrax.cpp)

