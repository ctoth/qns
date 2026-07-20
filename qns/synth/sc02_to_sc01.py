"""SC-02 (SSI-263) to SC-01 phoneme mapping.

Based on the VOTRAX SC-02 datasheet phoneme chart (page 2) and
matching to SC-01 phonemes by name and example word similarity.

The SSI-263 is also known as the Votrax SC-02.
"""

# SC-02/SSI-263 phoneme definitions from datasheet
SC02_PHONEMES: dict[int, tuple[str, str]] = {
    0x00: ("PA", "pause"),
    0x01: ("E", "MEET"),
    0x02: ("E1", "BENT"),
    0x03: ("Y", "BEFORE"),
    0x04: ("YI", "YEAR"),
    0x05: ("AY", "PLEASE"),
    0x06: ("IE", "ANY"),
    0x07: ("I", "SIX"),
    0x08: ("A", "MADE"),
    0x09: ("AI", "CARE"),
    0x0A: ("EH", "NEST"),
    0x0B: ("EH1", "BELT"),
    0x0C: ("AE", "DAD"),
    0x0D: ("AE1", "AFTER"),
    0x0E: ("AH", "GOT"),
    0x0F: ("AH1", "FATHER"),
    0x10: ("AW", "OFFICE"),
    0x11: ("O", "STORE"),
    0x12: ("OU", "BOAT"),
    0x13: ("OO", "LOOK"),
    0x14: ("IU", "YOU"),
    0x15: ("IU1", "COULD"),
    0x16: ("U", "TUNE"),
    0x17: ("U1", "CARTOON"),
    0x18: ("UH", "WONDER"),
    0x19: ("UH1", "LOVE"),
    0x1A: ("UH2", "WHAT"),
    0x1B: ("UH3", "NUT"),
    0x1C: ("ER", "BIRD"),
    0x1D: ("R", "ROOF"),
    0x1E: ("R1", "RUG"),
    0x1F: ("R2", "MUTTER"),
    0x20: ("L", "LIFT"),
    0x21: ("L1", "PLAY"),
    0x22: ("LF", "FALL"),
    0x23: ("W", "WATER"),
    0x24: ("B", "BAG"),
    0x25: ("D", "PAID"),
    0x26: ("KV", "TAG"),
    0x27: ("P", "PEN"),
    0x28: ("T", "TART"),
    0x29: ("K", "KIT"),
    0x2A: ("HV", "hold vocal"),
    0x2B: ("HVC", "hold vocal closure"),
    0x2C: ("HF", "HEART"),
    0x2D: ("HFC", "hold fricative closure"),
    0x2E: ("HN", "hold nasal"),
    0x2F: ("Z", "ZERO"),
    0x30: ("S", "SAME"),
    0x31: ("J", "MEASURE"),
    0x32: ("SCH", "SHIP"),
    0x33: ("V", "VERY"),
    0x34: ("F", "FOUR"),
    0x35: ("THV", "THERE"),
    0x36: ("TH", "WITH"),
    0x37: ("M", "MORE"),
    0x38: ("N", "NINE"),
    0x39: ("NG", "RANG"),
    0x3A: (":A", "MARCHEN"),
    0x3B: (":OH", "LOWE"),
    0x3C: (":U", "FUNF"),
    0x3D: (":UH", "MENU"),
    0x3E: ("E2", "BITTE"),
    0x3F: ("LB", "LUBE"),
}

