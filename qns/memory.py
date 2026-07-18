"""Memory subsystem with Z180 MMU banking."""

from pathlib import Path

_STATE_MAGIC = b"QNSRAM\x00\x01"


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

    def __init__(self, ram_size: int = 512 * 1024, rom_size: int = 256 * 1024):
        # RAM covers the full address space - shadow RAM behind ROM
        self.ram = bytearray(ram_size)
        self.rom = bytearray(rom_size)
        self.rom_loaded = False  # Track if ROM data was loaded

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
        """Load nonvolatile RAM bytes and the shadow-RAM written bitmap."""
        data = Path(path).read_bytes()
        header_size = len(_STATE_MAGIC) + 4
        if len(data) < header_size or data[:len(_STATE_MAGIC)] != _STATE_MAGIC:
            raise ValueError("not a QNS nonvolatile RAM state file")

        ram_size = int.from_bytes(data[len(_STATE_MAGIC):header_size], "little")
        if ram_size != len(self.ram):
            raise ValueError(
                f"state RAM size is {ram_size} bytes; emulator requires {len(self.ram)}"
            )

        bitmap_size = (ram_size + 7) // 8
        expected_size = header_size + bitmap_size + ram_size
        if len(data) != expected_size:
            raise ValueError(
                f"state file is {len(data)} bytes; expected {expected_size}"
            )

        bitmap = data[header_size:header_size + bitmap_size]
        self.ram[:] = data[header_size + bitmap_size:]
        self._written_addrs = {
            address
            for address in range(ram_size)
            if bitmap[address >> 3] & (1 << (address & 7))
        }

    def save_state(self, path: Path | str) -> None:
        """Atomically save nonvolatile RAM and shadow-RAM written addresses."""
        path = Path(path)
        bitmap = bytearray((len(self.ram) + 7) // 8)
        for address in self._written_addrs:
            if address < len(self.ram):
                bitmap[address >> 3] |= 1 << (address & 7)

        data = b"".join((
            _STATE_MAGIC,
            len(self.ram).to_bytes(4, "little"),
            bytes(bitmap),
            bytes(self.ram),
        ))
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
        if addr < len(self.ram):
            self.ram[addr] = value & 0xFF
            was_new = addr not in self._written_addrs
            self._written_addrs.add(addr)  # Track for shadow RAM reads
            # Debug: track VOLUME address (0x4215C)
            if addr == 0x4215C:
                print(f"[MEM] Write to VOLUME (0x4215C): {value}")

    def set_mmu(self, cbr: int | None = None, bbr: int | None = None, cbar: int | None = None):
        """Update MMU registers."""
        if cbr is not None:
            self.cbr = cbr & 0xFF
        if bbr is not None:
            self.bbr = bbr & 0xFF
        if cbar is not None:
            self.cbar = cbar & 0xFF
