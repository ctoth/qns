"""Firmware loader and boundary-discovery tests."""

import pytest

from qns.loader import (
    EnglishBoundary,
    InputBoundary,
    SpeechParameters,
    find_english_boundary,
    find_input_boundary,
    find_speech_parameters,
)

# BSPMON.ASM::ISSET exactly as linked into roms/bspeng.bns at 0x02D7.
# Kept verbatim rather than reassembled: the shipped build differs from
# the source listing (a CP 0Fh/DEC A rate clamp, and a pitch bias read
# from the flag byte at 0xDA28), and discovery has to survive that.
ISSET_AS_LINKED = bytes.fromhex(
    "f5c5"                  # PUSH AF; PUSH BC
    "3afdd5" "f650" "d3c3"  # LD A,(VOLUME); OR 50h; OUT (C3),A
    "cd530a"                # CALL ssi_delay
    "3afed5" "fe0f" "2001" "3d"          # LD A,(RATE); CP 0Fh; JR NZ; DEC A
    "cb27cb27cb27cb27" "f608" "d3c2"     # SLA A x4; OR 08h; OUT (C2),A
    "cd530a"
    "3a20d6" "d3c1"         # LD A,(INFL); OUT (C1),A
    "cd530a"
    "3a02da" "47"           # LD A,(flags); LD B,A
    "3affd5"                # LD A,(PITCH)
    "e5" "2128da" "cb46" "280c" "cb56" "2008" "cb4e" "2003"
    "80" "1801" "90" "e1"   # ADD A,B / SUB B inflection bias
    "f6e0" "d3c4"           # OR E0h; OUT (C4),A
    "cd530a"
    "3ec0" "d3c0"           # LD A,C0h; OUT (C0),A
)

# BSSERIAL.ASM's Echo parameter handlers as linked at 0x02AE: EHPITC
# stores INFL and its retained NINFL shadow back to back, with EHVOL and
# EHTONE alongside.  That company is what distinguishes the retained
# cell from the working one.
HANDLER_AS_LINKED = bytes.fromhex(
    "3a9bd4" "cb27" "cb27" "3220d6" "321ed6" "18c2"  # EHPITC: INFL, NINFL
    "3a9bd4" "32fdd5" "18ba"                          # EHVOL:  VOLUME
    "3a9bd4" "e61f" "32ffd5" "18b0"                   # EHTONE: PITCH
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


def make_isset_image(size: int = 0x10000, offset: int = 0x02D7) -> bytes:
    """Place ISSET and the settings handler into an empty image."""
    image = bytearray(size)
    image[0x02AE:0x02AE + len(HANDLER_AS_LINKED)] = HANDLER_AS_LINKED
    image[offset:offset + len(ISSET_AS_LINKED)] = ISSET_AS_LINKED
    return bytes(image)


def test_find_speech_parameters_recovers_linked_addresses():
    """Round-trip the proven bspeng.bns cells, logical to physical."""
    assert find_speech_parameters(make_isset_image()) == SpeechParameters(
        volume=0x415FD,
        rate=0x415FE,
        inflection=0x4161E,
        filter_frequency=0x415FF,
    )