# SC-01 phoneme names for reference (from sc01_rom.py)
# 0x00=EH3, 0x01=EH2, 0x02=EH1, 0x03=PA0, 0x04=DT, 0x05=A1, 0x06=A2, 0x07=ZH
# 0x08=AH2, 0x09=I3, 0x0A=I2, 0x0B=I1, 0x0C=M, 0x0D=N, 0x0E=B, 0x0F=V
# 0x10=CH, 0x11=SH, 0x12=Z, 0x13=AW1, 0x14=NG, 0x15=AH1, 0x16=OO1, 0x17=OO
# 0x18=L, 0x19=K, 0x1A=J, 0x1B=H, 0x1C=G, 0x1D=F, 0x1E=D, 0x1F=S
# 0x20=A, 0x21=AY, 0x22=Y1, 0x23=UH3, 0x24=AH, 0x25=P, 0x26=O, 0x27=I
# 0x28=U, 0x29=Y, 0x2A=T, 0x2B=R, 0x2C=E, 0x2D=W, 0x2E=AE, 0x2F=AE1
# 0x30=AW2, 0x31=UH2, 0x32=UH1, 0x33=UH, 0x34=O2, 0x35=O1, 0x36=IU, 0x37=U1
# 0x38=THV, 0x39=TH, 0x3A=ER, 0x3B=EH, 0x3C=E1, 0x3D=AW, 0x3E=PA1, 0x3F=STOP

# Corrected SC-02 to SC-01 mapping based on phoneme name/sound matching
# Format: SC02_code -> SC01_code
SC02_TO_SC01: tuple[int, ...] = (
    # 0x00-0x0F: Vowels starting with PA, E, Y, A
    0x03,  # 0x00 PA (pause) -> PA0
    0x2C,  # 0x01 E (MEET) -> E (mEEt)
    0x3B,  # 0x02 E1 (BENT) -> EH (gEt) - short E sound
    0x22,  # 0x03 Y (BEFORE) -> Y1 (Yard) - semivowel Y
    0x29,  # 0x04 YI (YEAR) -> Y (anY)
    0x21,  # 0x05 AY (PLEASE) -> AY (dAY)
    0x27,  # 0x06 IE (ANY) -> I (pIn) - short I
    0x27,  # 0x07 I (SIX) -> I (pIn)
    0x20,  # 0x08 A (MADE) -> A (dAY)
    0x2E,  # 0x09 AI (CARE) -> AE (dAd) - similar open sound
    0x3B,  # 0x0A EH (NEST) -> EH (gEt)
    0x02,  # 0x0B EH1 (BELT) -> EH1 (hEAvy)
    0x2E,  # 0x0C AE (DAD) -> AE (dAd)
    0x2F,  # 0x0D AE1 (AFTER) -> AE1 (After)
    0x24,  # 0x0E AH (GOT) -> AH (mOp)
    0x15,  # 0x0F AH1 (FATHER) -> AH1 (fAther)

    # 0x10-0x1F: O/U vowels, ER, R
    0x13,  # 0x10 AW (OFFICE) -> AW1 (lAWful)
    0x26,  # 0x11 O (STORE) -> O (cOld)
    0x35,  # 0x12 OU (BOAT) -> O1 (abOArd)
    0x17,  # 0x13 OO (LOOK) -> OO (bOOK)
    0x36,  # 0x14 IU (YOU) -> IU (yOU)
    0x16,  # 0x15 IU1 (COULD) -> OO1 (lOOking)
    0x28,  # 0x16 U (TUNE) -> U (mOve)
    0x37,  # 0x17 U1 (CARTOON) -> U1 (yOU)
    0x33,  # 0x18 UH (WONDER) -> UH (cUp)
    0x32,  # 0x19 UH1 (LOVE) -> UH1 (Uncle)
    0x31,  # 0x1A UH2 (WHAT) -> UH2 (About)
    0x23,  # 0x1B UH3 (NUT) -> UH3 (missIOn)
    0x3A,  # 0x1C ER (BIRD) -> ER (bIRd)
    0x2B,  # 0x1D R (ROOF) -> R (Red)
    0x2B,  # 0x1E R1 (RUG) -> R (Red)
    0x2B,  # 0x1F R2 (MUTTER) -> R (Red)

    # 0x20-0x2F: L, W, consonants B/D/K/P/T, H variants, Z
    0x18,  # 0x20 L (LIFT) -> L (Land)
    0x18,  # 0x21 L1 (PLAY) -> L (Land)
    0x18,  # 0x22 LF (FALL) -> L (Land)
    0x2D,  # 0x23 W (WATER) -> W (Win)
    0x0E,  # 0x24 B (BAG) -> B (Bag)
    0x1E,  # 0x25 D (PAID) -> D (paiD)
    0x1C,  # 0x26 KV (TAG) -> G (Get) - voiced velar
    0x25,  # 0x27 P (PEN) -> P (Past)
    0x2A,  # 0x28 T (TART) -> T (Tap)
    0x19,  # 0x29 K (KIT) -> K (triCK)
    0x1B,  # 0x2A HV (hold vocal) -> H (Hello)
    0x03,  # 0x2B HVC (hold vocal closure) -> PA0 (silence)
    0x1B,  # 0x2C HF (HEART) -> H (Hello)
    0x03,  # 0x2D HFC (hold fric closure) -> PA0 (silence)
    0x03,  # 0x2E HN (hold nasal) -> PA0 (silence)
    0x12,  # 0x2F Z (ZERO) -> Z (Zoo)

    # 0x30-0x3F: S, J, fricatives, nasals, foreign vowels
    0x1F,  # 0x30 S (SAME) -> S (paSS)
    0x07,  # 0x31 J (MEASURE) -> ZH (aZure) - voiced palatal fricative
    0x11,  # 0x32 SCH (SHIP) -> SH (SHop)
    0x0F,  # 0x33 V (VERY) -> V (Van)
    0x1D,  # 0x34 F (FOUR) -> F (Fast)
    0x38,  # 0x35 THV (THERE) -> THV (THe)
    0x39,  # 0x36 TH (WITH) -> TH (THin)
    0x0C,  # 0x37 M (MORE) -> M (Mat)
    0x0D,  # 0x38 N (NINE) -> N (suN)
    0x14,  # 0x39 NG (RANG) -> NG (thiNG)
    0x08,  # 0x3A :A (MARCHEN) -> AH2 (hOnest) - German A
    0x34,  # 0x3B :OH (LOWE) -> O2 (fOr) - French O
    0x28,  # 0x3C :U (FUNF) -> U (mOve) - German U
    0x33,  # 0x3D :UH (MENU) -> UH (cUp) - French U
    0x01,  # 0x3E E2 (BITTE) -> EH2 (Enlist) - German short E
    0x18,  # 0x3F LB (LUBE) -> L (Land)
)


