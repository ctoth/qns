"""SSI-263 audio from a register-level model of the chip itself.

The other backends turn decoded phoneme events into recorded or modelled
candidate audio.  This one hands the firmware's raw register writes, each at
its exact CPU cycle, to Tamas Geczy's SSI-263 engine
(https://github.com/tgeczy/ssi263-speech, MIT, the ``ssi263speech`` wheel):
a switched-capacitor vocal tract driven by the phoneme ROM read from the die.
Nothing is recorded or concatenated, and transitions, glides and closures are
the chip's own.

:class:`qns.ssi263.SSI263` still owns A/R and INT1.  Both follow the SSI-263A
data sheet, frame = 4096 (16 - R) / XCK and phoneme = frame (4 - D); see
``tests/test_ssi263_chip.py``, which holds the engine's A/R to ours.

One engine default is switched off here.  ``release_lookahead`` (with
``hold_release``, which depends on it) raises A/R 1.75 frames before a
releasing stop such as T, P or K ends and holds the host's writes until it
does, so the engine can see the next phoneme and decide whether to release.
Its own parameter notes call that a modelled device, not data-sheet
behaviour, and on QNS it would deliver INT1 to the firmware 50 ms early at
rate 9.  Pass ``release_lookahead=True`` to hear the engine's tuned stops.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..clock import HD64180_PHI_HZ
from ..ssi263 import SSI263_XCK_HZ, SSI263State
from .player import AudioPlayer

SAMPLE_RATE = 22050

# ssi263_params is a struct of doubles (csrc/ssi263.h).  These indices are for
# the pinned wheel, ssi263speech 0.9.1, and are checked against the library's
# own size and defaults before anything is changed.
_PARAMS_DOUBLES = 194
_XCK_HZ_INDEX = 0
_RELEASE_LOOKAHEAD_INDEX = 88
# The engine's ssi_pcm16 gain, which its own front ends use.
_OUTPUT_GAIN = 2.0
# Without writes, render at least this much emulated time per call so the
# main loop's frequent cycle updates do not become thousands of tiny calls.
_MIN_RENDER_SECONDS = 0.004


class ChipEngineError(RuntimeError):
    """The ssi263speech library is missing or is not the version QNS expects."""


class RegisterChip:
    """One ssi263speech chip with QNS's parameters, rendering exact sample counts."""

    def __init__(self, sample_rate: int = SAMPLE_RATE, release_lookahead: bool = False) -> None:
        try:
            from ssi263speech import _native
        except ImportError as exc:  # pragma: no cover - platform without a wheel
            raise ChipEngineError(
                "the chip backend needs the ssi263speech wheel (Windows x64, Linux x86_64/aarch64)"
            ) from exc
        lib = _native.chip_lib()
        size = lib.ssi263_params_size()
        if size != _PARAMS_DOUBLES * ctypes.sizeof(ctypes.c_double):
            raise ChipEngineError(f"unexpected ssi263_params size {size}; QNS expects 0.9.1")
        params = (ctypes.c_double * _PARAMS_DOUBLES)()
        lib.ssi263_default_params(params)
        if params[_XCK_HZ_INDEX] != SSI263_XCK_HZ or params[_RELEASE_LOOKAHEAD_INDEX] != 1.0:
            raise ChipEngineError("ssi263speech defaults do not match the 0.9.1 layout QNS expects")
        params[_RELEASE_LOOKAHEAD_INDEX] = 1.0 if release_lookahead else 0.0

        self._lib = lib
        self._chip = lib.ssi263_new(params, lib.ssi263_default_rom(), float(sample_rate))
        if not self._chip:
            raise ChipEngineError("ssi263speech could not create a chip")
        self.sample_rate = sample_rate
        self._buffer = (ctypes.c_double * 1)()

    def close(self) -> None:
        if self._chip:
            self._lib.ssi263_free(self._chip)
            self._chip = None

    def __del__(self) -> None:
        self.close()

    def write(self, register: int, value: int) -> None:
        self._lib.ssi263_write(self._chip, register & 7, value & 0xFF)

    @property
    def request(self) -> bool:
        """A/R asserted: the chip wants its next phoneme."""
        return bool(self._lib.ssi263_request(self._chip))

    @property
    def time(self) -> float:
        return float(self._lib.ssi263_time(self._chip))

    def render(self, count: int) -> np.ndarray:
        """Exactly ``count`` samples as float32 in [-1, 1]."""
        if count <= 0:
            return np.zeros(0, dtype=np.float32)
        if len(self._buffer) < count + 1:
            self._buffer = (ctypes.c_double * (count + 1))()
        got = self._lib.ssi263_run(self._chip, count, self._buffer)
        raw = np.ctypeslib.as_array(self._buffer)[:got]
        return np.clip(raw * _OUTPUT_GAIN, -1.0, 1.0).astype(np.float32)


