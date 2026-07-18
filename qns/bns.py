"""Main BNS emulator."""

import argparse
import queue
import sys
import threading
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from typing import BinaryIO

from .cpu import Z180
from .io import MSM6242RTC, BrailleKeyboard, IOBus, Watchdog
from .memory import Memory
from .ssi263 import SSI263
from .synth import SSI263Synth

# Raw English BNS keyboard chords from BSTABLES.ASM's regular English TABLE.
# A terminal newline represents the BNS carriage-return chord, and a terminal
# space represents the physical space-bar chord before firmware translation.
_ASCII_TO_BNS_KEY = bytes((
    0x88, 0x81, 0x83, 0x89, 0x99, 0x91, 0x8B, 0x9B,
    0x93, 0x8A, 0x8D, 0x85, 0x87, 0x8D, 0x9D, 0x95,
    0x8F, 0x9F, 0x97, 0x8E, 0x9E, 0xA5, 0xA7, 0xBA,
    0xAD, 0xBD, 0xB5, 0xAA, 0xB3, 0xBB, 0x98, 0xB8,
    0x40, 0x2E, 0x10, 0x3C, 0x2B, 0x29, 0x2F, 0x04,
    0x37, 0x3E, 0x21, 0x2C, 0x20, 0x24, 0x28, 0x0C,
    0x34, 0x02, 0x06, 0x12, 0x32, 0x22, 0x16, 0x36,
    0x26, 0x14, 0x31, 0x30, 0x23, 0x3F, 0x1C, 0x39,
    0x48, 0x41, 0x43, 0x49, 0x59, 0x51, 0x4B, 0x5B,
    0x53, 0x4A, 0x5A, 0x45, 0x47, 0x4D, 0x5D, 0x55,
    0x4F, 0x5F, 0x57, 0x4E, 0x5E, 0x65, 0x67, 0x7A,
    0x6D, 0x7D, 0x75, 0x6A, 0x73, 0x7B, 0x58, 0x38,
    0x08, 0x01, 0x03, 0x09, 0x19, 0x11, 0x0B, 0x1B,
    0x13, 0x0A, 0x1A, 0x05, 0x07, 0x0D, 0x1D, 0x15,
    0x0F, 0x1F, 0x17, 0x0E, 0x1E, 0x25, 0x27, 0x3A,
    0x2D, 0x3D, 0x35, 0x2A, 0x33, 0x3B, 0x18, 0x78,
))


