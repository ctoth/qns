"""SSI-263 phoneme speech synthesizer emulation.

The SSI-263 is a speech synthesizer chip that produces speech from phoneme codes.
It was used in various speech cards including the Echo II and Mockingboard.

Register map:
    0: Duration/Phoneme - D7:D6 = mode, D5:D0 = phoneme
    1: Inflection - I10:I3
    2: Rate/Inflection - D7:D4 = rate, D3 = I11, D2:D0 = I2:I0
    3: Ctrl/Art/Amp - D7 = CTL, D6:D4 = articulation, D3:D0 = amplitude
    4: Filter frequency

This module owns register decoding.  Audio backends receive decoded
:class:`SSI263State` snapshots through the :class:`SpeechBackend` protocol
and never see raw register bytes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

# SSI-263 (SC-02) phoneme table from datasheet (64 phonemes)
# Format: code -> (name, example_word, IPA approximation)
PHONEMES: dict[int, tuple[str, str, str]] = {
    0x00: ("PA", "pause", ""),
    0x01: ("E", "MEET", "i:"),
    0x02: ("E1", "BENT", "ɛ"),
    0x03: ("Y", "BEFORE", "j"),
    0x04: ("YI", "YEAR", "j"),
    0x05: ("AY", "PLEASE", "eɪ"),
    0x06: ("IE", "ANY", "i"),
    0x07: ("I", "SIX", "ɪ"),
    0x08: ("A", "MADE", "eɪ"),
    0x09: ("AI", "CARE", "ɛə"),
    0x0A: ("EH", "NEST", "ɛ"),
    0x0B: ("EH1", "BELT", "ɛ"),
    0x0C: ("AE", "DAD", "æ"),
    0x0D: ("AE1", "AFTER", "æ"),
    0x0E: ("AH", "GOT", "ɑ"),
    0x0F: ("AH1", "FATHER", "ɑ"),
    0x10: ("AW", "OFFICE", "ɔ"),
    0x11: ("O", "STORE", "ɔ"),
    0x12: ("OU", "BOAT", "oʊ"),
    0x13: ("OO", "LOOK", "ʊ"),
    0x14: ("IU", "YOU", "ju:"),
    0x15: ("IU1", "COULD", "ʊ"),
    0x16: ("U", "TUNE", "u:"),
    0x17: ("U1", "CARTOON", "u:"),
    0x18: ("UH", "WONDER", "ʌ"),
    0x19: ("UH1", "LOVE", "ʌ"),
    0x1A: ("UH2", "WHAT", "ʌ"),
    0x1B: ("UH3", "NUT", "ʌ"),
    0x1C: ("ER", "BIRD", "ɜr"),
    0x1D: ("R", "ROOF", "r"),
    0x1E: ("R1", "RUG", "r"),
    0x1F: ("R2", "MUTTER", "r"),
    0x20: ("L", "LIFT", "l"),
    0x21: ("L1", "PLAY", "l"),
    0x22: ("LF", "FALL", "l"),
    0x23: ("W", "WATER", "w"),
    0x24: ("B", "BAG", "b"),
    0x25: ("D", "PAID", "d"),
    0x26: ("KV", "TAG", "g"),
    0x27: ("P", "PEN", "p"),
    0x28: ("T", "TART", "t"),
    0x29: ("K", "KIT", "k"),
    0x2A: ("HV", "hold vocal", ""),
    0x2B: ("HVC", "hold vocal closure", ""),
    0x2C: ("HF", "HEART", "h"),
    0x2D: ("HFC", "hold fricative closure", ""),
    0x2E: ("HN", "hold nasal", ""),
    0x2F: ("Z", "ZERO", "z"),
    0x30: ("S", "SAME", "s"),
    0x31: ("J", "MEASURE", "ʒ"),
    0x32: ("SCH", "SHIP", "ʃ"),
    0x33: ("V", "VERY", "v"),
    0x34: ("F", "FOUR", "f"),
    0x35: ("THV", "THERE", "ð"),
    0x36: ("TH", "WITH", "θ"),
    0x37: ("M", "MORE", "m"),
    0x38: ("N", "NINE", "n"),
    0x39: ("NG", "RANG", "ŋ"),
    0x3A: (":A", "MARCHEN", "a"),
    0x3B: (":OH", "LOWE", "ø"),
    0x3C: (":U", "FUNF", "y"),
    0x3D: (":UH", "MENU", "y"),
    0x3E: ("E2", "BITTE", "ɛ"),
    0x3F: ("LB", "LUBE", "l"),
}


@dataclass(frozen=True)
class Phoneme:
    """One captured SSI-263 phoneme with its datasheet description."""

    code: int
    name: str
    example: str
    ipa: str


@dataclass(frozen=True)
class SSI263State:
    """Decoded SSI-263 register state captured at one phoneme event."""

    phoneme: int        # 6-bit phoneme code (0-63)
    duration: int       # 2-bit duration mode (0-3), 0 = IRQ disabled
    inflection: int     # 12-bit inflection (0-4095), 2048 = neutral pitch
    rate: int           # 4-bit rate (0-15), 0 = fastest
    articulation: int   # 3-bit articulation (0-7)
    amplitude: int      # 4-bit amplitude (0-15)
    filter_freq: int    # 8-bit filter frequency (0-255), 0xFF = silence


class SpeechBackend(Protocol):
    """Audio backend receiving decoded phoneme events from the chip."""

    def start(self) -> None:
        """Open the host audio output."""

    def stop(self) -> None:
        """Close the host audio output."""

    def play(self, state: SSI263State) -> None:
        """Produce audio for one decoded phoneme event."""


class SSI263:
    """SSI-263 speech synthesizer chip emulator.

    Decodes register writes, captures the phoneme stream, schedules the
    phoneme-completion interrupt (INT1), and forwards decoded phoneme
    events to an optional :class:`SpeechBackend`.
    """

    # Register offsets
    REG_DURPHON = 0    # Duration/Phoneme
    REG_INFLECT = 1    # Inflection
    REG_RATEINF = 2    # Rate/Inflection
    REG_CTRLAMP = 3    # Control/Articulation/Amplitude
    REG_FILTER = 4     # Filter frequency

    def __init__(self, base_port: int = 0xC0, clock: int = 12_288_000):
        """Initialize SSI-263.

        Args:
            base_port: Base I/O port (0xC0 for BSPLUS, 0x90 for BL40)
            clock: CPU clock frequency in Hz for timing calculations
        """
        self.base_port = base_port
        self.phoneme_log: list[int] = []
        self._clock = clock

        # Decoded register state at chip reset: transitioned-mode pause
        # phoneme, zero amplitude, filter silenced, standby.
        self.phoneme = 0
        self.duration = 3
        self.inflection = 0
        self.rate = 0
        self.articulation = 0
        self.amplitude = 0
        self.filter_freq = 0xFF
        self.control = True

        self.speaking = False

        # Timing for INT1 (phoneme completion interrupt)
        self._pending_irq_cycle: int | None = None  # Cycle when INT1 should fire
        self._current_cycle: int = 0  # Current cycle count (set via set_cycle_count)

        # Callbacks
        self._on_phoneme: Callable[[int, str], None] | None = None
        self._synth: SpeechBackend | None = None
        self._irq_callback: Callable[[int], None] | None = None  # INT1 signal

    @property
    def irq_enabled(self) -> bool:
        """Whether the current duration mode enables the completion IRQ."""
        return self.duration != 0

    @property
    def irq_pending(self) -> bool:
        """Whether a phoneme-completion INT1 is scheduled but not yet fired."""
        return self._pending_irq_cycle is not None

    def set_synth(self, synth: SpeechBackend | None) -> None:
        """Connect an audio backend that receives decoded phoneme events."""
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
        """Update the current cycle count for timing calculations."""
        self._current_cycle = cycles

    def _calc_phoneme_duration_cycles(self) -> int:
        """Calculate phoneme duration in CPU cycles.

        Uses the AppleWin formula from SSI263.cpp line 95:
            phonemeDuration_ms = (((16 - rate) * 4096) / 1023) * (4 - dur_mode)
        """
        duration_ms = (((16 - self.rate) * 4096) // 1023) * (4 - self.duration)
        return (duration_ms * self._clock) // 1000

    def check_pending_irq(self, current_cycle: int) -> None:
        """Fire the scheduled INT1 once its cycle is reached. Call from main loop."""
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
        """Decode one register write and trigger phoneme events."""
        reg = port - self.base_port

        if reg == self.REG_DURPHON:
            self.duration = (value >> 6) & 0x03
            self.phoneme = value & 0x3F
            # If CTL=0 (not in standby), play the phoneme
            if not self.control:
                self._speak_phoneme()

        elif reg == self.REG_INFLECT:
            # Bits I10:I3 of the 12-bit inflection value
            self.inflection = (self.inflection & 0x807) | ((value & 0xFF) << 3)

        elif reg == self.REG_RATEINF:
            self.rate = (value >> 4) & 0x0F
            # Bit 3 = I11, bits 2:0 = I2:I0
            self.inflection = (
                ((value & 0x08) << 8)
                | (self.inflection & 0x7F8)
                | (value & 0x07)
            )

        elif reg == self.REG_CTRLAMP:
            was_standby = self.control
            self.control = bool(value & 0x80)
            self.articulation = (value >> 4) & 0x07
            self.amplitude = value & 0x0F
            if was_standby and not self.control:
                # CTL transition 1->0: wake up and play current phoneme
                self._speak_phoneme()
            elif not was_standby and self.control:
                # CTL transition 0->1: go to standby
                self.speaking = False

        elif reg == self.REG_FILTER:
            self.filter_freq = value & 0xFF

    def state(self) -> SSI263State:
        """Return a snapshot of the decoded register state."""
        return SSI263State(
            phoneme=self.phoneme,
            duration=self.duration,
            inflection=self.inflection,
            rate=self.rate,
            articulation=self.articulation,
            amplitude=self.amplitude,
            filter_freq=self.filter_freq,
        )

    def _speak_phoneme(self) -> None:
        """Capture one phoneme event, notify observers, and schedule INT1."""
        self.phoneme_log.append(self.phoneme)

        if self._on_phoneme:
            name = PHONEMES.get(self.phoneme, ("?", "unknown", ""))[0]
            self._on_phoneme(self.phoneme, name)

        # Mark as speaking while phoneme plays
        self.speaking = True

        if self._synth is not None:
            self._synth.play(self.state())

        # The real SSI-263 asserts the A/R line AFTER the phoneme finishes,
        # which triggers INT1 and lets the ISR queue the next phoneme
        if self.irq_enabled and self._irq_callback:
            self._pending_irq_cycle = (
                self._current_cycle + self._calc_phoneme_duration_cycles()
            )

    def get_io_handlers(self) -> list[tuple[int, Callable[[int], int], Callable[[int, int], None]]]:
        """Return (port, read_handler, write_handler) for all ports."""
        return [
            (self.base_port + offset, self.read, self.write)
            for offset in range(5)
        ]

    def get_phonemes(
        self,
        *,
        include_pauses: bool = True,
        start: int = 0,
    ) -> tuple[Phoneme, ...]:
        """Return retained phonemes with names, examples, and IPA spellings."""
        result = []
        for code in self.phoneme_log[start:]:
            if not include_pauses and code == 0:
                continue
            name, example, ipa = PHONEMES.get(code, ("?", "unknown", ""))
            result.append(Phoneme(code=code, name=name, example=example, ipa=ipa))
        return tuple(result)

    def get_phoneme_text(self) -> str:
        """Return captured non-pause SSI-263 phoneme names."""
        return " ".join(
            phoneme.name for phoneme in self.get_phonemes(include_pauses=False)
        )
