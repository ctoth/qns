from __future__ import annotations

import gc
import threading
import tracemalloc
from types import SimpleNamespace

import numpy as np
import pytest

from qns.synth.player import AudioPlayer


@pytest.fixture
def fake_output_stream(monkeypatch):
    """Keep player tests independent of host PortAudio availability."""
    from qns.synth import player as player_module

    streams = []

    class OutputStream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            self.started = False
            self.stopped = False
            self.closed = False
            streams.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def close(self):
            self.closed = True

    monkeypatch.setattr(player_module, "_open_output_stream", OutputStream)
    return streams


def _output(frames: int) -> np.ndarray:
    return np.empty((frames, 1), dtype=np.float32)


def test_callback_uses_one_preallocated_bounded_ring_without_python_growth(
    monkeypatch,
) -> None:
    player = AudioPlayer(
        sample_rate=1_000,
        blocksize=4,
        prime_ms=0,
        max_buffer_ms=8,
        overflow_policy="drop_newest",
    )
    ring = player._ring
    output = _output(4)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("callback attempted a growing NumPy operation")

    monkeypatch.setattr(np, "concatenate", forbidden)
    monkeypatch.setattr(np, "array", forbidden)
    monkeypatch.setattr(np, "empty", forbidden)
    monkeypatch.setattr(np, "zeros", forbidden)

    # Warm interpreter/NumPy call-site caches before measuring retained
    # allocations attributed to the player's callback implementation.
    player.play(np.arange(8, dtype=np.float32))
    player._audio_callback(output, 4, None, None)
    player._audio_callback(output, 4, None, None)
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for _ in range(1_000):
        player._audio_callback(output, 4, None, None)
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    retained = sum(
        statistic.size_diff
        for statistic in after.compare_to(before, "filename")
        if statistic.size_diff > 0
        and statistic.traceback[0].filename.endswith("qns/synth/player.py")
    )
    assert retained == 0
    assert player._ring is ring
    assert len(ring) == player._capacity_frames == 8


def test_ring_wraparound_preserves_sample_order() -> None:
    player = AudioPlayer(
        sample_rate=1_000,
        blocksize=4,
        prime_ms=0,
        max_buffer_ms=8,
        overflow_policy="drop_newest",
    )
    output = _output(4)

    player.play(np.arange(6, dtype=np.float32))
    player._audio_callback(output, 4, None, None)
    np.testing.assert_array_equal(output[:, 0], [0, 1, 2, 3])

    player.play(np.arange(6, 12, dtype=np.float32))
    player._audio_callback(output, 4, None, None)
    np.testing.assert_array_equal(output[:, 0], [4, 5, 6, 7])
    player._audio_callback(output, 4, None, None)
    np.testing.assert_array_equal(output[:, 0], [8, 9, 10, 11])


def test_no_realtime_drop_newest_policy_caps_latency_and_reports_drops() -> None:
    player = AudioPlayer(
        sample_rate=1_000,
        blocksize=4,
        prime_ms=0,
        max_buffer_ms=4,
        overflow_policy="drop_newest",
    )
    output = _output(4)

    accepted = player.play(np.arange(6, dtype=np.float32))

    assert accepted == 4
    assert player._queued_frames == player._capacity_frames == 4
    assert player.dropped_frames == 2
    player._audio_callback(output, 4, None, None)
    np.testing.assert_array_equal(output[:, 0], [0, 1, 2, 3])


def test_stop_releases_blocked_producer_and_resets_restart_state(
    fake_output_stream,
) -> None:
    player = AudioPlayer(
        sample_rate=1_000,
        blocksize=4,
        prime_ms=4,
        max_buffer_ms=4,
        overflow_policy="block",
    )
    player.start()
    assert player.play(np.ones(4, dtype=np.float32)) == 4

    wait_entered = threading.Event()
    original_wait = player._space_available.wait

    def observed_wait() -> bool:
        wait_entered.set()
        return original_wait()

    player._space_available.wait = observed_wait
    result: list[int] = []
    producer = threading.Thread(
        target=lambda: result.append(player.play(np.ones(2, dtype=np.float32))),
    )
    producer.start()
    assert wait_entered.wait(timeout=1)

    player.stop()
    producer.join(timeout=1)

    assert not producer.is_alive()
    assert result == [0]
    assert player._queued_frames == 0
    assert player._read_index == player._write_index == 0
    assert not player.is_playing()

    player.start()
    assert player._priming
    assert player._primed_waits == 0
    assert player.play(np.ones(4, dtype=np.float32)) == 4
    player._audio_callback(_output(4), 4, None, None)
    assert player._queued_frames == 0
    player.stop()


def test_callback_log_status_is_formatted_only_on_logger_thread(
    fake_output_stream,
    tmp_path,
) -> None:
    callback_thread = threading.get_ident()
    formatted_on: list[int] = []

    class Status:
        def __bool__(self) -> bool:
            return True

        def __str__(self) -> str:
            formatted_on.append(threading.get_ident())
            return "underflow"

    player = AudioPlayer(
        sample_rate=1_000,
        blocksize=4,
        prime_ms=0,
        max_buffer_ms=4,
        log_path=tmp_path / "audio.csv",
    )
    player.start()
    player.play(np.ones(4, dtype=np.float32))
    player._audio_callback(
        _output(4),
        4,
        SimpleNamespace(currentTime=1.5, outputBufferDacTime=1.6),
        Status(),
    )
    player.stop()

    assert formatted_on
    assert callback_thread not in formatted_on


def test_concurrent_producer_callback_stress_preserves_ring_invariants() -> None:
    player = AudioPlayer(
        sample_rate=1_000,
        blocksize=16,
        prime_ms=0,
        max_buffer_ms=64,
        overflow_policy="drop_newest",
    )
    samples = np.arange(23, dtype=np.float32)
    output = _output(16)
    start = threading.Barrier(3)
    errors: list[BaseException] = []

    def produce() -> None:
        try:
            start.wait()
            for _ in range(5_000):
                player.play(samples)
        except BaseException as error:
            errors.append(error)

    def consume() -> None:
        try:
            start.wait()
            for _ in range(7_500):
                player._audio_callback(output, 16, None, None)
        except BaseException as error:
            errors.append(error)

    producer = threading.Thread(target=produce)
    callback = threading.Thread(target=consume)
    producer.start()
    callback.start()
    start.wait()
    producer.join(timeout=5)
    callback.join(timeout=5)

    assert not producer.is_alive()
    assert not callback.is_alive()
    assert errors == []
    assert 0 <= player._queued_frames <= player._capacity_frames
    assert 0 <= player._read_index < player._capacity_frames
    assert 0 <= player._write_index < player._capacity_frames


def test_bns_passes_realtime_overflow_policy_to_every_audio_backend() -> None:
    from qns.bns import BNS, SYNTH_BACKENDS

    for backend in SYNTH_BACKENDS:
        realtime = BNS(audio=True, synth_backend=backend, realtime=True)
        offline = BNS(audio=True, synth_backend=backend, realtime=False)

        assert realtime.synth._player._overflow_policy == "block"
        assert offline.synth._player._overflow_policy == "drop_newest"
