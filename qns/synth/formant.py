"""Votrax SC-01 formant synthesizer.

Ported from MAME's votrax.cpp by Olivier Galibert.
Generates speech audio using formant synthesis with parameters from the SC-01 ROM.

Signal flow:
    VOICE PATH: Glottal wave -> VA amp -> F1 -> F2v -> ...
    NOISE PATH: LFSR noise -> FA amp -> Noise shaper -> FC amp -> F2n -> ...
    MIXED: ... -> F3 -> F4 -> Closure -> Final LP -> Output
"""

from dataclasses import dataclass, field
from math import pi, sqrt, tan

import numpy as np

from .sc01_rom import GLOTTAL_WAVE, PAUSE_PHONES, PHONEME_PARAMS


@dataclass
class FilterCoeffs:
    """IIR filter coefficients."""

    a: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    b: list[float] = field(default_factory=lambda: [1.0, 0.0, 0.0, 0.0])


class FormantSynth:
    """Votrax SC-01 formant speech synthesizer.

    Generates audio samples for phonemes using formant synthesis,
    closely following MAME's votrax.cpp implementation.
    """

    def __init__(self, sample_rate: int = 22050):
        """Initialize the synthesizer.

        Args:
            sample_rate: Output sample rate in Hz
        """
        self.sample_rate = sample_rate

        # Clock frequencies (scaled from original SC-01)
        # Original: main=720kHz, sclock=40kHz, cclock=20kHz
        # We scale to match our sample rate
        self._sclock = float(sample_rate)  # Sample clock
        self._cclock = sample_rate / 2.0   # Capacitor switching clock

        # Inflection (pitch modifier, 0-3)
        self._inflection = 0

        # ROM parameters for current phoneme
        self._rom_f1 = 0
        self._rom_f2 = 0
        self._rom_f2q = 0
        self._rom_f3 = 0
        self._rom_fa = 0  # Noise amplitude
        self._rom_fc = 0  # F2 noise coefficient
        self._rom_va = 0  # Voice amplitude
        self._rom_vd = 0  # Voice delay
        self._rom_cld = 0  # Closure delay
        self._rom_closure = False
        self._rom_duration = 0
        self._rom_pause = False

        # Interpolated parameters (8-bit, updated at different rates)
        self._cur_fa = 0
        self._cur_fc = 0
        self._cur_va = 0
        self._cur_f1 = 0
        self._cur_f2 = 0
        self._cur_f2q = 0
        self._cur_f3 = 0

        # Filter-committed parameters (4-bit)
        self._filt_fa = 0
        self._filt_fc = 0
        self._filt_va = 0
        self._filt_f1 = 0
        self._filt_f2 = 0
        self._filt_f2q = 0
        self._filt_f3 = 0

        # Timing counters
        self._phonetick = 0  # 9-bit, counts within duration unit
        self._ticks = 0      # 5-bit, counts 16 ticks per phoneme
        self._pitch = 0      # 8-bit, pitch counter
        self._closure = 0    # 5-bit, glottal closure counter
        self._update_counter = 0  # 6-bit, controls interpolation timing

        # State
        self._cur_closure = True
        self._noise = 1  # 15-bit LFSR, can't be zero
        self._cur_noise = False

        # Filter coefficients
        self._f1 = FilterCoeffs()
        self._f2v = FilterCoeffs()
        self._f2n = FilterCoeffs(a=[0.0, 0.0], b=[1.0, 0.0])  # Disabled
        self._f3 = FilterCoeffs()
        self._f4 = FilterCoeffs()
        self._fx = FilterCoeffs(a=[1.0], b=[1.0, 0.0])
        self._fn = FilterCoeffs(a=[0.0, 0.0, 0.0], b=[1.0, 0.0, 0.0])

        # Filter history arrays (for IIR)
        self._voice_1 = [0.0] * 4
        self._voice_2 = [0.0] * 4
        self._voice_3 = [0.0] * 4

        self._noise_1 = [0.0] * 3
        self._noise_2 = [0.0] * 3
        self._noise_3 = [0.0] * 2
        self._noise_4 = [0.0] * 2

        self._vn_1 = [0.0] * 4
        self._vn_2 = [0.0] * 4
        self._vn_3 = [0.0] * 4
        self._vn_4 = [0.0] * 4
        self._vn_5 = [0.0] * 2
        self._vn_6 = [0.0] * 2

        # Build static filters
        self._build_f4_filter()
        self._build_fx_filter()
        self._build_fn_filter()

    def synthesize_phoneme(
        self,
        phoneme: int,
        duration_override: float | None = None,
        inflection: int = 0,
    ) -> np.ndarray:
        """Synthesize audio for a single phoneme.

        Args:
            phoneme: SC-01 phoneme code (0x00-0x3F)
            duration_override: Override duration in seconds (None = use ROM value)
            inflection: Pitch inflection (0-3)

        Returns:
            Audio samples as float32 array, normalized to -1.0 to 1.0
        """
        phoneme = phoneme & 0x3F
        self._inflection = inflection & 0x03

        # Load phoneme parameters
        self._phone_commit(phoneme)

        # Calculate duration in samples
        if duration_override is not None:
            num_samples = int(duration_override * self.sample_rate)
        else:
            # ROM duration is in abstract units, scale to reasonable time
            # Original: 16 ticks × (duration×4+1) × 4 × 9 clock cycles
            # We simplify: ~20-200ms depending on duration value
            duration_ms = 20 + (self._rom_duration * 1.5)
            num_samples = int(duration_ms * self.sample_rate / 1000)

        # Generate samples
        samples = np.zeros(num_samples, dtype=np.float32)
        for i in range(num_samples):
            # Update chip state (runs at effective 20kHz in original)
            self._chip_update()

            # Generate one audio sample
            samples[i] = self._analog_calc()

        # Normalize output
        max_val = np.max(np.abs(samples))
        if max_val > 0:
            samples = samples / max_val * 0.8  # Leave some headroom

        return samples

    def _phone_commit(self, phoneme: int) -> None:
        """Load parameters for a new phoneme."""
        # Reset timing
        self._phonetick = 0
        self._ticks = 0

        # Get parameters from ROM
        params = PHONEME_PARAMS.get(phoneme, PHONEME_PARAMS[0x03])  # Default to pause

        self._rom_f1 = params['f1']
        self._rom_f2 = params['f2']
        self._rom_f2q = params['f2q']
        self._rom_f3 = params['f3']
        self._rom_fa = params['fa']
        self._rom_fc = params['fc']
        self._rom_va = params['va']
        self._rom_vd = params['vd']
        self._rom_cld = params['cld']
        self._rom_closure = params['closure']
        self._rom_duration = params['duration']
        self._rom_pause = phoneme in PAUSE_PHONES

        # Initialize interpolated values to target (scaled for 8-bit internal)
        # This ensures parameters are active immediately rather than waiting
        # for slow interpolation timing which doesn't match our sample rate
        self._cur_fa = self._rom_fa << 4
        self._cur_fc = self._rom_fc << 4
        self._cur_va = self._rom_va << 4
        self._cur_f1 = self._rom_f1 << 4
        self._cur_f2 = self._rom_f2 << 3  # F2 is 5-bit
        self._cur_f2q = self._rom_f2q << 4
        self._cur_f3 = self._rom_f3 << 4

        # Initialize closure state
        if self._rom_cld == 0:
            self._cur_closure = self._rom_closure

        # Force filter rebuild with new parameters
        self._filters_commit()

    def _chip_update(self) -> None:
        """Update chip state (called once per sample)."""
        # Phone tick counter
        if self._ticks != 0x10:
            self._phonetick += 1
            # Simplified timing - advance ticks periodically
            if self._phonetick >= (self._rom_duration * 4 + 1):
                self._phonetick = 0
                self._ticks += 1
                if self._ticks == self._rom_cld:
                    self._cur_closure = self._rom_closure

        # Update counter (0-47)
        self._update_counter = (self._update_counter + 1) % 48

        # 625Hz updates (every 16 counts)
        tick_625 = (self._update_counter & 0xF) == 0
        # 208Hz updates (at count 40)
        tick_208 = self._update_counter == 40

        # Formant interpolation at 208Hz
        if tick_208 and (not self._rom_pause or not (self._filt_fa or self._filt_va)):
            self._cur_fc = self._interpolate(self._cur_fc, self._rom_fc)
            self._cur_f1 = self._interpolate(self._cur_f1, self._rom_f1)
            self._cur_f2 = self._interpolate(self._cur_f2, self._rom_f2)
            self._cur_f2q = self._interpolate(self._cur_f2q, self._rom_f2q)
            self._cur_f3 = self._interpolate(self._cur_f3, self._rom_f3)

        # Amplitude interpolation at 625Hz
        if tick_625:
            if self._ticks >= self._rom_vd:
                self._cur_fa = self._interpolate(self._cur_fa, self._rom_fa)
            if self._ticks >= self._rom_cld:
                self._cur_va = self._interpolate(self._cur_va, self._rom_va)

        # Closure counter
        if not self._cur_closure and (self._filt_fa or self._filt_va):
            self._closure = 0
        elif self._closure < 28:  # 7 << 2
            self._closure += 1

        # Pitch counter (8-bit, resets at computed point)
        self._pitch = (self._pitch + 1) & 0xFF
        reset_point = (0xE0 ^ (self._inflection << 5) ^ (self._filt_f1 << 1)) + 2
        if self._pitch == (reset_point & 0xFF):
            self._pitch = 0

        # Update filters when pitch is in range 8-11
        if 8 <= self._pitch < 12:
            self._filters_commit()

        # Noise LFSR (15-bit Galois)
        inp = (self._filt_fa > 0) and self._cur_noise and (self._noise != 0x7FFF)
        self._noise = ((self._noise << 1) & 0x7FFE) | (1 if inp else 0)
        self._cur_noise = not (((self._noise >> 14) ^ (self._noise >> 13)) & 1)

    @staticmethod
    def _interpolate(reg: int, target: int) -> int:
        """One step of parameter interpolation (1/8 of distance)."""
        return (reg - (reg >> 3) + (target << 1)) & 0xFF

    def _filters_commit(self) -> None:
        """Commit interpolated values to filter coefficients."""
        # Extract 4-bit values from 8-bit interpolated
        new_fa = self._cur_fa >> 4
        new_fc = self._cur_fc >> 4
        new_va = self._cur_va >> 4
        new_f1 = self._cur_f1 >> 4
        new_f2 = self._cur_f2 >> 3  # F2 is 5-bit
        new_f2q = self._cur_f2q >> 4
        new_f3 = self._cur_f3 >> 4

        # Rebuild filters only if parameters changed
        if new_f1 != self._filt_f1:
            self._filt_f1 = new_f1
            self._build_f1_filter()

        if new_f2 != self._filt_f2 or new_f2q != self._filt_f2q:
            self._filt_f2 = new_f2
            self._filt_f2q = new_f2q
            self._build_f2_filter()

        if new_f3 != self._filt_f3:
            self._filt_f3 = new_f3
            self._build_f3_filter()

        self._filt_fa = new_fa
        self._filt_fc = new_fc
        self._filt_va = new_va

    def _analog_calc(self) -> float:
        """Calculate one audio sample."""
        # === VOICE PATH ===

        # 1. Glottal wave source
        pitch_idx = self._pitch >> 3
        if pitch_idx >= 9:
            v = 0.0
        else:
            v = GLOTTAL_WAVE[pitch_idx]

        # 2. Voice amplitude
        v = v * self._filt_va / 15.0
        self._shift_hist(v, self._voice_1)

        # 3. F1 filter
        v = self._apply_filter(self._voice_1, self._voice_2, self._f1)
        self._shift_hist(v, self._voice_2)

        # 4. F2 voice filter
        v = self._apply_filter(self._voice_2, self._voice_3, self._f2v)
        self._shift_hist(v, self._voice_3)

        # === NOISE PATH ===

        # 5. Noise source (pitch-gated)
        n = 1e4 * (1.0 if ((self._pitch & 0x40) and self._cur_noise) else -1.0)
        n = n * self._filt_fa / 15.0
        self._shift_hist(n, self._noise_1)

        # 6. Noise shaper filter
        n = self._apply_filter(self._noise_1, self._noise_2, self._fn)
        self._shift_hist(n, self._noise_2)

        # 7. Scale with F2 noise coefficient
        n2 = n * self._filt_fc / 15.0
        self._shift_hist(n2, self._noise_3)

        # 8. F2 noise filter (currently bypassed like MAME)
        n2 = self._apply_filter_2(self._noise_3, self._noise_4, self._f2n)
        self._shift_hist(n2, self._noise_4)

        # === MIXED PATH ===

        # 9. Combine voice and noise F2 outputs
        vn = v + n2
        self._shift_hist(vn, self._vn_1)

        # 10. F3 filter
        vn = self._apply_filter(self._vn_1, self._vn_2, self._f3)
        self._shift_hist(vn, self._vn_2)

        # 11. Second noise injection
        vn += n * (5 + (15 - self._filt_fc)) / 20.0
        self._shift_hist(vn, self._vn_3)

        # 12. F4 filter
        vn = self._apply_filter(self._vn_3, self._vn_4, self._f4)
        self._shift_hist(vn, self._vn_4)

        # 13. Glottal closure amplitude
        vn = vn * (7 - (self._closure >> 2)) / 7.0
        self._shift_hist(vn, self._vn_5)

        # 14. Final lowpass filter
        vn = self._apply_filter_2(self._vn_5, self._vn_6, self._fx)
        self._shift_hist(vn, self._vn_6)

        return vn * 0.35

    @staticmethod
    def _shift_hist(val: float, hist: list[float]) -> None:
        """Shift history array and insert new value."""
        for i in range(len(hist) - 1, 0, -1):
            hist[i] = hist[i - 1]
        hist[0] = val

    def _apply_filter(
        self, x: list[float], y: list[float], f: FilterCoeffs
    ) -> float:
        """Apply 4th-order IIR filter."""
        total = 0.0
        for i in range(min(len(f.a), len(x))):
            total += x[i] * f.a[i]
        for i in range(1, min(len(f.b), len(y) + 1)):
            if i - 1 < len(y):
                total -= y[i - 1] * f.b[i]
        return total / f.b[0] if f.b[0] != 0 else 0.0

    def _apply_filter_2(
        self, x: list[float], y: list[float], f: FilterCoeffs
    ) -> float:
        """Apply 2nd-order IIR filter."""
        return self._apply_filter(x, y, f)

    # === Filter builders ===

    @staticmethod
    def _bits_to_caps(value: int, caps: list[float]) -> float:
        """Convert bit pattern to total capacitance."""
        total = 0.0
        for cap in caps:
            if value & 1:
                total += cap
            value >>= 1
        return total

    def _build_standard_filter(
        self,
        c1t: float,
        c1b: float,
        c2t: float,
        c2b: float,
        c3: float,
        c4: float,
    ) -> FilterCoeffs:
        """Build standard 4th-order formant filter."""
        # Compute analog coefficients
        k0 = c1t / (self._cclock * c1b) if c1b else 0
        k1 = c4 * c2t / (self._cclock * c1b * c3) if (c1b and c3) else 0
        k2 = c4 * c2b / (self._cclock * self._cclock * c1b * c3) if (c1b and c3) else 0

        if k2 == 0:
            return FilterCoeffs()

        # Find peak frequency for pre-warping
        fpeak = sqrt(abs(k0 * k1 - k2)) / (2 * pi * k2)
        if fpeak <= 0 or fpeak >= self._sclock / 2:
            fpeak = self._sclock / 4

        # Warp multiplier
        zc = 2 * pi * fpeak / tan(pi * fpeak / self._sclock)

        # Bilinear transform
        m0 = zc * k0
        m1 = zc * k1
        m2 = zc * zc * k2

        f = FilterCoeffs()
        f.a[0] = 1 + m0
        f.a[1] = 3 + m0
        f.a[2] = 3 - m0
        f.a[3] = 1 - m0
        f.b[0] = 1 + m1 + m2
        f.b[1] = 3 + m1 - m2
        f.b[2] = 3 - m1 - m2
        f.b[3] = 1 - m1 + m2

        return f

    def _build_f1_filter(self) -> None:
        """Build F1 formant filter."""
        c3 = 2280 + self._bits_to_caps(self._filt_f1, [2546, 4973, 9861, 19724])
        self._f1 = self._build_standard_filter(11247, 11797, 949, 52067, c3, 166272)

    def _build_f2_filter(self) -> None:
        """Build F2 voice formant filter."""
        c2t = 829 + self._bits_to_caps(self._filt_f2q, [1390, 2965, 5875, 11297])
        c3 = 2352 + self._bits_to_caps(self._filt_f2, [833, 1663, 3164, 6327, 12654])
        self._f2v = self._build_standard_filter(24840, 29154, c2t, 38180, c3, 34270)
        # F2 noise injection filter is disabled (like MAME)
        self._f2n = FilterCoeffs(a=[0.0, 0.0], b=[1.0, 0.0])

    def _build_f3_filter(self) -> None:
        """Build F3 formant filter."""
        c3 = 8480 + self._bits_to_caps(self._filt_f3, [2226, 4485, 9056, 18111])
        self._f3 = self._build_standard_filter(0, 17594, 868, 18828, c3, 50019)

    def _build_f4_filter(self) -> None:
        """Build F4 formant filter (static)."""
        self._f4 = self._build_standard_filter(0, 28810, 1165, 21457, 8558, 7289)

    def _build_fx_filter(self) -> None:
        """Build final lowpass filter."""
        c1t = 1122
        c1b = 23131

        # Fudge factor from MAME (150/4000) to move cutoff higher
        k = c1b / (self._cclock * c1t) * (150.0 / 4000.0)
        fpeak = 1 / (2 * pi * k) if k else self._sclock / 4
        if fpeak <= 0 or fpeak >= self._sclock / 2:
            fpeak = self._sclock / 4

        zc = 2 * pi * fpeak / tan(pi * fpeak / self._sclock)
        m = zc * k

        self._fx = FilterCoeffs(a=[1.0], b=[1 + m, 1 - m])

    def _build_fn_filter(self) -> None:
        """Build noise shaper filter."""
        c1 = 15500
        c2t = 14854
        c2b = 8450
        c3 = 9523
        c4 = 14083

        # Coefficients for bandpass H(s) = k1*s / (1 + k2*s + k3*s^2)
        k0 = c2t * c3 * c2b / c4
        k1 = c2t * (self._cclock * c2b)
        k2 = c1 * c2t * c3 / (self._cclock * c4)

        if k2 == 0:
            return

        fpeak = sqrt(1 / k2) / (2 * pi)
        if fpeak <= 0 or fpeak >= self._sclock / 2:
            fpeak = self._sclock / 4

        zc = 2 * pi * fpeak / tan(pi * fpeak / self._sclock)
        m0 = zc * k0
        m1 = zc * k1
        m2 = zc * zc * k2

        self._fn = FilterCoeffs(
            a=[m0, 0.0, -m0],
            b=[1 + m1 + m2, 2 - 2 * m2, 1 - m1 + m2],
        )
