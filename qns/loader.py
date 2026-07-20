"""Firmware extraction from BNS ROM files and update packages.

BNS update packages append the raw firmware image at a 4 KiB-aligned
``IMAGE_OFFSET``, preceded by six metadata bytes: the image's 32-bit
little-endian length and 16-bit CRC (``update/BEUPDATE.C`` in the BNS
source).  The offset varies by package generation (0x3000 for classic
packages, 0x7000/0x8000 for Millennium), so the boundary is discovered
from the metadata rather than assumed.
"""

from dataclasses import dataclass
from pathlib import Path

_PRE_EXTRACTED_SIZES = (0x10000, 0x40000)

@dataclass(frozen=True)
class _Insn:
    """One Z180 instruction shape: literal opcode, wildcarded operands."""

    mnemonic: str
    opcode: tuple[int, ...]
    operand_bytes: int = 0

    def tokens(self) -> "list[int | None]":
        """Match tokens: opcode bytes literal, operand bytes wildcards."""
        return list(self.opcode) + [None] * self.operand_bytes


_LD_HL_IMMEDIATE = _Insn("ld hl,nn", (0x21,), operand_bytes=2)
_XOR_A = _Insn("xor a", (0xAF,))
_LD_B_A = _Insn("ld b,a", (0x47,))
_LD_A_C = _Insn("ld a,c", (0x79,))
_OR_A = _Insn("or a", (0xB7,))
_JR = _Insn("jr d", (0x18,), operand_bytes=1)
_JR_Z = _Insn("jr z,d", (0x28,), operand_bytes=1)
_LD_A_MEMORY = _Insn("ld a,(nn)", (0x3A,), operand_bytes=2)
_LD_MEMORY_A = _Insn("ld (nn),a", (0x32,), operand_bytes=2)
_LD_A_7D = _Insn("ld a,7dh", (0x3E, 0x7D))
_LD_HL_INDIRECT_ZERO = _Insn("ld (hl),0", (0x36, 0x00))
_BIT_3_A = _Insn("bit 3,a", (0xCB, 0x5F))
_CALL_Z = _Insn("call z,nn", (0xCC,), operand_bytes=2)
_CALL = _Insn("call nn", (0xCD,), operand_bytes=2)

# BSSPEECH.ASM::MFULL3 around `LD HL,SPBUF` (see NOTES.md).  Every link
# starts with the same prologue; the speech-enable test is always
# present; Braille Lite builds add a display test — before the
# speech-enable test in the NFB99 links, after it in the 2003 links.
_MFULL3_PROLOGUE = (_LD_HL_IMMEDIATE, _XOR_A, _LD_B_A, _LD_A_C, _OR_A, _JR_Z)
_SPEECH_ENABLE_TEST = (_LD_A_MEMORY, _OR_A, _CALL_Z)
_DISPLAY_TEST = (_LD_A_MEMORY, _BIT_3_A, _JR_Z)

_ENGLISH_SIGNATURES = (
    # BSP/BS2/TNS: no display test; CALL _SPMAIN; CALL SPON
    _MFULL3_PROLOGUE + _SPEECH_ENABLE_TEST + (_CALL, _CALL),
    # NFB99 Braille Lite: display test first
    _MFULL3_PROLOGUE + _DISPLAY_TEST + _SPEECH_ENABLE_TEST + (_CALL, _CALL),
    # 2003 Braille Lite: speech-enable test first
    _MFULL3_PROLOGUE
    + _SPEECH_ENABLE_TEST
    + _DISPLAY_TEST
    + (_CALL, _CALL, _CALL),
)


@dataclass(frozen=True)
class FirmwareImage:
    """One extracted firmware image and its package provenance."""

    data: bytes
    package_size: int
    kind: str
    """"package" (extracted from an update package), "pre-extracted"
    (a .bin dump), or "raw" (already a bare firmware image)."""

    image_offset: int | None
    """Offset of the image inside its update package, or None unless
    ``kind`` is "package"."""


def load_firmware(path: Path | str) -> FirmwareImage:
    """Extract firmware from a raw image, .bin dump, or update package."""
    path = Path(path)
    data = path.read_bytes()
    package_size = len(data)

    if path.suffix.lower() == ".bin" and len(data) in _PRE_EXTRACTED_SIZES:
        return FirmwareImage(
            data=data,
            package_size=package_size,
            kind="pre-extracted",
            image_offset=None,
        )

    if len(data) >= 5 and data[2:5] == b"BNS":
        image_offset = _find_image_offset(data)
        return FirmwareImage(
            data=data[image_offset:],
            package_size=package_size,
            kind="package",
            image_offset=image_offset,
        )

    return FirmwareImage(
        data=data,
        package_size=package_size,
        kind="raw",
        image_offset=None,
    )


@dataclass(frozen=True)
class EnglishBoundary:
    """The firmware's exact-English observation point (see NOTES.md)."""

    capture_addr: int
    """Bank-zero address of the instruction after `LD HL,SPBUF`, where
    HL still holds SPBUF and the buffer holds the complete utterance."""

    spbuf: int
    """Logical address of the fixed SPBUF pre-translation text buffer."""


