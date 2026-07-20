"""Approximate SSI-263 audio using the AppleWin fixed PCM captures.

The captures provide one waveform for each available phoneme at one unknown
register setting.  This backend therefore honors phoneme and amplitude but
does not pretend to synthesize undocumented articulation, inflection, rate,
duration, or filter-frequency effects.
"""

from collections.abc import Callable

import numpy as np

from ..ssi263 import SSI263State
from .phonemes import PHONEME_INFO, SAMPLE_RATE, get_phoneme_samples
from .player import AudioPlayer


class SSI263PCMSynth:
    """Play fixed SSI-263 phoneme captures for decoded chip events.

    The hardware-facing :class:`qns.ssi263.SSI263` owns register decoding,
    phoneme completion timing, and interrupts.  This backend only supplies
    approximate audio for the events it receives.
    """

    def __init__(self, audio_enabled: bool = True) -> None:
        self.sample_rate = SAMPLE_RATE
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

    def set_phoneme_callback(self, callback: Callable[[int], None]) -> None:
        """Set a callback invoked whenever this backend emits a phoneme."""
        self._phoneme_callback = callback

    def play(self, state: SSI263State) -> None:
        """Produce audio for one decoded phoneme event from the chip."""
        self._emit(state.phoneme, state.amplitude)

    def speak_phoneme(self, phoneme: int, amplitude: int = 15) -> None:
        """Play a phoneme directly, outside emulator integration."""
        self._emit(phoneme & 0x3F, amplitude)

    def is_speaking(self) -> bool:
        """Return whether the host audio player still has queued samples."""
        return self._player is not None and self._player.is_playing()

    def get_phoneme_audio(self, phoneme: int, amplitude: int = 15) -> np.ndarray:
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

        gain = max(0, min(15, amplitude)) / 15.0
        samples = get_phoneme_samples(data_index).astype(np.float32)
        return samples * (gain / 32768.0)

    def _emit(self, phoneme: int, amplitude: int) -> None:
        if self._phoneme_callback is not None:
            self._phoneme_callback(phoneme)
        if self._player is not None:
            self._player.play(self.get_phoneme_audio(phoneme, amplitude))
