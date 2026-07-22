# SC-02 (SSI-263) to SC-01 Phoneme Mapping

## Background

The SSI-263 is also known as the **Votrax SC-02**. It has 64 phonemes that are different from the SC-01 (Votrax original).

The MAME emulator's `ssi263hle.cpp` admits its translation table is "completely wrong" - it was a hack just to get audio working in Thayer's Quest.

This document contains a corrected mapping based on the **official SC-02 datasheet** phoneme chart.

## SC-02 Phoneme Chart (from Datasheet)

| Hex | Symbol | Example Word |
|-----|--------|--------------|
| 00 | PA | (pause) |
| 01 | E | MEET |
| 02 | E1 | BENT |
| 03 | Y | BEFORE |
| 04 | YI | YEAR |
| 05 | AY | PLEASE |
| 06 | IE | ANY |
| 07 | I | SIX |
| 08 | A | MADE |
| 09 | AI | CARE |
| 0A | EH | NEST |
| 0B | EH1 | BELT |
| 0C | AE | DAD |
| 0D | AE1 | AFTER |
| 0E | AH | GOT |
| 0F | AH1 | FATHER |
| 10 | AW | OFFICE |
| 11 | O | STORE |
| 12 | OU | BOAT |
| 13 | OO | LOOK |
| 14 | IU | YOU |
| 15 | IU1 | COULD |
| 16 | U | TUNE |
| 17 | U1 | CARTOON |
| 18 | UH | WONDER |
| 19 | UH1 | LOVE |
| 1A | UH2 | WHAT |
| 1B | UH3 | NUT |
| 1C | ER | BIRD |
| 1D | R | ROOF |
| 1E | R1 | RUG |
| 1F | R2 | MUTTER (German) |
| 20 | L | LIFT |
| 21 | L1 | PLAY |
| 22 | LF | FALL (final) |
| 23 | W | WATER |
| 24 | B | BAG |
| 25 | D | PAID |
| 26 | KV | TAG |
| 27 | P | PEN |
| 28 | T | TART |
| 29 | K | KIT |
| 2A | HV | (hold vocal) |
| 2B | HVC | (hold vocal closure) |
| 2C | HF | HEART |
| 2D | HFC | (hold fricative closure) |
| 2E | HN | (hold nasal) |
| 2F | Z | ZERO |
| 30 | S | SAME |
| 31 | J | MEASURE |
| 32 | SCH | SHIP |
| 33 | V | VERY |
| 34 | F | FOUR |
| 35 | THV | THERE |
| 36 | TH | WITH |
| 37 | M | MORE |
| 38 | N | NINE |
| 39 | NG | RANG |
| 3A | :A | MARCHEN (German) |
| 3B | :OH | LOWE (French) |
| 3C | :U | FUNF (German) |
| 3D | :UH | MENU (French) |
| 3E | E2 | BITTE (German) |
| 3F | LB | LUBE |

## SC-01 Phoneme Reference

