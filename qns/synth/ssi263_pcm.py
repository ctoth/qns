"""Approximate SSI-263 audio using the AppleWin fixed PCM captures."""

from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..ssi263 import SSI263State, playback_length_samples
from .phonemes import PHONEME_INFO, SAMPLE_RATE, get_phoneme_samples
from .player import AudioPlayer
from .timing import fit_audio_to_elapsed

_NORMAL_INFLECTION = 3072
_NORMAL_INFLECTION_TARGET = 16


class SSI263PCMSynth:
    """Play fixed SSI-263 phoneme captures for decoded chip events.

    The hardware-facing :class:`qns.ssi263.SSI263` owns register decoding,
    phoneme completion timing, and interrupts.  This backend only supplies
    approximate audio for the events it receives.
    """

    def __init__(
        self,
        audio_enabled: bool = True,
        audio_log: Path | str | None = None,
        realtime: bool = False,
    ) -> None:
        self.sample_rate = SAMPLE_RATE
        self._player = (
            AudioPlayer(
                sample_rate=SAMPLE_RATE,
                overflow_policy="block" if realtime else "drop_newest",
                log_path=audio_log,
            )
            if audio_enabled
            else None
        )
        self._phoneme_callback: Callable[[int], None] | None = None
        self._current_inflection_level = float(_NORMAL_INFLECTION_TARGET)
        self._inflection_target = _NORMAL_INFLECTION_TARGET
        self._inflection_step = 0.0
        self._inflection_frames_remaining = 0
        self._last_inflection_setting: int | None = None
        self._pending_audio: np.ndarray | None = None

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
        """Stage audio for one decoded phoneme event from the chip."""
        if self._phoneme_callback is not None:
            self._phoneme_callback(state.phoneme)
        self._pending_audio = self.get_phoneme_audio(
            state.phoneme,
            state.amplitude,
            state.playback_duration,
            state.rate,
            state.inflection,
            state.transitioned_inflection,
        )

    def end_phoneme(self, elapsed_samples: int) -> None:
        """Queue only the audio time that the chip says elapsed."""
        if self._pending_audio is None:
            return
        audio = fit_audio_to_elapsed(self._pending_audio, elapsed_samples)
        self._pending_audio = None
        if self._player is not None:
            self._player.play(audio)

    def speak_phoneme(self, phoneme: int, amplitude: int = 15) -> None:
        """Play a phoneme directly, outside emulator integration."""
        self._emit(phoneme & 0x3F, amplitude)

    def is_speaking(self) -> bool:
        """Return whether the host audio player still has queued samples."""
        return self._player is not None and self._player.is_playing()

    def realtime_lead_seconds(self) -> float:
        """Return bounded emulator run-ahead needed to keep audio continuous."""
        if self._player is None:
            return 0.0
        return self._player.realtime_lead_seconds()

    @staticmethod
    def _apply_duration(samples: np.ndarray, duration: int) -> np.ndarray:
        """Consume a capture at the speed the duration mode selects.

        The captures are one fixed recording per phoneme, and the SSI-263's
        duration mode decides how fast that recording is played out.
        AppleWin's SSI263.cpp does this by averaging groups of input samples
        per output sample (and, in mode 1, discarding every fourth):

            mode 0  1:1                          longest
            mode 1  drop every 4th sample        3/4 length
            mode 2  average 2 samples per output 1/2 length
            mode 3  average 4 samples per output 1/4 length

        Ignoring this plays every phoneme at its slowest length, which runs
        each capture's decay tail out into the next phoneme.
        """
        if duration <= 0 or len(samples) == 0:
            return samples
        if duration == 1:
            keep = np.arange(len(samples)) % 4 != 3
            return samples[keep]

        group = 2 if duration == 2 else 4
        usable = (len(samples) // group) * group
        if usable == 0:
            return samples
        return samples[:usable].reshape(-1, group).mean(axis=1)

    @staticmethod
    def _apply_rate(samples: np.ndarray, target_length: int) -> np.ndarray:
        """Change speaking time without resampling the capture's pitch.

        Faster rates cut the capture short, as the chip does when it reaches
        the next phoneme sooner.  Slower rates repeat a pitch-synchronous
        section from the steady middle instead of stretching every sample,
        which would transpose the voice.
        """
        if target_length <= len(samples):
            return samples[:target_length]

        middle = samples[len(samples) // 4 : 3 * len(samples) // 4]
        if len(middle) < 8:
            return np.pad(samples, (0, target_length - len(samples)))

        centered = middle - middle.mean()
        correlation = np.correlate(centered, centered, "full")[len(middle) - 1 :]
        low = int(SAMPLE_RATE / 400)
        high = min(int(SAMPLE_RATE / 60), len(correlation) - 1)
        if high <= low or correlation[0] <= 0:
            return np.resize(samples, target_length)

        period = low + int(np.argmax(correlation[low:high]))
        strength = float(correlation[period] / correlation[0])
        if strength < 0.35:
            return np.resize(samples, target_length)

        onset_end = max(period, (len(samples) // 4 // period) * period)
        loop_periods = max(1, min(4, (len(samples) // 2) // period))
        loop = samples[onset_end : onset_end + period * loop_periods]
        if len(loop) == 0:
            return np.resize(samples, target_length)

        repeats = (target_length - onset_end + len(loop) - 1) // len(loop)
        return np.concatenate([samples[:onset_end], np.tile(loop, repeats)])[:target_length]

    @staticmethod
    def _periodicity(samples: np.ndarray) -> tuple[int, float]:
        """Return the capture's glottal period and normalized strength."""
        middle = samples[len(samples) // 4 : 3 * len(samples) // 4]
        if len(middle) < 8:
            return 0, 0.0

        centered = middle - middle.mean()
        correlation = np.correlate(centered, centered, "full")[len(middle) - 1 :]
        low = int(SAMPLE_RATE / 400)
        high = min(int(SAMPLE_RATE / 60), len(correlation) - 1)
        if high <= low or correlation[0] <= 0:
            return 0, 0.0

        period = low + int(np.argmax(correlation[low:high]))
        return period, float(correlation[period] / correlation[0])

    @classmethod
    def _pitch_shift_psola(
        cls,
        samples: np.ndarray,
        ratio: float | np.ndarray,
    ) -> np.ndarray:
        """Change glottal pulse spacing without resampling waveform grains."""
        ratios = np.asarray(ratio, dtype=np.float64).reshape(-1)
        if len(samples) < 8 or len(ratios) == 0 or np.all(np.abs(ratios - 1.0) < 1e-9):
            return samples

        period, strength = cls._periodicity(samples)
        if period <= 0 or strength < 0.35:
            return samples

        ratios = np.clip(ratios, 0.5, 2.0)
        anchor_span = min(period, len(samples))
        anchor = int(np.argmax(np.abs(samples[:anchor_span])))
        analysis_marks = np.arange(anchor, len(samples), period)
        if len(analysis_marks) < 2:
            return samples

        synthesis_marks: list[float] = []
        synthesis_mark = float(anchor)
        while synthesis_mark < len(samples) + period:
            synthesis_marks.append(synthesis_mark)
            ratio_index = min(
                int(synthesis_mark * len(ratios) / len(samples)),
                len(ratios) - 1,
            )
            synthesis_mark += period / ratios[ratio_index]

        radius = period
        window = np.hanning(radius * 2 + 1)
        padded = np.pad(samples.astype(np.float64), (radius, radius))
        output = np.zeros(len(samples), dtype=np.float64)
        weight = np.zeros(len(samples), dtype=np.float64)

        for synthesis_mark in synthesis_marks:
            center = int(round(synthesis_mark))
            if center - radius >= len(samples):
                break

            source_index = int(np.argmin(np.abs(analysis_marks - synthesis_mark)))
            source_center = int(analysis_marks[source_index]) + radius
            grain = padded[source_center - radius : source_center + radius + 1]

            output_start = center - radius
            output_stop = center + radius + 1
            source_start = max(0, -output_start)
            source_stop = len(grain) - max(0, output_stop - len(samples))
            destination_start = max(0, output_start)
            destination_stop = min(len(samples), output_stop)
            if destination_stop <= destination_start:
                continue

            grain_window = window[source_start:source_stop]
            output[destination_start:destination_stop] += (
                grain[source_start:source_stop] * grain_window
            )
            weight[destination_start:destination_stop] += grain_window

        covered = weight > 1e-8
        output[covered] /= weight[covered]
        output[~covered] = samples[~covered]
        return output.astype(np.float32)

    def _transition_levels(
        self,
        inflection: int,
        frame_count: int,
    ) -> np.ndarray:
        """Advance the SSI-263 transitioned-inflection target by frames."""
        setting = max(0, min(4095, inflection))
        if setting != self._last_inflection_setting:
            self._last_inflection_setting = setting
            self._inflection_target = (setting >> 6) & 0x1F
            transition_frames = 8 - ((setting >> 3) & 0x07)
            self._inflection_step = (
                self._inflection_target - self._current_inflection_level
            ) / transition_frames
            self._inflection_frames_remaining = transition_frames

        levels = np.empty(frame_count, dtype=np.float64)
        for frame in range(frame_count):
            start = self._current_inflection_level
            if self._inflection_frames_remaining > 0:
                if self._inflection_frames_remaining == 1:
                    self._current_inflection_level = float(self._inflection_target)
                else:
                    self._current_inflection_level += self._inflection_step
                self._inflection_frames_remaining -= 1
            levels[frame] = (start + self._current_inflection_level) / 2.0
        return levels

    def _apply_transitioned_inflection(
        self,
        samples: np.ndarray,
        inflection: int,
        frame_count: int,
    ) -> np.ndarray:
        """Apply the chip's target transition without moving formants."""
        levels = self._transition_levels(inflection, frame_count)
        immediate = (inflection & 0x800) | (inflection & 0x007)
        effective_inflections = immediate + levels * 64.0
        ratios = (4096 - _NORMAL_INFLECTION) / (4096 - effective_inflections)
        return self._pitch_shift_psola(samples, ratios)

    def get_phoneme_audio(
        self,
        phoneme: int,
        amplitude: int = 15,
        duration: int = 0,
        rate: int = 8,
        inflection: int = _NORMAL_INFLECTION,
        transitioned_inflection: bool = False,
    ) -> np.ndarray:
        """Return the available fixed capture as normalized float32 samples.

        AppleWin provides 62 captures for SSI-263 codes 2 through 63.  Code 0
        is pause.  Code 1 has no distinct capture, so this approximate backend
        uses the adjacent code-2 capture rather than substituting another
        synthesizer architecture.
        """
        code = phoneme & 0x3F
        if code == 0:
            samples = np.zeros(
                playback_length_samples(phoneme, duration, rate),
                dtype=np.float32,
            )
        else:
            if code == 1:
                code = 2

            data_index = code - 2
            if not 0 <= data_index < len(PHONEME_INFO):
                samples = np.zeros(1, dtype=np.float32)
            else:
                samples = get_phoneme_samples(data_index).astype(np.float32)
                samples = self._apply_duration(samples, duration)
                target_length = playback_length_samples(
                    phoneme,
                    duration,
                    rate,
                )
                if target_length != len(samples):
                    samples = self._apply_rate(samples, target_length)

        if transitioned_inflection:
            samples = self._apply_transitioned_inflection(
                samples,
                inflection,
                max(1, 4 - duration),
            )

        gain = max(0, min(15, amplitude)) / 15.0
        return samples * (gain / 32768.0)

    def _emit(
        self,
        phoneme: int,
        amplitude: int,
        duration: int = 0,
        rate: int = 8,
        inflection: int = _NORMAL_INFLECTION,
        transitioned_inflection: bool = False,
    ) -> None:
        if self._phoneme_callback is not None:
            self._phoneme_callback(phoneme)
        if self._player is not None:
            self._player.play(
                self.get_phoneme_audio(
                    phoneme,
                    amplitude,
                    duration,
                    rate,
                    inflection,
                    transitioned_inflection,
                )
            )
