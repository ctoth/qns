# SSI-263 Other Implementations Scout

## Mission
Survey ALL other SSI-263 emulator implementations beyond MAME. Cast a wide net - capture everything.

## Context
We're building an SSI-263 speech synthesizer emulator. Need to find what other projects have done, what approaches work, what phoneme data they use.

## Search Targets

1. **AppleWin** - Apple II emulator
   - Known to have SSI-263 emulation
   - We already extracted phoneme samples from it
   - Find their implementation approach
   - URL: github.com/AppleWin/AppleWin

2. **Other Apple II Emulators**
   - KEGS, GSplus, Virtual II, microM8
   - Any that support Mockingboard or Echo speech

3. **Standalone SSI-263 Projects**
   - GitHub search for "SSI263" or "SSI-263"
   - Any speech synthesis projects using this chip
   - Arduino/hardware recreations

4. **Documentation & Datasheets**
   - SSI-263 datasheet
   - Application notes
   - Technical documentation
   - Blog posts about reverse engineering

5. **Related Chips**
   - SSI-263A variants
   - Votrax SC-01 (similar era speech chip)
   - How do other speech chip emulators work?

## For Each Implementation Found, Capture:
- Repository URL
- Language used
- Approach (formant synthesis vs PCM samples vs other)
- Phoneme data source
- Audio generation method
- Timing/interrupt handling
- Any known issues or limitations
- License

## Output
Write raw findings to `reports/ssi263-other-implementations-raw.md`

Capture EVERYTHING. Don't filter. Don't recommend. Just document what exists.
