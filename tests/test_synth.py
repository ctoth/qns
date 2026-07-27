"""Formant synth backend and phoneme-data tests.

Run with: uv run pytest tests/test_synth.py -v
"""

import numpy as np
import pytest

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


def test_audio_player_lifecycle():
    """AudioPlayer can start and stop cleanly."""
    from qns.synth.player import AudioPlayer

    player = AudioPlayer(sample_rate=22050)

    assert not player.is_playing()
    player.start()
    assert not player.is_playing()  # No samples queued yet
    player.stop()


def test_audio_player_queues_samples():
    """AudioPlayer accepts samples for playback."""
    from qns.synth.player import AudioPlayer

    player = AudioPlayer(sample_rate=22050)
    player.start()

    samples = np.zeros(1000, dtype=np.float32)
    player.play(samples)
    # Player should accept samples (may or may not be playing yet)

    player.stop()


@pytest.mark.manual
def test_audio_player_produces_sound():
    """Manual test: verify audio output works.

    Run with: uv run pytest tests/test_synth.py -k manual -v -s
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

    Run with: uv run pytest tests/test_synth.py::test_synth_speaks_phoneme -v -s
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

    Run with: uv run pytest tests/test_synth.py::test_synth_with_emulator -v -s
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