class SSI263ChipSynth:
    """Audio backend driving :class:`RegisterChip` with the firmware's own writes."""

    def __init__(
        self,
        audio_enabled: bool = True,
        realtime: bool = False,
        clock: int = HD64180_PHI_HZ,
        release_lookahead: bool = False,
        wav_path: Path | str | None = None,
        min_render_seconds: float = _MIN_RENDER_SECONDS,
    ) -> None:
        self.sample_rate = SAMPLE_RATE
        self._clock = clock
        self.chip = RegisterChip(SAMPLE_RATE, release_lookahead=release_lookahead)
        self._player = (
            AudioPlayer(
                sample_rate=SAMPLE_RATE,
                overflow_policy="block" if realtime else "drop_newest",
            )
            if audio_enabled
            else None
        )
        self._wav_path = Path(wav_path) if wav_path is not None else None
        self._wav_chunks: list[np.ndarray] = []
        self._phoneme_callback: Callable[[int], None] | None = None
        # Emulated time is tracked as a whole-sample count from the first
        # cycle seen, so rounding never accumulates into drift.
        self._origin_cycle: int | None = None
        self._rendered_samples = 0
        self._min_render_cycles = int(clock * min_render_seconds)
        self._rendered_cycle = 0

    # -- SpeechBackend ---------------------------------------------------
    def start(self) -> None:
        if self._player is not None:
            self._player.start()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
        if self._wav_path is not None:
            self.write_wav(self._wav_path)

    def set_phoneme_callback(self, callback: Callable[[int], None]) -> None:
        self._phoneme_callback = callback

    def play(self, state: SSI263State) -> None:
        """Decoded events are informational: the chip hears the raw writes."""
        if self._phoneme_callback is not None:
            self._phoneme_callback(state.phoneme)

    def end_phoneme(self, elapsed_samples: int) -> None:
        """Nothing to conform: the chip renders elapsed time as it passes."""

    def realtime_lead_seconds(self) -> float:
        return self._player.realtime_lead_seconds() if self._player is not None else 0.0

    # -- RegisterBackend -------------------------------------------------
    def write_register(self, register: int, value: int, cycle: int) -> None:
        self._render_to(cycle)
        self.chip.write(register, value)

    def advance_to(self, cycle: int) -> None:
        if self._origin_cycle is None or cycle - self._rendered_cycle >= self._min_render_cycles:
            self._render_to(cycle)

    # -- output ----------------------------------------------------------
    def captured_audio(self) -> np.ndarray:
        """Every sample rendered so far, when a WAV path was given."""
        if not self._wav_chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._wav_chunks)

    def write_wav(self, path: Path | str) -> None:
        import wave

        pcm = (self.captured_audio() * 32767.0).astype("<i2")
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(SAMPLE_RATE)
            out.writeframes(pcm.tobytes())

    def _render_to(self, cycle: int) -> None:
        if self._origin_cycle is None:
            self._origin_cycle = cycle
            self._rendered_cycle = cycle
            return
        if cycle <= self._rendered_cycle:
            return
        self._rendered_cycle = cycle
        target = round((cycle - self._origin_cycle) * SAMPLE_RATE / self._clock)
        audio = self.chip.render(target - self._rendered_samples)
        self._rendered_samples = target
        if not len(audio):
            return
        if self._wav_path is not None:
            self._wav_chunks.append(audio)
        if self._player is not None:
            self._player.play(audio)
