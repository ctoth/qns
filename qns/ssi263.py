"""SSI-263 phoneme speech synthesizer emulation.

The SSI-263 is a speech synthesizer chip that produces speech from phoneme codes.
It was used in various speech cards including the Echo II and Mockingboard.

Register map:
    0: Duration/Phoneme - D7:D6 = mode, D5:D0 = phoneme
    1: Inflection - I10:I3
    2: Rate/Inflection - D7:D4 = rate, D3 = I11, D2:D0 = I2:I0
    3: Ctrl/Art/Amp - D7 = CTL, D6:D4 = articulation, D3:D0 = amplitude
    4: Filter frequency
"""

from __future__ import annotations

from typing import Callable

# Complete SSI-263 phoneme table (64 phonemes)
# Format: code -> (name, example_word, IPA approximation)
PHONEMES: dict[int, tuple[str, str, str]] = {
    0x00: ("PA", "pause", ""),
    0x01: ("E", "bEEt", "i:"),
    0x02: ("E1", "bIt", "ɪ"),
    0x03: ("Y", "Yet", "j"),
    0x04: ("YI", "bAby", "i"),
    0x05: ("AY", "bAlt", "eɪ"),
    0x06: ("EH", "gEt", "ɛ"),
    0x07: ("EH1", "bEt", "ɛ"),
    0x08: ("EH2", "gEt", "ɛ"),
    0x09: ("EH3", "jAcket", "ɛ"),
    0x0A: ("A", "dAy", "eɪ"),
    0x0B: ("A1", "mAde", "eɪ"),
    0x0C: ("A2", "hAt", "æ"),
    0x0D: ("AW", "fAther", "ɑ"),
    0x0E: ("AW1", "fAll", "ɔ"),
    0x0F: ("AW2", "cAlt", "ɔ"),
    0x10: ("UH", "bOOk", "ʊ"),
    0x11: ("UH1", "lOOk", "ʊ"),
    0x12: ("UH2", "rOOm", "u:"),
    0x13: ("UH3", "fOOl", "u:"),
    0x14: ("O", "bOAt", "oʊ"),
    0x15: ("O1", "rOAd", "oʊ"),
    0x16: ("O2", "nOt", "ɑ"),
    0x17: ("IU", "yOU", "ju:"),
    0x18: ("U", "yOU", "u:"),
    0x19: ("U1", "fOOd", "u:"),
    0x1A: ("ER", "bIRd", "ɜr"),
    0x1B: ("ER1", "hER", "ɜr"),
    0x1C: ("ER2", "lEARn", "ɜr"),
    0x1D: ("R", "Red", "r"),
    0x1E: ("R1", "caR", "r"),
    0x1F: ("R2", "gReat", "r"),
    0x20: ("L", "Let", "l"),
    0x21: ("L1", "caLL", "l"),
    0x22: ("LF", "Leaf", "l"),
    0x23: ("W", "Win", "w"),
    0x24: ("B", "Bet", "b"),
    0x25: ("D", "Dog", "d"),
    0x26: ("KV", "sKy", "k"),
    0x27: ("P", "Pot", "p"),
    0x28: ("T", "Top", "t"),
    0x29: ("K", "Kit", "k"),
    0x2A: ("HV", "aHead", "h"),
    0x2B: ("HVC", "aHead", "h"),
    0x2C: ("HF", "Help", "h"),
    0x2D: ("HFC", "Help", "h"),
    0x2E: ("HN", "Horse", "h"),
    0x2F: ("Z", "Zoo", "z"),
    0x30: ("S", "See", "s"),
    0x31: ("J", "aZure", "ʒ"),
    0x32: ("SCH", "SHip", "ʃ"),
    0x33: ("V", "Vest", "v"),
    0x34: ("F", "Fan", "f"),
    0x35: ("THV", "THis", "ð"),
    0x36: ("TH", "THin", "θ"),
    0x37: ("M", "Met", "m"),
    0x38: ("N", "Net", "n"),
    0x39: ("NG", "siNG", "ŋ"),
    0x3A: ("A", "lAst", "æ"),
    0x3B: ("OH", "cOUgh", "ɔ"),
    0x3C: ("U", "nEW", "u:"),
    0x3D: ("UH", "pUt", "ʊ"),
    0x3E: ("PA1", "pause", ""),
    0x3F: ("STOP", "stop", ""),
}


