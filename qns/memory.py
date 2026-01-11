"""Memory subsystem with Z180 MMU banking."""


class Memory:
    """
    Z180 memory with MMU support for BNS hardware.

    Physical memory layout (from BNS hardware):
    - Physical 0x00000-0x0FFFF: ROM (64KB max, typically 27512 EPROM)
    - Physical 0x10000-0x8FFFF: RAM (512KB)

    z180emu handles MMU translation internally and passes physical addresses
    to our callbacks. We just need to provide ROM at low addresses and
    RAM at 0x10000+.
    """

    # BNS memory map constants
    ROM_START = 0x00000
    ROM_SIZE = 0x10000  # 64KB ROM
    RAM_START = 0x10000  # RAM starts at physical 64KB

    def __init__(self, ram_size: int = 512 * 1024, rom_size: int = 64 * 1024):
        self.ram = bytearray(ram_size)
        self.rom = bytearray(rom_size)

        # MMU registers
        self.cbr = 0x00   # Common Base Register
        self.bbr = 0x00   # Bank Base Register
        self.cbar = 0xF0  # Common/Bank Area Register (default: all common area 0)

    def load_rom(self, data: bytes, offset: int = 0):
        """Load ROM image."""
        self.rom[offset:offset + len(data)] = data

    def _translate(self, logical: int) -> tuple[bool, int]:
        """
        Translate logical address to physical.
        Returns (is_rom, physical_address).
        """
        logical &= 0xFFFF

        # CBAR splits: low nibble = bank start, high nibble = common1 start
        bank_start = (self.cbar & 0x0F) << 12
        common1_start = (self.cbar >> 4) << 12

        if logical < bank_start:
            # Common Area 0 - uses CBR
            physical = logical + (self.cbr << 12)
        elif logical < common1_start:
            # Bank Area - uses BBR
            physical = (logical - bank_start) + (self.bbr << 12)
        else:
            # Common Area 1 - uses CBR
            physical = logical + (self.cbr << 12)

        physical &= 0xFFFFF  # 20-bit address

        # Simple ROM/RAM split: ROM in low addresses
        is_rom = physical < len(self.rom)
        return is_rom, physical

    def read(self, addr: int) -> int:
        """Read byte from physical address (z180emu does MMU translation)."""
        addr &= 0xFFFFF  # 20-bit physical address
        if addr < self.RAM_START:
            # ROM region (physical 0x00000-0x0FFFF)
            return self.rom[addr] if addr < len(self.rom) else 0xFF
        else:
            # RAM region (physical 0x10000+)
            ram_addr = addr - self.RAM_START
            return self.ram[ram_addr] if ram_addr < len(self.ram) else 0xFF

    def write(self, addr: int, value: int):
        """Write byte to physical address (z180emu does MMU translation)."""
        addr &= 0xFFFFF  # 20-bit physical address
        if addr < self.RAM_START:
            pass  # ROM region is read-only
        else:
            # RAM region (physical 0x10000+)
            ram_addr = addr - self.RAM_START
            if ram_addr < len(self.ram):
                self.ram[ram_addr] = value & 0xFF

    def set_mmu(self, cbr: int = None, bbr: int = None, cbar: int = None):
        """Update MMU registers."""
        if cbr is not None:
            self.cbr = cbr & 0xFF
        if bbr is not None:
            self.bbr = bbr & 0xFF
        if cbar is not None:
            self.cbar = cbar & 0xFF
