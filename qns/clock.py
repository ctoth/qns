"""Clock constants for the original HD64180-based BNS hardware."""

# The board's 12.288 MHz value is the frequency at the HD64180 crystal input.
# The processor divides that input by two to produce phi, the system clock
# counted by instruction timings and the PRT's phi/20 prescaler.
HD64180_CRYSTAL_HZ = 12_288_000
HD64180_PHI_HZ = HD64180_CRYSTAL_HZ // 2
