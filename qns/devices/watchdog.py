"""Watchdog timer."""


class Watchdog:
    """Watchdog timer."""

    def __init__(self, port: int = 0x80):
        self.port = port
        self.counter = 0
        self.serviced_at: int | None = None

    def read(self, port: int) -> int:
        return 0xFF

    def write(self, port: int, value: int) -> None:
        """Reset watchdog."""
        self.service()

    def service(self, cycle: int | None = None) -> None:
        """Reset the watchdog and retain the exact service cycle when known."""
        self.counter = 0
        self.serviced_at = cycle
