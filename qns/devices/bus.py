"""Central I/O bus coordinator."""

from collections.abc import Callable

ReadHandler = Callable[[int], int]
WriteHandler = Callable[[int, int], None]


class IOBus:
    """Central I/O bus coordinator."""

    def __init__(self):
        self._read_handlers: dict[int, ReadHandler] = {}
        self._write_handlers: dict[int, WriteHandler] = {}
        self._log: list[tuple[str, int, int]] = []
        self.logging = True

    def register(
        self,
        port: int,
        read_handler: ReadHandler | None = None,
        write_handler: WriteHandler | None = None,
    ) -> None:
        """Register handlers for a port."""
        if read_handler:
            self._read_handlers[port] = read_handler
        if write_handler:
            self._write_handlers[port] = write_handler

    def register_range(
        self,
        start: int,
        end: int,
        read_handler: ReadHandler | None = None,
        write_handler: WriteHandler | None = None,
    ) -> None:
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

    def write(self, port: int, value: int) -> None:
        """Write to I/O port."""
        port &= 0xFF
        value &= 0xFF
        if self.logging:
            self._log.append(('W', port, value))
        handler = self._write_handlers.get(port)
        if handler:
            handler(port, value)

    def dump_log(self, last_n: int | None = None) -> list[str]:
        """Get formatted I/O log."""
        log = self._log[-last_n:] if last_n else self._log
        return [f"{op} port={port:02X} val={val:02X}" for op, port, val in log]
