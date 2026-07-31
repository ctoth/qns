"""Audio Player using sounddevice.

Provides real-time audio output for the SSI-263 synthesizer.
"""

from __future__ import annotations

import csv
import queue
import threading
import time
from pathlib import Path
from typing import Any, TextIO

import numpy as np


def _open_output_stream(**kwargs: object) -> Any:
    """Create the optional PortAudio stream only when live audio starts."""
    try:
        import sounddevice as sd
    except (ImportError, OSError) as error:
        raise RuntimeError(
            "live audio requires sounddevice and a working PortAudio installation"
        ) from error
    return sd.OutputStream(**kwargs)


_LOG_HEADER = (
    "wall_seconds",
    "event",
    "frames",
    "audio_frames",
    "silence_frames",
    "queued_frames",
    "buffered_frames",
    "priming",
    "portaudio_current_time",
    "portaudio_output_dac_time",
    "portaudio_audio_end_time",
    "status",
)


class AudioPlayer:
    """Real-time audio player using sounddevice."""

    def __init__(
        self,
        sample_rate: int = 22050,
        channels: int = 1,
        blocksize: int = 2048,
        prime_ms: int = 250,
        log_path: Path | str | None = None,
    ):
        # 512 frames is 23 ms of headroom, which PulseAudio under WSL does
        # not reliably meet while the emulator thread holds the GIL between
        # sleeps; 2048 gives 93 ms.  The queue itself never starves the
        # callback - it pads with silence - so underruns here are host
        # scheduling jitter, not missing audio.
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize

        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: Any | None = None
        self._buffer: np.ndarray = np.array([], dtype=np.float32)
        self._lock = threading.Lock()
        self._playing = False
        self._queued_frames = 0
        self._log_path = Path(log_path) if log_path is not None else None
        self._log_start = 0.0
        self._log_file: TextIO | None = None
        self._log_queue: queue.SimpleQueue[tuple[object, ...] | None] | None = None
        self._log_thread: threading.Thread | None = None

        # The emulator queues each phoneme's audio just as the previous
        # one finishes: measured, a capture is the same length as the
        # interval before the next phoneme to within half a millisecond.
        # That leaves no margin at all, so any moment the emulator spends
        # below real time is immediately an audible hole - and it lands
        # after the *shortest* phoneme, which has the least audio to
        # cover the wait.  ("op" in "option" is 41 ms against 116-120 ms
        # for its neighbours, which is why the gap appears there.)
        #
        # Bank a reservoir before starting instead.  The emulator runs
        # faster than real time whenever the firmware sleeps between
        # phonemes, so it can build slack during the quiet stretches and
        # spend it during the burst of work at the start of an utterance.
        self._prime_frames = int(sample_rate * prime_ms / 1000)
        self._priming = True
        self._primed_waits = 0
        self._substantive_audio_queued = False
        # An utterance shorter than the reservoir would otherwise never
        # start, so give up waiting after this many starved callbacks once
        # more than a one-frame control sample has reached the queue.
        self._max_primed_waits = max(1, int(sample_rate * 0.4 / blocksize))

    def start(self) -> None:
        """Start the audio stream."""
        if self._stream is not None:
            return

        self._start_log()
        self._stream = _open_output_stream(
            samplerate=self.sample_rate,
            channels=self.channels,
            blocksize=self.blocksize,
            dtype=np.float32,
            latency="high",
            callback=self._audio_callback,
        )
        self._log_event("stream_start")
        self._stream.start()

    def stop(self) -> None:
        """Stop the audio stream."""
        if self._stream is None:
            return

        self._stream.stop()
        self._stream.close()
        self._stream = None

        with self._lock:
            self._log_event(
                "stream_stop",
                queued_frames=self._queued_frames,
                buffered_frames=len(self._buffer),
                priming=self._priming,
            )

        # Clear queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        with self._lock:
            self._buffer = np.array([], dtype=np.float32)
            self._playing = False
            self._queued_frames = 0
            self._priming = True
            self._primed_waits = 0
            self._substantive_audio_queued = False

        self._finish_log()

    def play(self, samples: np.ndarray) -> None:
        """Queue samples for playback.

        Args:
            samples: Audio samples (float32, -1.0 to 1.0)
        """
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)

        with self._lock:
            self._queue.put(samples)
            self._queued_frames += len(samples)
            if len(samples) > 1:
                self._substantive_audio_queued = True
            self._log_event(
                "enqueue",
                frames=len(samples),
                queued_frames=self._queued_frames,
                buffered_frames=len(self._buffer),
                priming=self._priming,
            )

    def realtime_lead_seconds(self) -> float:
        """Emulator lead needed to restore the active audio reservoir."""
        with self._lock:
            if self._queued_frames <= 0:
                return 0.0 if self._priming else self._prime_frames / self.sample_rate
            missing = max(0, self._prime_frames - self._queued_frames)
            return missing / self.sample_rate

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        with self._lock:
            return self._playing or not self._queue.empty() or len(self._buffer) > 0

    def _audio_callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time_info,
        status,
    ) -> None:
        """Sounddevice callback - fills output buffer from queue."""
        with self._lock:
            # Drain everything available, not just enough for this block:
            # the surplus is the reservoir that absorbs the emulator
            # running briefly below real time.
            target = max(frames, self._prime_frames if self._priming else 0)
            while len(self._buffer) < target:
                try:
                    chunk = self._queue.get_nowait()
                    self._buffer = np.concatenate([self._buffer, chunk])
                except queue.Empty:
                    break

            if self._priming:
                if len(self._buffer) >= self._prime_frames:
                    self._priming = False
                    self._primed_waits = 0
                elif (
                    not self._substantive_audio_queued
                    or self._primed_waits < self._max_primed_waits
                ):
                    # Still filling.  Hold silence rather than start and
                    # stutter - but not forever, or an utterance shorter
                    # than the reservoir would never play at all.
                    if self._substantive_audio_queued:
                        self._primed_waits += 1
                    outdata[:, 0] = 0
                    self._log_event(
                        "callback",
                        frames=frames,
                        audio_frames=0,
                        silence_frames=frames,
                        queued_frames=self._queued_frames,
                        buffered_frames=len(self._buffer),
                        priming=self._priming,
                        time_info=time_info,
                        status=status,
                    )
                    return
                else:
                    self._priming = False
                    self._primed_waits = 0

            # Output samples
            if len(self._buffer) >= frames:
                outdata[:, 0] = self._buffer[:frames]
                self._buffer = self._buffer[frames:]
                self._playing = True
                self._queued_frames = max(0, self._queued_frames - frames)
                audio_frames = frames
            else:
                # Not enough samples - output what we have, pad with silence
                available = len(self._buffer)
                if available > 0:
                    outdata[:available, 0] = self._buffer
                    self._buffer = np.array([], dtype=np.float32)
                outdata[available:, 0] = 0
                self._playing = False
                self._queued_frames = max(0, self._queued_frames - available)
                audio_frames = available

            self._log_event(
                "callback",
                frames=frames,
                audio_frames=audio_frames,
                silence_frames=frames - audio_frames,
                queued_frames=self._queued_frames,
                buffered_frames=len(self._buffer),
                priming=self._priming,
                time_info=time_info,
                status=status,
            )

    def _start_log(self) -> None:
        if self._log_path is None:
            return

        self._log_file = self._log_path.open("w", newline="", encoding="utf-8")
        writer = csv.writer(self._log_file)
        writer.writerow(_LOG_HEADER)
        self._log_file.flush()
        self._log_start = time.perf_counter()
        self._log_queue = queue.SimpleQueue()

        def write_records() -> None:
            assert self._log_queue is not None
            assert self._log_file is not None
            while (record := self._log_queue.get()) is not None:
                writer.writerow(record)
                self._log_file.flush()

        self._log_thread = threading.Thread(
            target=write_records,
            daemon=True,
            name="qns-audio-log",
        )
        self._log_thread.start()

    def _finish_log(self) -> None:
        if self._log_queue is None:
            return

        self._log_queue.put(None)
        if self._log_thread is not None:
            self._log_thread.join()
        if self._log_file is not None:
            self._log_file.close()
        self._log_queue = None
        self._log_thread = None
        self._log_file = None

    def _log_event(
        self,
        event: str,
        *,
        frames: int | str = "",
        audio_frames: int | str = "",
        silence_frames: int | str = "",
        queued_frames: int | str = "",
        buffered_frames: int | str = "",
        priming: bool | str = "",
        time_info=None,
        status="",
    ) -> None:
        if self._log_queue is None:
            return

        current_time = getattr(time_info, "currentTime", None)
        output_dac_time = getattr(time_info, "outputBufferDacTime", None)
        audio_end_time = (
            output_dac_time + audio_frames / self.sample_rate
            if output_dac_time is not None and isinstance(audio_frames, int)
            else None
        )
        self._log_queue.put(
            (
                f"{time.perf_counter() - self._log_start:.9f}",
                event,
                frames,
                audio_frames,
                silence_frames,
                queued_frames,
                buffered_frames,
                priming,
                f"{current_time:.9f}" if current_time is not None else "",
                f"{output_dac_time:.9f}" if output_dac_time is not None else "",
                f"{audio_end_time:.9f}" if audio_end_time is not None else "",
                str(status) if status else "",
            )
        )