| Hex | Name | Example |
|-----|------|---------|
| 00 | EH3 | jackEt |
| 01 | EH2 | Enlist |
| 02 | EH1 | hEAvy |
| 03 | PA0 | (pause) |
| 04 | DT | buTTer |
| 05 | A1 | mAde |
| 06 | A2 | mAde |
| 07 | ZH | aZure |
| 08 | AH2 | hOnest |
| 09 | I3 | inhibIt |
| 0A | I2 | Inhibit |
| 0B | I1 | inhIbit |
| 0C | M | Mat |
| 0D | N | suN |
| 0E | B | Bag |
| 0F | V | Van |
| 10 | CH | CHip |
| 11 | SH | SHop |
| 12 | Z | Zoo |
| 13 | AW1 | lAWful |
| 14 | NG | thiNG |
| 15 | AH1 | fAther |
| 16 | OO1 | lOOking |
| 17 | OO | bOOK |
| 18 | L | Land |
| 19 | K | triCK |
| 1A | J | juDGe |
| 1B | H | Hello |
| 1C | G | Get |
| 1D | F | Fast |
| 1E | D | paiD |
| 1F | S | paSS |
| 20 | A | dAY |
| 21 | AY | dAY |
| 22 | Y1 | Yard |
| 23 | UH3 | missIOn |
| 24 | AH | mOp |
| 25 | P | Past |
| 26 | O | cOld |
| 27 | I | pIn |
| 28 | U | mOve |
| 29 | Y | anY |
| 2A | T | Tap |
| 2B | R | Red |
| 2C | E | mEEt |
| 2D | W | Win |
| 2E | AE | dAd |
| 2F | AE1 | After |
| 30 | AW2 | sAlty |
| 31 | UH2 | About |
| 32 | UH1 | Uncle |
| 33 | UH | cUp |
| 34 | O2 | fOr |
| 35 | O1 | abOArd |
| 36 | IU | yOU |
| 37 | U1 | yOU |
| 38 | THV | THe |
| 39 | TH | THin |
| 3A | ER | bIRd |
| 3B | EH | gEt |
| 3C | E1 | bE |
| 3D | AW | cAll |
| 3E | PA1 | (pause) |
| 3F | STOP | (stop) |

## Corrected Mapping Table

| SC-02 | Name | Example | → | SC-01 | Name | Notes |
|-------|------|---------|---|-------|------|-------|
| 0x00 | PA | pause | → | 0x03 | PA0 | |
| 0x01 | E | MEET | → | 0x2C | E | long E |
| 0x02 | E1 | BENT | → | 0x3B | EH | short E |
| 0x03 | Y | BEFORE | → | 0x22 | Y1 | semivowel |
| 0x04 | YI | YEAR | → | 0x29 | Y | |
| 0x05 | AY | PLEASE | → | 0x21 | AY | |
| 0x06 | IE | ANY | → | 0x27 | I | |
| 0x07 | I | SIX | → | 0x27 | I | |
| 0x08 | A | MADE | → | 0x20 | A | |
| 0x09 | AI | CARE | → | 0x2E | AE | |
| 0x0A | EH | NEST | → | 0x3B | EH | |
| 0x0B | EH1 | BELT | → | 0x02 | EH1 | |
| 0x0C | AE | DAD | → | 0x2E | AE | |
| 0x0D | AE1 | AFTER | → | 0x2F | AE1 | |
| 0x0E | AH | GOT | → | 0x24 | AH | |
| 0x0F | AH1 | FATHER | → | 0x15 | AH1 | |
| 0x10 | AW | OFFICE | → | 0x13 | AW1 | |
| 0x11 | O | STORE | → | 0x26 | O | |
| 0x12 | OU | BOAT | → | 0x35 | O1 | |
| 0x13 | OO | LOOK | → | 0x17 | OO | |
| 0x14 | IU | YOU | → | 0x36 | IU | |
| 0x15 | IU1 | COULD | → | 0x16 | OO1 | |
| 0x16 | U | TUNE | → | 0x28 | U | |
| 0x17 | U1 | CARTOON | → | 0x37 | U1 | |
| 0x18 | UH | WONDER | → | 0x33 | UH | |
| 0x19 | UH1 | LOVE | → | 0x32 | UH1 | |
| 0x1A | UH2 | WHAT | → | 0x31 | UH2 | |
| 0x1B | UH3 | NUT | → | 0x23 | UH3 | |
| 0x1C | ER | BIRD | → | 0x3A | ER | |
| 0x1D | R | ROOF | → | 0x2B | R | |
| 0x1E | R1 | RUG | → | 0x2B | R | |
| 0x1F | R2 | MUTTER | → | 0x2B | R | |
| 0x20 | L | LIFT | → | 0x18 | L | |
| 0x21 | L1 | PLAY | → | 0x18 | L | |
| 0x22 | LF | FALL | → | 0x18 | L | |
| 0x23 | W | WATER | → | 0x2D | W | |
| 0x24 | B | BAG | → | 0x0E | B | |
| 0x25 | D | PAID | → | 0x1E | D | |
| 0x26 | KV | TAG | → | 0x1C | G | voiced velar |
| 0x27 | P | PEN | → | 0x25 | P | |
| 0x28 | T | TART | → | 0x2A | T | |
| 0x29 | K | KIT | → | 0x19 | K | |
| 0x2A | HV | hold vocal | → | 0x1B | H | |
| 0x2B | HVC | hold closure | → | 0x03 | PA0 | silence |
| 0x2C | HF | HEART | → | 0x1B | H | |
| 0x2D | HFC | hold fric | → | 0x03 | PA0 | silence |
| 0x2E | HN | hold nasal | → | 0x03 | PA0 | silence |
| 0x2F | Z | ZERO | → | 0x12 | Z | |
| 0x30 | S | SAME | → | 0x1F | S | |
| 0x31 | J | MEASURE | → | 0x07 | ZH | voiced palatal |
| 0x32 | SCH | SHIP | → | 0x11 | SH | |
| 0x33 | V | VERY | → | 0x0F | V | |
| 0x34 | F | FOUR | → | 0x1D | F | |
| 0x35 | THV | THERE | → | 0x38 | THV | |
| 0x36 | TH | WITH | → | 0x39 | TH | |
| 0x37 | M | MORE | → | 0x0C | M | |
| 0x38 | N | NINE | → | 0x0D | N | |
| 0x39 | NG | RANG | → | 0x14 | NG | |
| 0x3A | :A | MARCHEN | → | 0x08 | AH2 | German A |
| 0x3B | :OH | LOWE | → | 0x34 | O2 | French O |
| 0x3C | :U | FUNF | → | 0x28 | U | German U |
| 0x3D | :UH | MENU | → | 0x33 | UH | French U |
| 0x3E | E2 | BITTE | → | 0x01 | EH2 | German E |
| 0x3F | LB | LUBE | → | 0x18 | L | |

