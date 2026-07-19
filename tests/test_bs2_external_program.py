"""Property authorities for the real-ROM BS2 external-program verifier."""

import binascii

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from qns.bns import _ASCII_TO_BNS_KEY
from tools.verify_bs2_external_program import (
    FLASH_CONFIRMATION_PROMPT,
    FLASH_INITIALIZATION_PROMPT,
    FLASH_INITIALIZATION_Y_KEY,
    SOH,
    STX,
    crc16_xmodem,
    is_flash_confirmation_prompt,
    is_flash_initialization_prompt,
    ymodem_packet,
)


def test_flash_initialization_uses_firmware_brlyes_chord():
    """The English ROM's BRLYES is lowercase y, not uppercase Y."""
    assert FLASH_INITIALIZATION_Y_KEY == _ASCII_TO_BNS_KEY[ord("y")]
    assert FLASH_INITIALIZATION_Y_KEY != _ASCII_TO_BNS_KEY[ord("Y")]


@given(prefix=st.lists(st.text(max_size=8), max_size=40))
def test_flash_initialization_prompt_allows_arbitrary_prior_speech(
    prefix: list[str],
):
    """Only the exact retained suffix identifies the first-boot dialogue."""
    assert is_flash_initialization_prompt(prefix + list(FLASH_INITIALIZATION_PROMPT))


def test_flash_initialization_prompt_rejects_partial_or_altered_speech():
    """A nearby boot utterance must not authorize an automatic response."""
    assert not is_flash_initialization_prompt(list(FLASH_INITIALIZATION_PROMPT[:-1]))
    altered = [*FLASH_INITIALIZATION_PROMPT[:-1], "M"]
    assert not is_flash_initialization_prompt(altered)


@given(prefix=st.lists(st.text(max_size=8), max_size=40))
def test_flash_confirmation_prompt_allows_arbitrary_prior_speech(
    prefix: list[str],
):
    """The second destructive-action prompt is matched as an exact suffix."""
    assert is_flash_confirmation_prompt(prefix + list(FLASH_CONFIRMATION_PROMPT))


def test_flash_confirmation_prompt_rejects_partial_or_altered_speech():
    """The second BRLYES response requires the complete confirmation prompt."""
    assert not is_flash_confirmation_prompt(list(FLASH_CONFIRMATION_PROMPT[:-1]))
    altered = [*FLASH_CONFIRMATION_PROMPT[:-1], "M"]
    assert not is_flash_confirmation_prompt(altered)


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
