"""Main BNS emulator."""

import argparse
import queue
import sys
import threading
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from typing import BinaryIO

from .cpu import Z180
from .io import (
    MSM6242RTC,
    BQ2010GasGauge,
    BrailleDisplay,
    BrailleKeyboard,
    IOBus,
    ParallelBrailleDisplay,
    PIC16C56Clock,
    Watchdog,
)
from .memory import Memory
from .ssi263 import SSI263
from .stdio import (
    JSONLOutput,
    KeyboardInput,
    SerialInput,
    StopInput,
    WatchPCInput,
    parse_input_event,
)
from .synth.ssi263_pcm import SSI263PCMSynth

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

_COMBYT_PHYSICAL = 0x414B0
_BS2_POWER_ON_INITIALIZE_CHORD = 0x4A
_KEYBOARD_INPUT_BUFFER_PHYSICAL = {
    "bsp": 0x4327C,
    "bs2": 0x4327D,
    "bsl": 0x433E5,
    "bl2": 0x433E6,
    "bl4": 0x433F0,
}
_COMMAND_LOOP_TIMER_PHYSICAL = {
    "bsp": 0x41653,
    "bs2": 0x41654,
    "bsl": 0x41653,
    "bl2": 0x41654,
    "bl4": 0x4165A,
}
_COMMAND_LOOP_TIMER_WRITE_PC = {
    "bsp": 0x0A0D,
    "bs2": 0x0A7E,
    "bsl": 0x0A97,
    "bl2": 0x0AF5,
    "bl4": 0x0B36,
}


def _read_stdin_character() -> str:
    """Read one redirected byte or one unbuffered Windows console key."""
    if sys.platform == "win32" and sys.stdin.isatty():
        import msvcrt

        while True:
            character = msvcrt.getwch()
            if character in ("\x00", "\xe0"):
                msvcrt.getwch()
                continue
            return character
    return sys.stdin.read(1)