def find_english_boundary(firmware: bytes) -> EnglishBoundary | None:
    """Locate this firmware revision's `MFULL3` speech-path signature.

    Scans only the first 64 KiB bank: the capture address is compared
    against bank-zero physical addresses at runtime, so a site outside
    that bank could never fire.  Returns None unless exactly one site
    matches, so an ambiguous image yields no capture rather than a
    wrong one.
    """
    bank = firmware[:0x10000]
    matches = [
        offset
        for signature in _ENGLISH_SIGNATURES
        for offset in _find_signature(bank, signature)
    ]
    if len(matches) != 1:
        return None
    offset = matches[0]
    # Capture right after LD HL,SPBUF; its operand is SPBUF itself.
    return EnglishBoundary(
        capture_addr=offset + len(_LD_HL_IMMEDIATE.tokens()),
        spbuf=firmware[offset + 1] | (firmware[offset + 2] << 8),
    )


# BS.ASM::STARTA's command-loop epoch open: the timer address is the
# LD HL operand and the linked write instruction is the LD (HL),0.
_STARTA_SIGNATURE = (
    _XOR_A,
    _LD_MEMORY_A,
    _LD_HL_IMMEDIATE,
    _LD_HL_INDIRECT_ZERO,
    _CALL,
)

# The keyboard ISR's chord-accept tail: the accepted chord is stored to
# the firmware input buffer (_IIB), whose address is the first LD (nn),A
# operand.  The LD A,7DH marker constant precedes it in every supplied
# link, classic and 2003 alike.
_CHORD_ACCEPT_SIGNATURE = (
    _LD_A_7D,
    _JR,
    _LD_MEMORY_A,
    _XOR_A,
    _LD_MEMORY_A,
    _JR,
)

# Every supplied runtime maps the command-loop common area with CBR=34
# (see NOTES.md's live MMU records), which converts the logical operand
# addresses above into the physical addresses our callbacks receive.
_COMMON_AREA_CBR = 0x34


def _sequence_offset(signature: tuple[_Insn, ...], insn: _Insn) -> int:
    """Byte offset of an instruction's first occurrence in a sequence."""
    offset = 0
    for candidate in signature:
        if candidate is insn:
            return offset
        offset += len(candidate.tokens())
    raise ValueError(f"{insn.mnemonic} not in signature")


@dataclass(frozen=True)
class InputBoundary:
    """The firmware's chord-acceptance addresses (see NOTES.md)."""

    keyboard_input_buffer: int
    """Physical address of the firmware chord input buffer (_IIB)."""

    command_loop_timer: int
    """Physical address of the timer cleared at each command-loop epoch."""

    command_loop_timer_pc: int
    """Linked address of the STARTA instruction that clears that timer."""


def find_input_boundary(firmware: bytes) -> InputBoundary | None:
    """Locate this firmware revision's chord-acceptance addresses.

    Both signatures must match exactly once in bank zero; otherwise no
    boundary is reported rather than a wrong one.
    """
    bank = firmware[:0x10000]
    starta = _find_signature(bank, _STARTA_SIGNATURE)
    accept = _find_signature(bank, _CHORD_ACCEPT_SIGNATURE)
    if len(starta) != 1 or len(accept) != 1:
        return None

    timer_operand = starta[0] + _sequence_offset(
        _STARTA_SIGNATURE, _LD_HL_IMMEDIATE
    ) + 1
    timer_logical = bank[timer_operand] | (bank[timer_operand + 1] << 8)
    buffer_operand = accept[0] + _sequence_offset(
        _CHORD_ACCEPT_SIGNATURE, _LD_MEMORY_A
    ) + 1
    buffer_logical = bank[buffer_operand] | (bank[buffer_operand + 1] << 8)

    common_base = _COMMON_AREA_CBR << 12
    return InputBoundary(
        keyboard_input_buffer=common_base + buffer_logical,
        command_loop_timer=common_base + timer_logical,
        command_loop_timer_pc=starta[0] + _sequence_offset(
            _STARTA_SIGNATURE, _LD_HL_INDIRECT_ZERO
        ),
    )


def _find_signature(data: bytes, signature: tuple[_Insn, ...]) -> list[int]:
    """Return every offset where the instruction sequence matches."""
    pattern = [token for insn in signature for token in insn.tokens()]
    first = pattern[0]
    assert first is not None  # every instruction starts with its opcode

    matches = []
    search_end = len(data) - len(pattern)
    offset = data.find(first, 0)
    while 0 <= offset <= search_end:
        if all(
            expected is None or data[offset + index] == expected
            for index, expected in enumerate(pattern)
        ):
            matches.append(offset)
        offset = data.find(first, offset + 1)
    return matches


def _find_image_offset(data: bytes) -> int:
    """Find the unique 4 KiB-aligned length/CRC-validated image boundary."""
    matches = []
    for image_offset in range(0x1000, len(data), 0x1000):
        image_length = int.from_bytes(
            data[image_offset - 6:image_offset - 2],
            "little",
        )
        if image_length != len(data) - image_offset:
            continue
        expected_crc = int.from_bytes(
            data[image_offset - 2:image_offset],
            "little",
        )
        if _package_crc(data[image_offset:]) == expected_crc:
            matches.append(image_offset)

    if len(matches) != 1:
        raise ValueError(
            "BNS update package must contain exactly one aligned "
            f"length/CRC-validated image; found {len(matches)}"
        )
    return matches[0]


def _package_crc(image: bytes) -> int:
    """Compute ``BEUPDATE.C::crc_byte`` over an appended firmware image."""
    crc = 0
    for byte in image:
        high_bit = crc & 0x8000
        crc = (crc << 1) & 0xFFFF
        crc = (crc & 0xFF00) | ((crc + byte) & 0xFF)
        if high_bit:
            crc ^= 0xA097
    return crc
