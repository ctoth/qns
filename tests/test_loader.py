"""Firmware loader and English-boundary discovery tests."""

import pytest

from qns.loader import EnglishBoundary, find_english_boundary

MFULL3_SHAPES = ("bsp", "nfb99-braille-lite", "2003-braille-lite")


def make_mfull3_image(
    capture_addr: int,
    spbuf: int,
    shape: str = "bsp",
    size: int = 0x10000,
) -> bytes:
    """Place one linked MFULL3 signature into an otherwise empty image."""
    prologue = bytes((
        0x21, spbuf & 0xFF, spbuf >> 8,  # LD HL,SPBUF
        0xAF, 0x47, 0x79, 0xB7,          # XOR A; LD B,A; LD A,C; OR A
        0x28, 0x4D,                      # JR Z,d
    ))
    speech_enable = bytes((0x3A, 0x35, 0xE6, 0xB7, 0xCC, 0xCF, 0x59))
    display = bytes((0x3A, 0x49, 0xD4, 0xCB, 0x5F, 0x28, 0x4D))
    spmain_spon = bytes((0xCD, 0x15, 0x59, 0xCD, 0x14, 0x08))
    body = {
        "bsp": prologue + speech_enable + spmain_spon,
        "nfb99-braille-lite": prologue + display + speech_enable + spmain_spon,
        "2003-braille-lite": (
            prologue + speech_enable + display
            + spmain_spon + bytes((0xCD, 0x8F, 0xBC))
        ),
    }[shape]

    image = bytearray(size)
    start = capture_addr - 3
    image[start:start + len(body)] = body
    return bytes(image)


@pytest.mark.parametrize("shape", MFULL3_SHAPES)
def test_find_english_boundary_locates_each_linked_shape(shape):
    image = make_mfull3_image(0xBC9B, 0xD657, shape)

    assert find_english_boundary(image) == EnglishBoundary(
        capture_addr=0xBC9B,
        spbuf=0xD657,
    )


def test_find_english_boundary_requires_a_unique_site():
    first = make_mfull3_image(0x8000, 0xD657)
    second = make_mfull3_image(0x9000, 0xD657)
    image = bytes(a | b for a, b in zip(first, second))

    assert find_english_boundary(image) is None


def test_find_english_boundary_absent_signature_yields_none():
    assert find_english_boundary(bytes(0x10000)) is None


def test_find_english_boundary_ignores_sites_outside_bank_zero():
    image = bytes(0x10000) + make_mfull3_image(0x8000, 0xD657)

    assert find_english_boundary(image) is None
