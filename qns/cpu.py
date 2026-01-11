"""Z180 CPU wrapper - CFFI bindings to z180emu.

This module provides a Python interface to the z180emu C library.
If the CFFI extension isn't built, falls back to a stub implementation.
"""

from __future__ import annotations

from typing import Callable

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
    ):
        """Create a Z180 CPU.

        Args:
            clock: CPU clock frequency in Hz (default 12.288 MHz)
            mem_read: Callback for memory reads (address) -> value
            mem_write: Callback for memory writes (address, value) -> None
            io_read: Callback for I/O reads (port) -> value
            io_write: Callback for I/O writes (port, value) -> None
        """
        self.clock = clock
        self._halted = False

        # Store callbacks
        self._mem_read = mem_read
        self._mem_write = mem_write
        self._io_read = io_read
        self._io_write = io_write

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

        # Keep callbacks alive
        self._c_callbacks = (c_mem_read, c_mem_write, c_io_read, c_io_write)

        # Create the CPU
        self._cpu = lib.qns_z180_create(
            self.clock,
            c_mem_read,
            c_mem_write,
            c_io_read,
            c_io_write,
        )
        if self._cpu == ffi.NULL:
            raise RuntimeError("Failed to create Z180 CPU")

    def _init_stub(self) -> None:
        """Initialize stub implementation (no actual CPU execution)."""
        self._cpu = None
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

    def step(self) -> int:
        """Execute one instruction. Returns cycles consumed."""
        return self.run(1)

    def run(self, cycles: int) -> int:
        """Run for specified cycles. Returns actual cycles executed."""
        if CFFI_AVAILABLE and self._cpu:
            return lib.qns_z180_execute(self._cpu, cycles)
        else:
            # Stub: just return cycles without doing anything
            return cycles

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

    def __del__(self) -> None:
        """Clean up the CPU."""
        if CFFI_AVAILABLE and hasattr(self, '_cpu') and self._cpu:
            lib.qns_z180_destroy(self._cpu)
            self._cpu = None
