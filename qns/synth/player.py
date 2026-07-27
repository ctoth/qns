"""Audio Player using sounddevice.

Provides real-time audio output for the SSI-263 synthesizer.
"""

import queue
import threading

import numpy as np
import sounddevice as sd


class AudioPlayer:
    """Real-time audio player using sounddevice."""

    def __init__(
        self,
        sample_rate: int = 22050,
        channels: int = 1,
        blocksize: int = 2048,
        prime_ms: int = 250,
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
        self._stream: sd.OutputStream | None = None
        self._buffer: np.ndarray = np.array([], dtype=np.float32)
        self._lock = threading.Lock()
        self._playing = False
        self._timeline_origin_cycle: int | None = None
        self._timeline_origin_frame = 0
        self._timeline_clock: int | None = None
        self._timeline_end_frame = 0
        self._timeline_playhead = 0

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
        # An utterance shorter than the reservoir would otherwise never
        # start, so give up waiting after this many starved callbacks.
        self._max_primed_waits = max(1, int(sample_rate * 0.4 / blocksize))

    def start(self) -> None:
        """Start the audio stream."""
        if self._stream is not None:
            return

        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            blocksize=self.blocksize,
            dtype=np.float32,
            latency="high",
            callback=self._audio_callback,
        )
        self._stream.start()

    def stop(self) -> None:
        """Stop the audio stream."""
        if self._stream is None:
            return

        self._stream.stop()
        self._stream.close()
        self._stream = None

        # Clear queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        with self._lock:
            self._buffer = np.array([], dtype=np.float32)
            self._playing = False
            self._priming = True
            self._primed_waits = 0
            self._timeline_origin_cycle = None
            self._timeline_origin_frame = 0
            self._timeline_clock = None
            self._timeline_end_frame = 0
            self._timeline_playhead = 0

    def play(
        self,
        samples: np.ndarray,
        *,
        cycle: int | None = None,
        clock: int | None = None,
    ) -> None:
        """Queue samples for playback.

        Args:
            samples: Audio samples (float32, -1.0 to 1.0)
            cycle: Emulated cycle at which these samples begin.
            clock: Emulated cycles per second.
        """
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)

        if cycle is None or clock is None:
            self._queue.put(samples)
            return

        with self._lock:
            if (
                self._timeline_origin_cycle is None
                or self._timeline_clock != clock
                or cycle < self._timeline_origin_cycle
            ):
                self._timeline_origin_cycle = cycle
                self._timeline_origin_frame = self._timeline_playhead
                self._timeline_clock = clock
                self._timeline_end_frame = self._timeline_playhead

            elapsed_cycles = cycle - self._timeline_origin_cycle
            desired_start = (
                self._timeline_origin_frame
                + round(elapsed_cycles * self.sample_rate / clock)
            )
            occupied_until = max(
                self._timeline_end_frame,
                self._timeline_playhead,
            )
            gap = max(0, desired_start - occupied_until)
            if gap:
                samples = np.concatenate(
                    [np.zeros(gap, dtype=np.float32), samples]
                )
            self._timeline_end_frame = occupied_until + len(samples)
            self._queue.put(samples)

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
                elif self._primed_waits < self._max_primed_waits:
                    # Still filling.  Hold silence rather than start and
                    # stutter - but not forever, or an utterance shorter
                    # than the reservoir would never play at all.
                    self._primed_waits += 1
                    outdata[:, 0] = 0
                    return
                else:
                    self._priming = False
                    self._primed_waits = 0

            # Output samples
            if len(self._buffer) >= frames:
                outdata[:, 0] = self._buffer[:frames]
                self._buffer = self._buffer[frames:]
                self._playing = True
            else:
                # Not enough samples - output what we have, pad with silence
                available = len(self._buffer)
                if available > 0:
                    outdata[:available, 0] = self._buffer
                    self._buffer = np.array([], dtype=np.float32)
                outdata[available:, 0] = 0
                self._playing = False
                # Ran dry.  Rebuild the reservoir before resuming, so one
                # late phoneme does not leave us on the same knife-edge
                # for every phoneme after it.
                self._priming = True
                self._primed_waits = 0
            self._timeline_playhead += frames
