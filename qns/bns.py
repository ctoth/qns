"""Main BNS emulator."""

import sys
from pathlib import Path

from .cpu import Z180
from .memory import Memory
from .ssi263 import SSI263
from .synth import SSI263Synth
from .io import IOBus, BrailleKeyboard, BrailleDisplay, Watchdog


class BNS:
    """Braille 'N Speak emulator."""

    # I/O port assignments (BSPLUS variant)
    PORT_KEYBOARD = 0x40
    PORT_KEYCLR = 0x20
    PORT_DISPLAY = 0x80
    PORT_SSI263 = 0xC0
    PORT_WATCHDOG = 0x80
    PORT_CBR = 0x38
    PORT_BBR = 0x39
    PORT_CBAR = 0x3A

    def __init__(self, clock: int = 12_288_000, audio: bool = False):
        """Initialize the BNS emulator.

        Args:
            clock: CPU clock frequency in Hz (default 12.288 MHz for BSPLUS)
            audio: Enable audio output for SSI-263 speech
        """
        self.clock = clock
        self.memory = Memory()
        self.io = IOBus()

        # Peripherals
        self.ssi263 = SSI263(base_port=self.PORT_SSI263)
        self.keyboard = BrailleKeyboard(port=self.PORT_KEYBOARD)
        self.display = BrailleDisplay(base_port=self.PORT_DISPLAY)
        self.watchdog = Watchdog(port=self.PORT_WATCHDOG)

        # Audio synthesis
        self.synth = None
        if audio:
            self.synth = SSI263Synth()
            self.ssi263.set_synth(self.synth)

        self._setup_io()

        # Create CPU with memory/IO callbacks
        self.cpu = Z180(
            clock=clock,
            mem_read=self._mem_read,
            mem_write=self._mem_write,
            io_read=self._io_read,
            io_write=self._io_write,
        )

    def _mem_read(self, addr: int) -> int:
        """Memory read callback for CPU."""
        return self.memory.read(addr)

    def _mem_write(self, addr: int, value: int) -> None:
        """Memory write callback for CPU."""
        self.memory.write(addr, value)

    def _io_read(self, port: int) -> int:
        """I/O read callback for CPU."""
        return self.io.read(port)

    def _io_write(self, port: int, value: int) -> None:
        """I/O write callback for CPU."""
        self.io.write(port, value)

    def _setup_io(self) -> None:
        """Wire up I/O handlers."""
        # SSI-263 speech (0xC0-0xC4)
        for port, read_h, write_h in self.ssi263.get_io_handlers():
            self.io.register(port, read_h, write_h)

        # Keyboard (0x40)
        self.io.register(self.PORT_KEYBOARD, self.keyboard.read, self.keyboard.write)

        # Display (0x80-0x83)
        self.io.register_range(0x80, 0x83, self.display.read, self.display.write)

        # MMU registers
        self.io.register(self.PORT_CBR, lambda p: self.memory.cbr,
                        lambda p, v: self.memory.set_mmu(cbr=v))
        self.io.register(self.PORT_BBR, lambda p: self.memory.bbr,
                        lambda p, v: self.memory.set_mmu(bbr=v))
        self.io.register(self.PORT_CBAR, lambda p: self.memory.cbar,
                        lambda p, v: self.memory.set_mmu(cbar=v))

    def load_rom(self, path: Path | str) -> None:
        """Load ROM file."""
        path = Path(path)
        data = path.read_bytes()

        # Verify BNS header
        if len(data) >= 5 and data[2:5] != b'BNS':
            print(f"Warning: No BNS magic at offset 2 (got {data[2:5]!r})")

        self.memory.load_rom(data)
        print(f"Loaded ROM: {path.name} ({len(data)} bytes)")

    def reset(self) -> None:
        """Reset the emulator."""
        self.cpu.reset()
        self.memory.set_mmu(cbr=0, bbr=0, cbar=0xF0)
        print("BNS reset complete")

    def run(self, max_cycles: int = 0) -> None:
        """Run emulation.

        Args:
            max_cycles: Maximum number of CPU cycles to execute
        """
        print("Starting BNS emulation...")
        print(f"Memory: {len(self.memory.rom)} ROM, {len(self.memory.ram)} RAM")
        print(f"MMU: CBR={self.memory.cbr:02X} BBR={self.memory.bbr:02X} CBAR={self.memory.cbar:02X}")
        if self.synth:
            print("Audio: ENABLED")
            self.synth.start()

        cycles_run = 0
        try:
            while (max_cycles == 0 or cycles_run < max_cycles) and not self.cpu.halted:
                # Run in chunks of 1000 cycles
                chunk = 1000 if max_cycles == 0 else min(1000, max_cycles - cycles_run)
                actual = self.cpu.run(chunk)
                cycles_run += actual

                # Check for speech output (log only if no audio)
                if self.ssi263.phoneme_log and not self.synth:
                    print(f"[Speech] Phonemes: {self.ssi263.phoneme_log}")
                    self.ssi263.phoneme_log.clear()

        except KeyboardInterrupt:
            print("\nEmulation stopped by user")
        finally:
            if self.synth:
                self.synth.stop()

        print(f"Executed {cycles_run:,} cycles")
        print(f"Final PC: {self.cpu.pc:04X}")

    def step(self) -> int:
        """Execute a single instruction. Returns cycles consumed."""
        return self.cpu.step()

    def trace_boot(self) -> None:
        """Trace the boot sequence (diagnostic mode)."""
        print("=== BNS Boot Trace ===")
        if len(self.memory.rom) < 16:
            print("Error: ROM too small")
            return

        print(f"ROM starts with: {self.memory.rom[0]:02X} {self.memory.rom[1]:02X}")
        print(f"  -> JR +{self.memory.rom[1]} (jump over header)")
        print(f"Magic: {bytes(self.memory.rom[2:6])!r}")

        # Show first few bytes after header
        entry = 2 + self.memory.rom[1]  # After JR offset
        print(f"Entry point: 0x{entry:04X}")
        print(f"First bytes: {' '.join(f'{b:02X}' for b in self.memory.rom[entry:entry+16])}")

        # Try stepping through first instructions
        self.reset()
        print("\n=== First 10 instructions ===")
        for i in range(10):
            pc_before = self.cpu.pc
            cycles = self.step()
            pc_after = self.cpu.pc
            print(f"{i+1}. PC: {pc_before:04X} -> {pc_after:04X} ({cycles} cycles)")


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m qns.bns [--audio] [--trace] <rom_file>")
        print("       --audio  Enable SSI-263 audio output")
        print("       --trace  Show boot trace instead of running")
        sys.exit(1)

    trace_mode = '--trace' in sys.argv
    audio_mode = '--audio' in sys.argv
    rom_path = sys.argv[-1]

    bns = BNS(audio=audio_mode)
    bns.load_rom(rom_path)

    if trace_mode:
        bns.trace_boot()
    else:
        bns.run()


if __name__ == "__main__":
    main()
