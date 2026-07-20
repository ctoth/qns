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
