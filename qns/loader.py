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
_LD_HL_MEMORY = _Insn("ld hl,(nn)", (0x2A,), operand_bytes=2)
_XOR_A = _Insn("xor a", (0xAF,))
_DI = _Insn("di", (0xF3,))
_LD_B_H = _Insn("ld b,h", (0x44,))
_LD_C_L = _Insn("ld c,l", (0x4D,))
_LD_B_A = _Insn("ld b,a", (0x47,))
_LD_A_C = _Insn("ld a,c", (0x79,))
_LD_A_IMMEDIATE = _Insn("ld a,n", (0x3E,), operand_bytes=1)
_LD_A_HL_INDIRECT = _Insn("ld a,(hl)", (0x7E,))
_OR_A = _Insn("or a", (0xB7,))
_CP_HL_INDIRECT = _Insn("cp (hl)", (0xBE,))
_JR = _Insn("jr d", (0x18,), operand_bytes=1)
_JR_Z = _Insn("jr z,d", (0x28,), operand_bytes=1)
_JR_NZ = _Insn("jr nz,d", (0x20,), operand_bytes=1)
_LD_A_MEMORY = _Insn("ld a,(nn)", (0x3A,), operand_bytes=2)
_LD_MEMORY_A = _Insn("ld (nn),a", (0x32,), operand_bytes=2)
_LD_A_7D = _Insn("ld a,7dh", (0x3E, 0x7D))
_LD_A_02 = _Insn("ld a,02h", (0x3E, 0x02))
_LD_A_64 = _Insn("ld a,64h", (0x3E, 0x64))
_LD_HL_INDIRECT_ZERO = _Insn("ld (hl),0", (0x36, 0x00))
_INC_HL_INDIRECT = _Insn("inc (hl)", (0x34,))
_LD_HL_INDIRECT_C = _Insn("ld (hl),c", (0x71,))
_INC_HL = _Insn("inc hl", (0x23,))
_LD_HL_INDIRECT_B = _Insn("ld (hl),b", (0x70,))
_BIT_3_A = _Insn("bit 3,a", (0xCB, 0x5F))
_CALL_Z = _Insn("call z,nn", (0xCC,), operand_bytes=2)
_CALL = _Insn("call nn", (0xCD,), operand_bytes=2)
_HALT = _Insn("halt", (0x76,))

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
    _MFULL3_PROLOGUE + _SPEECH_ENABLE_TEST + _DISPLAY_TEST + (_CALL, _CALL, _CALL),
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
        offset for signature in _ENGLISH_SIGNATURES for offset in _find_signature(bank, signature)
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

# BSKEY.ASM::_put_key's queue append prologue: the first LD HL operand is
# queue_count.  The queue-size immediate differs by hardware family.
_KEY_QUEUE_SIGNATURE = (
    _DI,
    _LD_B_H,
    _LD_C_L,
    _LD_HL_IMMEDIATE,
    _LD_A_IMMEDIATE,
    _CP_HL_INDIRECT,
    _JR_Z,
    _INC_HL_INDIRECT,
    _LD_HL_MEMORY,
    _LD_HL_INDIRECT_C,
    _INC_HL,
    _LD_HL_INDIRECT_B,
)

# BSKEY.ASM::_get_key's application wait.  Most links read the background
# timer before HALT; BL2 omits that read.  The LD HL operand is queue_count,
# and readiness is observed at the following LD A,(HL).
_KEY_WAIT_SIGNATURES = (
    (
        _LD_HL_IMMEDIATE,
        _LD_A_HL_INDIRECT,
        _OR_A,
        _JR_NZ,
        _LD_A_MEMORY,
        _HALT,
        _CALL,
        _JR,
    ),
    (
        _LD_HL_IMMEDIATE,
        _LD_A_HL_INDIRECT,
        _OR_A,
        _JR_NZ,
        _HALT,
        _CALL,
        _JR,
    ),
)

