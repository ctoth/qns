"""Firmware loader and boundary-discovery tests."""

import pytest

from qns.loader import (
    EnglishBoundary,
    InputBoundary,
    find_english_boundary,
    find_input_boundary,
)

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


def make_input_boundary_image(
    timer_pc: int,
    timer_logical: int,
    buffer_logical: int,
    queue_logical: int = 0xDA32,
    reset_logical: int = 0xD4B0,
    size: int = 0x10000,
) -> bytes:
    """Place the input-boundary signatures into an empty image."""
    starta = bytes((
        0xAF,                                            # XOR A
        0x32, 0x4C, 0xD6,                                # LD (nn),A
        0x21, timer_logical & 0xFF, timer_logical >> 8,  # LD HL,timer
        0x36, 0x00,                                      # LD (HL),0
        0xCD, 0x2F, 0x13,                                # CALL nn
    ))
    accept = bytes((
        0x3E, 0x7D,                                        # LD A,7DH
        0x18, 0xE1,                                        # JR d
        0x32, buffer_logical & 0xFF, buffer_logical >> 8,  # LD (_IIB),A
        0xAF,                                              # XOR A
        0x32, 0x68, 0xD4,                                  # LD (nn),A
        0x18, 0x0E,                                        # JR d
    ))
    key_queue = bytes((
        0xF3,                                                # DI
        0x44,                                                # LD B,H
        0x4D,                                                # LD C,L
        0x21, queue_logical & 0xFF, queue_logical >> 8,      # LD HL,count
        0x3E, 0x40,                                          # LD A,queue size
        0xBE,                                                # CP (HL)
        0x28, 0x18,                                          # JR Z,d
        0x34,                                                # INC (HL)
        0x2A, 0x33, 0xDA,                                    # LD HL,(queue in)
        0x71,                                                # LD (HL),C
        0x23,                                                # INC HL
        0x70,                                                # LD (HL),B
    ))
    key_wait = bytes((
        0x21, queue_logical & 0xFF, queue_logical >> 8,      # LD HL,count
        0x7E,                                                # LD A,(HL)
        0xB7,                                                # OR A
        0x20, 0x09,                                          # JR NZ,d
        0x3A, timer_logical & 0xFF, timer_logical >> 8,      # LD A,(timer)
        0x76,                                                # HALT
        0xCD, 0x2F, 0x13,                                    # CALL nn
        0x18, 0xF0,                                          # JR d
    ))
    reset_complete = bytes((
        0x3E, 0x02,                                            # LD A,2
        0x32, 0xAF, 0xD4,                                      # LD (HNDSHK),A
        0xCD, 0x00, 0x20,                                      # CALL flush
        0x3E, 0x64,                                            # LD A,64H
        0x32, reset_logical & 0xFF, reset_logical >> 8,        # LD (COMBYT),A
    ))
    image = bytearray(size)
    starta_offset = timer_pc - 7
    image[starta_offset:starta_offset + len(starta)] = starta
    image[0x0B00:0x0B00 + len(accept)] = accept
    image[0x0C00:0x0C00 + len(key_queue)] = key_queue
    image[0x0D00:0x0D00 + len(key_wait)] = key_wait
    image[0x0E00:0x0E00 + len(reset_complete)] = reset_complete
    return bytes(image)


def test_find_input_boundary_recovers_linked_addresses():
    """Round-trip through the proven NFB99 BSP addresses (NOTES.md)."""
    image = make_input_boundary_image(
        timer_pc=0x0A0D,
        timer_logical=0xD653,
        buffer_logical=0xF27C,
    )

    assert find_input_boundary(image) == InputBoundary(
        keyboard_input_buffer=0x4327C,
        keyboard_queue_count=0x41A32,
        keyboard_wait_pc=0x0D03,
        command_loop_timer=0x41653,
        command_loop_timer_pc=0x0A0D,
        reset_complete=0x414B0,
    )


def test_find_input_boundary_requires_all_signatures():
    complete = make_input_boundary_image(0x0A0D, 0xD653, 0xF27C)
    starta_only = bytearray(complete)
    starta_only[0x0B00:0x0B10] = bytes(0x10)
    no_queue = bytearray(complete)
    no_queue[0x0C00:0x0C20] = bytes(0x20)
    no_wait = bytearray(complete)
    no_wait[0x0D00:0x0D20] = bytes(0x20)
    no_reset = bytearray(complete)
    no_reset[0x0E00:0x0E20] = bytes(0x20)

    assert find_input_boundary(bytes(starta_only)) is None
    assert find_input_boundary(bytes(no_queue)) is None
    assert find_input_boundary(bytes(no_wait)) is None
    assert find_input_boundary(bytes(no_reset)) is None
    assert find_input_boundary(bytes(0x10000)) is None
