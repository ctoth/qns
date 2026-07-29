"""Main BNS emulator."""

import contextlib
import queue
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from z180 import IrqLine, Machine, Reg, WatchKind
from z180.compat import Z180 as CompatZ180

from .devices import (
    MSM6242RTC,
    BQ2010GasGauge,
    BrailleDisplay,
    BrailleKeyboard,
    IOBus,
    ParallelBrailleDisplay,
    PIC16C56Clock,
    TNSKeyboard,
    Watchdog,
)
from .input_driver import ChordInputDriver
from .loader import (
    RETAINED_SPEECH_DEFAULTS,
    EnglishBoundary,
    InputBoundary,
    SpeechParameters,
    find_english_boundary,
    find_input_boundary,
    find_speech_parameters,
    find_speech_power_timeout,
    load_firmware,
)
from .memory import Memory
from .pc_disk import PCDisk
from .profiles import PROFILES
from .ssi263 import SSI263
from .stdio import (
    JSONLOutput,
    KeyboardInput,
    SerialInput,
    StopInput,
    WatchPCInput,
    parse_input_event,
)
from .synth import SSI263LPCSynth, SSI263PCMSynth, SSI263Synth

# Selectable audio backends, in the order they became usable.  Each trades
# differently: pcm has the chip's timbre but replays isolated captures, lpc
# resynthesizes those captures through one continuous filter, and formant
# models the SC-01 - a different chip - but is continuous by construction.
SYNTH_BACKENDS = {
    "pcm": SSI263PCMSynth,
    "lpc": SSI263LPCSynth,
    "formant": SSI263Synth,
}


def _read_stdin_character() -> str:
    """Read one redirected byte or one unbuffered console key."""
    if sys.platform == "win32" and sys.stdin.isatty():
        import msvcrt

        while True:
            character = msvcrt.getwch()
            if character in ("\x00", "\xe0"):
                msvcrt.getwch()
                continue
            return character
    return sys.stdin.read(1)


@contextlib.contextmanager
def _keystrokes_unbuffered():
    """Deliver terminal keystrokes singly, restoring the terminal after.

    A POSIX terminal is line-buffered, so a chord would not reach the
    firmware until Enter - and Enter is itself a chord.  cbreak turns off
    canonical mode and echo while leaving ISIG intact, so Ctrl-C still
    interrupts rather than arriving as a phantom chord.

    Windows needs no mode change: `_read_stdin_character` reads console
    keys through msvcrt.  Redirected input needs none either.  Both, and
    any stdin without a real file descriptor, pass straight through.
    """
    try:
        interactive = sys.platform != "win32" and sys.stdin.isatty()
        fd = sys.stdin.fileno() if interactive else None
    except (AttributeError, ValueError, OSError):
        fd = None

    if fd is None:
        yield
        return

    import termios
    import tty

    try:
        saved = termios.tcgetattr(fd)
    except termios.error:
        yield
        return

    try:
        tty.setcbreak(fd)
        yield
    finally:
        # TCSADRAIN so queued output is not discarded on the way out.
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


