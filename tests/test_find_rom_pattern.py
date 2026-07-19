"""Authorities for masked firmware byte-pattern searches."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tools.find_rom_pattern import (
    BNS_IMAGE_OFFSET,
    find_pattern,
    load_firmware,
    parse_pattern,
)


@given(
    prefix=st.binary(max_size=256),
    operands=st.binary(min_size=2, max_size=2),
    suffix=st.binary(max_size=256),
)
def test_masked_pattern_finds_randomized_linked_operands(
    prefix: bytes,
    operands: bytes,
    suffix: bytes,
):
    """Wildcards must retain the exact offset of arbitrary linked operands."""
    fixed_prefix = bytes.fromhex("F5 E5 21")
    fixed_suffix = bytes.fromhex("CB A6 7E F6 08 ED 39 00 E1 F1 C9")
    data = prefix + fixed_prefix + operands + fixed_suffix + suffix
    pattern = parse_pattern("F5 E5 21 ?? ?? CB A6 7E F6 08 ED 39 00 E1 F1 C9")

    assert len(prefix) in find_pattern(data, pattern)


@pytest.mark.parametrize("text", ("", "0", "GG", "000"))
def test_parse_pattern_rejects_malformed_bytes(text: str):
    """Ambiguous or non-hexadecimal pattern tokens must be rejected."""
    with pytest.raises(ValueError):
        parse_pattern(text)


def test_load_firmware_strips_exact_bns_header(tmp_path):
    """Reported firmware offsets must exclude the BNS package header."""
    payload = b"firmware"
    package = bytearray(BNS_IMAGE_OFFSET)
    package[2:5] = b"BNS"
    path = tmp_path / "firmware.bns"
    path.write_bytes(package + payload)

    assert load_firmware(path) == (payload, BNS_IMAGE_OFFSET)
