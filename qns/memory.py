"""QNS-owned firmware image, effective RAM state, and banked flash."""

from pathlib import Path

_STATE_MAGIC_V1 = b"QNSRAM\x00\x01"
_STATE_MAGIC_V2 = b"QNSRAM\x00\x02"
_STATE_MAGIC_V3 = b"QNSRAM\x00\x03"

_FLASH_WINDOW_START = 0x80000
_FLASH_PAGE_SIZE = 0x80000
_FLASH_SECTOR_SIZE = 0x10000
_FLASH_ENABLE = 0x08
_FLASH_UNLOCK_1 = 0x5555
_FLASH_UNLOCK_2 = 0x2AAA


class Memory:
    """Own retained ROM bytes, z-core's effective RAM view, and external flash.

    z-core owns MMU translation and the 512 KiB RAM hot path. QNS retains the
    firmware image for discovery and legacy-state conversion, and its callbacks
    serve only the optional banked flash aperture.
    """

    def __init__(
        self,
        ram_size: int = 512 * 1024,
        rom_size: int = 256 * 1024,
        flash_size: int = 0,
    ):
        # BNS replaces this with z-core's writable zero-copy RAM view.
        self.ram: bytearray | memoryview = bytearray(ram_size)
        self.rom = bytearray(rom_size)
        self.flash = bytearray((0xFF,)) * flash_size
        self.high_bank_latch = 0
        self._flash_command = "ready"

        # MMU registers
        self.cbr = 0x00   # Common Base Register
        self.bbr = 0x00   # Bank Base Register
        self.cbar = 0xF0  # Common/Bank Area Register (default: all common area 0)

    def load_rom(self, data: bytes, offset: int = 0) -> None:
        """Initialize effective RAM and the retained firmware image."""
        if offset < 0 or offset + len(data) > len(self.ram):
            raise ValueError("ROM image exceeds configured RAM size")
        if offset + len(data) > len(self.rom):
            raise ValueError("ROM image exceeds configured ROM size")
        self.ram[:] = b"\x00" * len(self.ram)
        self.rom[:] = b"\x00" * len(self.rom)
        self.ram[offset:offset + len(data)] = data
        self.rom[offset:offset + len(data)] = data

    def load_state(self, path: Path | str) -> None:
        """Load effective RAM, converting legacy shadow-RAM state when needed."""
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
        elif magic == _STATE_MAGIC_V3:
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
        if magic in (_STATE_MAGIC_V2, _STATE_MAGIC_V3) and flash_size != len(self.flash):
            raise ValueError(
                f"state flash size is {flash_size} bytes; emulator requires {len(self.flash)}"
            )

        legacy = magic in (_STATE_MAGIC_V1, _STATE_MAGIC_V2)
        bitmap_size = (ram_size + 7) // 8 if legacy else 0
        expected_size = header_size + bitmap_size + ram_size + flash_size
        if len(data) != expected_size:
            raise ValueError(
                f"state file is {len(data)} bytes; expected {expected_size}"
            )

        bitmap = data[header_size:header_size + bitmap_size]
        ram_end = header_size + bitmap_size + ram_size
        stored_ram = data[header_size + bitmap_size:ram_end]
        if legacy:
            effective_ram = bytearray(self.ram)
            for address, value in enumerate(stored_ram):
                if address >= len(self.rom) or bitmap[address >> 3] & (1 << (address & 7)):
                    effective_ram[address] = value
        else:
            effective_ram = stored_ram

        self.ram[:] = effective_ram
        if flash_size:
            self.flash[:] = data[ram_end:]

    def save_state(self, path: Path | str) -> None:
        """Atomically save V3 effective RAM and flash."""
        path = Path(path)
        header = b"".join((
            _STATE_MAGIC_V3,
            len(self.ram).to_bytes(4, "little"),
            len(self.flash).to_bytes(4, "little"),
        ))
        data = b"".join((header, bytes(self.ram), bytes(self.flash)))
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(data)
        temporary.replace(path)

    def load_state_dir(self, path: Path | str) -> None:
        """Load nonvolatile state from separate files in a directory."""
        path = Path(path)
        if not path.is_dir():
            raise ValueError(f"state directory does not exist: {path}")

        ram = (path / "ram.bin").read_bytes()
        flash = (path / "flash.bin").read_bytes()

        if len(ram) != len(self.ram):
            raise ValueError(
                f"state RAM size is {len(ram)} bytes; emulator requires {len(self.ram)}"
            )
        if len(flash) != len(self.flash):
            raise ValueError(
                f"state flash size is {len(flash)} bytes; "
                f"emulator requires {len(self.flash)}"
            )

        shadow_path = path / "shadow.bin"
        if shadow_path.exists():
            shadow = shadow_path.read_bytes()
            expected_shadow_size = (len(self.ram) + 7) // 8
            if len(shadow) != expected_shadow_size:
                raise ValueError(
                    f"state shadow bitmap is {len(shadow)} bytes; "
                    f"expected {expected_shadow_size}"
                )
            effective_ram = bytearray(self.ram)
            for address, value in enumerate(ram):
                if address >= len(self.rom) or shadow[address >> 3] & (1 << (address & 7)):
                    effective_ram[address] = value
        else:
            effective_ram = ram

        self.ram[:] = effective_ram
        self.flash[:] = flash

    def save_state_dir(self, path: Path | str) -> None:
        """Save effective RAM and flash as separate files."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        components = {
            "ram.bin": bytes(self.ram),
            "flash.bin": bytes(self.flash),
        }
        for name, data in components.items():
            target = path / name
            temporary = path / f".{name}.tmp"
            temporary.write_bytes(data)
            temporary.replace(target)
        shadow_path = path / "shadow.bin"
        if shadow_path.exists():
            shadow_path.unlink()

    def read(self, addr: int) -> int:
        """Read a byte from qns-owned physical storage."""
        addr &= 0xFFFFF  # 20-bit physical address

        flash_offset = self._flash_offset(addr)
        if flash_offset is not None:
            return self.flash[flash_offset]

        if addr < len(self.ram):
            return self.ram[addr]
        return 0xFF

    def write(self, addr: int, value: int):
        """Write a byte to qns-owned physical storage."""
        addr &= 0xFFFFF  # 20-bit physical address
        flash_offset = self._flash_offset(addr)
        if flash_offset is not None:
            self._write_flash(flash_offset, value & 0xFF)
            return

        if addr < len(self.ram):
            self.ram[addr] = value & 0xFF

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
