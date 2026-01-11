"""I/O port handling for BNS hardware."""


class BrailleKeyboard:
    """8-dot Braille keyboard input."""

    def __init__(self, port: int = 0x40):
        self.port = port
        self.dots = 0x00  # Bits 0-7 = dots 1-8

    def read(self, port: int) -> int:
        """Read current key state."""
        return self.dots

    def write(self, port: int, value: int):
        """Write to keyboard (latch clear)."""
        pass  # Keyboard is input only

    def press(self, dots: int):
        """Simulate key press (dots as bitmask)."""
        self.dots = dots & 0xFF

    def release(self):
        """Release all keys."""
        self.dots = 0x00


class BrailleDisplay:
    """Braille cell display output."""

    def __init__(self, base_port: int = 0x80, cells: int = 40):
        self.base_port = base_port
        self.cells = cells
        self.buffer = bytearray(cells)
        self.cursor = 0

    def read(self, port: int) -> int:
        """Read display status."""
        offset = port - self.base_port
        if offset == 1:  # Status port
            return 0x00  # Ready
        return 0xFF

    def write(self, port: int, value: int):
        """Write to display."""
        offset = port - self.base_port
        if offset == 0:  # Data port
            if self.cursor < self.cells:
                self.buffer[self.cursor] = value & 0xFF
                self.cursor += 1

    def get_text(self) -> str:
        """Convert buffer to ASCII representation."""
        # Simple dot pattern to char (placeholder)
        return ''.join(chr(b) if 32 <= b < 127 else '.' for b in self.buffer)


class Watchdog:
    """Watchdog timer."""

    def __init__(self, port: int = 0x80):
        self.port = port
        self.counter = 0

    def read(self, port: int) -> int:
        return 0xFF

    def write(self, port: int, value: int):
        """Reset watchdog."""
        self.counter = 0


class IOBus:
    """Central I/O bus coordinator."""

    def __init__(self):
        self._read_handlers: dict[int, callable] = {}
        self._write_handlers: dict[int, callable] = {}
        self._log: list[tuple[str, int, int]] = []
        self.logging = True

    def register(self, port: int, read_handler=None, write_handler=None):
        """Register handlers for a port."""
        if read_handler:
            self._read_handlers[port] = read_handler
        if write_handler:
            self._write_handlers[port] = write_handler

    def register_range(self, start: int, end: int, read_handler=None, write_handler=None):
        """Register handlers for a port range."""
        for port in range(start, end + 1):
            self.register(port, read_handler, write_handler)

    def read(self, port: int) -> int:
        """Read from I/O port."""
        port &= 0xFF
        handler = self._read_handlers.get(port)
        value = handler(port) if handler else 0xFF
        if self.logging:
            self._log.append(('R', port, value))
        return value

    def write(self, port: int, value: int):
        """Write to I/O port."""
        port &= 0xFF
        value &= 0xFF
        if self.logging:
            self._log.append(('W', port, value))
        handler = self._write_handlers.get(port)
        if handler:
            handler(port, value)

    def dump_log(self, last_n: int = None) -> list[str]:
        """Get formatted I/O log."""
        log = self._log[-last_n:] if last_n else self._log
        return [f"{op} port={port:02X} val={val:02X}" for op, port, val in log]