# BS.ASM::WARM0 initializes the serial handshake immediately before writing
# COMBYT=64h.  That write proves every source-defined warm or cold reset has
# accepted its held startup gesture.  COMBYT is linked at a revision-specific
# address, so discover it rather than retaining the old BS2 address.
_RESET_COMPLETE_SIGNATURE = (
    _LD_A_02,
    _LD_MEMORY_A,
    _CALL,
    _LD_A_64,
    _LD_MEMORY_A,
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

    keyboard_queue_count: int
    """Physical address of the firmware application's queued-key count."""

    keyboard_wait_pc: int
    """Linked `_get_key` instruction that reads the queued-key count."""

    command_loop_timer: int
    """Physical address of the timer cleared at each command-loop epoch."""

    command_loop_timer_pc: int
    """Linked address of the STARTA instruction that clears that timer."""

    reset_complete: int
    """Physical COMBYT write proving a power-on reset gesture was accepted."""


def find_input_boundary(firmware: bytes) -> InputBoundary | None:
    """Locate this firmware revision's chord-acceptance addresses.

    All signatures must match exactly once in bank zero; otherwise no
    boundary is reported rather than a wrong one.
    """
    bank = firmware[:0x10000]
    starta = _find_signature(bank, _STARTA_SIGNATURE)
    accept = _find_signature(bank, _CHORD_ACCEPT_SIGNATURE)
    key_queue = _find_signature(bank, _KEY_QUEUE_SIGNATURE)
    reset_complete = _find_signature(bank, _RESET_COMPLETE_SIGNATURE)
    if len(starta) != 1 or len(accept) != 1 or len(key_queue) != 1 or len(reset_complete) != 1:
        return None

    timer_operand = starta[0] + _sequence_offset(_STARTA_SIGNATURE, _LD_HL_IMMEDIATE) + 1
    timer_logical = bank[timer_operand] | (bank[timer_operand + 1] << 8)
    buffer_operand = accept[0] + _sequence_offset(_CHORD_ACCEPT_SIGNATURE, _LD_MEMORY_A) + 1
    buffer_logical = bank[buffer_operand] | (bank[buffer_operand + 1] << 8)
    queue_operand = key_queue[0] + _sequence_offset(_KEY_QUEUE_SIGNATURE, _LD_HL_IMMEDIATE) + 1
    queue_logical = bank[queue_operand] | (bank[queue_operand + 1] << 8)
    reset_operand = (
        reset_complete[0]
        + _sequence_offset(_RESET_COMPLETE_SIGNATURE, _LD_A_64)
        + len(_LD_A_64.tokens())
        + 1
    )
    reset_logical = bank[reset_operand] | (bank[reset_operand + 1] << 8)
    key_waits = [
        offset
        for signature in _KEY_WAIT_SIGNATURES
        for offset in _find_signature(bank, signature)
        if bank[offset + 1] | (bank[offset + 2] << 8) == queue_logical
    ]
    if len(key_waits) != 1:
        return None

    common_base = _COMMON_AREA_CBR << 12
    return InputBoundary(
        keyboard_input_buffer=common_base + buffer_logical,
        keyboard_queue_count=common_base + queue_logical,
        keyboard_wait_pc=key_waits[0] + len(_LD_HL_IMMEDIATE.tokens()),
        command_loop_timer=common_base + timer_logical,
        command_loop_timer_pc=starta[0] + _sequence_offset(_STARTA_SIGNATURE, _LD_HL_INDIRECT_ZERO),
        reset_complete=common_base + reset_logical,
    )


@dataclass(frozen=True)
class SpeechParameters:
    """Physical addresses of the four retained speech settings.

    `BSPMON.ASM::ISSET` applies these to the SSI-263 on every utterance.
    They live in the monitor's uninitialised `DS` scratch area and no
    shipped code path ever gives them a value: a field unit carries them
    in battery-backed RAM, set once through the parameter handler
    (`BSSERIAL.ASM::EHVOL`/`EHPITC`/`EHTONE`).  An emulator that starts
    RAM at zero therefore makes the firmware write amplitude 0 - correct
    emulation of an uninitialised machine, but silence.

    These names cross badly, so the fields below are named for the chip
    register each cell reaches, which is the one unambiguous sense.  The
    firmware variable `PITCH` drives the chip's *filter frequency*, and
    the API (`BSAPI.C::api_speech_parms`) in turn calls that byte
    "Pitch" while calling the *inflection* byte "Frequency".

    Each field lists every cell that holds its setting.  Rate and
    inflection are held twice: ISSET reads a working cell (`RATE`,
    `INFL`) that the firmware rebuilds for each utterance from a
    retained shadow (`NRATE`, `NINFL`) - applying, for inflection, the
    intonation markers `BRL.ASM::INTON` inserts.  Seeding only one of a
    pair does not hold: the working cell is overwritten from the shadow
    partway through boot, and the shadow alone leaves the setting wrong
    until the first rebuild.

    Addresses are physical, matching InputBoundary and the addresses our
    memory callbacks receive.
    """

    volume: tuple[int, ...]
    """`VOLUME` -> amplitude nibble of the control register (C3)."""

    rate: tuple[int, ...]
    """`RATE`, `NRATE` -> speaking-speed nibble (C2)."""

    inflection: tuple[int, ...]
    """`INFL`, `NINFL` -> inflection register (C1).  API name: "Frequency"."""

    filter_frequency: tuple[int, ...]
    """`PITCH` -> filter-frequency register (C4).  API name: "Pitch"."""


# The midpoint of each setting's documented range.  `BSAPI.H` and
# `BNSAPI.H` both specify them, agreeing exactly:
#
#     Volume 0..15   Pitch 1..32   Rate 1..16   Frequency 0..255
#
# where the API's "Pitch" is the filter-frequency cell and its
# "Frequency" is the inflection cell (see SpeechParameters).  Nothing in
# the firmware records what a unit actually shipped with - the values in
# BSSPEECH.ASM::ISINIT are unreachable dead code - so the midpoint is a
# deliberate neutral choice, not a recovered default.
RETAINED_SPEECH_DEFAULTS = {
    "volume": 8,
    "rate": 9,
    "inflection": 128,
    "filter_frequency": 17,
}
FIFTH_RETAINED_SPEECH_CELL_DEFAULT = 2

# BS.ASM::DOPITCH recognizes the translator's low/normal/high marker bytes,
# calculates INFL +/- 1Bh, then consults _VIFLAG before writing the new value.
# Source initialization stores 1 in that retained flag by default.
_DOPITCH_SIGNATURE = (
    0xFE,
    0x3C,
    0x28,
    None,
    0xFE,
    0x3D,
    0x28,
    None,
    0xFE,
    0x3E,
    0xC0,
    0x3A,
    None,
    None,
    0xC6,
    0x1B,
    0x18,
    None,
    0x3A,
    None,
    None,
    0xD6,
    0x1B,
    0x30,
    None,
    0x3A,
    None,
    None,
    0xF5,
    0x3A,
    None,
    None,
    0xCB,
    0x47,
    0x28,
    None,
    0xF1,
    0x32,
    None,
    None,
    0x32,
    None,
    None,
    0xED,
    0x39,
)
_DOPITCH_VIFLAG_OPERAND = 30


def find_voice_inflection_flag(firmware: bytes) -> int | None:
    """Locate the physical `_VIFLAG` byte read by English DOPITCH."""
    bank = firmware[:0x10000]
    matches = [
        start
        for start in range(len(bank) - len(_DOPITCH_SIGNATURE) + 1)
        if all(
            expected is None or bank[start + offset] == expected
            for offset, expected in enumerate(_DOPITCH_SIGNATURE)
        )
    ]
    if len(matches) != 1:
        return None
    operand = matches[0] + _DOPITCH_VIFLAG_OPERAND
    logical = bank[operand] | (bank[operand + 1] << 8)
    if logical < _LOWEST_RAM_ADDRESS:
        return None
    return logical + (_COMMON_AREA_CBR << 12)


def find_fifth_retained_speech_cell(firmware: bytes) -> int | None:
    """Locate the fifth retained speech cell relative to `_VIFLAG`.

    Both supported BSP revisions place this otherwise unnamed retained byte
    two cells after the voice-inflection flag. A reset initializes it to 2,
    while an ordinary boot leaves it untouched.
    """
    voice_inflection_flag = find_voice_inflection_flag(firmware)
    if voice_inflection_flag is None:
        return None
    return voice_inflection_flag + 2


# ISSET writes each setting as `LD A,(param)` ... `OUT (reg),A`, so the
# operand of the nearest preceding `LD A,(nn)` names the RAM cell.  The
# volume write anchors the routine: `OR 50h` into the control register
# (CTL low, articulation 5) appears nowhere else.
_ISSET_ANCHOR = (0xF6, 0x50, 0xD3)
_ISSET_WINDOW = 0x60
_HANDLER_WINDOW = 0x40
_LOWEST_RAM_ADDRESS = 0x8000


def find_speech_parameters(
    firmware: bytes,
    ssi263_port: int = 0xC0,
) -> SpeechParameters | None:
    """Locate this revision's retained speech-setting RAM cells.

    Returns None unless exactly one `ISSET` matches and all four cells
    resolve to RAM, so an unrecognised image yields no addresses rather
    than wrong ones.
    """
    bank = firmware[:0x10000]
    anchor = bytes(_ISSET_ANCHOR) + bytes((ssi263_port + 3,))
    starts = [
        offset
        for offset in range(len(bank) - 3 - len(anchor))
        if bank[offset] == _LD_A_MEMORY.opcode[0]
        and bank[offset + 3 : offset + 3 + len(anchor)] == anchor
    ]
    if len(starts) != 1:
        return None

    start = starts[0]
    window = bank[start : start + _ISSET_WINDOW]
    addresses = {"volume": _operand(window, 0)}
    for field, register in (
        ("rate", 2),
        ("inflection", 1),
        ("filter_frequency", 4),
    ):
        address = _parameter_before_out(window, ssi263_port + register)
        if address is None:
            return None
        addresses[field] = address

    cells = {field: (address,) for field, address in addresses.items()}
    for field in ("rate", "inflection"):
        shadow = _retained_shadow(bank, addresses[field], addresses["volume"])
        if shadow is None:
            return None
        cells[field] += (shadow,)

    if any(address < _LOWEST_RAM_ADDRESS for field in cells.values() for address in field):
        return None
    common_base = _COMMON_AREA_CBR << 12
    return SpeechParameters(
        **{
            field: tuple(address + common_base for address in addresses)
            for field, addresses in cells.items()
        }
    )


@dataclass(frozen=True)
class SpeechPowerTimeout:
    """The speech-power turn-off threshold and the value it should hold."""

    address: int
    """Physical address of `SPTIMVA`."""

    value: int
    """What the firmware's own initialiser stores there."""


# BSBGTASK.ASM::TIMSTAT, which quiesces the speech chip once the idle
# counter reaches its threshold:
#
#     LD A,(SPTIMER) / LD HL,SPTIMVA / CP (HL) / CALL NC,SPOFF
#
# `CALL NC` fires on SPTIMER >= SPTIMVA, so a threshold left at zero
# makes it fire on every pass - writing `VOLUME AND 70h`, which is
# always amplitude zero, roughly every 50 ms.  That silences a phoneme
# mid-word.  The threshold's initialiser is not reached on our boot, so
# take the value it would have stored.
_TIMSTAT_SIGNATURE = (
    _LD_A_MEMORY,
    _LD_HL_IMMEDIATE,
    _Insn("cp (hl)", (0xBE,)),
    _Insn("call nc,nn", (0xD4,), operand_bytes=2),
)


def find_speech_power_timeout(firmware: bytes) -> SpeechPowerTimeout | None:
    """Locate `SPTIMVA` and the constant the firmware initialises it to."""
    bank = firmware[:0x10000]
    matches = _find_signature(bank, _TIMSTAT_SIGNATURE)
    if len(matches) != 1:
        return None
    threshold = _operand(bank, matches[0] + len(_LD_A_MEMORY.tokens()))
    if threshold < _LOWEST_RAM_ADDRESS:
        return None

    # `LD A,n / LD (SPTIMVA),A` is the only place the constant appears.
    store = bytes((_LD_A_IMMEDIATE.opcode[0],))
    tail = bytes((_LD_MEMORY_A.opcode[0],)) + _address_bytes(threshold)
    values = {
        bank[offset + 1]
        for offset in range(len(bank) - 5)
        if bank[offset] == store[0] and bank[offset + 2 : offset + 5] == tail
    }
    if len(values) != 1:
        return None
    return SpeechPowerTimeout(
        address=threshold + (_COMMON_AREA_CBR << 12),
        value=values.pop(),
    )


def _retained_shadow(bank: bytes, working: int, volume: int) -> int | None:
    """Address of the retained shadow a settings handler writes.

    `BSSERIAL.ASM::EHPITC` and its rate counterpart store the new value
    to the working cell and its shadow back to back.  Other routines
    store the same working cell beside a different cell entirely, so a
    settings handler is identified by the company it keeps: it writes
    the other retained settings within the same routine.

    Several handlers may qualify - the live one and BSSPEECH.ASM's dead
    ISINIT both do - so they are required to agree rather than to be
    unique.
    """
    pair = (
        bytes((_LD_MEMORY_A.opcode[0],))
        + _address_bytes(working)
        + bytes((_LD_MEMORY_A.opcode[0],))
    )
    volume_store = bytes((_LD_MEMORY_A.opcode[0],)) + _address_bytes(volume)

    shadows = set()
    offset = bank.find(pair)
    while offset >= 0:
        start = max(0, offset - _HANDLER_WINDOW)
        if volume_store in bank[start : offset + _HANDLER_WINDOW]:
            shadows.add(_operand(bank, offset + 3))
        offset = bank.find(pair, offset + 1)

    if len(shadows) != 1:
        return None
    return shadows.pop()


def _address_bytes(address: int) -> bytes:
    """Little-endian encoding of a 16-bit operand."""
    return bytes((address & 0xFF, address >> 8))


def _parameter_before_out(window: bytes, register: int) -> int | None:
    """Operand of the last `LD A,(nn)` fully preceding `OUT (register),A`."""
    out = window.find(bytes((0xD3, register)))
    if out < 0:
        return None
    load = window.rfind(bytes(_LD_A_MEMORY.opcode), 0, out - 2)
    if load < 0:
        return None
    return _operand(window, load)


def _operand(data: bytes, offset: int) -> int:
    """Little-endian 16-bit operand of the instruction at ``offset``."""
    return data[offset + 1] | (data[offset + 2] << 8)


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
            data[image_offset - 6 : image_offset - 2],
            "little",
        )
        if image_length != len(data) - image_offset:
            continue
        expected_crc = int.from_bytes(
            data[image_offset - 2 : image_offset],
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
