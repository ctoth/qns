"""Audio Player using sounddevice.

Provides real-time audio output for the SSI-263 synthesizer.
"""

from __future__ import annotations

import csv
import queue
import threading
import time
from pathlib import Path
from typing import Any, Literal, TextIO

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
    """Real-time audio player using a bounded, preallocated mono ring.

    ``overflow_policy="block"`` preserves every frame by holding the producer
    until PortAudio makes room. ``"drop_newest"`` never blocks: it accepts the
    prefix that fits and drops the newest overflow frames. The CLI uses the
    blocking policy in real time and the bounded drop-newest policy for
    ``--no-realtime``, where emulation can outrun the sound device indefinitely.
    """

    def __init__(
        self,
        sample_rate: int = 22050,
        channels: int = 1,
        blocksize: int = 2048,
        prime_ms: int = 250,
        max_buffer_ms: int = 1000,
        overflow_policy: Literal["block", "drop_newest"] = "drop_newest",
        log_path: Path | str | None = None,
    ):
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if channels != 1:
            raise ValueError("QNS audio output is mono")
        if blocksize <= 0:
            raise ValueError("blocksize must be positive")
        if prime_ms < 0:
            raise ValueError("prime_ms cannot be negative")
        if max_buffer_ms <= 0:
            raise ValueError("max_buffer_ms must be positive")
        if overflow_policy not in ("block", "drop_newest"):
            raise ValueError(f"unsupported overflow policy: {overflow_policy}")

        # 512 frames is 23 ms of headroom, which PulseAudio under WSL does
        # not reliably meet while the emulator thread holds the GIL between
        # sleeps; 2048 gives 93 ms.  The ring itself never starves the
        # callback - it pads with silence - so underruns here are host
        # scheduling jitter, not missing audio.
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize

        self._stream: Any | None = None
        self._lock = threading.Lock()
        self._space_available = threading.Condition(self._lock)
        self._playing = False
        self._queued_frames = 0
        self._read_index = 0
        self._write_index = 0
        self._dropped_frames = 0
        self._accepting = True
        self._generation = 0
        self._overflow_policy = overflow_policy
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
        self._capacity_frames = max(
            1,
            blocksize,
            self._prime_frames,
            int(sample_rate * max_buffer_ms / 1000),
        )
        self._ring = np.empty(self._capacity_frames, dtype=np.float32)

    def start(self) -> None:
        """Start the audio stream."""
        if self._stream is not None:
            return

        with self._space_available:
            if not self._accepting:
                self._reset_ring_locked()
                self._accepting = True

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
        """Stop playback and atomically close/reset the producer generation."""
        with self._space_available:
            queued_frames = self._queued_frames
            priming = self._priming
            self._accepting = False
            self._generation += 1
            self._reset_ring_locked()
            self._space_available.notify_all()

        stream = self._stream
        if stream is not None:
            stream.stop()
            stream.close()
            self._stream = None

        self._log_event(
            "stream_stop",
            queued_frames=queued_frames,
            buffered_frames=queued_frames,
            priming=priming,
        )
        self._finish_log()

    def play(self, samples: np.ndarray) -> int:
        """Queue samples for playback and return the accepted frame count.

        Args:
            samples: Audio samples (float32, -1.0 to 1.0)

        With ``drop_newest``, only the prefix that fits is accepted and the
        remaining newest frames are counted by :attr:`dropped_frames`.
        ``block`` waits for callback consumption and aborts if :meth:`stop`
        closes the current producer generation.
        """
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)

        accepted = 0
        dropped = 0
        with self._space_available:
            generation = self._generation
            while accepted < len(samples) and self._accepting and generation == self._generation:
                available = self._capacity_frames - self._queued_frames
                if available == 0:
                    if self._overflow_policy == "drop_newest":
                        dropped = len(samples) - accepted
                        self._dropped_frames += dropped
                        break
                    self._space_available.wait()
                    continue

                count = min(available, len(samples) - accepted)
                first = min(count, self._capacity_frames - self._write_index)
                self._ring[self._write_index : self._write_index + first] = samples[
                    accepted : accepted + first
                ]
                second = count - first
                if second:
                    self._ring[0:second] = samples[accepted + first : accepted + count]
                self._write_index = (self._write_index + count) % self._capacity_frames
                self._queued_frames += count
                accepted += count

            if accepted < len(samples) and (not self._accepting or generation != self._generation):
                dropped = len(samples) - accepted

            if accepted and len(samples) > 1:
                self._substantive_audio_queued = True
            queued_frames = self._queued_frames
            priming = self._priming

        self._log_event(
            "enqueue",
            frames=accepted,
            silence_frames=dropped,
            queued_frames=queued_frames,
            buffered_frames=queued_frames,
            priming=priming,
        )
        return accepted

    def realtime_lead_seconds(self) -> float:
        """Emulator lead needed to restore the active audio reservoir."""
        with self._lock:
            if self._queued_frames <= 0:
                # Once the reservoir is empty, audio is genuinely behind.
                # Granting a fresh prime-sized lead here makes emulated time
                # jump forward during a pause instead of recovering from the
                # underrun at wall-clock pace.
                return 0.0
            missing = max(0, self._prime_frames - self._queued_frames)
            return missing / self.sample_rate

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        with self._lock:
            return self._playing or self._queued_frames > 0

    @property
    def dropped_frames(self) -> int:
        """Number of newest frames discarded by this player generation."""
        with self._lock:
            return self._dropped_frames

    def _audio_callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time_info,
        status,
    ) -> None:
        """Fill one PortAudio block with at most two bounded ring copies."""
        outdata.fill(0)
        with self._space_available:
            if self._priming:
                if self._queued_frames >= self._prime_frames:
                    self._priming = False
                    self._primed_waits = 0
                    audio_frames = min(frames, self._queued_frames)
                elif (
                    not self._substantive_audio_queued
                    or self._primed_waits < self._max_primed_waits
                ):
                    # Still filling.  Hold silence rather than start and
                    # stutter - but not forever, or an utterance shorter
                    # than the reservoir would never play at all.
                    if self._substantive_audio_queued:
                        self._primed_waits += 1
                    audio_frames = 0
                else:
                    self._priming = False
                    self._primed_waits = 0
                    audio_frames = min(frames, self._queued_frames)
            else:
                audio_frames = min(frames, self._queued_frames)

            if audio_frames:
                first = min(audio_frames, self._capacity_frames - self._read_index)
                outdata[:first, 0] = self._ring[self._read_index : self._read_index + first]
                second = audio_frames - first
                if second:
                    outdata[first:audio_frames, 0] = self._ring[0:second]
                self._read_index = (self._read_index + audio_frames) % self._capacity_frames
                self._queued_frames -= audio_frames
                self._space_available.notify_all()

            self._playing = audio_frames == frames
            queued_frames = self._queued_frames
            priming = self._priming

        # Logging is deliberately outside the callback state lock.  This
        # queues raw values only; CSV/string formatting belongs to the writer.
        self._log_event(
            "callback",
            frames=frames,
            audio_frames=audio_frames,
            silence_frames=frames - audio_frames,
            queued_frames=queued_frames,
            buffered_frames=queued_frames,
            priming=priming,
            time_info=time_info,
            status=status,
        )

    def _reset_ring_locked(self) -> None:
        self._playing = False
        self._queued_frames = 0
        self._read_index = 0
        self._write_index = 0
        self._dropped_frames = 0
        self._priming = True
        self._primed_waits = 0
        self._substantive_audio_queued = False

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
                writer.writerow(self._format_log_record(record))
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

        self._log_queue.put(
            (
                time.perf_counter() - self._log_start,
                event,
                frames,
                audio_frames,
                silence_frames,
                queued_frames,
                buffered_frames,
                priming,
                getattr(time_info, "currentTime", None),
                getattr(time_info, "outputBufferDacTime", None),
                status,
            )
        )

    def _format_log_record(self, record: tuple[object, ...]) -> tuple[object, ...]:
        (
            wall_seconds,
            event,
            frames,
            audio_frames,
            silence_frames,
            queued_frames,
            buffered_frames,
            priming,
            current_time,
            output_dac_time,
            status,
        ) = record
        audio_end_time = (
            output_dac_time + audio_frames / self.sample_rate
            if isinstance(output_dac_time, (int, float)) and isinstance(audio_frames, int)
            else None
        )
        return (
            f"{wall_seconds:.9f}",
            event,
            frames,
            audio_frames,
            silence_frames,
            queued_frames,
            buffered_frames,
            priming,
            f"{current_time:.9f}" if isinstance(current_time, (int, float)) else "",
            f"{output_dac_time:.9f}" if isinstance(output_dac_time, (int, float)) else "",
            f"{audio_end_time:.9f}" if audio_end_time is not None else "",
            str(status) if status else "",
        )
