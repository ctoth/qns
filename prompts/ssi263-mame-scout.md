# SSI-263 MAME Implementation Scout

## Mission
Survey the MAME SSI-263 implementation thoroughly. Capture everything - don't filter or judge.

## Context
We're building an SSI-263 speech synthesizer emulator. Our current implementation produces audio but it sounds "terrifying and alien" - garbled, wrong timing, high/low tones mixed. We need to understand what MAME does and what we might be missing.

## Search Locations

1. **MAME Source** - Search GitHub for MAME's SSI-263 implementation
   - Look for `ssi263` in mamedev/mame repository
   - Find the main emulation file(s)
   - Document the class structure and methods

2. **Key Implementation Details** to capture:
   - How does MAME generate audio samples?
   - What phoneme data does it use? Where does it come from?
   - How does it handle timing between phonemes?
   - What DSP/filtering does it apply?
   - How does it handle the control registers?
   - Does it use lookup tables? Formant synthesis? PCM samples?

3. **Dependencies**
   - What other MAME components does SSI-263 depend on?
   - Are there audio mixing/streaming components?

## Output
Write raw findings to `reports/ssi263-mame-raw.md`

Include:
- All relevant source file paths and URLs
- Code snippets for key algorithms
- Any comments from the MAME developers
- Configuration/register handling
- Sample generation approach
- Timing mechanisms
- Dependencies and interfaces

Do NOT filter or make recommendations - just capture everything you find.
