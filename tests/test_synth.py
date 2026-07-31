"""Formant synth backend and phoneme-data tests.

Run with: uv run pytest tests/test_synth.py -v
"""

import subprocess
import sys

import numpy as np
import pytest


@pytest.fixture
def fake_output_stream(monkeypatch):
    """Keep automated audio-player tests independent of host audio hardware."""
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


# =============================================================================
# Phoneme sample data
# =============================================================================


def test_phoneme_data_exists():
    """Phoneme module exports required constants."""
    from qns.synth.phonemes import SAMPLE_RATE

    assert SAMPLE_RATE == 22050


def test_phoneme_count():
    """AppleWin has 62 phonemes."""
    from qns.synth.phonemes import PHONEME_INFO

    assert len(PHONEME_INFO) == 62


def test_phoneme_data_length():
    """AppleWin has 156,566 total samples."""
    from qns.synth.phonemes import PHONEME_DATA

    assert len(PHONEME_DATA) == 156566


def test_phoneme_info_valid():
    """Each phoneme has valid offset and length within data bounds."""
    from qns.synth.phonemes import PHONEME_DATA, PHONEME_INFO

    for i, (offset, length) in enumerate(PHONEME_INFO):
        assert offset >= 0, f"Phoneme {i}: offset {offset} < 0"
        assert length > 0, f"Phoneme {i}: length {length} <= 0"
        assert offset + length <= len(PHONEME_DATA), (
            f"Phoneme {i}: offset {offset} + length {length} exceeds data size {len(PHONEME_DATA)}"
        )


def test_get_phoneme_samples():
    """get_phoneme_samples returns correct slice of data."""
    from qns.synth.phonemes import PHONEME_INFO, get_phoneme_samples

    # First phoneme
    samples = get_phoneme_samples(0)
    assert len(samples) > 0
    assert samples.dtype == np.int16
    assert len(samples) == PHONEME_INFO[0][1]

    # Last phoneme
    samples = get_phoneme_samples(61)
    assert len(samples) > 0
    assert len(samples) == PHONEME_INFO[61][1]


# =============================================================================
# Audio player
# =============================================================================