def _keyboard_input_chord(value: str | int) -> int:
    """Convert one terminal character or raw JSONL chord to firmware dots."""
    if isinstance(value, int):
        return value
    codepoint = ord(value)
    if codepoint >= len(_ASCII_TO_BNS_KEY):
        raise ValueError(f"unsupported input character: U+{codepoint:04X}")
    return _ASCII_TO_BNS_KEY[codepoint]


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
                 model: str = "bsp",
                 trace_io: bool = False, trace_writes: int | None = None,
                 trace_writes_range: tuple[int, int] | None = None,
                 trace_first_writes: int | None = None,
                 dump_writes_file: str | None = None,
                 trace_interrupts: bool = False,
                 stdin_device: str | None = None,
                 power_on_input: bool = False,
                 serial_output: BinaryIO | None = None,
                 serial_output_channel: int | None = None,
                 stdio_output: JSONLOutput | None = None,
                 stdio_watch_pc: int | None = None):
        """Initialize the BNS emulator.

        Args:
            clock: CPU clock frequency in Hz (default 12.288 MHz for BSPLUS)
            audio: Enable audio output for SSI-263 speech
            model: Hardware profile: bsp, bs2, bsl, bl2, or bl4
            trace_io: Log all I/O port reads/writes
            trace_writes: Physical address to trace writes to (None = disabled)
            trace_writes_range: (start, end) tuple for range tracing
            trace_first_writes: Number of first writes to log
            dump_writes_file: File to dump all write addresses to (CSV format)
            trace_interrupts: Log interrupt-related activity (IRQ lines, ITC register)
            stdin_device: Standard-input target: keyboard, serial0, serial1, or jsonl
            power_on_input: Hold the first keyboard stdin chord during power-on
            serial_output: Raw byte stream for the selected serial output channel
            serial_output_channel: ASCI channel routed to serial_output
            stdio_output: Structured output for all emulated device events
            stdio_watch_pc: Program counter reported through structured output
        """
        if model not in ("bsp", "bs2", "bsl", "bl2", "bl4"):
            raise ValueError(f"Unsupported BNS model: {model}")
        if power_on_input and stdin_device not in ("keyboard", "jsonl"):
            raise ValueError("power-on input requires keyboard stdin")
        if power_on_input and model not in ("bs2", "bl2", "bl4"):
            raise ValueError(
                "power-on input requires a proven BS2, BL2, or BL4 boundary"
            )

        self.clock = clock
        self.model = model
        flash_size = {
            "bs2": 2 * 1024 * 1024,
            "bl2": 2 * 1024 * 1024,
            "bl4": 4 * 1024 * 1024,
        }.get(model, 0)
        self.memory = Memory(flash_size=flash_size)
        self.io = IOBus()
        self.trace_interrupts = trace_interrupts
        self.stdin_device = stdin_device
        self.power_on_input = power_on_input
        self._keyboard_input_buffer_physical = (
            _KEYBOARD_INPUT_BUFFER_PHYSICAL[model]
        )
        self._command_loop_timer_physical = _COMMAND_LOOP_TIMER_PHYSICAL[model]
        self._command_loop_timer_write_pc = _COMMAND_LOOP_TIMER_WRITE_PC[model]
        self.serial_output = serial_output
        self.serial_output_channel = serial_output_channel
        self.stdio_output = stdio_output
        self._stdio_watch_pc = stdio_watch_pc
        self._serial_input_queue: queue.Queue[int] = queue.Queue()
        self._stdio_serial_input_queues = (queue.Queue(), queue.Queue())
        self._stdio_watch_queue: queue.Queue[int] = queue.Queue()
        self._stdio_stop_requested = threading.Event()
        self._stdin_error_queue: queue.Queue[ValueError] = queue.Queue()

        # Debugging options
        self.trace_writes_addr = trace_writes
        self.trace_writes_range = trace_writes_range
        self.trace_first_writes = trace_first_writes
        self.dump_writes_file = dump_writes_file
        self.io.logging = trace_io  # Enable/disable I/O logging

        # Write tracking for first-N and dump-all modes
        self.write_log = []  # List of (addr, value) tuples
        self.write_counts = {}  # Address -> occurrence count
        self.traced_writes: list[tuple[int, int, int, int]] = []
        self._command_loop_write_count = 0
        self._combyt_writes = 0
        self._bl4_key_samples = 0

        # Statistics
        self.stats = {
            'cycles': 0,
            'writes': 0,
            'phonemes': 0,
        }

        # Peripherals
        ssi263_port = 0x90 if model == "bl4" else self.PORT_SSI263
        keyboard_port = 0xB0 if model == "bl4" else self.PORT_KEYBOARD
        keyclr_port = 0xD0 if model == "bl4" else self.PORT_KEYCLR
        self.ssi263 = SSI263(base_port=ssi263_port, clock=clock)
        self.keyboard = BrailleKeyboard(
            port=keyboard_port,
            keyclr_port=keyclr_port,
        )
        self.rtc = MSM6242RTC(base_port=self.PORT_RTC_START)
        self.clock_pic = (
            PIC16C56Clock() if model in ("bs2", "bl2", "bl4") else None
        )
        if model == "bsl":
            self.display = BrailleDisplay()
        elif model == "bl2":
            self.display = ParallelBrailleDisplay(cells=18)
        elif model == "bl4":
            self.display = ParallelBrailleDisplay(cells=40)
        self.gas_gauge = (
            BQ2010GasGauge() if model in ("bs2", "bl2", "bl4") else None
        )
        self.watchdog = Watchdog(port=self.PORT_WATCHDOG)
        self.speech_power_enabled = False
        self.rs232_power_enabled = False
        self.flash_power_enabled = False
        self.disk_power_enabled = False
        self.charge_output_high = False
        self.power_latch = 0
        self.parallel_ports = [0xFF, 0xFF, 0x00, 0xFF]
        self._parallel_port_base = 0xA0 if model == "bl4" else 0x80
        self.bl4_latch = 0
        self.high_bank_latch = 0

        # Audio synthesis
        self.synth = None
        if audio:
            self.synth = SSI263PCMSynth()
            self.ssi263.set_synth(self.synth)

        self._setup_io()
        csio_device = self.display if model == "bsl" else self.clock_pic

        # Create CPU with memory/IO callbacks
        self.cpu = Z180(
            clock=clock,
            mem_read=self._mem_read,
            mem_write=self._mem_write,
            io_read=self._io_read,
            io_write=self._io_write,
            serial_rx=self._serial_receive,
            serial_tx=self._serial_transmit,
            csio_rx=csio_device.receive if csio_device else None,
            csio_tx=csio_device.transmit if csio_device else None,
        )
        if stdio_watch_pc is not None:
            self.cpu.watch_pc(stdio_watch_pc)

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

        if addr == _COMBYT_PHYSICAL:
            self._combyt_writes += 1

        # Count only the linked STARTA instruction that opens another command-loop
        # epoch.  The same timer is also cleared during early RAM initialization.
        if (
            addr == self._command_loop_timer_physical
            and value == 0
            and self.cpu.instruction_pc == self._command_loop_timer_write_pc
        ):
            self._command_loop_write_count += 1

        single_trace = self.trace_writes_addr is not None and addr == self.trace_writes_addr
        range_trace = (
            self.trace_writes_range is not None
            and self.trace_writes_range[0] <= addr <= self.trace_writes_range[1]
        )
        if single_trace or range_trace:
            self.traced_writes.append(
                (self.cpu.cycle_count, self.cpu.instruction_pc, addr, value)
            )

        # Single address trace
        if single_trace:
            print(f"[TRACE] Write 0x{addr:05X} = 0x{value:02X}")

        # Range trace
        if range_trace:
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

        # Keyboard and key-clear ports are profile-owned.
        keyboard_read = (
            self._read_bl4_dots if self.model == "bl4" else self.keyboard.read
        )
        self.io.register(self.keyboard.port, keyboard_read, self.keyboard.write)
        self.io.register(
            self.keyboard.keyclr_port,
            self.keyboard.keyclr_read,
            self.keyboard.keyclr_write,
        )
        if self.model == "bl4":
            self.io.register(0xC0, read_handler=self._read_bl4_space)

        # BSPLUS maps the MSM6242 direct-bus RTC across 0x60-0x6F.
        self.io.register_range(
            self.PORT_RTC_START,
            self.PORT_RTC_END,
            self.rtc.read,
            self.rtc.write,
        )

        if self.model in ("bs2", "bl2"):
            # BSNEW shares 0x80 with watchdog reads and 8255 port-A writes.
            self.io.register(0x80, self.watchdog.read, self._write_parallel_port)
            for port in range(0x81, 0x83):
                self.io.register(port, self._read_parallel_port, self._write_parallel_port)
            self.io.register(0x83, write_handler=self._write_parallel_port)
            self.io.register(0xA0, write_handler=self._write_bsnew_power)
            self.io.register(0xE0, write_handler=self._write_high_bank)
        elif self.model == "bl4":
            self.io.register(0x80, write_handler=self._write_bl4_power)
            for port in range(0xA0, 0xA4):
                self.io.register(
                    port,
                    self._read_parallel_port if port != 0xA3 else None,
                    self._write_parallel_port,
                )
            self.io.register(0xE0, self._read_bl4_status, self._write_bl4_latch)
            self.io.register(0xF0, write_handler=self._write_high_bank)
        else:
            # BSPLUS and B_LITE decode reads at 0x80 as watchdog service and
            # writes as speech-power control. B_LITE's display uses CSI/O.
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

    def _read_parallel_port(self, port: int) -> int:
        """Read one BSNEW 8255 register."""
        value = self.parallel_ports[port - self._parallel_port_base]
        if self.model in ("bs2", "bl2") and port == 0x81 and self.gas_gauge:
            if self.gas_gauge.read_line(self.cpu.cycle_count):
                value |= 0x08
            else:
                value &= ~0x08
        return value

    def _write_parallel_port(self, port: int, value: int) -> None:
        """Apply one BSNEW 8255 data or control-register write."""
        register = port - self._parallel_port_base
        self.parallel_ports[register] = value
        if register != 3:
            return
        if self.model in ("bl2", "bl4"):
            self.display.write_control(value)
        if value & 0x80:
            self.parallel_ports[2] = 0
            return

        bit = (value >> 1) & 0x07
        mask = 1 << bit
        was_set = bool(self.parallel_ports[2] & mask)
        if value & 0x01:
            self.parallel_ports[2] |= mask
        else:
            self.parallel_ports[2] &= ~mask
        if bit == 4 and value & 0x01 and not was_set and self.clock_pic:
            self.clock_pic.strobe()

    def _write_bsnew_power(self, port: int, value: int) -> None:
        """Apply the BSNEW combined serial, speech, flash, and disk latch."""
        self.power_latch = value
        self.rs232_power_enabled = bool(value & 0x01)
        self.speech_power_enabled = bool(value & 0x02)
        self.flash_power_enabled = bool(value & 0x04)
        self.disk_power_enabled = bool(value & 0x08)
        self.charge_output_high = bool(value & 0x80)
        if self.gas_gauge:
            self.gas_gauge.write_line(bool(value & 0x20), self.cpu.cycle_count)

    def _read_bl4_dots(self, port: int) -> int:
        """Return BL4 dot keys without its separately wired space bar."""
        return self.keyboard.read(port) & 0x3F

    def _read_bl4_space(self, port: int) -> int:
        """Return the BL4 space-bar input on port C0 bit zero."""
        self._bl4_key_samples += 1
        return int(bool(self.keyboard.dots & 0x40))

    def _write_bl4_power(self, port: int, value: int) -> None:
        """Apply the BL4 combined power and gas-gauge output latch."""
        self.power_latch = value
        self.rs232_power_enabled = bool(value & 0x01)
        self.speech_power_enabled = bool(value & 0x02)
        self.disk_power_enabled = bool(value & 0x10)
        self.charge_output_high = bool(value & 0x80)
        if self.gas_gauge:
            self.gas_gauge.write_line(bool(value & 0x80), self.cpu.cycle_count)

    def _read_bl4_status(self, port: int) -> int:
        """Return power-on status plus the BL4 gas-gauge input on bit three."""
        value = 0xFF
        if self.gas_gauge and not self.gas_gauge.read_line(self.cpu.cycle_count):
            value &= ~0x08
        return value

    def _write_bl4_latch(self, port: int, value: int) -> None:
        """Retain the BL4 cursor-key/PIC latch output."""
        self.bl4_latch = value

    def _write_high_bank(self, port: int, value: int) -> None:
        """Store the BSNEW language-ROM/high-bank latch."""
        self.high_bank_latch = value
        self.memory.set_high_bank_latch(value)

    def _serial_receive(self, channel: int) -> int:
        """Return the next stdin byte for the selected ASCI channel."""
        if self.stdin_device == "jsonl":
            input_queue = self._stdio_serial_input_queues[channel]
        elif self.stdin_device == f"serial{channel}":
            input_queue = self._serial_input_queue
        else:
            return -1
        try:
            return input_queue.get_nowait()
        except queue.Empty:
            return -1

    def _serial_transmit(self, channel: int, value: int) -> None:
        """Write an ASCI byte only to its explicitly selected raw stream."""
        if self.stdio_output is not None:
            self.stdio_output.emit_serial(channel, bytes((value,)))
        if self.serial_output is not None:
            if channel != self.serial_output_channel:
                return
            self.serial_output.write(bytes((value,)))
            self.serial_output.flush()

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
                print("Warning: BNS package too small for firmware extraction")

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
        print(
            f"MMU: CBR={self.memory.cbr:02X} BBR={self.memory.bbr:02X} "
            f"CBAR={self.memory.cbar:02X}"
        )
        if self.synth:
            print("Audio: ENABLED")
            self.synth.start()

        keyboard_input_queue: queue.Queue[str | int] | None = None
        input_phase: str | None = None
        input_chord: int | None = None
        input_ready_reported = False
        pc_watch_reported = False
        key_wait_candidate: tuple[int, int] | None = None
        power_on_combyt_writes = self._combyt_writes
        power_on_bl4_key_samples = self._bl4_key_samples
        input_command_loop_writes = self._command_loop_write_count
        if self.stdin_device is not None:
            if self.stdin_device in ("keyboard", "jsonl"):
                keyboard_input_queue = queue.Queue()
                if self.power_on_input:
                    if self.stdin_device == "jsonl":
                        line = sys.stdin.readline()
                        if not line:
                            power_on_value = None
                        else:
                            event = parse_input_event(line)
                            if not isinstance(event, KeyboardInput):
                                raise RuntimeError(
                                    "power-on input requires a keyboard JSONL event"
                                )
                            if isinstance(event.value, str):
                                power_on_value = event.value[:1] or None
                                for character in event.value[1:]:
                                    keyboard_input_queue.put(character)
                            else:
                                power_on_value = event.value
                    else:
                        power_on_value = _read_stdin_character() or None

                    if power_on_value is None:
                        if self.model == "bs2":
                            raise RuntimeError(
                                "power-on input ended before uppercase I"
                            )
                        raise RuntimeError("power-on input ended before the initial chord")
                    try:
                        input_chord = _keyboard_input_chord(power_on_value)
                    except ValueError as error:
                        raise RuntimeError(str(error)) from error
                    if (
                        self.model == "bs2"
                        and input_chord != _BS2_POWER_ON_INITIALIZE_CHORD
                    ):
                        raise RuntimeError(
                            "power-on input must begin with uppercase I"
                        )
                    self.keyboard.press(input_chord)
                    input_phase = "power-on"

            def read_stdin() -> None:
                if self.stdin_device == "keyboard":
                    while character := _read_stdin_character():
                        keyboard_input_queue.put(character)
                elif self.stdin_device == "jsonl":
                    for line in sys.stdin:
                        try:
                            event = parse_input_event(line)
                        except ValueError as error:
                            self._stdin_error_queue.put(error)
                            return
                        if isinstance(event, KeyboardInput):
                            if isinstance(event.value, str):
                                for character in event.value:
                                    keyboard_input_queue.put(character)
                            else:
                                keyboard_input_queue.put(event.value)
                        elif isinstance(event, SerialInput):
                            for byte in event.data:
                                self._stdio_serial_input_queues[event.channel].put(byte)
                        elif isinstance(event, WatchPCInput):
                            self._stdio_watch_queue.put(event.address)
                        elif isinstance(event, StopInput):
                            self._stdio_stop_requested.set()
                else:
                    while data := sys.stdin.buffer.read(1):
                        self._serial_input_queue.put(data[0])

            threading.Thread(target=read_stdin, daemon=True, name="bns-stdin").start()
            print(f"Input: STDIN ({self.stdin_device})")

        cycles_run = 0
        try:
            while max_cycles == 0 or cycles_run < max_cycles:
                try:
                    stdin_error = self._stdin_error_queue.get_nowait()
                except queue.Empty:
                    pass
                else:
                    raise RuntimeError(f"invalid JSONL stdin event: {stdin_error}")

                if self._stdio_stop_requested.is_set():
                    break

                try:
                    watch_pc = self._stdio_watch_queue.get_nowait()
                except queue.Empty:
                    pass
                else:
                    self._stdio_watch_pc = watch_pc
                    self.cpu.watch_pc(watch_pc)
                    pc_watch_reported = False
                    if self.stdio_output is not None:
                        self.stdio_output.emit(
                            "cpu",
                            event="watch-armed",
                            pc=watch_pc,
                        )

                # Run in chunks of 1000 cycles
                chunk = 1000 if max_cycles == 0 else min(1000, max_cycles - cycles_run)
                actual = self.cpu.run(chunk)
                cycles_run += actual
                self.stats['cycles'] = cycles_run

                if (
                    self.stdio_output is not None
                    and self._stdio_watch_pc is not None
                    and self.cpu.pc_watch_count > 0
                    and not pc_watch_reported
                ):
                    self.stdio_output.emit(
                        "cpu",
                        event="pc-watch",
                        pc=self._stdio_watch_pc,
                        cycle=self.cpu.pc_watch_cycle,
                        cbar=self.cpu.pc_watch_cbar,
                    )
                    pc_watch_reported = True

                # Update SSI-263 cycle count and check for pending phoneme completion IRQ
                self.ssi263.set_cycle_count(cycles_run)
                self.ssi263.check_pending_irq(cycles_run)

                key_wait_signature = None
                if (
                    self.cpu.halted
                    and self.ssi263._pending_irq_cycle is None
                ):
                    key_wait_signature = (
                        self.cpu.pc,
                        len(self.ssi263.phoneme_log),
                    )
                stable_key_wait = (
                    key_wait_signature is not None
                    and key_wait_signature == key_wait_candidate
                )
                key_wait_candidate = key_wait_signature

                if (
                    input_phase == "power-on"
                    and (
                        (
                            self.model == "bs2"
                            and self._combyt_writes > power_on_combyt_writes
                        )
                        or (self.model == "bl2" and not self.keyboard.latched)
                        or (
                            self.model == "bl4"
                            and self._bl4_key_samples > power_on_bl4_key_samples
                        )
                    )
                ):
                    accepted_chord = input_chord
                    self.keyboard.release()
                    input_phase = None
                    input_chord = None
                    if self.stdio_output is not None:
                        self.stdio_output.emit(
                            "keyboard",
                            state="accepted",
                            chord=accepted_chord,
                        )
                elif (
                    input_phase == "down"
                    and not self.keyboard.latched
                    and input_chord is not None
                    and self.memory.read(self._keyboard_input_buffer_physical)
                    == input_chord
                ):
                    self.keyboard.release()
                    input_phase = "up"
                elif (
                    input_phase == "up"
                    and not self.keyboard.latched
                    and self.memory.read(self._keyboard_input_buffer_physical) == 0
                ):
                    accepted_chord = input_chord
                    input_phase = None
                    input_chord = None
                    if self.stdio_output is not None:
                        self.stdio_output.emit(
                            "keyboard",
                            state="accepted",
                            chord=accepted_chord,
                        )

                if (
                    keyboard_input_queue is not None
                    and input_phase is None
                    and (
                        stable_key_wait
                        or self._command_loop_write_count
                        > input_command_loop_writes
                    )
                ):
                    try:
                        character = keyboard_input_queue.get_nowait()
                    except queue.Empty:
                        if self.stdio_output is not None and not input_ready_reported:
                            self.stdio_output.emit("keyboard", state="ready")
                            input_ready_reported = True
                    else:
                        try:
                            input_chord = _keyboard_input_chord(character)
                        except ValueError as error:
                            print(f"[Input] {error}")
                        else:
                            self.keyboard.press(input_chord)
                            input_phase = "down"
                            input_ready_reported = False
                            input_command_loop_writes = (
                                self._command_loop_write_count
                            )

                self.stats['phonemes'] = len(self.ssi263.phoneme_log)

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

    def load_state(self, path: Path | str) -> None:
        """Load the BNS nonvolatile RAM state."""
        self.memory.load_state(path)
        print(f"Loaded nonvolatile RAM state: {path}")

    def save_state(self, path: Path | str) -> None:
        """Save the BNS nonvolatile RAM state."""
        self.memory.save_state(path)
        print(f"Saved nonvolatile RAM state: {path}")

    def print_stats(self) -> None:
        """Print execution statistics."""
        print("\n=== Execution Statistics ===")
        print(f"Cycles executed: {self.stats['cycles']:,}")
        print(f"Memory writes:   {self.stats['writes']:,}")
        print(f"Phonemes output: {self.stats['phonemes']}")
        print(f"Final PC:        0x{self.cpu.pc:04X}")
        print(f"CPU halted:      {self.cpu.halted}")
        print(
            f"MMU state:       CBR=0x{self.cpu.cbr:02X} BBR=0x{self.cpu.bbr:02X} "
            f"CBAR=0x{self.cpu.cbar:02X}"
        )

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
    parser.add_argument(
        "--model",
        choices=("bsp", "bs2", "bsl", "bl2", "bl4"),
        default="bsp",
        help="Select the hardware profile (default: bsp)",
    )
    parser.add_argument("--trace", action="store_true",
                        help="Show boot trace instead of running")
    parser.add_argument("--input", choices=("keyboard", "serial0", "serial1"),
                        help="Route standard input to the BNS keyboard or an ASCI channel")
    parser.add_argument(
        "--power-on-input",
        action="store_true",
        help=(
            "Read and hold the first keyboard chord during power-on "
            "(BS2 requires uppercase I)"
        ),
    )
    parser.add_argument("--output", choices=("console", "serial0", "serial1"),
                        default="console",
                        help="Show console logs or route one raw ASCI channel to standard output")
    parser.add_argument(
        "--stdio",
        choices=("jsonl",),
        help="Multiplex keyboard, serial, speech, and display events as JSON Lines",
    )
    parser.add_argument(
        "--speech",
        choices=("codes", "names", "ipa", "examples"),
        help="Print retained speech as codes, phoneme names, IPA, or datasheet example words",
    )
    parser.add_argument(
        "--speech-stream",
        choices=("codes", "names", "ipa", "examples"),
        help="Stream each non-pause phoneme as codes, names, IPA, or datasheet example words",
    )
    parser.add_argument(
        "--display",
        choices=("codes", "unicode"),
        help="Print the final retained Braille display through standard output",
    )

    # Debugging options
    parser.add_argument("--cycles", type=int, default=0, metavar="N",
                        help="Run for N cycles then exit (default: unlimited)")
    parser.add_argument("--trace-io", action="store_true",
                        help="Log all I/O port reads/writes")
    parser.add_argument("--trace-interrupts", action="store_true",
                        help="Log interrupt activity (IRQ lines, ITC register)")
    parser.add_argument("--trace-writes", type=parse_hex_address, metavar="ADDR",
                        help="Log writes to specific physical address (hex, e.g., 0xD468)")
    parser.add_argument(
        "--watch-pc",
        type=parse_hex_address,
        metavar="ADDR",
        help="Emit one JSONL CPU event when execution reaches this logical address",
    )
    parser.add_argument("--trace-writes-range", nargs=2, type=parse_hex_address,
                        metavar=("START", "END"),
                        help="Log writes to physical address range (hex, e.g., 0xD000 0xE000)")
    parser.add_argument("--trace-first-writes", type=int, metavar="N",
                        help="Log first N memory writes with addresses and values")
    parser.add_argument("--dump-writes", type=str, metavar="FILE",
                        help="Dump all unique write addresses to CSV file (address,count)")
    parser.add_argument("--dump-ram", type=str, metavar="FILE",
                        help="Dump RAM contents to file after execution")
    parser.add_argument("--state", type=str, metavar="FILE",
                        help="Load nonvolatile RAM state before execution and save it afterward")
    parser.add_argument("--stats", action="store_true",
                        help="Show execution statistics at end")

    args = parser.parse_args()

    if args.stdio and (
        args.input is not None
        or args.output != "console"
        or args.speech is not None
        or args.speech_stream is not None
        or args.display is not None
    ):
        parser.error(
            "--stdio jsonl cannot be combined with --input, --output, "
            "--speech, --speech-stream, or --display"
        )
    if args.watch_pc is not None and not args.stdio:
        parser.error("--watch-pc requires --stdio jsonl")
    if args.watch_pc is not None and not 0 <= args.watch_pc <= 0xFFFF:
        parser.error("--watch-pc must be a logical address from 0x0000 through 0xFFFF")

    # Convert range args to tuple if provided
    trace_range = None
    if args.trace_writes_range:
        trace_range = tuple(args.trace_writes_range)

    structured_stdio = args.stdio == "jsonl"
    raw_serial_output = not structured_stdio and args.output != "console"
    serial_output_channel = int(args.output[-1]) if raw_serial_output else None
    serial_output = sys.stdout.buffer if raw_serial_output else None
    stdio_output = JSONLOutput(sys.stdout) if structured_stdio else None
    output_context = (
        redirect_stdout(sys.stderr)
        if raw_serial_output or structured_stdio
        else nullcontext()
    )
    display_frame_emitted = False

    with output_context:
        bns = BNS(
            audio=args.audio,
            model=args.model,
            trace_io=args.trace_io,
            trace_interrupts=args.trace_interrupts,
            trace_writes=args.trace_writes,
            trace_writes_range=trace_range,
            trace_first_writes=args.trace_first_writes,
            dump_writes_file=args.dump_writes,
            stdin_device="jsonl" if structured_stdio else (args.input or "keyboard"),
            power_on_input=args.power_on_input,
            serial_output=serial_output,
            serial_output_channel=serial_output_channel,
            stdio_output=stdio_output,
            stdio_watch_pc=args.watch_pc,
        )
        if stdio_output is not None:
            def emit_stdio_speech(_code: int, _name: str) -> None:
                phoneme = bns.ssi263.get_phonemes(start=-1)[0]
                stdio_output.emit(
                    "speech",
                    code=phoneme.code,
                    name=phoneme.name,
                    ipa=phoneme.ipa,
                    example=phoneme.example,
                )

            bns.ssi263.set_phoneme_callback(emit_stdio_speech)
            if hasattr(bns, "display"):
                bns.display.set_frame_callback(
                    lambda frame: stdio_output.emit("display", cells=list(frame))
                )

        elif args.speech_stream:
            def emit_speech_phoneme(code: int, _name: str) -> None:
                if code == 0:
                    return
                phoneme = bns.ssi263.get_phonemes(start=-1)[0]
                if args.speech_stream == "codes":
                    speech = f"{phoneme.code:02X}"
                else:
                    field = {
                        "names": "name",
                        "ipa": "ipa",
                        "examples": "example",
                    }[args.speech_stream]
                    speech = getattr(phoneme, field)
                print(f"Speech {args.speech_stream}: {speech}", flush=True)

            bns.ssi263.set_phoneme_callback(emit_speech_phoneme)

        if args.display:
            if not hasattr(bns, "display"):
                raise RuntimeError(
                    f"{args.model} has no built-in Braille display"
                )

            def emit_display_frame(frame: bytes) -> None:
                nonlocal display_frame_emitted
                display_frame_emitted = True
                if args.display == "codes":
                    display = " ".join(f"{cell:02X}" for cell in frame)
                else:
                    display = "".join(chr(0x2800 | cell) for cell in frame)
                print(f"Display {args.display}: {display}", flush=True)

            bns.display.set_frame_callback(emit_display_frame)

        bns.load_rom(args.rom_file)
        if args.state:
            state_path = Path(args.state)
            if state_path.exists():
                bns.load_state(state_path)
            else:
                print(f"Initializing nonvolatile RAM state: {state_path}")

        if args.trace:
            bns.trace_boot()
        else:
            bns.run(max_cycles=args.cycles)

        if args.speech:
            phonemes = bns.ssi263.get_phonemes(include_pauses=False)
            if args.speech == "codes":
                speech = " ".join(f"{phoneme.code:02X}" for phoneme in phonemes)
            else:
                field = {"names": "name", "ipa": "ipa", "examples": "example"}[args.speech]
                speech = " ".join(getattr(phoneme, field) for phoneme in phonemes)
            print(f"Speech {args.speech}: {speech}")

        if args.display and not display_frame_emitted:
            emit_display_frame(bytes(bns.display.buffer))

        # Post-run actions
        if args.dump_ram:
            bns.dump_ram(args.dump_ram)

        if args.state:
            bns.save_state(args.state)

        # Dump trace data if any tracing was enabled
        bns.dump_trace_data()

        if args.stats:
            bns.print_stats()

        if stdio_output is not None:
            stdio_output.emit("system", state="exited")


if __name__ == "__main__":
    main()
