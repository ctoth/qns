"""Round-trip tests for the reconstructed SC-01 conformance ROM."""

import struct

from qns.synth.sc01_rom import PHONEME_PARAMS
from tools.decode_sc01_rom import decode_phoneme
from tools.encode_sc01_rom import encode_entry


def test_encoded_rom_entries_round_trip_through_msb_first_decoder() -> None:
    fields = (
        "f1",
        "f2",
        "f2q",
        "f3",
        "va",
        "fa",
        "fc",
        "vd",
        "cld",
        "closure",
        "duration",
    )

    for code, parameters in PHONEME_PARAMS.items():
        encoded = struct.pack("<Q", encode_entry(code, parameters))
        decoded = decode_phoneme(encoded)

        assert decoded["id"] == code
        assert decoded["name"] == parameters["name"]
        assert {field: decoded[field] for field in fields} == {
            field: parameters[field] for field in fields
        }