class BNS:
    """Braille 'N Speak emulator."""

    # I/O port assignments (BSPLUS variant)
    PORT_KEYBOARD = 0x40
    PORT_KEYCLR = 0x20
    PORT_SSI263 = 0xC0
    PORT_WATCHDOG = 0x80
    PORT_SPEECH_POWER = 0x80
    PORT_RS232_POWER = 0xA0
    PORT_RTC_START = 0x60
    PORT_RTC_END = 0x6F
    PORT_CBR = 0x38
    PORT_BBR = 0x39
    PORT_CBAR = 0x3A

    # ITC register port (Z180 internal I/O)
    PORT_ITC = 0x34

    def __init__(self, clock: int = 12_288_000, audio: bool = False,
                 trace_io: bool = False, trace_writes: int | None = None,
                 trace_writes_range: tuple[int, int] | None = None,
                 trace_first_writes: int | None = None,
                 dump_writes_file: str | None = None,
                 trace_interrupts: bool = False,
                 stdin_device: str | None = None,
                 serial_output: BinaryIO | None = None,
                 serial_output_channel: int | None = None):
        """Initialize the BNS emulator.

        Args:
            clock: CPU clock frequency in Hz (default 12.288 MHz for BSPLUS)
            audio: Enable audio output for SSI-263 speech
            trace_io: Log all I/O port reads/writes
            trace_writes: Physical address to trace writes to (None = disabled)
            trace_writes_range: (start, end) tuple for range tracing
            trace_first_writes: Number of first writes to log
            dump_writes_file: File to dump all write addresses to (CSV format)
            trace_interrupts: Log interrupt-related activity (IRQ lines, ITC register)
            stdin_device: Standard-input target: keyboard, serial0, or serial1
            serial_output: Raw byte stream for the selected serial output channel
            serial_output_channel: ASCI channel routed to serial_output
        """
        self.clock = clock
        self.memory = Memory()
        self.io = IOBus()
        self.trace_interrupts = trace_interrupts
        self.stdin_device = stdin_device
        self.serial_output = serial_output
        self.serial_output_channel = serial_output_channel
        self._serial_input_queue: queue.Queue[int] = queue.Queue()

        # Debugging options
        self.trace_writes_addr = trace_writes
        self.trace_writes_range = trace_writes_range
        self.trace_first_writes = trace_first_writes
        self.dump_writes_file = dump_writes_file
        self.io.logging = trace_io  # Enable/disable I/O logging

        # Write tracking for first-N and dump-all modes
        self.write_log = []  # List of (addr, value) tuples
        self.write_counts = {}  # Address -> occurrence count
        self._bsp_bg_timer_zero_writes = 0
        self._bsp_command_loop_ready = False

        # Statistics
        self.stats = {
            'cycles': 0,
            'writes': 0,
            'phonemes': 0,
        }

        # Peripherals
        self.ssi263 = SSI263(base_port=self.PORT_SSI263, clock=clock)
        self.keyboard = BrailleKeyboard(port=self.PORT_KEYBOARD, keyclr_port=self.PORT_KEYCLR)
        self.rtc = MSM6242RTC(base_port=self.PORT_RTC_START)
        self.watchdog = Watchdog(port=self.PORT_WATCHDOG)
        self.speech_power_enabled = False
        self.rs232_power_enabled = False

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
            serial_rx=self._serial_receive,
            serial_tx=self._serial_transmit,
        )

        # Connect keyboard interrupt (INT2) to CPU
        self.keyboard.set_irq_callback(self._make_irq_callback(2, "keyboard"))

        # Connect SSI-263 speech interrupt (INT1) to CPU
        self.ssi263.set_irq_callback(self._make_irq_callback(1, "ssi263"))

    def _make_irq_callback(self, line: int, source: str):
        """Create an IRQ callback with optional tracing.

        Args:
            line: IRQ line number (0, 1, or 2)
            source: Name of the interrupt source (for logging)
        """
        def callback(state: int) -> None:
            if self.trace_interrupts:
                state_str = "ASSERT" if state else "CLEAR"
                cycles = self.stats.get('cycles', 0)
                print(f"[IRQ] INT{line} {state_str} from {source} (cycle ~{cycles})")
            self.cpu.set_irq(line, state)
        return callback

    def _mem_read(self, addr: int) -> int:
        """Memory read callback for CPU."""
        return self.memory.read(addr)

    def _mem_write(self, addr: int, value: int) -> None:
        """Memory write callback for CPU."""
        self.stats['writes'] += 1

        # BSP STARTA writes zero to bg_timer and immediately calls bg_task,
        # which writes zero there again.  Under the linked BSP MMU state,
        # logical 0xD653 is physical 0x41653.
        if addr == 0x41653:
            if value == 0:
                self._bsp_bg_timer_zero_writes += 1
                if self._bsp_bg_timer_zero_writes >= 2:
                    self._bsp_command_loop_ready = True
            else:
                self._bsp_bg_timer_zero_writes = 0

        # Single address trace
        if self.trace_writes_addr is not None and addr == self.trace_writes_addr:
            print(f"[TRACE] Write 0x{addr:05X} = 0x{value:02X}")

        # Range trace
        if self.trace_writes_range is not None:
            start, end = self.trace_writes_range
            if start <= addr <= end:
                print(f"[TRACE] Write 0x{addr:05X} = 0x{value:02X}")

        # First-N trace
        if self.trace_first_writes is not None and len(self.write_log) < self.trace_first_writes:
            self.write_log.append((addr, value))

        # All writes dump
        if self.dump_writes_file is not None:
            self.write_counts[addr] = self.write_counts.get(addr, 0) + 1

        self.memory.write(addr, value)

    def _io_read(self, port: int) -> int:
        """I/O read callback for CPU."""
        value = self.io.read(port)
        # Trace ITC register reads
        if self.trace_interrupts and (port & 0xFF) == self.PORT_ITC:
            self._log_itc("READ", value)
        return value

    def _io_write(self, port: int, value: int) -> None:
        """I/O write callback for CPU."""
        # Trace ITC register writes
        if self.trace_interrupts and (port & 0xFF) == self.PORT_ITC:
            self._log_itc("WRITE", value)
        self.io.write(port, value)

    def _log_itc(self, op: str, value: int) -> None:
        """Log ITC register access with decoded bits."""
        # ITC bits: 0=INT0_EN, 1=INT1_EN, 2=INT2_EN
        int0 = "EN" if value & 0x01 else "DIS"
        int1 = "EN" if value & 0x02 else "DIS"
        int2 = "EN" if value & 0x04 else "DIS"
        cycles = self.stats.get('cycles', 0)
        print(f"[ITC] {op} 0x{value:02X} INT0={int0} INT1={int1} INT2={int2} (cycle ~{cycles})")

    def _setup_io(self) -> None:
        """Wire up I/O handlers."""
        # SSI-263 speech (0xC0-0xC4)
        for port, read_h, write_h in self.ssi263.get_io_handlers():
            self.io.register(port, read_h, write_h)

        # Keyboard (0x40) and keyclr (0x20)
        self.io.register(self.PORT_KEYBOARD, self.keyboard.read, self.keyboard.write)
        self.io.register(self.PORT_KEYCLR, self.keyboard.keyclr_read, self.keyboard.keyclr_write)

        # BSPLUS maps the MSM6242 direct-bus RTC across 0x60-0x6F.
        self.io.register_range(
            self.PORT_RTC_START,
            self.PORT_RTC_END,
            self.rtc.read,
            self.rtc.write,
        )

        # BSPLUS decodes reads at 0x80 as watchdog service and writes as
        # speech-power control. This speech-only model has no Braille display.
        self.io.register(
            self.PORT_SPEECH_POWER,
            self.watchdog.read,
            self._write_speech_power,
        )

        # BSPLUS MAXON/MAXOFF drive bit zero of the MAX232 power latch.
        self.io.register(self.PORT_RS232_POWER, write_handler=self._write_rs232_power)

        # MMU registers
        self.io.register(self.PORT_CBR, lambda p: self.memory.cbr,
                        lambda p, v: self.memory.set_mmu(cbr=v))
        self.io.register(self.PORT_BBR, lambda p: self.memory.bbr,
                        lambda p, v: self.memory.set_mmu(bbr=v))
        self.io.register(self.PORT_CBAR, lambda p: self.memory.cbar,
                        lambda p, v: self.memory.set_mmu(cbar=v))

    def _write_speech_power(self, port: int, value: int) -> None:
        """Apply the BSPLUS speech-power latch's bit-zero state."""
        self.speech_power_enabled = bool(value & 0x01)

    def _write_rs232_power(self, port: int, value: int) -> None:
        """Apply the BSPLUS RS-232 transceiver-power latch's bit-zero state."""
        self.rs232_power_enabled = bool(value & 0x01)

    def _serial_receive(self, channel: int) -> int:
        """Return the next stdin byte for the selected ASCI channel."""
        if self.stdin_device != f"serial{channel}":
            return -1
        try:
            return self._serial_input_queue.get_nowait()
        except queue.Empty:
            return -1

    def _serial_transmit(self, channel: int, value: int) -> None:
        """Write an ASCI byte to its selected raw stream or the console log."""
        if self.serial_output is not None:
            if channel != self.serial_output_channel:
                return
            self.serial_output.write(bytes((value,)))
            self.serial_output.flush()
            return
        print(f"[Serial{channel}] {bytes((value,))!r}")

    def load_rom(self, path: Path | str) -> None:
        """Load ROM file.

        Handles three formats:
        1. Pre-extracted .bin files (64KB, loaded directly)
        2. Raw firmware files (may need truncation)
        3. BNS update packages (firmware at offset 0x3000)

        The BNS hardware uses a 64KB ROM (27512 EPROM). The firmware files
        contain multiple 64KB banks - we load only the first bank.
        """
        path = Path(path)
        data = path.read_bytes()

        # Check for pre-extracted .bin file (64KB or 256KB, no BNS header)
        if path.suffix.lower() == '.bin' and len(data) in (0x10000, 0x40000):
            print(f"Loading pre-extracted firmware: {path.name}")
            self.memory.load_rom(data)
            print(f"Loaded ROM: {path.name} ({len(data)} bytes at physical 0x00000)")
            return

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

        # Load full ROM (up to 256KB for all 4 banks)
        # The BNS uses Z180 MMU bank switching to access different ROM banks
        if len(data) > 256 * 1024:
            print(f"  Limiting to 256KB ROM (from {len(data)} bytes)")
            data = data[:256 * 1024]

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

        keyboard_input_queue: queue.Queue[str] | None = None
        input_phase: str | None = None
        if self.stdin_device is not None:
            if self.stdin_device == "keyboard":
                keyboard_input_queue = queue.Queue()

            def read_stdin() -> None:
                if self.stdin_device == "keyboard":
                    while character := sys.stdin.read(1):
                        keyboard_input_queue.put(character)
                else:
                    while data := sys.stdin.buffer.read(1):
                        self._serial_input_queue.put(data[0])

            threading.Thread(target=read_stdin, daemon=True, name="bns-stdin").start()
            print(f"Input: STDIN ({self.stdin_device})")

        cycles_run = 0
        try:
            while (max_cycles == 0 or cycles_run < max_cycles) and not self.cpu.halted:
                # Run in chunks of 1000 cycles
                chunk = 1000 if max_cycles == 0 else min(1000, max_cycles - cycles_run)
                actual = self.cpu.run(chunk)
                cycles_run += actual
                self.stats['cycles'] = cycles_run

                # Update SSI-263 cycle count and check for pending phoneme completion IRQ
                self.ssi263.set_cycle_count(cycles_run)
                self.ssi263.check_pending_irq(cycles_run)

                if input_phase == "down" and not self.keyboard.latched:
                    self.keyboard.release()
                    input_phase = "up"
                elif input_phase == "up" and not self.keyboard.latched:
                    input_phase = None

                if (
                    keyboard_input_queue is not None
                    and input_phase is None
                    and self._bsp_command_loop_ready
                ):
                    try:
                        character = keyboard_input_queue.get_nowait()
                    except queue.Empty:
                        pass
                    else:
                        codepoint = ord(character)
                        if codepoint < len(_ASCII_TO_BNS_KEY):
                            self.keyboard.press(_ASCII_TO_BNS_KEY[codepoint])
                            input_phase = "down"
                        else:
                            print(f"[Input] Unsupported character: U+{codepoint:04X}")

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
        print(f"MMU state:       CBR=0x{self.cpu.cbr:02X} BBR=0x{self.cpu.bbr:02X} CBAR=0x{self.cpu.cbar:02X}")

    def dump_trace_data(self) -> None:
        """Dump traced data to files."""
        # Dump first-N writes
        if self.trace_first_writes is not None and self.write_log:
            print(f"\n=== First {len(self.write_log)} Memory Writes ===")
            for i, (addr, value) in enumerate(self.write_log, 1):
                print(f"{i:3d}. 0x{addr:05X} = 0x{value:02X}")

        # Dump all writes to CSV
        if self.dump_writes_file is not None and self.write_counts:
            path = Path(self.dump_writes_file)
            with path.open('w') as f:
                f.write("address,count\n")
                for addr in sorted(self.write_counts.keys()):
                    count = self.write_counts[addr]
                    f.write(f"0x{addr:05X},{count}\n")
            print(f"\nDumped {len(self.write_counts)} unique write addresses to {path.name}")

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
    parser.add_argument("--input", choices=("keyboard", "serial0", "serial1"),
                        default="keyboard",
                        help="Route standard input to the BNS keyboard or an ASCI channel")
    parser.add_argument("--output", choices=("console", "serial0", "serial1"),
                        default="console",
                        help="Show console logs or route one raw ASCI channel to standard output")

    # Debugging options
    parser.add_argument("--cycles", type=int, default=0, metavar="N",
                        help="Run for N cycles then exit (default: unlimited)")
    parser.add_argument("--trace-io", action="store_true",
                        help="Log all I/O port reads/writes")
    parser.add_argument("--trace-interrupts", action="store_true",
                        help="Log interrupt activity (IRQ lines, ITC register)")
    parser.add_argument("--trace-writes", type=parse_hex_address, metavar="ADDR",
                        help="Log writes to specific physical address (hex, e.g., 0xD468)")
    parser.add_argument("--trace-writes-range", nargs=2, type=parse_hex_address,
                        metavar=("START", "END"),
                        help="Log writes to physical address range (hex, e.g., 0xD000 0xE000)")
    parser.add_argument("--trace-first-writes", type=int, metavar="N",
                        help="Log first N memory writes with addresses and values")
    parser.add_argument("--dump-writes", type=str, metavar="FILE",
                        help="Dump all unique write addresses to CSV file (address,count)")
    parser.add_argument("--dump-ram", type=str, metavar="FILE",
                        help="Dump RAM contents to file after execution")
    parser.add_argument("--stats", action="store_true",
                        help="Show execution statistics at end")

    args = parser.parse_args()

    # Convert range args to tuple if provided
    trace_range = None
    if args.trace_writes_range:
        trace_range = tuple(args.trace_writes_range)

    raw_serial_output = args.output != "console"
    serial_output_channel = int(args.output[-1]) if raw_serial_output else None
    serial_output = sys.stdout.buffer if raw_serial_output else None
    output_context = redirect_stdout(sys.stderr) if raw_serial_output else nullcontext()

    with output_context:
        bns = BNS(
            audio=args.audio,
            trace_io=args.trace_io,
            trace_interrupts=args.trace_interrupts,
            trace_writes=args.trace_writes,
            trace_writes_range=trace_range,
            trace_first_writes=args.trace_first_writes,
            dump_writes_file=args.dump_writes,
            stdin_device=args.input,
            serial_output=serial_output,
            serial_output_channel=serial_output_channel,
        )
        bns.load_rom(args.rom_file)

        if args.trace:
            bns.trace_boot()
        else:
            bns.run(max_cycles=args.cycles)

        # Post-run actions
        if args.dump_ram:
            bns.dump_ram(args.dump_ram)

        # Dump trace data if any tracing was enabled
        bns.dump_trace_data()

        if args.stats:
            bns.print_stats()


if __name__ == "__main__":
    main()
