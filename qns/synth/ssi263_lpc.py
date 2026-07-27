"""SSI-263 audio by linear-prediction resynthesis of the captures.

The PCM backend has the chip's exact timbre but replays 62 isolated
recordings, so every phoneme boundary is an edge.  The formant backend is
continuous but models the SC-01, a different chip.  This backend takes the
captures' own spectrum and excitation (see :mod:`qns.synth.lpc`) and runs
them through one continuous, gliding filter, which is the combination the
other two cannot reach: the SSI-263's voice without the boundaries.
"""

from collections.abc import Callable

import numpy as np

from ..ssi263 import SSI263State, playback_length_samples
from .lpc import SAMPLE_RATE, LPCStream, warm_analysis_cache
from .player import AudioPlayer


class SSI263LPCSynth:
    """Resynthesize decoded phoneme events as one continuous voice.

    The hardware-facing :class:`qns.ssi263.SSI263` owns register decoding,
    phoneme completion timing, and interrupts.  This backend turns each
    decoded event into exactly as much audio as the chip will hold that
    phoneme for, so the stream stays paced against the emulated clock.
    """

    def __init__(self, audio_enabled: bool = True) -> None:
        self.sample_rate = SAMPLE_RATE
        self._player = AudioPlayer(sample_rate=SAMPLE_RATE) if audio_enabled else None
        self._phoneme_callback: Callable[[int], None] | None = None
        self._stream = LPCStream()
        # Analysing a capture the first time it is spoken would land inside
        # the emulator's real-time budget.  All 62 cost ~40 ms together, so
        # pay it once here instead.
        warm_analysis_cache()

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
        self._emit(
            state.phoneme,
            state.amplitude,
            state.playback_duration,
            state.rate,
            state.cycle,
            state.clock,
        )

    def speak_phoneme(self, phoneme: int, amplitude: int = 15) -> None:
        """Play a phoneme directly, outside emulator integration."""
        self._emit(phoneme & 0x3F, amplitude)

    def is_speaking(self) -> bool:
        """Return whether the host audio player still has queued samples."""
        return self._player is not None and self._player.is_playing()

    def get_phoneme_audio(
        self,
        phoneme: int,
        amplitude: int = 15,
        duration: int = 0,
        rate: int = 8,
    ) -> np.ndarray:
        """Resynthesize one phoneme, continuing on from the previous one.

        This is stateful by design: calling it advances the filter history
        and pitch phase, which is exactly what removes the boundary.
        """
        if phoneme & 0x3F == 0:
            # A pause gets no audio, however long the duration model claims.
            # The model has no capture to measure and borrows the first
            # phoneme's length, giving 30 ms; measured against the cycle
            # counts in a --trace-speech run the firmware writes a pause and
            # the next phoneme without waiting at all, so pauses really
            # elapse in ~0 ms.  Honouring the model instead put a hole
            # between every phoneme and stretched the greeting from 3.3 to
            # 5.7 seconds.  Silence arrives on its own from the emulator not
            # feeding the player while the firmware is quiet.
            #
            # Continuity is deliberately left alone.  A pause that elapses in
            # no time is a no-op between two phonemes, so resetting the
            # stream here would start every phoneme cold - and with 88 pauses
            # around the greeting's 28 phonemes, that is every phoneme,
            # which is the isolated-capture choppiness this backend exists
            # to remove.
            return np.zeros(1, dtype=np.float32)

        samples = playback_length_samples(phoneme, duration, rate)
        return self._stream.render(phoneme & 0x3F, samples, amplitude)

    def _emit(
        self,
        phoneme: int,
        amplitude: int,
        duration: int = 0,
        rate: int = 8,
        cycle: int | None = None,
        clock: int | None = None,
    ) -> None:
        if self._phoneme_callback is not None:
            self._phoneme_callback(phoneme)
        audio = self.get_phoneme_audio(phoneme, amplitude, duration, rate)
        if self._player is not None:
            self._player.play(audio, cycle=cycle, clock=clock)
