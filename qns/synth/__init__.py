"""SSI-263 audio backends for the QNS emulator.

Register decoding lives in :mod:`qns.ssi263`; the backends here implement
its ``SpeechBackend`` protocol and produce the actual audio.
"""

from .formant import FormantSynth
from .ssi263_pcm import SSI263PCMSynth
from .ssi263_synth import SSI263Synth

__all__ = ["FormantSynth", "SSI263PCMSynth", "SSI263Synth"]
