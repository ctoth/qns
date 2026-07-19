"""Memory subsystem with Z180 MMU banking."""

from pathlib import Path

_STATE_MAGIC_V1 = b"QNSRAM\x00\x01"
_STATE_MAGIC_V2 = b"QNSRAM\x00\x02"

_FLASH_WINDOW_START = 0x80000
_FLASH_PAGE_SIZE = 0x80000
_FLASH_SECTOR_SIZE = 0x10000
_FLASH_ENABLE = 0x08
_FLASH_UNLOCK_1 = 0x5555
_FLASH_UNLOCK_2 = 0x2AAA


class Memory:
    """
    Z180 memory with MMU support for BNS hardware.

    Physical memory layout (from BNS hardware):
    The BNS uses "shadow RAM" - ROM and RAM overlap in the physical address space.
    - Reads from physical 0x00000-0x0FFFF return ROM data (if loaded)
    - Writes to ANY address go to RAM (shadow RAM behind ROM)
    - RAM covers the full 20-bit address space (up to 1MB)

    BNS logical memory map (from EMULATION_REPORT):
    - 0x0000-0x3FFF (16KB): Common RAM (fixed)
    - 0x4000-0x7FFF (16KB): Banked RAM (switchable via CBR)
    - 0x8000-0xFFFF (32KB): ROM + Common RAM (shadow RAM)

    z180emu handles MMU translation internally and passes physical addresses
    to our callbacks.
    """

    def __init__(
        self,
        ram_size: int = 512 * 1024,
        rom_size: int = 256 * 1024,
        flash_size: int = 0,
    ):
        # RAM covers the full address space - shadow RAM behind ROM
        self.ram = bytearray(ram_size)
        self.rom = bytearray(rom_size)
        self.rom_loaded = False  # Track if ROM data was loaded
        self.flash = bytearray((0xFF,)) * flash_size
        self.high_bank_latch = 0
        self._flash_command = "ready"

        # Track which addresses have been written to (for shadow RAM)
        self._written_addrs: set[int] = set()

        # MMU registers
        self.cbr = 0x00   # Common Base Register
        self.bbr = 0x00   # Bank Base Register
        self.cbar = 0xF0  # Common/Bank Area Register (default: all common area 0)

    def load_rom(self, data: bytes, offset: int = 0):
        """Load ROM image."""
        self.rom[offset:offset + len(data)] = data
        self.rom_loaded = True

    def load_state(self, path: Path | str) -> None:
        """Load nonvolatile RAM, shadow metadata, and optional flash bytes."""
        data = Path(path).read_bytes()
        magic_size = len(_STATE_MAGIC_V1)
        if len(data) < magic_size + 4:
            raise ValueError("not a QNS nonvolatile RAM state file")

        magic = data[:magic_size]
        if magic == _STATE_MAGIC_V1:
            header_size = magic_size + 4
            flash_size = 0
        elif magic == _STATE_MAGIC_V2:
            header_size = magic_size + 8
            if len(data) < header_size:
                raise ValueError("not a QNS nonvolatile RAM state file")
            flash_size = int.from_bytes(data[magic_size + 4:header_size], "little")
        else:
            raise ValueError("not a QNS nonvolatile RAM state file")

        ram_size = int.from_bytes(data[magic_size:magic_size + 4], "little")
        if ram_size != len(self.ram):
            raise ValueError(
                f"state RAM size is {ram_size} bytes; emulator requires {len(self.ram)}"
            )
        if magic == _STATE_MAGIC_V2 and flash_size != len(self.flash):
            raise ValueError(
                f"state flash size is {flash_size} bytes; emulator requires {len(self.flash)}"
            )

        bitmap_size = (ram_size + 7) // 8
        expected_size = header_size + bitmap_size + ram_size + flash_size
        if len(data) != expected_size:
            raise ValueError(
                f"state file is {len(data)} bytes; expected {expected_size}"
            )

        bitmap = data[header_size:header_size + bitmap_size]
        ram_end = header_size + bitmap_size + ram_size
        self.ram[:] = data[header_size + bitmap_size:ram_end]
        if flash_size:
            self.flash[:] = data[ram_end:]
        self._written_addrs = {
            address
            for address in range(ram_size)
            if bitmap[address >> 3] & (1 << (address & 7))
        }

    def save_state(self, path: Path | str) -> None:
        """Atomically save nonvolatile RAM, shadow metadata, and flash."""
        path = Path(path)
        bitmap = bytearray((len(self.ram) + 7) // 8)
        for address in self._written_addrs:
            if address < len(self.ram):
                bitmap[address >> 3] |= 1 << (address & 7)

        if self.flash:
            header = b"".join((
                _STATE_MAGIC_V2,
                len(self.ram).to_bytes(4, "little"),
                len(self.flash).to_bytes(4, "little"),
            ))
        else:
            header = b"".join((
                _STATE_MAGIC_V1,
                len(self.ram).to_bytes(4, "little"),
            ))
        data = b"".join((header, bytes(bitmap), bytes(self.ram), bytes(self.flash)))
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(data)
        temporary.replace(path)

    def read(self, addr: int) -> int:
        """Read byte from physical address (z180emu does MMU translation).

        Shadow RAM architecture:
        - The BNS has ROM that can be banked into the lower 64KB physical space
        - RAM "shadows" ROM - writes always go to RAM
        - Reads: return RAM if that address was written, otherwise ROM

        To properly implement this, we track written addresses. Any address
        that was written to returns RAM; unwritten addresses return ROM.
        """
        addr &= 0xFFFFF  # 20-bit physical address

        flash_offset = self._flash_offset(addr)
        if flash_offset is not None:
            return self.flash[flash_offset]

        # If address was written to, return RAM (shadow RAM took priority)
        if addr < len(self.ram) and addr in self._written_addrs:
            return self.ram[addr]

        # Otherwise return ROM if in ROM region
        if addr < len(self.rom) and self.rom_loaded:
            return self.rom[addr]

        # Fall back to RAM for addresses beyond ROM
        if addr < len(self.ram):
            return self.ram[addr]
        return 0xFF

    def write(self, addr: int, value: int):
        """Write byte to physical address (z180emu does MMU translation).

        Shadow RAM: ALL writes go to RAM, regardless of ROM region.
        This is how the BNS hardware works - RAM sits behind ROM.
        """
        addr &= 0xFFFFF  # 20-bit physical address
        flash_offset = self._flash_offset(addr)
        if flash_offset is not None:
            self._write_flash(flash_offset, value & 0xFF)
            return

        if addr < len(self.ram):
            self.ram[addr] = value & 0xFF
            was_new = addr not in self._written_addrs
            self._written_addrs.add(addr)  # Track for shadow RAM reads
            # Debug: track VOLUME address (0x4215C)
            if addr == 0x4215C:
                print(f"[MEM] Write to VOLUME (0x4215C): {value}")

    def set_high_bank_latch(self, value: int) -> None:
        """Select the BSNEW 512 KiB flash page and enable state."""
        self.high_bank_latch = value & 0xFF

    def _flash_offset(self, addr: int) -> int | None:
        """Translate the enabled BSNEW high-memory window into flash."""
        if not self.flash or not self.high_bank_latch & _FLASH_ENABLE:
            return None
        if not _FLASH_WINDOW_START <= addr < _FLASH_WINDOW_START + _FLASH_PAGE_SIZE:
            return None

        page = self.high_bank_latch & 0x07
        offset = page * _FLASH_PAGE_SIZE + addr - _FLASH_WINDOW_START
        return offset if offset < len(self.flash) else None

    def _write_flash(self, offset: int, value: int) -> None:
        """Apply the AMD command sequences emitted by BSNEW firmware."""
        command_offset = offset % _FLASH_PAGE_SIZE

        if self._flash_command == "program":
            self.flash[offset] &= value
            self._flash_command = "ready"
            return

        expected = {
            "ready": (_FLASH_UNLOCK_1, 0xAA, "unlock_1"),
            "unlock_1": (_FLASH_UNLOCK_2, 0x55, "unlock_2"),
            "erase": (_FLASH_UNLOCK_1, 0xAA, "erase_unlock_1"),
            "erase_unlock_1": (_FLASH_UNLOCK_2, 0x55, "erase_unlock_2"),
        }
        if self._flash_command in expected:
            address, byte, next_command = expected[self._flash_command]
            if command_offset == address and value == byte:
                self._flash_command = next_command
            else:
                self._flash_command = "ready"
            return

        if self._flash_command == "unlock_2":
            if command_offset == _FLASH_UNLOCK_1 and value == 0xA0:
                self._flash_command = "program"
            elif command_offset == _FLASH_UNLOCK_1 and value == 0x80:
                self._flash_command = "erase"
            else:
                self._flash_command = "ready"
            return

        if self._flash_command == "erase_unlock_2":
            if command_offset == _FLASH_UNLOCK_1 and value == 0x10:
                self.flash[:] = b"\xFF" * len(self.flash)
            elif value == 0x30:
                sector_start = offset - offset % _FLASH_SECTOR_SIZE
                sector_end = min(sector_start + _FLASH_SECTOR_SIZE, len(self.flash))
                self.flash[sector_start:sector_end] = b"\xFF" * (sector_end - sector_start)
            self._flash_command = "ready"

    def set_mmu(self, cbr: int | None = None, bbr: int | None = None, cbar: int | None = None):
        """Update MMU registers."""
        if cbr is not None:
            self.cbr = cbr & 0xFF
        if bbr is not None:
            self.bbr = bbr & 0xFF
        if cbar is not None:
            self.cbar = cbar & 0xFF
