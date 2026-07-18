"""Approximate SSI-263 audio using the AppleWin fixed PCM captures.

The captures provide one waveform for each available phoneme at one unknown
register setting.  This backend therefore preserves the documented register
interface but does not pretend to synthesize undocumented articulation,
inflection, rate, duration, or filter-frequency effects.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .phonemes import PHONEME_INFO, SAMPLE_RATE, get_phoneme_samples
from .player import AudioPlayer


@dataclass
class SSI263PCMState:
    """Register state mirrored from an SSI-263 reset."""

    phoneme: int = 0
    duration: int = 3
    inflection: int = 0
    rate: int = 0
    articulation: int = 0
    amplitude: int = 0
    filter_freq: int = 0xFF
    control: bool = True


class SSI263PCMSynth:
    """Play fixed SSI-263 phoneme captures through the chip register contract.

    The hardware-facing :class:`qns.ssi263.SSI263` remains responsible for
    phoneme completion timing and interrupts.  This class only mirrors writes
    and supplies approximate audio.
    """

    def __init__(self, audio_enabled: bool = True) -> None:
        self.sample_rate = SAMPLE_RATE
        self.state = SSI263PCMState()
        self._player = AudioPlayer(sample_rate=SAMPLE_RATE) if audio_enabled else None
        self._phoneme_callback: Callable[[int], None] | None = None

    def start(self) -> None:
        """Start the host audio stream when audio output is enabled."""
        if self._player is not None:
            self._player.start()

    def stop(self) -> None:
        """Stop the host audio stream when audio output is enabled."""
        if self._player is not None:
            self._player.stop()

    def write_durphon(self, value: int) -> None:
        """Mirror the duration/phoneme register and play while active."""
        self.state.duration = (value >> 6) & 0x03
        self.state.phoneme = value & 0x3F
        if not self.state.control:
            self._play_current_phoneme()

    def write_inflect(self, value: int) -> None:
        """Mirror inflection bits I10:I3."""
        self.state.inflection = (self.state.inflection & 0x807) | (value << 3)

    def write_rateinf(self, value: int) -> None:
        """Mirror rate and the split high/low inflection bits."""
        self.state.rate = (value >> 4) & 0x0F
        self.state.inflection = (
            ((value & 0x08) << 8)
            | (self.state.inflection & 0x7F8)
            | (value & 0x07)
        )

    def write_ctrlamp(self, value: int) -> None:
        """Mirror control, articulation, and amplitude fields."""
        old_control = self.state.control
        self.state.control = bool(value & 0x80)
        self.state.articulation = (value >> 4) & 0x07
        self.state.amplitude = value & 0x0F
        if old_control and not self.state.control:
            self._play_current_phoneme()

    def write_filter(self, value: int) -> None:
        """Mirror the filter-frequency register."""
        self.state.filter_freq = value

    def set_phoneme_callback(self, callback: Callable[[int], None]) -> None:
        """Set a callback invoked whenever this backend emits a phoneme."""
        self._phoneme_callback = callback

    def speak_phoneme(self, phoneme: int) -> None:
        """Play a phoneme directly with the current amplitude setting."""
        self.state.phoneme = phoneme & 0x3F
        self._play_current_phoneme()

    def is_speaking(self) -> bool:
        """Return whether the host audio player still has queued samples."""
        return self._player is not None and self._player.is_playing()

    def get_phoneme_audio(self, phoneme: int, amplitude: int | None = None) -> np.ndarray:
        """Return the available fixed capture as normalized float32 samples.

        AppleWin provides 62 captures for SSI-263 codes 2 through 63.  Code 0
        is pause.  Code 1 has no distinct capture, so this approximate backend
        uses the adjacent code-2 capture rather than substituting another
        synthesizer architecture.
        """
        code = phoneme & 0x3F
        if code == 0:
            return np.zeros(1, dtype=np.float32)
        if code == 1:
            code = 2

        data_index = code - 2
        if not 0 <= data_index < len(PHONEME_INFO):
            return np.zeros(1, dtype=np.float32)

        level = self.state.amplitude if amplitude is None else amplitude
        gain = max(0, min(15, level)) / 15.0
        samples = get_phoneme_samples(data_index).astype(np.float32)
        return samples * (gain / 32768.0)

    def _play_current_phoneme(self) -> None:
        phoneme = self.state.phoneme
        if self._phoneme_callback is not None:
            self._phoneme_callback(phoneme)
        if self._player is not None:
            self._player.play(self.get_phoneme_audio(phoneme))
