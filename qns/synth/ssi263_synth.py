"""SSI-263 Speech Synthesizer.

High-level synthesizer combining phoneme data, DSP, and audio output.
Can be used standalone or connected to the emulator's SSI263 chip.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from .dsp import apply_amplitude, apply_filter, pitch_shift, time_stretch
from .phonemes import PHONEME_INFO, get_phoneme_samples
from .player import AudioPlayer


@dataclass
class SSI263State:
    """Current SSI-263 register state."""

    phoneme: int = 0  # 6-bit (0-63)
    duration: int = 0  # 2-bit (0-3), 0 = no averaging (longest output)
    inflection: int = 2048  # 12-bit (0-4095), 2048 = neutral pitch
    rate: int = 8  # 4-bit (0-15), 8 = middle speed
    articulation: int = 0  # 3-bit (0-7)
    amplitude: int = 15  # 4-bit (0-15)
    filter_freq: int = 0  # 8-bit (0-255)
    control: bool = True  # CTL bit (True = standby/power-down)


class SSI263Synth:
    """SSI-263 speech synthesizer.

    Standalone usage:
        synth = SSI263Synth()
        synth.start()
        synth.speak_phoneme(0x01)
        synth.stop()

    Emulator integration:
        synth = SSI263Synth()
        chip = SSI263(base_port=0xC0)
        chip.set_synth(synth)  # Register writes now produce audio
    """

    def __init__(
        self,
        sample_rate: int = 22050,
        audio_enabled: bool = True,
    ):
        self.sample_rate = sample_rate
        self._audio_enabled = audio_enabled

        self.state = SSI263State()
        self._player: Optional[AudioPlayer] = None
        self._phoneme_callback: Optional[Callable[[int], None]] = None
        self._phoneme_complete_callback: Optional[Callable[[], None]] = None

        if audio_enabled:
            self._player = AudioPlayer(sample_rate=sample_rate)

    def start(self) -> None:
        """Start audio output."""
        if self._player:
            self._player.start()

    def stop(self) -> None:
        """Stop audio output."""
        if self._player:
            self._player.stop()

    # === Register interface (for emulator integration) ===

    def write_durphon(self, value: int) -> None:
        """Write to Duration/Phoneme register (reg 0).

        Bits 7-6: Duration mode (0-3)
        Bits 5-0: Phoneme ID (0-63)
        """
        self.state.duration = (value >> 6) & 0x03
        self.state.phoneme = value & 0x3F

        # If not in standby, play the phoneme
        if not self.state.control:
            self._play_current_phoneme()

    def write_inflect(self, value: int) -> None:
        """Write to Inflection register (reg 1).

        Sets bits I10:I3 of the 12-bit inflection value.
        """
        # I10:I3 (8 bits)
        self.state.inflection = (self.state.inflection & 0x007) | (value << 3)

    def write_rateinf(self, value: int) -> None:
        """Write to Rate/Inflection register (reg 2).

        Bits 7-4: Rate (0-15)
        Bit 3: I11 (MSB of inflection)
        Bits 2-0: I2:I0 (LSB of inflection)
        """
        self.state.rate = (value >> 4) & 0x0F
        i11 = (value >> 3) & 0x01
        i2_0 = value & 0x07
        self.state.inflection = (i11 << 11) | (self.state.inflection & 0x7F8) | i2_0

    def write_ctrlamp(self, value: int) -> None:
        """Write to Control/Articulation/Amplitude register (reg 3).

        Bit 7: CTL (1=standby, 0=active)
        Bits 6-4: Articulation (0-7)
        Bits 3-0: Amplitude (0-15)
        """
        old_control = self.state.control
        self.state.control = bool(value & 0x80)
        self.state.articulation = (value >> 4) & 0x07
        self.state.amplitude = value & 0x0F

        # CTL transition 1->0 wakes up and plays phoneme
        if old_control and not self.state.control:
            self._play_current_phoneme()

    def write_filter(self, value: int) -> None:
        """Write to Filter Frequency register (reg 4)."""
        self.state.filter_freq = value

    # === High-level API (for standalone use) ===

    def speak_phoneme(self, phoneme: int, blocking: bool = False) -> None:
        """Speak a single phoneme with current register settings."""
        self.state.phoneme = phoneme
        self._play_current_phoneme()

    def speak_phonemes(self, phonemes: list[int], blocking: bool = False) -> None:
        """Speak a sequence of phonemes."""
        for p in phonemes:
            self.speak_phoneme(p)

    def set_pitch(self, pitch: float) -> None:
        """Set pitch as a multiplier (1.0 = normal)."""
        # Convert to inflection value
        # pitch 1.0 -> inflection 2048
        self.state.inflection = int(2048 + (pitch - 1.0) * 4096)
        self.state.inflection = max(0, min(4095, self.state.inflection))

    def set_speed(self, speed: float) -> None:
        """Set speed as a multiplier (1.0 = normal)."""
        # Map to rate (0-15, higher = faster)
        self.state.rate = int(speed * 8)
        self.state.rate = max(0, min(15, self.state.rate))

    def set_volume(self, volume: float) -> None:
        """Set volume as 0.0-1.0."""
        self.state.amplitude = int(volume * 15)
        self.state.amplitude = max(0, min(15, self.state.amplitude))

    def is_speaking(self) -> bool:
        """Check if currently speaking."""
        if self._player:
            return self._player.is_playing()
        return False

    def wait_until_done(self) -> None:
        """Block until speech completes."""
        import time

        while self.is_speaking():
            time.sleep(0.01)

    def set_phoneme_callback(self, callback: Callable[[int], None]) -> None:
        """Set callback for when a phoneme is played."""
        self._phoneme_callback = callback

    def set_phoneme_complete_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for when phoneme completes (for IRQ generation)."""
        self._phoneme_complete_callback = callback

    # === Audio generation ===

    def get_phoneme_audio(
        self,
        phoneme: int,
        amplitude: int = 15,
        inflection: int = 2048,
        rate: int = 0,
        duration: int = 0,
        filter_freq: int = 0,
    ) -> np.ndarray:
        """Get processed audio samples for a phoneme.

        Returns float32 samples normalized to -1.0 to 1.0.

        SSI-263 phoneme mapping (from AppleWin):
        - Phoneme 0: pause (return silence)
        - Phoneme 1: missing sample, maps to phoneme 2
        - Phonemes 2-63: map to data indices 0-61 (subtract 2)
        """
        # Handle pause phoneme
        if phoneme == 0:
            # Return short silence for pause
            return np.zeros(int(self.sample_rate * 0.05), dtype=np.float32)

        # Map phoneme 1 to phoneme 2 (missing sample workaround)
        if phoneme == 1:
            phoneme = 2

        # Convert SSI-263 phoneme code to data index (subtract 2)
        data_index = phoneme - 2

        # Validate index
        if data_index < 0 or data_index >= len(PHONEME_INFO):
            # Return silence for invalid phonemes
            return np.zeros(100, dtype=np.float32)

        samples = get_phoneme_samples(data_index)

        # Apply DSP chain
        samples = apply_amplitude(samples, amplitude)
        samples = apply_filter(samples, filter_freq)
        samples = time_stretch(samples, rate, duration)
        samples = pitch_shift(samples, inflection)

        # Convert to float32 normalized
        return (samples / 32768.0).astype(np.float32)

    # === Private ===

    def _play_current_phoneme(self) -> None:
        """Play phoneme with current register state."""
        phoneme = self.state.phoneme
        # HACK: Force amplitude to 15 if it's 0 (workaround for VOLUME bug)
        if self.state.amplitude == 0:
            self.state.amplitude = 15
        print(f"[SYNTH] _play_current_phoneme: phon={phoneme}, amp={self.state.amplitude}, infl={self.state.inflection}, dur={self.state.duration}")

        # Notify callback
        if self._phoneme_callback:
            self._phoneme_callback(phoneme)

        # Generate and play audio
        if self._audio_enabled and self._player:
            samples = self.get_phoneme_audio(
                phoneme=phoneme,
                amplitude=self.state.amplitude,
                inflection=self.state.inflection,
                rate=self.state.rate,
                duration=self.state.duration,
                filter_freq=self.state.filter_freq,
            )
            self._player.play(samples)
