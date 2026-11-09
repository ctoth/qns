"""SSI-263 phoneme timing against the data sheet, and the chip backend against it.

The firmware has no speech timing of its own (BSPMON.ASM SAYIT/SSIWT only
wait on A/R), so the chip's phoneme duration is the device's timing.  The
SSI-263A data sheet: frame = 4096 (16 - R) / XCK, phoneme = frame (4 - D),
frame timing mode one frame per phoneme.
"""

from __future__ import annotations

import pytest

from qns.clock import HD64180_PHI_HZ
from qns.ssi263 import SSI263, SSI263_XCK_HZ, playback_length_samples

T, P, K, AH, S, B, PA = 0x28, 0x27, 0x29, 0x0E, 0x30, 0x24, 0x00


def data_sheet_cycles(rate: int, frames: int) -> int:
    return round(4096 * (16 - rate) * frames * HD64180_PHI_HZ / SSI263_XCK_HZ)


def _setup(chip: SSI263, mode: int, rate: int, cycle: int = 0) -> None:
    base = chip.base_port
    chip.set_cycle_count(cycle)
    chip.write(base + 3, 0x80)  # CTL high: the next CTL H->L latches the mode
    chip.write(base + 0, mode << 6)
    chip.write(base + 1, 0x40)
    chip.write(base + 2, rate << 4)
    chip.write(base + 4, 0xE7)
    chip.write(base + 3, 0x7C)  # CTL low


def _load_to_request(mode: int, rate: int, duration: int, code: int = AH) -> int:
    chip = SSI263()
    _setup(chip, mode, rate)
    chip.set_cycle_count(10_000)
    chip.write(chip.base_port, (duration << 6) | code)
    assert chip.pending_irq_cycle is not None
    return chip.pending_irq_cycle - 10_000


@pytest.mark.parametrize("mode", (3, 2))
@pytest.mark.parametrize("rate", (0, 5, 9, 11, 15))
@pytest.mark.parametrize("duration", (0, 1, 2, 3))
def test_phoneme_timing_follows_the_data_sheet(mode: int, rate: int, duration: int) -> None:
    assert _load_to_request(mode, rate, duration) == data_sheet_cycles(rate, 4 - duration)


@pytest.mark.parametrize("code", (PA, AH, S, B, P, T, K))
def test_every_phoneme_code_lasts_the_same_time(code: int) -> None:
    assert _load_to_request(3, 9, 0, code) == data_sheet_cycles(9, 4)


@pytest.mark.parametrize("duration", (0, 3))
def test_frame_timing_mode_requests_every_frame(duration: int) -> None:
    assert _load_to_request(1, 9, duration) == data_sheet_cycles(9, 1)


def test_playback_length_is_the_data_sheet_duration() -> None:
    # rate 9, D = 0: 4 frames of 28.672 ms
    assert playback_length_samples(AH, duration=0, rate=9) == round(0.114688 * 22050)
    assert playback_length_samples(T, duration=0, rate=9) == playback_length_samples(
        AH, duration=0, rate=9
    )


chip_backend = pytest.importorskip("qns.synth.ssi263_chip")


def _chip_pair(**kwargs: object) -> tuple[SSI263, chip_backend.SSI263ChipSynth]:
    try:
        synth = chip_backend.SSI263ChipSynth(audio_enabled=False, min_render_seconds=0, **kwargs)
    except chip_backend.ChipEngineError as exc:
        pytest.skip(str(exc))
    chip = SSI263()
    chip.set_synth(synth)
    return chip, synth


# The engine reports A/R at its next host sample after the output filter's
# delay: measured 30-44 us.  Allow 100 us.
_TOLERANCE = int(HD64180_PHI_HZ * 100e-6)


@pytest.mark.parametrize("code", (AH, S, T, P, K))
@pytest.mark.parametrize(
    ("mode", "rate", "duration"), ((3, 9, 0), (3, 9, 3), (2, 0, 1), (1, 11, 0))
)
def test_engine_request_agrees_with_qns(code: int, mode: int, rate: int, duration: int) -> None:
    chip, synth = _chip_pair()
    _setup(chip, mode, rate, cycle=1_000)
    load = 20_000
    chip.set_cycle_count(load)
    chip.write(chip.base_port, (duration << 6) | code)
    due = chip.pending_irq_cycle
    assert due is not None

    synth.advance_to(due - _TOLERANCE)
    assert not synth.chip.request, "engine asked for the next phoneme before QNS"
    synth.advance_to(due + _TOLERANCE)
    assert synth.chip.request, "engine still busy after QNS raised A/R"


def test_release_lookahead_would_request_early_before_stops() -> None:
    """Why the backend switches release_lookahead off (see ssi263_chip)."""
    chip, synth = _chip_pair(release_lookahead=True)
    _setup(chip, 3, 9, cycle=1_000)
    chip.set_cycle_count(20_000)
    chip.write(chip.base_port, T)
    due = chip.pending_irq_cycle
    assert due is not None
    synth.advance_to(due - data_sheet_cycles(9, 1))
    assert synth.chip.request


def test_backend_renders_exact_elapsed_samples() -> None:
    chip, synth = _chip_pair(wav_path="unused.wav")
    _setup(chip, 3, 9, cycle=0)
    chip.write(chip.base_port, AH)
    for cycle in (1_234, 99_999, 1_000_000, HD64180_PHI_HZ):
        synth.advance_to(cycle)
    assert len(synth.captured_audio()) == 22050  # one emulated second
    assert float(abs(synth.captured_audio()).max()) > 0.05  # the vowel sounds


def test_firmware_boot_greeting_speaks_through_the_chip(tmp_path) -> None:
    from qns.bns import BNS

    wav = tmp_path / "greeting.wav"
    try:
        bns = BNS(synth_backend="chip", audio_wav=wav)
    except chip_backend.ChipEngineError as exc:
        pytest.skip(str(exc))
    bns.load_rom("roms/bspeng.bns")
    bns.run(max_cycles=26_000_000)
    audio = bns.synth.captured_audio()
    # Rendering starts at the firmware's first chip write, a few thousand
    # cycles into boot, and then covers every emulated cycle.
    assert len(audio) == pytest.approx(26_000_000 * 22050 / HD64180_PHI_HZ, rel=0.001)
    assert float(abs(audio).max()) > 0.1
    assert wav.exists()
