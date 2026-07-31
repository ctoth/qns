"""Builders for valid synthetic BNS update packages."""


def build_update_package(image_offset: int, firmware: bytes) -> bytes:
    """Wrap firmware in a length/CRC-valid package at ``image_offset``."""
    package = bytearray(image_offset)
    package[2:5] = b"BNS"
    package[image_offset - 6 : image_offset - 2] = len(firmware).to_bytes(
        4,
        "little",
    )

    crc = 0
    for byte in firmware:
        high_bit = crc & 0x8000
        crc = (crc << 1) & 0xFFFF
        crc = (crc & 0xFF00) | ((crc + byte) & 0xFF)
        if high_bit:
            crc ^= 0xA097
    package[image_offset - 2 : image_offset] = crc.to_bytes(2, "little")
    return bytes(package) + firmware
