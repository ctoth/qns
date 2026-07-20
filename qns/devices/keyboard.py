"""BNS keyboard input devices."""

from collections.abc import Callable

IrqCallback = Callable[[int], None]


class BrailleKeyboard:
    """8-dot Braille keyboard input with interrupt support.

    The BNS uses INT2 for keyboard interrupts. When a key is pressed,
    INT2 is asserted. The ISR reads the keyboard port and clears the
    interrupt by writing to the keyclr port.
    """

    def __init__(self, port: int = 0x40, keyclr_port: int = 0x20):
        self.port = port
        self.keyclr_port = keyclr_port
        self.dots = 0x00  # Latched bits 0-7 = dots 1-8
        self._key_down = False
        self.latched = False  # Key press latched (pending interrupt)
        self._irq_callback: IrqCallback | None = None  # Callback to trigger INT2

    def set_irq_callback(self, callback: IrqCallback) -> None:
        """Set callback for triggering keyboard interrupt.

        Args:
            callback: Function(state) where state is 1=assert, 0=clear
        """
        self._irq_callback = callback

    def read(self, port: int) -> int:
        """Read current key state."""
        return self.dots

    def write(self, port: int, value: int) -> None:
        """Ignore writes to the input-only keyboard port."""

    def keyclr_read(self, port: int) -> int:
        """Read from keyclr port - clears keyboard latch."""
        self._clear_latch()
        return 0xFF

    def keyclr_write(self, port: int, value: int) -> None:
        """Write to keyclr port - clears keyboard latch."""
        self._clear_latch()

    def _clear_latch(self) -> None:
        """Clear the keyboard latch and interrupt."""
        if self.latched:
            self.latched = False
            if self._irq_callback:
                self._irq_callback(0)  # Clear INT2
        if not self._key_down:
            self.dots = 0x00

    def press(self, dots: int) -> None:
        """Simulate key press (dots as bitmask)."""
        self.dots = dots & 0xFF
        self._key_down = bool(self.dots)
        if self.dots and not self.latched:
            self.latched = True
            if self._irq_callback:
                self._irq_callback(1)  # Assert INT2

    def release(self) -> None:
        """Latch the completed chord and signal the key-up edge."""
        if not self._key_down:
            return
        self._key_down = False
        if not self.latched:
            self.latched = True
            if self._irq_callback:
                self._irq_callback(1)  # Assert INT2


class TNSKeyboard:
    """Type 'n Speak keyboard-PIC scan-byte input on INT2."""

    def __init__(self, port: int = 0xD0) -> None:
        self.port = port
        self.code = 0
        self.latched = False
        self._down_code = 0
        self._irq_callback: IrqCallback | None = None

    def set_irq_callback(self, callback: IrqCallback) -> None:
        """Set the INT2 line callback."""
        self._irq_callback = callback

    def read(self, _port: int) -> int:
        """Return and acknowledge the current keyboard-PIC byte."""
        code = self.code
        if self.latched:
            self.latched = False
            if self._irq_callback:
                self._irq_callback(0)
        return code

    def write(self, _port: int, _value: int) -> None:
        """Ignore writes to the input-only keyboard-PIC port."""

    def press(self, code: int) -> None:
        """Present one key-down scan code."""
        self._down_code = code | 0x80
        self._present(self._down_code)

    def release(self, code: int | None = None) -> None:
        """Present a named key-up scan, or release the latest key-down."""
        if code is None:
            code = self._down_code
        if not code:
            return
        if code | 0x80 == self._down_code:
            self._down_code = 0
        self._present(code & 0x7F)

    def _present(self, code: int) -> None:
        self.code = code & 0xFF
        self.latched = True
        if self._irq_callback:
            self._irq_callback(1)