def test_audio_player_import_does_not_require_portaudio():
    """Headless hosts can use non-audio QNS features without PortAudio."""
    script = """
import builtins

real_import = builtins.__import__

def import_without_portaudio(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "sounddevice":
        raise OSError("PortAudio library not found")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = import_without_portaudio

from qns.synth.player import AudioPlayer

try:
    AudioPlayer().start()
except RuntimeError as error:
    assert "PortAudio" in str(error)
else:
    raise AssertionError("live audio unexpectedly started without PortAudio")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_audio_player_lifecycle(fake_output_stream):
    """AudioPlayer can start and stop cleanly."""
    from qns.synth.player import AudioPlayer

    player = AudioPlayer(sample_rate=22050)

    assert not player.is_playing()
    player.start()
    assert not player.is_playing()  # No samples queued yet
    player.stop()
    assert len(fake_output_stream) == 1
    assert fake_output_stream[0].started
    assert fake_output_stream[0].stopped
    assert fake_output_stream[0].closed


def test_audio_player_queues_samples(fake_output_stream):
    """AudioPlayer accepts samples for playback."""
    from qns.synth.player import AudioPlayer

    player = AudioPlayer(sample_rate=22050)
    player.start()

    samples = np.zeros(1000, dtype=np.float32)
    player.play(samples)
    # Player should accept samples (may or may not be playing yet)

    player.stop()


def test_audio_player_requests_only_the_runahead_needed_to_refill():
    from qns.synth.player import AudioPlayer

    player = AudioPlayer(sample_rate=1000, prime_ms=100)
    assert player.realtime_lead_seconds() == 0.0

    player.play(np.zeros(40, dtype=np.float32))
    assert player.realtime_lead_seconds() == pytest.approx(0.06)

    player.play(np.zeros(70, dtype=np.float32))
    assert player.realtime_lead_seconds() == 0.0


def test_audio_player_does_not_grant_prime_lead_after_underrun():
    from qns.synth.player import AudioPlayer

    player = AudioPlayer(sample_rate=1000, blocksize=100, prime_ms=250)
    player.play(np.ones(250, dtype=np.float32))
    output = np.empty((100, 1), dtype=np.float32)

    player._audio_callback(output, 100, None, None)
    player._audio_callback(output, 100, None, None)
    player._audio_callback(output, 100, None, None)

    assert player.realtime_lead_seconds() == 0.0

    player.play(np.ones(100, dtype=np.float32))
    player._audio_callback(output, 100, None, None)

    assert np.all(output == 1.0)


def test_audio_player_does_not_release_initial_priming_for_control_frames():
    from qns.synth.player import AudioPlayer

    player = AudioPlayer(sample_rate=1000, blocksize=100, prime_ms=250)
    player.play(np.ones(1, dtype=np.float32))
    output = np.empty((100, 1), dtype=np.float32)

    for _ in range(player._max_primed_waits + 2):
        player._audio_callback(output, 100, None, None)
        assert np.all(output == 0)

    assert player._priming

    player.play(np.ones(100, dtype=np.float32))
    for _ in range(player._max_primed_waits):
        player._audio_callback(output, 100, None, None)
        assert np.all(output == 0)

    player._audio_callback(output, 100, None, None)

    assert not player._priming
    assert np.all(output == 1.0)


def test_audio_player_logs_callback_delivery_and_inserted_silence(
    fake_output_stream,
    tmp_path,
):
    import csv
    from types import SimpleNamespace

    from qns.synth.player import AudioPlayer

    log_path = tmp_path / "pcm-audio.csv"
    player = AudioPlayer(
        sample_rate=1000,
        blocksize=4,
        prime_ms=0,
        log_path=log_path,
    )
    player.start()
    player.play(np.ones(3, dtype=np.float32))
    output = np.empty((4, 1), dtype=np.float32)
    player._audio_callback(
        output,
        4,
        SimpleNamespace(currentTime=1.5, outputBufferDacTime=1.6),
        "underflow",
    )
    player.stop()

    with log_path.open(newline="", encoding="utf-8") as log_file:
        rows = list(csv.DictReader(log_file))

    assert [row["event"] for row in rows] == [
        "stream_start",
        "enqueue",
        "callback",
        "stream_stop",
    ]
    callback = rows[2]
    assert callback["frames"] == "4"
    assert callback["audio_frames"] == "3"
    assert callback["silence_frames"] == "1"
    assert callback["queued_frames"] == "0"
    assert callback["portaudio_current_time"] == "1.500000000"
    assert callback["portaudio_output_dac_time"] == "1.600000000"
    assert callback["status"] == "underflow"


@pytest.mark.manual
def test_audio_player_produces_sound():
    """Manual test: verify audio output works.

    Run with: uv run pytest tests/test_synth.py -m manual -v -s
    """
    import time

    from qns.synth.player import AudioPlayer

    player = AudioPlayer(sample_rate=22050)
    player.start()

    # 440 Hz sine wave for 0.5 seconds
    duration = 0.5
    t = np.linspace(0, duration, int(22050 * duration), dtype=np.float32)
    samples = (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)

    print(f"\nPlaying 440 Hz sine wave for {duration}s...")
    player.play(samples)
    time.sleep(duration + 0.1)  # Wait for playback

    player.stop()
    print("Done.")


# =============================================================================
# Formant backend
# =============================================================================


@pytest.mark.parametrize(
    "backend_type",
    [
        pytest.param("pcm", id="pcm"),
        pytest.param("lpc", id="lpc"),
        pytest.param("formant", id="formant"),
    ],
)
@pytest.mark.parametrize("phoneme", range(64))
@pytest.mark.parametrize("duration", range(4))
@pytest.mark.parametrize("rate", [0, 4, 8, 12, 15])
def test_synth_backends_match_the_chip_duration_contract(
    backend_type,
    phoneme,
    duration,
    rate,
):
    """Every backend must fill exactly the time scheduled by the chip."""
    from qns.ssi263 import playback_length_samples
    from qns.synth import SSI263LPCSynth, SSI263PCMSynth, SSI263Synth

    backend_class = {
        "pcm": SSI263PCMSynth,
        "lpc": SSI263LPCSynth,
        "formant": SSI263Synth,
    }[backend_type]
    synth = backend_class(audio_enabled=False)

    samples = synth.get_phoneme_audio(
        phoneme,
        amplitude=15,
        duration=duration,
        rate=rate,
    )

    assert len(samples) == playback_length_samples(phoneme, duration, rate)


def test_formant_duration_conformance_preserves_rms():
    """Lengthening formant audio must not fill the extra time with silence."""
    from qns.synth import SSI263Synth

    phoneme = 0x30
    raw = np.sin(np.linspace(0.0, 20 * np.pi, 1_400)).astype(np.float32)
    synth = SSI263Synth(audio_enabled=False)
    synth._formant.synthesize_phoneme = lambda **_kwargs: raw.copy()
    conformed = synth.get_phoneme_audio(
        phoneme,
        duration=0,
        rate=8,
    )

    assert len(conformed) > len(raw)
    raw_rms = float(np.sqrt(np.mean(raw.astype(np.float64) ** 2)))
    conformed_rms = float(np.sqrt(np.mean(conformed.astype(np.float64) ** 2)))
    assert 0.8 <= conformed_rms / raw_rms <= 1.2


def test_synth_get_phoneme_audio():
    """get_phoneme_audio returns synthesized samples."""
    from qns.synth import SSI263Synth

    synth = SSI263Synth(audio_enabled=False)

    samples = synth.get_phoneme_audio(phoneme=1, amplitude=15)
    assert len(samples) > 0
    assert samples.dtype == np.float32


def test_synth_amplitude_scales_audio():
    """Amplitude scales output; zero amplitude is silent.

    The formant model is stateful across phonemes, so each amplitude is
    rendered on a fresh backend to compare like with like.
    """
    from qns.synth import SSI263Synth

    full = SSI263Synth(audio_enabled=False).get_phoneme_audio(1, amplitude=15)
    half = SSI263Synth(audio_enabled=False).get_phoneme_audio(1, amplitude=5)
    mute = SSI263Synth(audio_enabled=False).get_phoneme_audio(1, amplitude=0)

    assert np.any(full)
    np.testing.assert_allclose(half, full * (5 / 15))
    assert not np.any(mute)


def test_synth_standalone_speak_uses_settings():
    """speak_phoneme emits the callback with the standalone settings."""
    from qns.synth import SSI263Synth

    synth = SSI263Synth(audio_enabled=False)
    played = []
    synth.set_phoneme_callback(played.append)

    synth.set_volume(1.0)
    synth.set_pitch(1.0)
    synth.speak_phonemes([0x01, 0x06])

    assert played == [0x01, 0x06]
    assert synth.amplitude == 15
    assert synth.inflection == 2048


# =============================================================================
# Integration with the SSI-263 chip
# =============================================================================


def test_ssi263_chip_drives_formant_backend():
    """Chip register writes produce decoded phoneme events on the backend."""
    from qns.ssi263 import SSI263
    from qns.synth import SSI263Synth

    chip = SSI263(base_port=0xC0)
    synth = SSI263Synth(audio_enabled=False)
    chip.set_synth(synth)

    phonemes = []
    synth.set_phoneme_callback(phonemes.append)

    # Sequence: set phoneme while in standby, then wake
    chip.write(0xC0, 0xC1)  # DURPHON: phoneme 1
    assert phonemes == []
    chip.write(0xC3, 0x7F)  # CTRLAMP: CTL=0, wake up

    assert phonemes == [1]


# =============================================================================
# End-to-end audio tests (manual)
# =============================================================================


@pytest.mark.manual
def test_synth_speaks_phoneme():
    """Manual: hear a single phoneme.

    Run with: uv run pytest tests/test_synth.py::test_synth_speaks_phoneme -m manual -v -s
    """
    import time

    from qns.synth import SSI263Synth

    synth = SSI263Synth()
    synth.start()

    print("\nPlaying phoneme 0x01 (E as in 'beet')...")
    synth.speak_phoneme(0x01)
    time.sleep(0.5)

    print("Playing phoneme 0x06 (EH as in 'get')...")
    synth.speak_phoneme(0x06)
    time.sleep(0.5)

    print("Playing phoneme 0x20 (L as in 'let')...")
    synth.speak_phoneme(0x20)
    time.sleep(0.5)

    synth.stop()
    print("Done.")


@pytest.mark.manual
def test_synth_with_emulator():
    """Manual: hear synth via emulator chip writes.

    Run with: uv run pytest tests/test_synth.py::test_synth_with_emulator -m manual -v -s
    """
    import time

    from qns.ssi263 import SSI263
    from qns.synth import SSI263Synth

    synth = SSI263Synth()
    synth.start()

    chip = SSI263(base_port=0xC0)
    chip.set_synth(synth)

    print("\nSimulating BNS init sequence...")

    # Power down first
    chip.write(0xC3, 0x80)  # CTL=1 (standby)

    # Set phoneme
    chip.write(0xC0, 0xC1)  # phoneme 1 (E)

    # Wake and play
    print("Playing phoneme via chip...")
    chip.write(0xC3, 0x7F)  # CTL=0, amp=15

    time.sleep(0.5)

    # Another phoneme
    chip.write(0xC0, 0xC6)  # phoneme 6 (EH)
    time.sleep(0.5)

    synth.stop()
    print("Done.")
