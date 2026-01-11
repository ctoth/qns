"""Main BNS emulator."""

import argparse
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

    def __init__(self, clock: int = 12_288_000, audio: bool = False,
                 trace_io: bool = False, trace_writes: int = None):
        """Initialize the BNS emulator.

        Args:
            clock: CPU clock frequency in Hz (default 12.288 MHz for BSPLUS)
            audio: Enable audio output for SSI-263 speech
            trace_io: Log all I/O port reads/writes
            trace_writes: Physical address to trace writes to (None = disabled)
        """
        self.clock = clock
        self.memory = Memory()
        self.io = IOBus()

        # Debugging options
        self.trace_writes_addr = trace_writes
        self.io.logging = trace_io  # Enable/disable I/O logging

        # Statistics
        self.stats = {
            'cycles': 0,
            'writes': 0,
            'phonemes': 0,
        }

        # Peripherals
        self.ssi263 = SSI263(base_port=self.PORT_SSI263)
        self.keyboard = BrailleKeyboard(port=self.PORT_KEYBOARD, keyclr_port=self.PORT_KEYCLR)
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

        # Connect keyboard interrupt (INT2) to CPU
        self.keyboard.set_irq_callback(lambda state: self.cpu.set_irq(2, state))

    def _mem_read(self, addr: int) -> int:
        """Memory read callback for CPU."""
        return self.memory.read(addr)

    def _mem_write(self, addr: int, value: int) -> None:
        """Memory write callback for CPU."""
        self.stats['writes'] += 1
        if self.trace_writes_addr is not None and addr == self.trace_writes_addr:
            print(f"[TRACE] Write 0x{addr:05X} = 0x{value:02X}")
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

        # Keyboard (0x40) and keyclr (0x20)
        self.io.register(self.PORT_KEYBOARD, self.keyboard.read, self.keyboard.write)
        self.io.register(self.PORT_KEYCLR, self.keyboard.keyclr_read, self.keyboard.keyclr_write)

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
        """Load ROM file.

        Handles both raw firmware and .bns update packages.
        Update packages have firmware at IMAGE_OFFSET (0x3000).

        The BNS hardware uses a 64KB ROM (27512 EPROM). The firmware files
        contain multiple 64KB banks - we load only the first bank.
        """
        path = Path(path)
        data = path.read_bytes()

        # Check for BNS update package format
        if len(data) >= 5 and data[2:5] == b'BNS':
            # This is an update package - firmware is at offset 0x3000
            IMAGE_OFFSET = 0x3000
            if len(data) > IMAGE_OFFSET:
                firmware = data[IMAGE_OFFSET:]
                print(f"Extracted firmware from update package at offset 0x{IMAGE_OFFSET:X}")
                print(f"  Package size: {len(data)} bytes, Firmware size: {len(firmware)} bytes")
                data = firmware
            else:
                print(f"Warning: BNS package too small for firmware extraction")

        # Limit to 64KB (first bank) - the BNS hardware uses a 27512 EPROM
        if len(data) > 0x10000:
            print(f"  Truncating to 64KB ROM (from {len(data)} bytes)")
            data = data[:0x10000]

        self.memory.load_rom(data)
        print(f"Loaded ROM: {path.name} ({len(data)} bytes at physical 0x00000)")

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
                if self.ssi263.phoneme_log:
                    self.stats['phonemes'] += len(self.ssi263.phoneme_log)
                    if not self.synth:
                        print(f"[Speech] Phonemes: {self.ssi263.phoneme_log}")
                    self.ssi263.phoneme_log.clear()

                # Print I/O log if tracing (periodically to avoid flooding)
                if self.io.logging and self.io._log:
                    for entry in self.io.dump_log():
                        print(f"[IO] {entry}")
                    self.io._log.clear()

        except KeyboardInterrupt:
            print("\nEmulation stopped by user")
        finally:
            if self.synth:
                self.synth.stop()

        self.stats['cycles'] = cycles_run
        print(f"Executed {cycles_run:,} cycles")
        print(f"Final PC: {self.cpu.pc:04X}")

    def step(self) -> int:
        """Execute a single instruction. Returns cycles consumed."""
        return self.cpu.step()

    def dump_ram(self, path: Path | str) -> None:
        """Dump RAM contents to a file."""
        path = Path(path)
        path.write_bytes(bytes(self.memory.ram))
        print(f"RAM dumped to {path} ({len(self.memory.ram)} bytes)")

    def print_stats(self) -> None:
        """Print execution statistics."""
        print("\n=== Execution Statistics ===")
        print(f"Cycles executed: {self.stats['cycles']:,}")
        print(f"Memory writes:   {self.stats['writes']:,}")
        print(f"Phonemes output: {self.stats['phonemes']}")
        print(f"Final PC:        0x{self.cpu.pc:04X}")
        print(f"CPU halted:      {self.cpu.halted}")

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


def parse_hex_address(value: str) -> int:
    """Parse a hex address like 0xD468 or D468."""
    try:
        return int(value, 16)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid hex address: {value}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="qns.bns",
        description="BNS (Braille 'N Speak) emulator"
    )
    parser.add_argument("rom_file", help="ROM file to load (.bns or raw firmware)")

    # Basic options
    parser.add_argument("--audio", action="store_true",
                        help="Enable SSI-263 audio output")
    parser.add_argument("--trace", action="store_true",
                        help="Show boot trace instead of running")

    # Debugging options
    parser.add_argument("--cycles", type=int, default=0, metavar="N",
                        help="Run for N cycles then exit (default: unlimited)")
    parser.add_argument("--trace-io", action="store_true",
                        help="Log all I/O port reads/writes")
    parser.add_argument("--trace-writes", type=parse_hex_address, metavar="ADDR",
                        help="Log writes to specific physical address (hex, e.g., 0xD468)")
    parser.add_argument("--dump-ram", type=str, metavar="FILE",
                        help="Dump RAM contents to file after execution")
    parser.add_argument("--stats", action="store_true",
                        help="Show execution statistics at end")

    args = parser.parse_args()

    bns = BNS(
        audio=args.audio,
        trace_io=args.trace_io,
        trace_writes=args.trace_writes
    )
    bns.load_rom(args.rom_file)

    if args.trace:
        bns.trace_boot()
    else:
        bns.run(max_cycles=args.cycles)

    # Post-run actions
    if args.dump_ram:
        bns.dump_ram(args.dump_ram)

    if args.stats:
        bns.print_stats()


if __name__ == "__main__":
    main()