class SSI263:
    """SSI-263 speech synthesizer chip emulator.

    This is a basic emulator that logs phonemes. Full audio synthesis
    would require the phoneme waveform data from AppleWin.
    """

    # Register offsets
    REG_DURPHON = 0    # Duration/Phoneme
    REG_INFLECT = 1    # Inflection
    REG_RATEINF = 2    # Rate/Inflection
    REG_CTRLAMP = 3    # Control/Articulation/Amplitude
    REG_FILTER = 4     # Filter frequency

    # Duration modes (bits 7:6 of REG_DURPHON)
    MODE_IRQ_DISABLED = 0x00          # Interrupts disabled
    MODE_FRAME_IMMEDIATE = 0x40       # Frame immediate inflection
    MODE_PHONEME_IMMEDIATE = 0x80     # Phoneme immediate inflection
    MODE_PHONEME_TRANSITIONED = 0xC0  # Phoneme transitioned inflection

    # Control bit
    CONTROL_BIT = 0x80  # CTL in REG_CTRLAMP

    def __init__(self, base_port: int = 0xC0, clock: int = 12_288_000):
        """Initialize SSI-263.

        Args:
            base_port: Base I/O port (0xC0 for BSPLUS, 0x90 for BL40)
            clock: CPU clock frequency in Hz for timing calculations
        """
        self.base_port = base_port
        self.phoneme_log: list[int] = []
        self._clock = clock

        # Registers
        self.duration_phoneme = 0xC0  # MODE_PHONEME_TRANSITIONED | phoneme 0
        self.inflection = 0
        self.rate_inflection = 0
        self.ctrl_art_amp = 0x80  # CTL=1 (standby)
        self.filter_freq = 0xFF  # Silence

        # State
        self.speaking = False
        self.irq_enabled = False
        self.current_phoneme = 0

        # Timing for INT1 (phoneme completion interrupt)
        self._pending_irq_cycle: int | None = None  # Cycle when INT1 should fire
        self._current_cycle: int = 0  # Current cycle count (set via set_cycle_count)

        # Callbacks
        self._on_phoneme: Callable[[int, str], None] | None = None
        self._synth = None  # Optional SSI263Synth for audio output
        self._irq_callback: Callable[[int], None] | None = None  # INT1 signal

    def set_synth(self, synth) -> None:
        """Connect a synthesizer for audio output.

        When connected, register writes produce actual audio.

        Args:
            synth: SSI263Synth instance
        """
        self._synth = synth

    def set_phoneme_callback(self, callback: Callable[[int, str], None]) -> None:
        """Set callback for phoneme events.

        Args:
            callback: Function(phoneme_code, phoneme_name) called when phoneme played
        """
        self._on_phoneme = callback

    def set_irq_callback(self, callback: Callable[[int], None]) -> None:
        """Set callback for IRQ signaling (INT1).

        The SSI-263 asserts the A/R line when ready for the next phoneme.
        This is connected to INT1 on the Z180.

        Args:
            callback: Function(state) called with 1 when asserting, 0 when clearing
        """
        self._irq_callback = callback

    def set_cycle_count(self, cycles: int) -> None:
        """Update the current cycle count for timing calculations.

        Args:
            cycles: Current CPU cycle count
        """
        self._current_cycle = cycles

    def _calc_phoneme_duration_cycles(self) -> int:
        """Calculate phoneme duration in CPU cycles.

        Uses the AppleWin formula from SSI263.cpp line 95:
            phonemeDuration_ms = (((16 - rate) * 4096) / 1023) * (4 - dur_mode)

        Where:
            rate = bits 7:4 of rate_inflection register (0 = fastest, 15 = slowest)
            dur_mode = bits 7:6 of duration_phoneme register (0-3)

        Returns:
            Duration in CPU cycles
        """
        rate = (self.rate_inflection >> 4) & 0x0F
        dur_mode = (self.duration_phoneme >> 6) & 0x03
        duration_ms = (((16 - rate) * 4096) // 1023) * (4 - dur_mode)
        return (duration_ms * self._clock) // 1000

    def check_pending_irq(self, current_cycle: int) -> None:
        """Check if pending IRQ should fire. Call from main loop.

        Args:
            current_cycle: Current CPU cycle count
        """
        if self._pending_irq_cycle is not None and current_cycle >= self._pending_irq_cycle:
            self._pending_irq_cycle = None
            self.speaking = False  # Phoneme finished
            if self._irq_callback:
                self._irq_callback(1)  # Assert INT1

    def read(self, port: int) -> int:
        """Read from SSI-263 register."""
        reg = port - self.base_port
        if reg == self.REG_FILTER:
            # Status: bit 7 = A/R (request) - 0 = ready for new phoneme
            return 0x00 if not self.speaking else 0x80
        return 0xFF

    def write(self, port: int, value: int) -> None:
        """Write to SSI-263 register."""
        reg = port - self.base_port

        if reg == self.REG_DURPHON:
            self.duration_phoneme = value
            mode = value & 0xC0
            phoneme = value & 0x3F

            # Check if interrupts enabled
            self.irq_enabled = mode != self.MODE_IRQ_DISABLED

            # Forward to synth if connected
            if self._synth:
                self._synth.write_durphon(value)

            # If CTL=0 (not in standby), play the phoneme
            if not (self.ctrl_art_amp & self.CONTROL_BIT):
                self._speak_phoneme(phoneme)

        elif reg == self.REG_INFLECT:
            self.inflection = value
            if self._synth:
                self._synth.write_inflect(value)

        elif reg == self.REG_RATEINF:
            self.rate_inflection = value
            if self._synth:
                self._synth.write_rateinf(value)

        elif reg == self.REG_CTRLAMP:
            old_ctl = self.ctrl_art_amp & self.CONTROL_BIT
            self.ctrl_art_amp = value
            new_ctl = value & self.CONTROL_BIT
            amp = value & 0x0F
            print(f"[SSI263] CTRLAMP write: 0x{value:02X} CTL={1 if new_ctl else 0} AMP={amp}")

            # Forward to synth if connected
            if self._synth:
                self._synth.write_ctrlamp(value)

            if old_ctl and not new_ctl:
                # CTL transition 1->0: wake up and play current phoneme
                phoneme = self.duration_phoneme & 0x3F
                self._speak_phoneme(phoneme)
            elif not old_ctl and new_ctl:
                # CTL transition 0->1: go to standby
                self.speaking = False

        elif reg == self.REG_FILTER:
            self.filter_freq = value
            if self._synth:
                self._synth.write_filter(value)

    def _speak_phoneme(self, phoneme: int) -> None:
        """Process a phoneme."""
        self.current_phoneme = phoneme
        self.phoneme_log.append(phoneme)

        info = PHONEMES.get(phoneme, ("?", "unknown", ""))
        name, example, _ = info

        # Log it
        duration_cycles = self._calc_phoneme_duration_cycles()
        duration_ms = (duration_cycles * 1000) // self._clock
        print(f"[SSI263] Phoneme: 0x{phoneme:02X} {name} ({example}) duration={duration_ms}ms")

        # Call callback if set
        if self._on_phoneme:
            self._on_phoneme(phoneme, name)

        # Mark as speaking while phoneme plays
        self.speaking = True

        # Schedule INT1 to fire after phoneme duration
        # The real SSI-263 asserts the A/R line AFTER the phoneme finishes,
        # which triggers INT1 and lets the ISR queue the next phoneme
        if self.irq_enabled and self._irq_callback:
            self._pending_irq_cycle = self._current_cycle + duration_cycles

    def _reset(self) -> None:
        """Reset the chip."""
        self.duration_phoneme = 0xC0
        self.inflection = 0
        self.rate_inflection = 0
        self.ctrl_art_amp = 0x80
        self.filter_freq = 0xFF
        self.speaking = False
        self.irq_enabled = False
        print("[SSI263] Reset")

    def get_io_handlers(self) -> list[tuple[int, Callable[[int], int], Callable[[int, int], None]]]:
        """Return (port, read_handler, write_handler) for all ports."""
        handlers = []
        for offset in range(5):
            port = self.base_port + offset
            handlers.append((port, self.read, self.write))
        return handlers

    def get_phoneme_text(self) -> str:
        """Convert phoneme log to approximate text."""
        result = []
        for code in self.phoneme_log:
            info = PHONEMES.get(code, ("?", "", ""))
            name = info[0]
            if name not in ("PA", "PA1", "STOP"):
                result.append(name)
        return " ".join(result)
