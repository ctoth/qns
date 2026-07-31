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

from .clock import HD64180_PHI_HZ

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


# DURPHON mode selector values, shifted down from the datasheet's register
# encoding (0xC0/0x80/0x40/0x00).
_MODE_PHONEME_TRANSITIONED = 3
_MODE_PHONEME_IMMEDIATE = 2
_MODE_FRAME_IMMEDIATE = 1
_MODE_IRQ_DISABLED = 0

# The phoneme waveform table is the model for how long a phoneme lasts.
# Imported lazily: qns.synth imports back from this module.
_PHONEME_SAMPLE_RATE = 22050
_CAPTURE_RATE = 8
_phoneme_lengths: tuple[int, ...] | None = None


def _phoneme_length_samples(phoneme: int) -> int:
    """Waveform length of one phoneme, in samples at _PHONEME_SAMPLE_RATE."""
    global _phoneme_lengths
    if _phoneme_lengths is None:
        from .synth.phonemes import PHONEME_INFO

        _phoneme_lengths = tuple(length for _, length in PHONEME_INFO)

    code = phoneme & 0x3F
    if code == 0:
        # Pause has no capture; AppleWin uses the first phoneme's length.
        return _phoneme_lengths[0] if _phoneme_lengths else 0
    if code == 1:
        code = 2
    index = code - 2
    if 0 <= index < len(_phoneme_lengths):
        return _phoneme_lengths[index]
    return 0


