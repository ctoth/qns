"""Property authorities for the real-ROM BS2 external-program verifier."""

import binascii

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tools.verify_bs2_external_program import (
    SOH,
    STX,
    TimestampedBytesIO,
    crc16_xmodem,
    ymodem_packet,
)


def test_timestamped_bytes_io_records_completion_cycles():
    """Serial evidence must preserve bytes and attribute their write cycles."""
    cycle = [10]
    output = TimestampedBytesIO(lambda: cycle[0])

    assert output.write(b"\x05\x06") == 2
    cycle[0] = 20
    assert output.write(b"C") == 1

    assert output.getvalue() == b"\x05\x06C"
    assert output.events == [(10, 0x05), (10, 0x06), (20, ord("C"))]


@settings(max_examples=100, deadline=None)
@given(data=st.binary(max_size=4096))
def test_crc16_xmodem_matches_standard_library(data: bytes):
    """Verifier CRC must match an independent CRC-16/XMODEM implementation."""
    assert crc16_xmodem(data) == binascii.crc_hqx(data, 0)


@settings(max_examples=64, deadline=None)
@given(
    block_number=st.integers(min_value=0, max_value=255),
    block_size=st.sampled_from((128, 1024)),
    data=st.data(),
)
def test_ymodem_packet_has_valid_envelope_and_crc(
    block_number: int,
    block_size: int,
    data: st.DataObject,
):
    """Every generated packet must carry an exact payload and valid complement/CRC."""
    payload = data.draw(st.binary(min_size=block_size, max_size=block_size))

    packet = ymodem_packet(block_number, payload, block_size)

    assert packet[0] == (SOH if block_size == 128 else STX)
    assert packet[1] == block_number
    assert packet[2] == 0xFF - block_number
    assert packet[3:-2] == payload
    assert int.from_bytes(packet[-2:], "big") == binascii.crc_hqx(payload, 0)
    assert len(packet) == block_size + 5


@given(
    payload=st.binary(max_size=64),
    block_size=st.sampled_from((128, 1024)),
)
def test_ymodem_packet_rejects_wrong_payload_size(payload: bytes, block_size: int):
    """Packet construction must reject every non-block-sized payload."""
    with pytest.raises(ValueError, match="expected"):
        ymodem_packet(0, payload, block_size)
