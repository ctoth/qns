"""SSI-263 Synthesizer Tests.

TDD test suite - tests are written before implementation.
Run with: uv run pytest tests/test_synth.py -v
"""

import numpy as np
import pytest


# =============================================================================
# Phase 1: Phoneme Data Tests
# =============================================================================


def test_phoneme_data_exists():
    """Phoneme module exports required constants."""
    from qns.synth.phonemes import PHONEME_DATA, PHONEME_INFO, SAMPLE_RATE

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
# Phase 2: DSP Functions Tests
# =============================================================================


def test_amplitude_scaling():
    """Amplitude scales samples linearly 0-15."""
    from qns.synth.dsp import apply_amplitude

    samples = np.array([1000, -1000, 0], dtype=np.int16)

    # Full volume (15) = no change
    result = apply_amplitude(samples, amplitude=15)
    np.testing.assert_array_equal(result, samples)

    # Half volume (7-8) ≈ half amplitude
    result = apply_amplitude(samples, amplitude=7)
    assert abs(result[0]) < abs(samples[0])
    assert abs(result[0]) > 0  # Not silent

    # Zero volume = silence
    result = apply_amplitude(samples, amplitude=0)
    np.testing.assert_array_equal(result, np.zeros(3, dtype=np.int16))


def test_filter_silence():
    """filter_freq=0xFF means silence."""
    from qns.synth.dsp import apply_filter

    samples = np.array([1000, -1000], dtype=np.int16)

    # filter_freq=0xFF means silence
    result = apply_filter(samples, filter_freq=0xFF)
    np.testing.assert_array_equal(result, np.zeros(2, dtype=np.int16))

    # Other values should pass audio through (possibly filtered)
    result = apply_filter(samples, filter_freq=0x00)
    assert len(result) == len(samples)


def test_time_stretch_duration_modes():
    """Duration modes control sample averaging/stretching."""
    from qns.synth.dsp import time_stretch

    samples = np.array([100, 200, 300, 400], dtype=np.int16)

    # DUR=0: no averaging, same length
    result = time_stretch(samples, rate=0, duration=0)
    assert len(result) == len(samples)

    # DUR=3: average 4 samples, shorter output
    result = time_stretch(samples, rate=0, duration=3)
    assert len(result) < len(samples)


def test_pitch_shift_identity():
    """Neutral inflection preserves sample count."""
    from qns.synth.dsp import pitch_shift

    samples = np.array([100, 200, 300, 400, 500, 600, 700, 800], dtype=np.int16)

    # Neutral inflection (≈2048) = approximately same length
    result = pitch_shift(samples, inflection=2048)
    # Allow some tolerance due to resampling
    assert abs(len(result) - len(samples)) <= 1


# =============================================================================
# Phase 3: Audio Player Tests
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
# Phase 4: Synthesizer Core Tests
# =============================================================================


def test_synth_state_defaults():
    """SSI263State has correct defaults."""
    from qns.synth import SSI263State

    state = SSI263State()
    assert state.phoneme == 0
    assert state.amplitude == 15
    assert state.control == True  # Standby by default


def test_synth_write_durphon():
    """write_durphon extracts duration and phoneme."""
    from qns.synth import SSI263Synth

    synth = SSI263Synth(audio_enabled=False)

    synth.write_durphon(0xC5)  # duration=3, phoneme=5
    assert synth.state.duration == 3
    assert synth.state.phoneme == 5

    synth.write_durphon(0x81)  # duration=2, phoneme=1
    assert synth.state.duration == 2
    assert synth.state.phoneme == 1


def test_synth_write_ctrlamp_wake():
    """CTL 1->0 triggers phoneme playback."""
    from qns.synth import SSI263Synth

    synth = SSI263Synth(audio_enabled=False)

    # Set phoneme first
    synth.write_durphon(0xC1)  # phoneme 1

    # Track phonemes played
    phonemes_played = []
    synth.set_phoneme_callback(lambda p: phonemes_played.append(p))

    # CTL 1->0 should trigger speech
    synth.write_ctrlamp(0x7F)  # CTL=0, amp=15

    assert synth.state.control == False
    assert 1 in phonemes_played


def test_synth_get_phoneme_audio():
    """get_phoneme_audio returns processed samples."""
    from qns.synth import SSI263Synth

    synth = SSI263Synth(audio_enabled=False)

    # Should return processed samples for a phoneme
    samples = synth.get_phoneme_audio(phoneme=1, amplitude=15)
    assert len(samples) > 0
    assert samples.dtype == np.float32


# =============================================================================
# Phase 5: Integration with Emulator Tests
# =============================================================================


def test_ssi263_set_synth():
    """SSI263 chip can connect to synthesizer."""
    from qns.ssi263 import SSI263
    from qns.synth import SSI263Synth

    chip = SSI263(base_port=0xC0)
    synth = SSI263Synth(audio_enabled=False)

    chip.set_synth(synth)

    # Write to chip should forward to synth
    chip.write(0xC0, 0xC5)  # DURPHON: duration=3, phoneme=5
    assert synth.state.phoneme == 5
    assert synth.state.duration == 3


def test_ssi263_synth_plays_on_wake():
    """SSI263 chip triggers synth on CTL wake."""
    from qns.ssi263 import SSI263
    from qns.synth import SSI263Synth

    chip = SSI263(base_port=0xC0)
    synth = SSI263Synth(audio_enabled=False)
    chip.set_synth(synth)

    phonemes = []
    synth.set_phoneme_callback(lambda p: phonemes.append(p))

    # Sequence: set phoneme, then wake
    chip.write(0xC0, 0xC1)  # DURPHON: phoneme 1
    chip.write(0xC3, 0x7F)  # CTRLAMP: CTL=0, wake up

    assert 1 in phonemes


# =============================================================================
# Phase 6: End-to-End Audio Tests (Manual)
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