def playback_length_samples(
    phoneme: int,
    duration: int,
    rate: int = _CAPTURE_RATE,
) -> int:
    """How many samples one phoneme plays for under rate and duration.

    The duration mode decimates the waveform (1, 4/3, 2 or 4), which is what
    combines with the 4-bit rate control to decide both when the chip reports
    the phoneme complete and how much audio a backend has to produce to fill
    that time.  The fixed captures have no recorded register settings, so
    rate 8 is their neutral playback point; the chip's documented linear
    ``16 - rate`` timing scale changes their length around that point.
    """
    samples = _phoneme_length_samples(phoneme)
    if samples <= 0:
        return 0
    if duration == 1:
        samples = (samples * 3) // 4
    elif duration == 2:
        samples //= 2
    elif duration == 3:
        samples //= 4

    rate = rate & 0x0F
    return max(1, (samples * (16 - rate)) // (16 - _CAPTURE_RATE))


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

    phoneme: int  # 6-bit phoneme code (0-63)
    duration: int  # 2-bit mode selector as written (0 = IRQ disabled)
    inflection: int  # 12-bit inflection (0-4095), 2048 = neutral pitch
    rate: int  # 4-bit rate (0-15), 0 = slowest
    articulation: int  # 3-bit articulation (0-7)
    amplitude: int  # 4-bit amplitude (0-15)
    filter_freq: int  # 8-bit filter frequency (0-255), 0xFF = silence
    # Duration mode that actually governs playback speed.  Frame timing mode
    # forces it to 3 regardless of the bits written, and a mode-0 write keeps
    # whatever the last CTL H->L latched, so this is not always `duration`.
    playback_duration: int = 0
    # Whether the last CTL H->L transition selected phoneme-timed,
    # transitioned inflection rather than either immediate-inflection mode.
    transitioned_inflection: bool = False


@dataclass(frozen=True)
class _DeferredWriteTiming:
    """One CPU-originated write awaiting z-core's exact I/O event cycle."""

    port: int
    value: int
    phoneme_generation: int | None
    duration_cycles: int
    code: int
    name: str
    state: SSI263State | None
    phoneme_end: _DeferredPhonemeEnd | None


@dataclass(frozen=True)
class _DeferredPhonemeEnd:
    """Active phoneme state retained until an exact ending cycle arrives."""

    generation: int | None
    start_cycle: int
    pending_irq_cycle: int | None
    modeled_samples: int


class SpeechBackend(Protocol):
    """Audio backend receiving decoded phoneme events from the chip."""

    def start(self) -> None:
        """Open the host audio output."""

    def stop(self) -> None:
        """Close the host audio output."""

    def play(self, state: SSI263State) -> None:
        """Begin one decoded phoneme event."""

    def end_phoneme(self, elapsed_samples: int) -> None:
        """Commit audio equal to the phoneme's elapsed emulated time."""

    def realtime_lead_seconds(self) -> float:
        """Return bounded run-ahead needed to keep host audio continuous."""


class SSI263:
    """SSI-263 speech synthesizer chip emulator.

    Decodes register writes, captures the phoneme stream, schedules the
    phoneme-completion interrupt (INT1), and forwards decoded phoneme
    events to an optional :class:`SpeechBackend`.
    """

    # Register offsets
    REG_DURPHON = 0  # Duration/Phoneme
    REG_INFLECT = 1  # Inflection
    REG_RATEINF = 2  # Rate/Inflection
    REG_CTRLAMP = 3  # Control/Articulation/Amplitude
    REG_FILTER = 4  # Filter frequency

    def __init__(self, base_port: int = 0xC0, clock: int = HD64180_PHI_HZ):
        """Initialize SSI-263.

        Args:
            base_port: Base I/O port (0xC0 for BSPLUS, 0x90 for BL40)
            clock: HD64180 phi/system-clock frequency in Hz for timing calculations
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

        # Mode latched at the last CTL H->L transition.  The two high bits of
        # DURPHON select one of three modes, or 0 meaning "disable A/!R output
        # only; does not change previous A/!R response" - so a mode-0 write
        # must NOT be read as "this phoneme has no interrupt", which would
        # silently remove the handshake that paces the whole utterance.
        self._mode_function = 0  # 1 = frame timing, 2/3 = phoneme timing
        self._mode_enable_ints = False

        # A/!R status, returned inverted in bit 7 of any register read.  Set
        # when a phoneme completes (even with interrupts disabled), cleared by
        # writes to registers 0-2 or by entering standby.
        self._d7 = False

        # Timing for INT1 (phoneme completion interrupt)
        self._pending_irq_cycle: int | None = None  # Cycle when INT1 should fire
        self._current_cycle: int = 0  # Current cycle count (set via set_cycle_count)
        self._phoneme_start_cycle: int | None = None
        self._phoneme_modeled_samples = 0
        self._phoneme_generation = 0
        self._active_phoneme_generation: int | None = None
        self._defer_next_write = False
        self._defer_current_write = False
        self._deferred_end_for_current_write: _DeferredPhonemeEnd | None = None
        self._deferred_write_timings: list[_DeferredWriteTiming] = []
        self._exact_phoneme_starts: dict[int, int] = {}

        # Callbacks
        self._on_phoneme: Callable[[int, str], None] | None = None
        self._synth: SpeechBackend | None = None
        self._irq_callback: Callable[[int], None] | None = None  # INT1 signal

    @property
    def irq_enabled(self) -> bool:
        """Whether the latched mode enables the completion IRQ.

        This is the mode captured at the last CTL H->L transition, not the
        mode bits of the most recent DURPHON write: writing mode 0 disables
        the A/!R output without changing the retained response.
        """
        return self._mode_enable_ints

    @property
    def playback_duration(self) -> int:
        """Duration mode that governs how fast a phoneme plays out.

        Frame timing mode plays every phoneme at the shortest duration
        regardless of the bits written.
        """
        if self._mode_function == _MODE_FRAME_IMMEDIATE:
            return 3
        return self.duration

    @property
    def request_pending(self) -> bool:
        """Whether A/!R is asserted, i.e. the last phoneme has completed."""
        return self._d7

    @property
    def irq_pending(self) -> bool:
        """Whether a phoneme-completion INT1 is scheduled but not yet fired."""
        return self._pending_irq_cycle is not None

    @property
    def pending_irq_cycle(self) -> int | None:
        """Cycle a scheduled phoneme completes, or None if none is pending.

        The main loop needs this to know how far it may advance emulated
        time while the CPU sleeps waiting for that completion.
        """
        return self._pending_irq_cycle

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

    def defer_next_write_cycle(self) -> None:
        """Wait for z-core's exact I/O event before publishing write timing."""
        self._defer_next_write = True

    def confirm_write_cycle(self, port: int, value: int, cycle: int) -> None:
        """Apply the exact native cycle for one deferred CPU I/O write."""
        if not self._deferred_write_timings:
            raise RuntimeError("missing deferred SSI-263 write timing")
        timing = self._deferred_write_timings.pop(0)
        if (timing.port, timing.value) != (port, value):
            raise RuntimeError(
                "SSI-263 write event order diverged: "
                f"expected {(timing.port, timing.value)}, got {(port, value)}"
            )

        self._current_cycle = cycle
        if timing.phoneme_end is not None:
            self._finish_deferred_phoneme(timing.phoneme_end, cycle)
        generation = timing.phoneme_generation
        if generation is None:
            return
        self._exact_phoneme_starts[generation] = cycle
        if self._active_phoneme_generation == generation:
            self._phoneme_start_cycle = cycle
            self._pending_irq_cycle = cycle + timing.duration_cycles
        if self._on_phoneme:
            self._on_phoneme(timing.code, timing.name)
        if self._synth is not None and timing.state is not None:
            self._synth.play(timing.state)

    @property
    def current_cycle(self) -> int:
        """Latest exact executed-cycle timestamp published to the chip.

        Observers run inside the emulator's mutable borrow of the CPU and
        cannot read the cycle count back off it. Native I/O events therefore
        publish exact write cycles, while the run loop publishes chunk ends.
        """
        return self._current_cycle

    def _calc_phoneme_duration_cycles(self) -> int:
        """Calculate phoneme duration in CPU cycles.

        A phoneme lasts as long as it takes to play out, which is the length
        of the phoneme's waveform divided by the decimation the duration mode
        selects (1, 4/3, 2 or 4).  This is how AppleWin's SSI263 completes a
        phoneme: it decrements m_phonemeLengthRemaining per output sample and
        signals completion when it reaches zero.

        Note the formula in AppleWin's SSI_Output() - (((16-rate)*4096)/1023)
        * (4-dur) - is not this: it lives inside a LOG_SSI263B debug logger
        and only estimates a duration for a log line.  Using it here gave
        256 ms phonemes, roughly four times too long.
        """
        samples = playback_length_samples(
            self.phoneme,
            self.playback_duration,
            self.rate,
        )
        if samples <= 0:
            return 0

        return int(samples * self._clock / _PHONEME_SAMPLE_RATE)

    def check_pending_irq(self, current_cycle: int) -> None:
        """Complete a scheduled phoneme once its cycle is reached.

        Call from the main loop.  Completion always raises A/!R (D7), even
        when interrupts are disabled; INT1 is only asserted when the latched
        mode enables them.
        """
        if self._pending_irq_cycle is not None and current_cycle >= self._pending_irq_cycle:
            self._end_active_phoneme(self._pending_irq_cycle)
            self._pending_irq_cycle = None
            self.speaking = False  # Phoneme finished
            if not self.control:
                self._d7 = True
            if self.irq_enabled and self._irq_callback:
                self._irq_callback(1)  # Assert INT1

    def read(self, port: int) -> int:
        """Read A/!R inverted in bit 7, regardless of which register.

        Bit 7 is high once a phoneme has completed, i.e. the chip is
        requesting the next one.  Returning "busy" here instead would make
        the firmware queue phonemes as fast as it could execute.
        """
        return 0x80 if self._d7 else 0x00

    def _latch_mode_and_ints(self) -> None:
        """Latch mode and interrupt enable, as CTL H->L does on the chip.

        A mode-0 write disables the A/!R output but retains the previously
        selected response, so the function is only replaced for modes 1-3.
        """
        if self.duration != _MODE_IRQ_DISABLED:
            self._mode_function = self.duration
            self._mode_enable_ints = True
        else:
            self._mode_enable_ints = False

    def write(self, port: int, value: int) -> None:
        """Decode one register write and trigger phoneme events."""
        reg = port - self.base_port
        deferred = self._defer_next_write
        self._defer_next_write = False
        self._defer_current_write = deferred
        self._deferred_end_for_current_write = None
        generation_before = self._phoneme_generation

        try:
            # Writes to registers 0-2 complete the handshake: they de-assert the
            # interrupt and clear A/!R.
            if reg <= self.REG_RATEINF:
                self._d7 = False
                if self._irq_callback:
                    self._irq_callback(0)

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
                self.inflection = ((value & 0x08) << 8) | (self.inflection & 0x7F8) | (value & 0x07)

            elif reg == self.REG_CTRLAMP:
                was_standby = self.control
                self.control = bool(value & 0x80)
                self.articulation = (value >> 4) & 0x07
                self.amplitude = value & 0x0F
                if was_standby and not self.control:
                    # CTL transition 1->0: latch the mode, then play the phoneme
                    self._latch_mode_and_ints()
                    self._speak_phoneme()
                elif not was_standby and self.control:
                    # CTL transition 0->1: standby de-asserts the interrupt too
                    self._end_active_phoneme(self._current_cycle)
                    self.speaking = False
                    self._d7 = False
                    if self._irq_callback:
                        self._irq_callback(0)

            elif reg == self.REG_FILTER:
                self.filter_freq = value & 0xFF
        finally:
            self._defer_current_write = False

        if deferred:
            generation = (
                self._phoneme_generation if self._phoneme_generation != generation_before else None
            )
            duration_cycles = (
                self._pending_irq_cycle - self._current_cycle
                if generation is not None and self._pending_irq_cycle is not None
                else 0
            )
            name = PHONEMES.get(self.phoneme, ("?", "unknown", ""))[0]
            self._deferred_write_timings.append(
                _DeferredWriteTiming(
                    port=port,
                    value=value,
                    phoneme_generation=generation,
                    duration_cycles=duration_cycles,
                    code=self.phoneme,
                    name=name,
                    state=self.state() if generation is not None else None,
                    phoneme_end=self._deferred_end_for_current_write,
                )
            )

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
            playback_duration=self.playback_duration,
            transitioned_inflection=self._mode_function == 3,
        )

    def _speak_phoneme(self) -> None:
        """Capture one phoneme event, notify observers, and schedule INT1."""
        self._end_active_phoneme(self._current_cycle)
        self.phoneme_log.append(self.phoneme)
        self._phoneme_generation += 1
        self._active_phoneme_generation = self._phoneme_generation

        if self._on_phoneme and not self._defer_current_write:
            name = PHONEMES.get(self.phoneme, ("?", "unknown", ""))[0]
            self._on_phoneme(self.phoneme, name)

        # Mark as speaking while phoneme plays
        self.speaking = True

        if self._synth is not None and not self._defer_current_write:
            self._synth.play(self.state())

        # The real SSI-263 asserts the A/R line AFTER the phoneme finishes,
        # which triggers INT1 and lets the ISR queue the next phoneme.  The
        # completion is scheduled whether or not interrupts are enabled,
        # because it also drives the A/!R status bit.
        self._phoneme_start_cycle = self._current_cycle
        self._phoneme_modeled_samples = playback_length_samples(
            self.phoneme,
            self.playback_duration,
            self.rate,
        )
        self._pending_irq_cycle = self._current_cycle + self._calc_phoneme_duration_cycles()

    def _end_active_phoneme(self, end_cycle: int) -> None:
        """End the active phoneme at an exact emulated-sample boundary."""
        if self._phoneme_start_cycle is None:
            return

        generation = self._active_phoneme_generation
        if self._defer_current_write:
            self._deferred_end_for_current_write = _DeferredPhonemeEnd(
                generation=generation,
                start_cycle=self._phoneme_start_cycle,
                pending_irq_cycle=self._pending_irq_cycle,
                modeled_samples=self._phoneme_modeled_samples,
            )
        else:
            elapsed_samples = self._elapsed_phoneme_samples(
                start_cycle=self._phoneme_start_cycle,
                pending_irq_cycle=self._pending_irq_cycle,
                modeled_samples=self._phoneme_modeled_samples,
                end_cycle=end_cycle,
            )
            if self._synth is not None:
                self._synth.end_phoneme(elapsed_samples)
            if generation is not None:
                self._exact_phoneme_starts.pop(generation, None)
        self._phoneme_start_cycle = None
        self._phoneme_modeled_samples = 0
        self._active_phoneme_generation = None

    def _finish_deferred_phoneme(
        self,
        phoneme_end: _DeferredPhonemeEnd,
        end_cycle: int,
    ) -> None:
        """Publish an exact backend end after its native I/O event drains."""
        generation = phoneme_end.generation
        start_cycle = (
            self._exact_phoneme_starts.pop(generation, phoneme_end.start_cycle)
            if generation is not None
            else phoneme_end.start_cycle
        )
        elapsed_samples = self._elapsed_phoneme_samples(
            start_cycle=start_cycle,
            pending_irq_cycle=phoneme_end.pending_irq_cycle,
            modeled_samples=phoneme_end.modeled_samples,
            end_cycle=end_cycle,
        )
        if self._synth is not None:
            self._synth.end_phoneme(elapsed_samples)

    def _elapsed_phoneme_samples(
        self,
        *,
        start_cycle: int,
        pending_irq_cycle: int | None,
        modeled_samples: int,
        end_cycle: int,
    ) -> int:
        """Convert an exact executed-cycle interval to bounded output samples."""
        elapsed_cycles = max(0, end_cycle - start_cycle)
        if pending_irq_cycle is not None and end_cycle >= pending_irq_cycle:
            return modeled_samples
        elapsed_samples = int(elapsed_cycles * _PHONEME_SAMPLE_RATE / self._clock)
        return min(elapsed_samples, modeled_samples)

    def get_io_handlers(self) -> list[tuple[int, Callable[[int], int], Callable[[int, int], None]]]:
        """Return (port, read_handler, write_handler) for all ports."""
        return [(self.base_port + offset, self.read, self.write) for offset in range(5)]

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
        return " ".join(phoneme.name for phoneme in self.get_phonemes(include_pauses=False))