def get_mapping_info(sc02_code: int) -> dict:
    """Get detailed mapping info for an SC-02 phoneme."""
    from .sc01_rom import PHONE_NAMES as SC01_NAMES

    sc02_name, sc02_example = SC02_PHONEMES.get(sc02_code, ("?", "?"))
    sc01_code = SC02_TO_SC01[sc02_code & 0x3F]
    sc01_name = SC01_NAMES[sc01_code] if sc01_code < len(SC01_NAMES) else "?"

    return {
        "sc02_code": sc02_code,
        "sc02_name": sc02_name,
        "sc02_example": sc02_example,
        "sc01_code": sc01_code,
        "sc01_name": sc01_name,
    }


def print_mapping_table():
    """Print the full mapping table for debugging."""
    from .sc01_rom import PHONE_NAMES as SC01_NAMES

    print("SC-02 (SSI-263) to SC-01 Phoneme Mapping")
    print("=" * 70)
    print(f"{'SC-02':^25} | {'SC-01':^25}")
    print(f"{'Code':<6} {'Name':<6} {'Example':<12} | {'Code':<6} {'Name':<10}")
    print("-" * 70)

    for code in range(64):
        info = get_mapping_info(code)
        print(
            f"0x{info['sc02_code']:02X}   {info['sc02_name']:<6} {info['sc02_example']:<12} | "
            f"0x{info['sc01_code']:02X}   {info['sc01_name']:<10}"
        )


if __name__ == "__main__":
    print_mapping_table()
