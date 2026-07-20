"""SSI-263 formant-synthesis audio backend.

Synthesizes phonemes with the SC-01 formant model ported from MAME,
translating SSI-263 (SC-02) phoneme codes to SC-01 codes.
See docs/sc02-phoneme-mapping.md for the mapping provenance.
"""

import time
from collections.abc import Callable

import numpy as np

from ..ssi263 import SSI263State
from .formant import FormantSynth
from .player import AudioPlayer
from .sc02_to_sc01 import SC02_TO_SC01


def _sc01_inflection(inflection: int) -> int:
    """Map the 12-bit inflection (2048 = neutral) to SC-01's 2-bit pitch."""
    if inflection > 3072:
        return 3
    if inflection > 2560:
        return 2
    if inflection > 1536:
        return 1
    return 0


class SSI263Synth:
    """SSI-263 speech backend using formant synthesis.

    Standalone usage:
        synth = SSI263Synth()
        synth.start()
        synth.speak_phoneme(0x01)
        synth.stop()

    Emulator integration:
        chip = SSI263(base_port=0xC0)
        chip.set_synth(SSI263Synth())  # Register writes now produce audio
    """

    def __init__(
        self,
        sample_rate: int = 22050,
        audio_enabled: bool = True,
    ):
        self.sample_rate = sample_rate
        # Standalone-mode settings, used when speaking outside the emulator
        self.amplitude = 15
        self.inflection = 2048

        self._formant = FormantSynth(sample_rate=sample_rate)
        self._player = AudioPlayer(sample_rate=sample_rate) if audio_enabled else None
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
        self._emit(state.phoneme, state.amplitude, state.inflection)

    def speak_phoneme(self, phoneme: int) -> None:
        """Speak a single phoneme with the standalone settings."""
        self._emit(phoneme & 0x3F, self.amplitude, self.inflection)

    def speak_phonemes(self, phonemes: list[int]) -> None:
        """Speak a sequence of phonemes with the standalone settings."""
        for phoneme in phonemes:
            self.speak_phoneme(phoneme)

    def set_pitch(self, pitch: float) -> None:
        """Set the standalone pitch as a multiplier (1.0 = normal)."""
        inflection = int(2048 + (pitch - 1.0) * 4096)
        self.inflection = max(0, min(4095, inflection))

    def set_volume(self, volume: float) -> None:
        """Set the standalone volume as 0.0-1.0."""
        self.amplitude = max(0, min(15, int(volume * 15)))

    def is_speaking(self) -> bool:
        """Return whether the host audio player still has queued samples."""
        return self._player is not None and self._player.is_playing()

    def wait_until_done(self) -> None:
        """Block until speech completes."""
        while self.is_speaking():
            time.sleep(0.01)

    def get_phoneme_audio(
        self,
        phoneme: int,
        amplitude: int = 15,
        inflection: int = 2048,
    ) -> np.ndarray:
        """Return formant-synthesized float32 samples for a phoneme.

        SSI-263 phoneme codes are translated to SC-01 codes and rendered
        with the SC-01 formant model.
        """
        samples = self._formant.synthesize_phoneme(
            phoneme=SC02_TO_SC01[phoneme & 0x3F],
            inflection=_sc01_inflection(inflection),
        )
        gain = max(0, min(15, amplitude)) / 15.0
        if gain < 1.0:
            samples = samples * gain
        return samples

    def _emit(self, phoneme: int, amplitude: int, inflection: int) -> None:
        if self._phoneme_callback is not None:
            self._phoneme_callback(phoneme)
        if self._player is not None:
            self._player.play(
                self.get_phoneme_audio(phoneme, amplitude, inflection)
            )