class BNS:
    """Braille 'N Speak emulator."""

    # I/O port assignments shared by every profile
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
                 synth_backend: str = "pcm",
                 model: str = "bsp",
                 core: str = "direct",
                 trace_io: bool = False, trace_writes: int | None = None,
                 trace_writes_range: tuple[int, int] | None = None,
                 trace_first_writes: int | None = None,
                 dump_writes_file: str | None = None,
                 trace_interrupts: bool = False,
                 stdin_device: str | None = None,
                 reset: str | None = None,
                 serial_output: BinaryIO | None = None,
                 serial_output_channel: int | None = None,
                 pc_disk_dir: Path | str | None = None,
                 stdio_output: JSONLOutput | None = None,
                 stdio_watch_pc: int | None = None,
                 speech_settings: dict[str, int] | None = None,
                 realtime: bool = False,
                 english_callback: Callable[[str], None] | None = None):
        """Initialize the BNS emulator.

        Args:
            clock: CPU clock frequency in Hz (default 12.288 MHz for BSPLUS)
            audio: Enable audio output for SSI-263 speech
            synth_backend: Audio backend: pcm, lpc, or formant
            model: Hardware profile: bsp, bs2, bsl, bl2, bl4, or tns
            core: z-core API path: compat or direct
            trace_io: Log all I/O port reads/writes
            trace_writes: Physical address to trace writes to (None = disabled)
            trace_writes_range: (start, end) tuple for range tracing
            trace_first_writes: Number of first writes to log
            dump_writes_file: File to dump all write addresses to (CSV format)
            trace_interrupts: Log interrupt-related activity (IRQ lines, ITC register)
            stdin_device: Standard-input target: keyboard, serial0, serial1, or jsonl
            reset: Apply the model's warm- or cold-reset power-on gesture
            serial_output: Raw byte stream for the selected serial output channel
            serial_output_channel: ASCI channel routed to serial_output
            pc_disk_dir: Host directory exposed to the firmware as PC Disk on ASCI0
            stdio_output: Structured output for all emulated device events
            stdio_watch_pc: Program counter reported through structured output
            speech_settings: Retained speech settings seeded into battery-backed
                RAM at load, overriding RETAINED_SPEECH_DEFAULTS per key
            realtime: Hold emulated time to wall-clock time, so speech plays at
                the speed the hardware would speak it
            english_callback: Observer for exact pre-translation firmware text
        """
        profile = PROFILES.get(model)
        if profile is None:
            raise ValueError(f"Unsupported BNS model: {model}")
        if core not in ("compat", "direct"):
            raise ValueError(f"Unsupported z-core path: {core}")
        if reset not in (None, "warm", "cold"):
            raise ValueError(f"Unsupported reset mode: {reset}")

        self.clock = clock
        self.model = model
        self.core = core
        self.profile = profile
        self.memory = Memory(
            ram_size=profile.ram_size,
            rom_size=profile.rom_size,
            flash_size=profile.flash_size,
        )
        self.io = IOBus()
        self.trace_interrupts = trace_interrupts
        self.stdin_device = stdin_device
        self.reset_mode = reset
        self.serial_output = serial_output
        self.serial_output_channel = serial_output_channel
        self.pc_disk = PCDisk(pc_disk_dir) if pc_disk_dir is not None else None
        self.stdio_output = stdio_output
        self._stdio_watch_pc = stdio_watch_pc
        self._english_callback = english_callback
        self._english_boundary: EnglishBoundary | None = None
        self._input_boundary: InputBoundary | None = None
        self._input_driver: ChordInputDriver | None = None
        self._speech_overrides = dict(speech_settings or {})
        self._speech_settings = RETAINED_SPEECH_DEFAULTS | self._speech_overrides
        self._speech_parameters: SpeechParameters | None = None
        self.realtime = realtime
        # Real-time pacing sleeps between chunks, so the chunk sets the
        # granularity of that sleep.  1000 cycles is 81 us at 12.288 MHz -
        # far below the host's sleep resolution - so pace in ~1 ms chunks
        # instead, still two orders of magnitude finer than a phoneme.
        self._chunk_cycles = 12_288 if realtime else 1000
        self._english_capture_cycle: int | None = None
        self._serial_input_queue: queue.Queue[int] = queue.Queue()
        self._stdio_serial_input_queues = (queue.Queue(), queue.Queue())
        self._stdio_watch_queue: queue.Queue[int] = queue.Queue()
        self._stdio_stop_requested = threading.Event()
        self._stdin_error_queue: queue.Queue[ValueError] = queue.Queue()
        self._pending_irq_states = {0: False, 1: False, 2: False}
        self._applied_irq_states: dict[int, bool | None] = {0: None, 1: None, 2: None}
        self._callback_cycle = 0
        self._callback_pc = 0
        self._pending_asci_rx: list[int | None] = [None, None]
        self._pending_csio_rx: int | None = None
        self._pc_watch_address: int | None = None
        self._pc_watch_cycle = 0
        self._pc_watch_cbar = 0

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
        self._keyboard_ready_epoch = 0
        self._keyboard_accept_epoch = 0
        self._keyboard_queue_epoch = 0
        self._keyboard_consume_epoch = 0
        self._reset_complete_writes = 0

        # Statistics
        self.stats = {
            'cycles': 0,
            'writes': 0,
            'phonemes': 0,
        }

        # Peripherals
        self.ssi263 = SSI263(base_port=profile.ssi263_port, clock=clock)
        if profile.family == "tns":
            self.keyboard = TNSKeyboard(port=profile.keyboard_port)
        else:
            assert profile.keyclr_port is not None
            self.keyboard = BrailleKeyboard(
                port=profile.keyboard_port,
                keyclr_port=profile.keyclr_port,
            )
        self.rtc = MSM6242RTC(base_port=self.PORT_RTC_START)
        self.clock_pic = PIC16C56Clock() if profile.has_clock_pic else None
        if profile.display == "csio":
            self.display = BrailleDisplay(cells=profile.display_cells)
        elif profile.display == "parallel":
            self.display = ParallelBrailleDisplay(cells=profile.display_cells)
        else:
            self.display = None
        self.gas_gauge = BQ2010GasGauge() if profile.has_gas_gauge else None
        self.watchdog = Watchdog(port=self.PORT_WATCHDOG)
        self.speech_power_enabled = False
        self.rs232_power_enabled = False
        self.flash_power_enabled = False
        self.disk_power_enabled = False
        self.charge_output_high = False
        self.power_latch = 0
        self.parallel_ports = [0xFF, 0xFF, 0x00, 0xFF]
        self.bl4_latch = 0
        self.high_bank_latch = 0

        # Audio synthesis
        if synth_backend not in SYNTH_BACKENDS:
            raise ValueError(f"Unsupported synth backend: {synth_backend}")
        self.synth = None
        if audio:
            self.synth = SYNTH_BACKENDS[synth_backend]()
            self.ssi263.set_synth(self.synth)

        self._setup_io()
        self._csio_device = (
            self.display if profile.display == "csio" else self.clock_pic
        )

        if core == "direct":
            regions = [
                {"base": 0x00000, "size": profile.ram_size, "kind": "ram"},
            ]
            if profile.flash_size:
                regions.append(
                    {"base": 0x80000, "size": 0x80000, "kind": "external"}
                )
            self.cpu = Machine(
                config_dict={
                    "clock_hz": clock,
                    "phys_addr_bits": 20,
                    "unmapped_read": 0xFF,
                    "variant": "Z80180",
                    "regions": regions,
                    "event_capacity": 4096,
                },
                mem_read=self._mem_read,
                mem_write=self._mem_write,
                io_read=self._io_read,
                io_write=self._io_write,
            )
            self.memory.ram = self.cpu.ram(0x00000)
            self._ram_write_watch = self.cpu.add_mem_watch(
                0x00000,
                profile.ram_size,
                WatchKind.Write,
            )
        else:
            self.cpu = CompatZ180(
                clock=clock,
                mem_read=self._mem_read,
                mem_write=self._mem_write,
                io_read=self._io_read,
                io_write=self._io_write,
                serial_rx=self._serial_receive,
                serial_tx=self._serial_transmit,
                csio_rx=(
                    self._csio_device.receive
                    if self._csio_device is not None
                    else None
                ),
                csio_tx=(
                    self._csio_device.transmit
                    if self._csio_device is not None
                    else None
                ),
            )
        if stdio_watch_pc is not None:
            self._arm_pc_watch(stdio_watch_pc)

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
            if self.core == "direct":
                self._pending_irq_states[line] = bool(state)
            else:
                self.cpu.set_irq(line, state)
        return callback

    def _mem_read(self, addr: int) -> int:
        """Read memory and preserve compatibility-path read observers."""
        if self.core == "compat":
            input_boundary = self._input_boundary
            if (
                input_boundary is not None
                and addr == input_boundary.keyboard_wait_pc
            ):
                if self.memory.read(input_boundary.keyboard_queue_count) == 0:
                    self._keyboard_ready_epoch += 1
                else:
                    self._keyboard_consume_epoch += 1

            boundary = self._english_boundary
            if (
                self._english_callback is not None
                and boundary is not None
                and addr == boundary.capture_addr
            ):
                cycle = self.cpu.cycle_count
                if cycle != self._english_capture_cycle:
                    self._english_capture_cycle = cycle
                    source = self.cpu.get_reg(CompatZ180.HL)
                    segment_length = self.cpu.get_reg(CompatZ180.BC) & 0xFFFF
                    common_page = self.cpu.cbar >> 4
                    if (
                        source == boundary.spbuf
                        and source >> 12 >= common_page
                        and 0 < segment_length <= 0xFF
                    ):
                        physical = (source + (self.cpu.cbr << 12)) & 0xFFFFF
                        message = bytearray()
                        for offset in range(0x100):
                            value = self.memory.read(physical + offset)
                            if value == 0:
                                text = bytes(message).decode(
                                    "ascii",
                                    errors="replace",
                                ).strip()
                                if text:
                                    self._english_callback(text)
                                break
                            message.append(value)
        return self.memory.read(addr)

    def _observe_instruction_boundary(self) -> None:
        """Preserve callback-era observers at the exact instruction boundary."""
        pc = self.cpu.reg(Reg.PC)
        physical_pc = self.cpu.mmu_translate(pc)
        self._observe_input_boundary(physical_pc)

        boundary = self._english_boundary
        if (
            self._english_callback is not None
            and boundary is not None
            and physical_pc == boundary.capture_addr
        ):
            self._capture_english_boundary(boundary)

    def _observe_input_boundary(self, physical_pc: int) -> None:
        """Update firmware input epochs at one physical instruction address."""
        input_boundary = self._input_boundary
        if (
            input_boundary is not None
            and physical_pc == input_boundary.keyboard_wait_pc
        ):
            if self.memory.read(input_boundary.keyboard_queue_count) == 0:
                self._keyboard_ready_epoch += 1
            else:
                self._keyboard_consume_epoch += 1

    def _capture_english_boundary(self, boundary: EnglishBoundary) -> None:
        """Capture one exact pre-translation string from native register state."""
        cycle = self.cpu.cycle_count()
        if cycle == self._english_capture_cycle:
            return
        self._english_capture_cycle = cycle
        source = self.cpu.reg(Reg.HL)
        segment_length = self.cpu.reg(Reg.BC) & 0xFFFF
        cbr = self.cpu.io_reg_peek(self.PORT_CBR)
        common_page = self.cpu.io_reg_peek(self.PORT_CBAR) >> 4
        if not (
            source == boundary.spbuf
            and source >> 12 >= common_page
            and 0 < segment_length <= 0xFF
        ):
            return
        physical = (source + (cbr << 12)) & 0xFFFFF
        message = bytearray()
        for offset in range(0x100):
            value = self.memory.read(physical + offset)
            if value == 0:
                text = bytes(message).decode("ascii", errors="replace").strip()
                if text:
                    self._english_callback(text)
                return
            message.append(value)

    def _mem_write(self, addr: int, value: int) -> None:
        """Write memory with backend-specific instruction observations."""
        if self.core == "compat":
            pc = self.cpu.instruction_pc
            cycle = self.cpu.cycle_count
        else:
            pc = self._callback_pc
            cycle = self._callback_cycle
        self._observe_write(
            addr,
            value,
            pc=pc,
            cycle=cycle,
        )
        self.memory.write(addr, value)

    def _observe_write(self, addr: int, value: int, *, pc: int, cycle: int) -> None:
        """Apply QNS write observers after z-core has stored internal RAM."""
        self.stats['writes'] += 1

        # Count only the linked STARTA instruction that opens another command-loop
        # epoch.  The same timer is also cleared during early RAM initialization.
        input_boundary = self._input_boundary
        if input_boundary is not None and addr == input_boundary.reset_complete:
            self._reset_complete_writes += 1
        if (
            input_boundary is not None
            and addr == input_boundary.keyboard_input_buffer
            and value != 0
        ):
            self._keyboard_accept_epoch = self._keyboard_ready_epoch
        if (
            input_boundary is not None
            and addr == input_boundary.keyboard_queue_count
            and value != 0
        ):
            self._keyboard_queue_epoch += 1
        if (
            input_boundary is not None
            and addr == input_boundary.command_loop_timer
            and value == 0
            and pc == input_boundary.command_loop_timer_pc
        ):
            self._command_loop_write_count += 1
            if self.memory.read(input_boundary.keyboard_queue_count) == 0:
                self._keyboard_ready_epoch += 1

        single_trace = self.trace_writes_addr is not None and addr == self.trace_writes_addr
        range_trace = (
            self.trace_writes_range is not None
            and self.trace_writes_range[0] <= addr <= self.trace_writes_range[1]
        )
        if single_trace or range_trace:
            self.traced_writes.append((cycle, pc, addr, value))

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

    def _process_memory_events(self) -> None:
        """Drain native RAM-write events before their bounded queue can overflow."""
        for event in self.cpu.drain_events():
            if event["kind"] == "mem_write":
                self._observe_write(
                    event["phys"],
                    event["value"],
                    pc=event["pc"],
                    cycle=event["cycle"],
                )
        if self.cpu.events_lost():
            raise RuntimeError("z-core memory events were lost; QNS observers are invalid")

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

        family = self.profile.family

        # Keyboard and key-clear ports are profile-owned.
        keyboard_read = (
            self._read_bl4_dots if family == "bl4" else self.keyboard.read
        )
        self.io.register(self.keyboard.port, keyboard_read, self.keyboard.write)
        if isinstance(self.keyboard, BrailleKeyboard):
            self.io.register(
                self.keyboard.keyclr_port,
                self.keyboard.keyclr_read,
                self.keyboard.keyclr_write,
            )
        if family == "bl4":
            self.io.register(0xC0, read_handler=self._read_bl4_space)

        # BSPLUS maps the MSM6242 direct-bus RTC across 0x60-0x6F.
        if family != "tns":
            self.io.register_range(
                self.PORT_RTC_START,
                self.PORT_RTC_END,
                self.rtc.read,
                self.rtc.write,
            )

        if family == "tns":
            self.io.register(0x80, self.watchdog.read, self._write_speech_power)
            self.io.register(0xB0, write_handler=self._write_tns_power)
            for port in range(0xC0, 0xC4):
                self.io.register(
                    port,
                    self._read_parallel_port if port != 0xC3 else None,
                    self._write_parallel_port,
                )
            self.io.register(0xE0, self._read_tns_status, self._write_tns_latch)
        elif family == "bsnew":
            # BSNEW shares 0x80 with watchdog reads and 8255 port-A writes.
            self.io.register(0x80, self.watchdog.read, self._write_parallel_port)
            for port in range(0x81, 0x83):
                self.io.register(port, self._read_parallel_port, self._write_parallel_port)
            self.io.register(0x83, write_handler=self._write_parallel_port)
            self.io.register(0xA0, write_handler=self._write_bsnew_power)
            self.io.register(0xE0, write_handler=self._write_high_bank)
        elif family == "bl4":
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
        value = self.parallel_ports[port - self.profile.parallel_port_base]
        if self.profile.family == "bsnew" and port == 0x81 and self.gas_gauge:
            if self.gas_gauge.read_line(self._callback_cycle):
                value |= 0x08
            else:
                value &= ~0x08
        return value

    def _write_parallel_port(self, port: int, value: int) -> None:
        """Apply one BSNEW 8255 data or control-register write."""
        register = port - self.profile.parallel_port_base
        self.parallel_ports[register] = value
        if register != 3:
            return
        if isinstance(self.display, ParallelBrailleDisplay):
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
            self.gas_gauge.write_line(bool(value & 0x20), self._callback_cycle)

    def _write_tns_power(self, port: int, value: int) -> None:
        """Retain the Type 'n Speak power-control latch."""
        self.power_latch = value

    def _read_tns_status(self, port: int) -> int:
        """Expose the active-low Type 'n Speak keyboard-PIC ready input."""
        return self.keyboard.status()

    def _write_tns_latch(self, port: int, value: int) -> None:
        """Retain the Type 'n Speak status/clock latch output."""
        self.high_bank_latch = value

    def _read_bl4_dots(self, port: int) -> int:
        """Return BL4 dot keys without its separately wired space bar."""
        return self.keyboard.read(port) & 0x3F

    def _read_bl4_space(self, port: int) -> int:
        """Return the BL4 space-bar input on port C0 bit zero."""
        return int(bool(self.keyboard.dots & 0x40))

    def _write_bl4_power(self, port: int, value: int) -> None:
        """Apply the BL4 combined power and gas-gauge output latch."""
        self.power_latch = value
        self.rs232_power_enabled = bool(value & 0x01)
        self.speech_power_enabled = bool(value & 0x02)
        self.disk_power_enabled = bool(value & 0x10)
        self.charge_output_high = bool(value & 0x80)
        if self.gas_gauge:
            self.gas_gauge.write_line(bool(value & 0x80), self._callback_cycle)

    def _read_bl4_status(self, port: int) -> int:
        """Return power-on status plus the BL4 gas-gauge input on bit three."""
        value = 0xFF
        if self.gas_gauge and not self.gas_gauge.read_line(self._callback_cycle):
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
        """Return the next PC Disk or stdin byte for the selected ASCI channel."""
        if channel == 0 and self.pc_disk is not None:
            value = self.pc_disk.receive()
            if value >= 0:
                return value
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
        """Deliver an ASCI byte to PC Disk and explicitly selected observers."""
        if channel == 0 and self.pc_disk is not None:
            self.pc_disk.transmit(value)
        if self.stdio_output is not None:
            self.stdio_output.emit_serial(channel, bytes((value,)))
        if self.serial_output is not None:
            if channel != self.serial_output_channel:
                return
            self.serial_output.write(bytes((value,)))
            self.serial_output.flush()

    def _apply_pending_irqs(self) -> None:
        """Apply device IRQ state only outside z-core bus callbacks."""
        lines = (IrqLine.Int0, IrqLine.Int1, IrqLine.Int2)
        for number, line in enumerate(lines):
            state = self._pending_irq_states[number]
            if self._applied_irq_states[number] != state:
                self.cpu.set_irq(line, state)
                self._applied_irq_states[number] = state

    def _pump_serial_inputs(self) -> None:
        """Offer retained ASCI and CSI/O input bytes to z-core."""
        for channel in range(2):
            pending = self._pending_asci_rx[channel]
            if pending is None:
                received = self._serial_receive(channel)
                if received >= 0:
                    pending = received & 0xFF
                    self._pending_asci_rx[channel] = pending
            if pending is not None and self.cpu.asci_rx_push(channel, pending):
                self._pending_asci_rx[channel] = None

        if self._csio_device is not None:
            if self._pending_csio_rx is None:
                received = self._csio_device.receive()
                if received >= 0:
                    self._pending_csio_rx = received & 0xFF
            if (
                self._pending_csio_rx is not None
                and self.cpu.csio_rx_push(self._pending_csio_rx)
            ):
                self._pending_csio_rx = None

    def _drain_serial_outputs(self) -> None:
        """Deliver all native ASCI and CSI/O output bytes to QNS devices."""
        for channel in range(2):
            while (value := self.cpu.asci_tx_pop(channel)) is not None:
                self._serial_transmit(channel, value)
        if self._csio_device is not None:
            while (value := self.cpu.csio_tx_pop()) is not None:
                self._csio_device.transmit(value)

    def _arm_pc_watch(self, address: int) -> None:
        """Arm z-core's PC counter and QNS's cycle/CBAR observation."""
        self._pc_watch_address = address
        self._pc_watch_cycle = 0
        self._pc_watch_cbar = 0
        if self.core == "direct":
            self.cpu.set_pc_watch(address)
        else:
            self.cpu.watch_pc(address)

    def _prepare_instruction(self, *, pump_inputs: bool = True) -> None:
        """Perform all ordering-sensitive work immediately before one step."""
        self._apply_pending_irqs()
        if pump_inputs:
            self._pump_serial_inputs()
        self._observe_instruction_boundary()
        self._callback_cycle = self.cpu.cycle_count()
        self._callback_pc = self.cpu.reg(Reg.PC)
        if self._pc_watch_address == self._callback_pc:
            self._pc_watch_cycle = self._callback_cycle
            self._pc_watch_cbar = self.cpu.io_reg_peek(self.PORT_CBAR)

    def _finish_execution(self) -> None:
        """Drain all native outputs and observer events after execution."""
        self._process_memory_events()
        self._drain_serial_outputs()

    def _execute_instruction(self, *, pump_inputs: bool = True) -> int:
        """Execute one instruction with QNS queue and observer ordering."""
        self._prepare_instruction(pump_inputs=pump_inputs)
        actual = self.cpu.step()
        self._finish_execution()
        return actual

    def _requires_instruction_steps(self) -> bool:
        """Return whether callbacks or observers require instruction boundaries.

        The input boundary is only observed on behalf of ChordInputDriver,
        which runs only when input or a reset gesture is requested.  Having
        merely *discovered* the boundary is not a reason to step: that alone
        held every run to the per-instruction path, which is ~6x slower than
        letting the core run a whole budget and is the difference between
        keeping up with real-time speech and falling behind it.
        """
        return any((
            self._english_callback is not None,
            self.profile.flash_size > 0,
            self.gas_gauge is not None,
            self.trace_interrupts,
            self._keyboard_needs_steps(),
            self.stdin_device not in (None, "keyboard"),
            self.reset_mode is not None,
            self._pc_watch_address is not None,
        ))

    def _keyboard_needs_steps(self) -> bool:
        """Whether a keystroke is in flight and needs boundary observation.

        Stepping costs roughly six times the core's own speed, which is
        the difference between keeping ahead of real-time speech and
        falling behind it.  A keyboard that is merely *connected* does
        not need it: the epochs the observer maintains are only consulted
        while delivering a chord.  So pay for it during delivery, and run
        the core at full speed the rest of the time - which is precisely
        when speech is playing.
        """
        if self.stdin_device != "keyboard":
            return False
        driver = self._input_driver
        return driver is None or driver.busy

    def _execute_budget(self, cycles: int) -> int:
        """Execute at least the requested cycle budget with correct device ordering."""
        if self.core == "compat":
            return self.cpu.run(cycles)

        if self._requires_instruction_steps():
            self._pump_serial_inputs()
            actual = 0
            while actual < cycles:
                step_cycles = self._execute_instruction(pump_inputs=False)
                if step_cycles == 0:
                    break
                actual += step_cycles
            return actual

        self._apply_pending_irqs()
        self._pump_serial_inputs()
        self._callback_cycle = self.cpu.cycle_count()
        self._callback_pc = self.cpu.reg(Reg.PC)
        actual = self.cpu.run(cycles)
        self._finish_execution()
        return actual

    def _realtime_sleep_duration(self, ahead: float) -> float:
        """Keep low audio buffered by spending bounded emulator run-ahead."""
        audio_lead = (
            self.synth.realtime_lead_seconds()
            if self.synth is not None
            else 0.0
        )
        return max(0.0, ahead - audio_lead)

    def load_rom(self, path: Path | str) -> None:
        """Load a pre-extracted .bin, raw firmware image, or update package."""
        path = Path(path)
        image = load_firmware(path)
        if image.kind == "pre-extracted":
            print(f"Loading pre-extracted firmware: {path.name}")
        elif image.kind == "package":
            print(
                "Extracted firmware from update package at offset "
                f"0x{image.image_offset:X}"
            )
            print(
                f"  Package size: {image.package_size} bytes, "
                f"Firmware size: {len(image.data)} bytes"
            )
        self.memory.load_rom(image.data)
        print(f"Loaded ROM: {path.name} ({len(image.data)} bytes at physical 0x00000)")

        self._english_boundary = find_english_boundary(image.data)
        if self._english_boundary is not None:
            print(
                "English speech boundary: capture "
                f"0x{self._english_boundary.capture_addr:04X}, "
                f"SPBUF 0x{self._english_boundary.spbuf:04X}"
            )
        self._seed_retained_speech_settings(image.data)

        self._input_boundary = find_input_boundary(image.data)
        if self._input_boundary is not None:
            print(
                "Chord acceptance boundary: buffer "
                f"0x{self._input_boundary.keyboard_input_buffer:05X}, "
                f"queue 0x{self._input_boundary.keyboard_queue_count:05X}, "
                f"wait PC 0x{self._input_boundary.keyboard_wait_pc:04X}, "
                f"timer 0x{self._input_boundary.command_loop_timer:05X} "
                f"@ PC 0x{self._input_boundary.command_loop_timer_pc:04X}, "
                f"reset 0x{self._input_boundary.reset_complete:05X}"
            )

    def _seed_retained_speech_settings(self, firmware: bytes) -> None:
        """Give the speech settings the values a field unit would retain.

        `BSPMON.ASM::ISSET` applies volume, rate, inflection and filter
        frequency to the SSI-263 from uninitialised scratch RAM.  No
        shipped code path ever writes them - a real unit carries them in
        battery-backed RAM - so a machine that starts RAM at zero makes
        the firmware faithfully write amplitude 0 and speak silence.

        Seeding here rather than in `reset` is deliberate: this is
        retained state that survives a reset, which is exactly the
        property that makes the real hardware work.
        """
        timeout = find_speech_power_timeout(firmware)
        if timeout is not None:
            self.memory.write(timeout.address, timeout.value)
            print(
                f"Speech power timeout: {timeout.value} @ "
                f"0x{timeout.address:05X}"
            )

        self._speech_parameters = find_speech_parameters(
            firmware,
            self.profile.ssi263_port,
        )
        if self._speech_parameters is None:
            print("Retained speech settings: ISSET not found, leaving RAM at 0")
            return

        self._write_retained_speech_settings(self._speech_settings)
        print(
            "Retained speech settings: "
            + ", ".join(
                f"{field} {self._speech_settings[field]} @ "
                + "/".join(
                    f"0x{address:05X}"
                    for address in getattr(self._speech_parameters, field)
                )
                for field in RETAINED_SPEECH_DEFAULTS
            )
        )

    def _write_retained_speech_settings(
        self,
        settings: dict[str, int],
    ) -> None:
        """Write selected retained settings to every firmware-owned cell."""
        if self._speech_parameters is None:
            return
        for field, value in settings.items():
            for address in getattr(self._speech_parameters, field):
                self.memory.write(address, value)

    def reset(self) -> None:
        """Reset the emulator."""
        self.cpu.reset()
        if self.core == "direct":
            self._applied_irq_states = {0: None, 1: None, 2: None}
            self._callback_cycle = 0
            self._callback_pc = 0
            self._pending_asci_rx = [None, None]
            self._pending_csio_rx = None
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

        input_driver: ChordInputDriver | None = None
        pc_watch_reported = False
        terminal = contextlib.ExitStack()
        if self.stdin_device is not None or self.reset_mode is not None:
            if self.stdin_device in ("keyboard", "jsonl") or self.reset_mode is not None:
                if self._input_boundary is None:
                    if self.reset_mode is not None:
                        raise RuntimeError(
                            "chord-acceptance addresses were not discovered "
                            "in this firmware; reset is unavailable"
                        )
                    print(
                        "[Input] chord-acceptance addresses not discovered "
                        "in this firmware; keyboard input disabled"
                    )
                else:
                    input_driver = ChordInputDriver(self)
                    self._input_driver = input_driver
                if input_driver is not None and self.reset_mode is not None:
                    input_driver.start_reset(self.reset_mode)

            stdin_started = threading.Event()

            def read_stdin() -> None:
                stdin_started.set()
                if self.stdin_device == "keyboard":
                    while character := _read_stdin_character():
                        input_driver.queue.put(character)
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
                                    input_driver.queue.put(character)
                            else:
                                input_driver.queue.put(event.value)
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

            if self.stdin_device is not None:
                # Enter cbreak before the reader starts, and leave it from
                # this thread: the reader is a daemon and would be killed
                # without unwinding, stranding the user's terminal.
                if self.stdin_device == "keyboard":
                    terminal.enter_context(_keystrokes_unbuffered())
                stdin_thread = threading.Thread(
                    target=read_stdin,
                    daemon=True,
                    name="bns-stdin",
                )
                stdin_thread.start()
                stdin_started.wait()
                print(f"Input: STDIN ({self.stdin_device})")

        cycles_run = 0
        start_wall = time.perf_counter()
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
                    self._arm_pc_watch(watch_pc)
                    pc_watch_reported = False
                    if self.stdio_output is not None:
                        self.stdio_output.emit(
                            "cpu",
                            event="watch-armed",
                            pc=watch_pc,
                        )

                chunk_size = self._chunk_cycles
                chunk = (
                    chunk_size
                    if max_cycles == 0
                    else min(chunk_size, max_cycles - cycles_run)
                )
                actual = self._execute_budget(chunk)
                cycles_run += actual

                if actual == 0:
                    # The Z180 executed SLP and is waiting for an interrupt
                    # (the firmware calls a RAM-resident `SLP; RET` stub at
                    # the end of every phoneme).  A sleeping core advances no
                    # cycles, so nothing would ever reach the phoneme's
                    # scheduled completion and the loop would spin forever -
                    # which is exactly what made a 6M-cycle greeting appear
                    # to take 40 minutes.  Jump emulated time to the next
                    # scheduled device event instead; sleeping then costs
                    # one iteration rather than a million.
                    wake = self.ssi263.pending_irq_cycle
                    if wake is not None and wake > cycles_run:
                        cycles_run = wake if max_cycles == 0 else min(wake, max_cycles)
                    else:
                        # Nothing scheduled here, but the Z180's own timers
                        # still wake the background task, so let time pass
                        # rather than stopping: asleep is not dead.
                        cycles_run += chunk

                self.stats['cycles'] = cycles_run

                if self.realtime:
                    # Hold emulated time to wall-clock time.  The chip already
                    # paces phonemes correctly in emulated time, so once the
                    # two clocks agree, a phoneme that lasts 120 ms of emulated
                    # time also lasts 120 ms of real time - and the audio the
                    # backend queues per phoneme plays continuously.
                    ahead = start_wall + cycles_run / self.clock - time.perf_counter()
                    sleep_duration = self._realtime_sleep_duration(ahead)
                    if sleep_duration > 0:
                        time.sleep(sleep_duration)

                watch_hits = (
                    self.cpu.pc_watch_hits()
                    if self.core == "direct"
                    else self.cpu.pc_watch_count
                )
                if (
                    self.stdio_output is not None
                    and self._stdio_watch_pc is not None
                    and watch_hits > 0
                    and not pc_watch_reported
                ):
                    if self.core == "compat":
                        self._pc_watch_cycle = self.cpu.pc_watch_cycle
                        self._pc_watch_cbar = self.cpu.pc_watch_cbar
                    self.stdio_output.emit(
                        "cpu",
                        event="pc-watch",
                        pc=self._stdio_watch_pc,
                        cycle=self._pc_watch_cycle,
                        cbar=self._pc_watch_cbar,
                    )
                    pc_watch_reported = True

                # Update SSI-263 cycle count and check for pending phoneme completion IRQ
                self.ssi263.set_cycle_count(cycles_run)
                self.ssi263.check_pending_irq(cycles_run)

                if input_driver is not None:
                    input_driver.tick()

                self.stats['phonemes'] = len(self.ssi263.phoneme_log)

                # Print I/O log if tracing (periodically to avoid flooding)
                if self.io.logging and self.io._log:
                    for entry in self.io.dump_log():
                        print(f"[IO] {entry}")
                    self.io._log.clear()

        except KeyboardInterrupt:
            print("\nEmulation stopped by user")
        finally:
            terminal.close()
            if self.synth:
                self.synth.stop()

        self.stats['cycles'] = cycles_run
        print(f"Executed {cycles_run:,} cycles")
        final_pc = (
            self.cpu.reg(Reg.PC)
            if self.core == "direct"
            else self.cpu.pc
        )
        print(f"Final PC: {final_pc:04X}")

    def step(self) -> int:
        """Execute a single instruction. Returns cycles consumed."""
        if self.core == "direct":
            return self._execute_instruction()
        return self.cpu.step()

    def dump_ram(self, path: Path | str) -> None:
        """Dump RAM contents to a file."""
        path = Path(path)
        path.write_bytes(bytes(self.memory.ram))
        print(f"RAM dumped to {path} ({len(self.memory.ram)} bytes)")

    def load_state(self, path: Path | str) -> None:
        """Load the BNS nonvolatile RAM state."""
        self.memory.load_state(path)
        self._write_retained_speech_settings(self._speech_overrides)
        print(f"Loaded nonvolatile RAM state: {path}")

    def save_state(self, path: Path | str) -> None:
        """Save the BNS nonvolatile RAM state."""
        self.memory.save_state(path)
        print(f"Saved nonvolatile RAM state: {path}")

    def load_state_dir(self, path: Path | str) -> None:
        """Load BNS nonvolatile state from a directory."""
        self.memory.load_state_dir(path)
        self._write_retained_speech_settings(self._speech_overrides)
        print(f"Loaded nonvolatile state directory: {path}")

    def save_state_dir(self, path: Path | str) -> None:
        """Save BNS nonvolatile state to a directory."""
        self.memory.save_state_dir(path)
        print(f"Saved nonvolatile state directory: {path}")

    def print_stats(self) -> None:
        """Print execution statistics."""
        if self.core == "direct":
            pc = self.cpu.reg(Reg.PC)
            halted = self.cpu.halted()
            cbr = self.cpu.io_reg_peek(self.PORT_CBR)
            bbr = self.cpu.io_reg_peek(self.PORT_BBR)
            cbar = self.cpu.io_reg_peek(self.PORT_CBAR)
        else:
            pc = self.cpu.pc
            halted = self.cpu.halted
            cbr = self.cpu.cbr
            bbr = self.cpu.bbr
            cbar = self.cpu.cbar
        print("\n=== Execution Statistics ===")
        print(f"Cycles executed: {self.stats['cycles']:,}")
        print(f"Memory writes:   {self.stats['writes']:,}")
        print(f"Phonemes output: {self.stats['phonemes']}")
        print(f"Final PC:        0x{pc:04X}")
        print(f"CPU halted:      {halted}")
        print(
            f"MMU state:       CBR=0x{cbr:02X} BBR=0x{bbr:02X} "
            f"CBAR=0x{cbar:02X}"
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
            pc_before = (
                self.cpu.reg(Reg.PC)
                if self.core == "direct"
                else self.cpu.pc
            )
            cycles = self.step()
            pc_after = (
                self.cpu.reg(Reg.PC)
                if self.core == "direct"
                else self.cpu.pc
            )
            print(f"{i+1}. PC: {pc_before:04X} -> {pc_after:04X} ({cycles} cycles)")


if __name__ == "__main__":
    from .cli import main

    main()
