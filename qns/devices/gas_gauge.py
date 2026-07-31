"""BSNEW battery gas gauge on the bq2010 single-wire data line."""


class BQ2010GasGauge:
    """BSNEW battery gas gauge on the bq2010 single-wire data line."""

    def __init__(self):
        self.nac = 100
        self.lmd = 100
        self.flags = 0
        self._line_high = True
        self._fall_cycle: int | None = None
        self._rise_cycle = 0
        self._resynchronizing_break = False
        self._break_cycles = 0
        self._command_bits: list[int] = []
        self.command_log: list[int] = []
        self._awaiting_break = True
        self._reply_value: int | None = None
        self._reply_start = 0

    def write_line(self, high: bool, cycle: int) -> None:
        """Observe one host-driven edge on the open-drain data line."""
        high = bool(high)
        if high == self._line_high:
            return
        self._line_high = high
        if not high:
            high_cycles = cycle - self._rise_cycle
            self._resynchronizing_break = bool(
                not self._awaiting_break
                and self._break_cycles
                and high_cycles > self._break_cycles * 2
            )
            self._fall_cycle = cycle
            return
        if self._fall_cycle is None:
            return

        low_cycles = cycle - self._fall_cycle
        self._fall_cycle = None
        self._rise_cycle = cycle
        if self._awaiting_break or self._resynchronizing_break:
            self._break_cycles = max(1, low_cycles)
            self._command_bits.clear()
            self._reply_value = None
            self._awaiting_break = False
            self._resynchronizing_break = False
            return

        threshold = self._break_cycles // 4
        self._command_bits.append(int(low_cycles < threshold))
        if len(self._command_bits) != 8:
            return

        command = sum(bit << index for index, bit in enumerate(self._command_bits))
        self.command_log.append(command)
        self._reply_value = {
            0x01: self.flags,
            0x03: self.nac,
            0x05: self.lmd,
        }.get(command, 0xFF) & 0xFF
        self._reply_start = cycle + self._break_cycles // 3
        self._awaiting_break = True

    def read_line(self, cycle: int) -> bool:
        """Return the device-driven data-line level at one CPU cycle."""
        if self._reply_value is None or cycle < self._reply_start:
            return True

        elapsed = cycle - self._reply_start
        bit_index, bit_cycle = divmod(elapsed, self._break_cycles)
        if bit_index >= 8:
            self._reply_value = None
            return True

        bit = bool(self._reply_value & (1 << bit_index))
        low_cycles = self._break_cycles // (6 if bit else 2)
        return bit_cycle >= low_cycles