## Python Tuple (for code)

```python
SC02_TO_SC01: tuple[int, ...] = (
    0x03, 0x2C, 0x3B, 0x22, 0x29, 0x21, 0x27, 0x27,  # 0x00-0x07
    0x20, 0x2E, 0x3B, 0x02, 0x2E, 0x2F, 0x24, 0x15,  # 0x08-0x0F
    0x13, 0x26, 0x35, 0x17, 0x36, 0x16, 0x28, 0x37,  # 0x10-0x17
    0x33, 0x32, 0x31, 0x23, 0x3A, 0x2B, 0x2B, 0x2B,  # 0x18-0x1F
    0x18, 0x18, 0x18, 0x2D, 0x0E, 0x1E, 0x1C, 0x25,  # 0x20-0x27
    0x2A, 0x19, 0x1B, 0x03, 0x1B, 0x03, 0x03, 0x12,  # 0x28-0x2F
    0x1F, 0x07, 0x11, 0x0F, 0x1D, 0x38, 0x39, 0x0C,  # 0x30-0x37
    0x0D, 0x14, 0x08, 0x34, 0x28, 0x33, 0x01, 0x18,  # 0x38-0x3F
)
```

## Key Fixes from MAME's Table

The old MAME table had these major errors:

| SC-02 | Old (MAME) | New (Corrected) | Issue |
|-------|------------|-----------------|-------|
| 0x03 Y | E1 | Y1 | Y mapped to E sound |
| 0x06 EH | Y | I | EH mapped to Y sound |
| 0x2A HV | PA0 | H | H sound was silent |
| 0x2C HF | H | H | (was correct) |
| 0x3F STOP | L | L | STOP mapped to L |

22 phonemes had first-letter mismatches indicating completely wrong sounds.
