"""Authorities for masked firmware byte-pattern searches."""

import sys

import pytest
from hypothesis import given
from hypothesis import strategies as st
from package_fixtures import build_update_package

from tools.find_rom_pattern import (
    find_pattern,
    main,
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


@pytest.mark.parametrize("image_offset", [0x3000, 0x7000, 0x8000])
def test_main_reports_loader_discovered_package_offsets(
    tmp_path,
    monkeypatch,
    capsys,
    image_offset,
):
    """Classic and Millennium matches must use the discovered image boundary."""
    pattern = bytes.fromhex("DE AD BE EF 42")
    pattern_offset = 0x123
    firmware = bytearray(0x10000)
    firmware[pattern_offset : pattern_offset + len(pattern)] = pattern
    path = tmp_path / "firmware.bns"
    path.write_bytes(build_update_package(image_offset, bytes(firmware)))
    monkeypatch.setattr(
        sys,
        "argv",
        ["find_rom_pattern.py", str(path), pattern.hex(" ")],
    )

    main()

    assert capsys.readouterr().out == (
        f"file=0x{image_offset + pattern_offset:06X} "
        f"firmware=0x{pattern_offset:06X} "
        f"bank=0 address=0x{pattern_offset:04X} "
        "bytes=DE AD BE EF 42\n"
    )
