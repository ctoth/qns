"""Z180 CPU wrapper - CFFI bindings to z180emu.

This module provides a Python interface to the z180emu C library.
If the CFFI extension isn't built, falls back to a stub implementation.
"""

from __future__ import annotations

from collections.abc import Callable

# Try to import the compiled CFFI module
try:
    from ._z180_cffi import ffi, lib
    CFFI_AVAILABLE = True
except ImportError:
    CFFI_AVAILABLE = False
    ffi = None
    lib = None


class Z180:
    """Z180 CPU emulator.

    Uses z180emu via CFFI when available, otherwise provides a stub.
    """

    # CPU state indices (from z180.h)
    PC = 0x100000
    SP = 0x100001
    AF = 0x100002
    BC = 0x100003
    DE = 0x100004
    HL = 0x100005
    IX = 0x100006
    IY = 0x100007

    # IRQ lines
    IRQ0 = 0
    IRQ1 = 1
    IRQ2 = 2

    # Line states
    CLEAR = 0
    ASSERT = 1

    def __init__(
        self,
        clock: int = 12_288_000,
        mem_read: Callable[[int], int] | None = None,
        mem_write: Callable[[int, int], None] | None = None,
        io_read: Callable[[int], int] | None = None,
        io_write: Callable[[int, int], None] | None = None,
        serial_rx: Callable[[int], int] | None = None,
        serial_tx: Callable[[int, int], None] | None = None,
        csio_rx: Callable[[], int] | None = None,
        csio_tx: Callable[[int], None] | None = None,
    ):
        """Create a Z180 CPU.

        Args:
            clock: CPU clock frequency in Hz (default 12.288 MHz)
            mem_read: Callback for memory reads (address) -> value
            mem_write: Callback for memory writes (address, value) -> None
            io_read: Callback for I/O reads (port) -> value
            io_write: Callback for I/O writes (port, value) -> None
            serial_rx: Callback returning a byte or -1 when no byte is available
            serial_tx: Callback for transmitted (channel, byte) pairs
            csio_rx: Callback returning a CSI/O byte or -1 when unavailable
            csio_tx: Callback for transmitted CSI/O bytes
        """
        self.clock = clock
        self._halted = False

        # Store callbacks
        self._mem_read = mem_read
        self._mem_write = mem_write
        self._io_read = io_read
        self._io_write = io_write
        self._serial_rx = serial_rx
        self._serial_tx = serial_tx
        self._csio_rx = csio_rx
        self._csio_tx = csio_tx

        if CFFI_AVAILABLE:
            self._init_cffi()
        else:
            self._init_stub()

    def _init_cffi(self) -> None:
        """Initialize using CFFI z180emu bindings."""
        # Create CFFI callback handles
        # These must be kept alive for the duration of the CPU

        @ffi.callback("UINT8(offs_t)")
        def c_mem_read(addr: int) -> int:
            if self._mem_read:
                return self._mem_read(addr) & 0xFF
            return 0xFF

        @ffi.callback("void(offs_t, UINT8)")
        def c_mem_write(addr: int, val: int) -> None:
            if self._mem_write:
                self._mem_write(addr, val)

        @ffi.callback("UINT8(offs_t)")
        def c_io_read(port: int) -> int:
            if self._io_read:
                return self._io_read(port) & 0xFF
            return 0xFF

        @ffi.callback("void(offs_t, UINT8)")
        def c_io_write(port: int, val: int) -> None:
            if self._io_write:
                self._io_write(port, val)

        @ffi.callback("int(int)")
        def c_serial_rx(channel: int) -> int:
            if self._serial_rx:
                return self._serial_rx(channel)
            return -1

        @ffi.callback("void(int, UINT8)")
        def c_serial_tx(channel: int, val: int) -> None:
            if self._serial_tx:
                self._serial_tx(channel, val)

        @ffi.callback("int(void)")
        def c_csio_rx() -> int:
            if self._csio_rx:
                return self._csio_rx()
            return -1

        @ffi.callback("void(UINT8)")
        def c_csio_tx(val: int) -> None:
            if self._csio_tx:
                self._csio_tx(val)

        # Keep callbacks alive
        self._c_callbacks = (
            c_mem_read,
            c_mem_write,
            c_io_read,
            c_io_write,
            c_serial_rx,
            c_serial_tx,
            c_csio_rx,
            c_csio_tx,
        )

        # Create the CPU
        self._cpu = lib.qns_z180_create(
            self.clock,
            c_mem_read,
            c_mem_write,
            c_io_read,
            c_io_write,
            c_serial_rx,
            c_serial_tx,
            c_csio_rx,
            c_csio_tx,
        )
        if self._cpu == ffi.NULL:
            raise RuntimeError("Failed to create Z180 CPU")

    def _init_stub(self) -> None:
        """Initialize stub implementation (no actual CPU execution)."""
        self._cpu = None
        self._cycle_count = 0
        self._regs = {
            self.PC: 0x0000,
            self.SP: 0xFFFF,
            self.AF: 0x0000,
            self.BC: 0x0000,
            self.DE: 0x0000,
            self.HL: 0x0000,
            self.IX: 0x0000,
            self.IY: 0x0000,
        }
        print("[Z180] Warning: CFFI not available, using stub implementation")
        print("[Z180] Run 'python tools/build_ffi.py' to build the extension")

    def reset(self) -> None:
        """Reset the CPU."""
        if CFFI_AVAILABLE and self._cpu:
            lib.qns_z180_reset(self._cpu)
        else:
            self._regs[self.PC] = 0x0000
            self._regs[self.SP] = 0xFFFF
            self._halted = False
            self._cycle_count = 0

    def step(self) -> int:
        """Execute one instruction. Returns cycles consumed."""
        return self.run(1)

    def run(self, cycles: int) -> int:
        """Run for specified cycles. Returns actual cycles executed."""
        if CFFI_AVAILABLE and self._cpu:
            return lib.qns_z180_execute(self._cpu, cycles)
        else:
            # Stub: just return cycles without doing anything
            self._cycle_count += cycles
            return cycles

    @property
    def cycle_count(self) -> int:
        """Return the accumulated cycle position visible to I/O callbacks."""
        if CFFI_AVAILABLE and self._cpu:
            return int(lib.qns_z180_get_cycle_count(self._cpu))
        return self._cycle_count

    def get_reg(self, reg: int) -> int:
        """Get a CPU register value."""
        if CFFI_AVAILABLE and self._cpu:
            return lib.qns_z180_get_reg(self._cpu, reg)
        else:
            return self._regs.get(reg, 0)

    @property
    def pc(self) -> int:
        """Get program counter."""
        if CFFI_AVAILABLE and self._cpu:
            return lib.qns_z180_get_pc(self._cpu)
        return self._regs.get(self.PC, 0)

    @property
    def sp(self) -> int:
        """Get stack pointer."""
        return self.get_reg(self.SP)

    @property
    def halted(self) -> bool:
        """Check if CPU is halted."""
        if CFFI_AVAILABLE and self._cpu:
            return bool(lib.qns_z180_is_halted(self._cpu))
        return self._halted

    def set_irq(self, line: int, state: int) -> None:
        """Set an IRQ line state."""
        if CFFI_AVAILABLE and self._cpu:
            lib.qns_z180_set_irq(self._cpu, line, state)

    @property
    def cbr(self) -> int:
        """Get Common Base Register (MMU)."""
        if CFFI_AVAILABLE and self._cpu:
            return lib.qns_z180_get_cbr(self._cpu)
        return 0

    @property
    def bbr(self) -> int:
        """Get Bank Base Register (MMU)."""
        if CFFI_AVAILABLE and self._cpu:
            return lib.qns_z180_get_bbr(self._cpu)
        return 0

    @property
    def cbar(self) -> int:
        """Get Common/Bank Area Register (MMU)."""
        if CFFI_AVAILABLE and self._cpu:
            return lib.qns_z180_get_cbar(self._cpu)
        return 0xF0

    def asci_debug_state(self, channel: int) -> dict[str, int | bool]:
        """Return a read-only snapshot of one native ASCI receive path."""
        if channel not in (0, 1):
            raise ValueError(f"ASCI channel must be 0 or 1, got {channel}")
        if not CFFI_AVAILABLE or not self._cpu:
            return {
                "status": 0,
                "rx_bits_remaining": 0,
                "rx_fifo_depth": 0,
                "irq_pending": False,
            }
        return {
            "status": int(lib.qns_z180_get_asci_stat(self._cpu, channel)),
            "rx_bits_remaining": int(
                lib.qns_z180_get_asci_rx_bits_remaining(self._cpu, channel)
            ),
            "rx_fifo_depth": int(lib.qns_z180_get_asci_rx_fifo_depth(self._cpu, channel)),
            "irq_pending": bool(lib.qns_z180_get_asci_irq_pending(self._cpu, channel)),
        }

    def watch_pc(self, address: int | None) -> None:
        """Reset and enable one native instruction-address watch, or disable it."""
        if address is not None and not 0 <= address <= 0xFFFF:
            raise ValueError(f"PC watch address must be 0..FFFF, got {address}")
        if CFFI_AVAILABLE and self._cpu:
            lib.qns_z180_watch_pc(self._cpu, -1 if address is None else address)

    @property
    def pc_watch_count(self) -> int:
        """Return the number of instructions entered at the watched address."""
        if CFFI_AVAILABLE and self._cpu:
            return int(lib.qns_z180_get_pc_watch_count(self._cpu))
        return 0

    @property
    def pc_watch_cycle(self) -> int:
        """Return the accumulated cycle position of the most recent watch hit."""
        if CFFI_AVAILABLE and self._cpu:
            return int(lib.qns_z180_get_pc_watch_cycle(self._cpu))
        return 0

    def __del__(self) -> None:
        """Clean up the CPU."""
        if CFFI_AVAILABLE and hasattr(self, '_cpu') and self._cpu:
            lib.qns_z180_destroy(self._cpu)
            self._cpu = None
