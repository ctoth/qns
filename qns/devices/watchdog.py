"""Watchdog timer."""


class Watchdog:
    """Watchdog timer."""

    def __init__(self, port: int = 0x80):
        self.port = port
        self.counter = 0

    def read(self, port: int) -> int:
        return 0xFF

    def write(self, port: int, value: int) -> None:
        """Reset watchdog."""
        self.counter = 0
