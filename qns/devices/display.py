"""Braille Lite display devices."""

from collections.abc import Callable

FrameCallback = Callable[[bytes], None]


class BrailleDisplay:
    """Braille Lite 18 display connected through the Z180 CSI/O port."""

    def __init__(
        self,
        cells: int = 18,
        *,
        status: int = 0x0A,
        battery: int = 238,
        current: int = 0xFF,
    ) -> None:
        self.cells = cells
        self.buffer = bytearray(cells)
        self.cursor = 0
        self.status = status
        self.battery = battery
        self.current = current
        self._cell_follows = False
        self._response = -1
        self._frame_callback: FrameCallback | None = None

    def set_frame_callback(self, callback: FrameCallback) -> None:
        """Set the standard-output observer for complete display frames."""
        self._frame_callback = callback

    def transmit(self, value: int) -> None:
        """Accept one source-defined Braille Lite display command or cell."""
        value &= 0xFF
        if self._cell_follows:
            self.buffer[self.cursor] = value
            self.cursor = (self.cursor + 1) % self.cells
            self._cell_follows = False
            if self.cursor == 0 and self._frame_callback is not None:
                self._frame_callback(bytes(self.buffer))
        elif value == 0x81:
            self._response = self.status
        elif value == 0x82:
            self.buffer[:] = b"\0" * self.cells
            self.cursor = 0
            if self._frame_callback is not None:
                self._frame_callback(bytes(self.buffer))
        elif value == 0x83:
            self._cell_follows = True
        elif value == 0x85:
            self._response = self.battery
        elif value == 0x86:
            self._response = self.current

    def receive(self) -> int:
        """Return one pending display response, or -1 while none is pending."""
        response = self._response
        self._response = -1
        return response


class ParallelBrailleDisplay:
    """Braille Lite display shifted through 8255 port-C control bits."""

    def __init__(self, cells: int) -> None:
        if cells not in (18, 40):
            raise ValueError(f"Unsupported parallel display width: {cells}")
        self.cells = cells
        self.buffer = bytearray(cells)
        self._port_c = 0
        self._shift_byte = 0
        self._shift_bits = 0
        self._shifted_bytes: list[int] = []
        self._frame_callback: FrameCallback | None = None

    def set_frame_callback(self, callback: FrameCallback) -> None:
        """Set the standard-output observer for latched display frames."""
        self._frame_callback = callback

    def write_control(self, value: int) -> None:
        """Apply one 8255 mode-set or bit-set/reset control word."""
        value &= 0xFF
        if value & 0x80:
            self._port_c = 0
            self._shift_byte = 0
            self._shift_bits = 0
            self._shifted_bytes.clear()
            return

        bit = (value >> 1) & 0x07
        mask = 1 << bit
        was_set = bool(self._port_c & mask)
        if value & 0x01:
            self._port_c |= mask
        else:
            self._port_c &= ~mask

        if bit == 1 and value & 0x01 and not was_set:
            self._shift_byte |= (self._port_c & 0x01) << self._shift_bits
            self._shift_bits += 1
            if self._shift_bits == 8:
                self._shifted_bytes.append(self._shift_byte)
                self._shift_byte = 0
                self._shift_bits = 0
        elif bit == 2 and value & 0x01 and not was_set:
            self._latch_frame()

    def _latch_frame(self) -> None:
        """Expose the cells visible after the firmware raises display strobe."""
        physical_cells = 24 if self.cells == 18 else 40
        if len(self._shifted_bytes) < physical_cells:
            return
        frame = self._shifted_bytes[-physical_cells:]
        if self.cells == 18:
            frame = [
                value
                for index, value in enumerate(frame)
                if index not in (6, 7, 14, 15, 22, 23)
            ]
        self.buffer[:] = bytes(reversed(frame))
        self._shifted_bytes.clear()
        if self._frame_callback is not None:
            self._frame_callback(bytes(self.buffer))
