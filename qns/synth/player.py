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

    def play(self, samples: np.ndarray) -> None:
        """Queue samples for playback.

        Args:
            samples: Audio samples (float32, -1.0 to 1.0)
        """
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)

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
            # Fill buffer from queue if needed
            while len(self._buffer) < frames:
                try:
                    chunk = self._queue.get_nowait()
                    self._buffer = np.concatenate([self._buffer, chunk])
                except queue.Empty:
                    break

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
