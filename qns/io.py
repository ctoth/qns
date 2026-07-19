"""I/O port handling for BNS hardware."""

from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta


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


class PIC16C56Clock:
    """Battery-backed BSNEW clock PIC connected through Z180 CSI/O."""

    def __init__(self, now: Callable[[], datetime] | None = None):
        self._now = now or datetime.now
        self._pending_command: int | None = None
        self._responses: deque[int] = deque()
        current = self._now()
        self._normal_fields = {
            "year": current.year,
            "month": current.month,
            "day": current.day,
            "hour": current.hour,
            "minute": current.minute,
            "second": current.second,
            "microsecond": current.microsecond,
        }
        self._normal_reference = current
        self._normal_selected = True
        self._alarm_fields = {
            "year": 1989,
            "month": 0,
            "day": 0,
            "hour": 0,
            "minute": 0,
        }
        self._alarm_minute_wildcard = False
        self._last_alarm_notification: tuple[int, int, int, int, int] | None = None

    def transmit(self, value: int) -> None:
        """Hold one CSI/O byte until the firmware raises the clock strobe."""
        self._pending_command = value & 0xFF

    def strobe(self) -> None:
        """Latch and execute the pending firmware-to-PIC command."""
        if self._pending_command is None:
            return
        command = self._pending_command
        self._pending_command = None
        if command == 2:
            self._normal_selected = True
        elif command == 3:
            self._normal_selected = False
        elif command == 4:
            self._queue_current_datetime()
        else:
            self._write_selected_field(command)

    def receive(self) -> int:
        """Return one PIC-to-firmware byte, or -1 when none is pending."""
        if self._responses:
            return self._responses.popleft()
        self._advance_normal_clock()
        alarm_token = self._current_alarm_token()
        if alarm_token is None or alarm_token == self._last_alarm_notification:
            return -1
        self._last_alarm_notification = alarm_token
        return 0x0A

    def _queue_current_datetime(self) -> None:
        if self._normal_selected:
            self._advance_normal_clock()
            current = self._normal_fields
        else:
            current = self._alarm_fields
        self._responses.append(0x20 | (current["minute"] & 0x1F))
        if current["minute"] > 31:
            self._responses.append(0x05)
        self._responses.extend((
            0x40 | current["month"],
            0x60 | current["day"],
            0xA0 | current["hour"],
            0x80 | ((current["year"] - 1989) & 0x1F),
        ))

    def _write_selected_field(self, value: int) -> None:
        if self._normal_selected:
            self._advance_normal_clock()
            fields = self._normal_fields
        else:
            fields = self._alarm_fields
            if value == 0x06:
                self._alarm_minute_wildcard = True
                self._last_alarm_notification = None
                return
        field = value & 0xE0
        data = value & 0x1F
        if value == 0x05:
            fields["minute"] += 32
        elif field == 0x20:
            fields["minute"] = data
            if not self._normal_selected:
                self._alarm_minute_wildcard = False
        elif field == 0x40:
            fields["month"] = data
        elif field == 0x60:
            fields["day"] = data
        elif field == 0x80:
            fields["year"] = 1989 + data
        elif field == 0xA0:
            fields["hour"] = data
        if self._normal_selected:
            self._normal_reference = self._now()
        else:
            self._last_alarm_notification = None

    def _current_alarm_token(self) -> tuple[int, int, int, int, int] | None:
        alarm = self._alarm_fields
        if not (
            1989 < alarm["year"] <= 2020
            and 0 <= alarm["month"] <= 12
            and 0 <= alarm["day"] <= 31
            and (0 <= alarm["hour"] <= 23 or alarm["hour"] == 0x1F)
            and (self._alarm_minute_wildcard or 0 <= alarm["minute"] <= 59)
        ):
            return None
        current = self._normal_fields
        token = (
            current["year"],
            current["month"],
            current["day"],
            current["hour"],
            current["minute"],
        )
        matches = (
            current["year"] == alarm["year"]
            and (alarm["month"] == 0 or current["month"] == alarm["month"])
            and (alarm["day"] == 0 or current["day"] == alarm["day"])
            and (alarm["hour"] == 0x1F or current["hour"] == alarm["hour"])
            and (
                self._alarm_minute_wildcard
                or current["minute"] == alarm["minute"]
            )
        )
        return token if matches else None

    def _advance_normal_clock(self) -> None:
        current_reference = self._now()
        try:
            current = datetime(
                self._normal_fields["year"],
                self._normal_fields["month"],
                self._normal_fields["day"],
                self._normal_fields["hour"],
                self._normal_fields["minute"],
                self._normal_fields["second"],
                self._normal_fields["microsecond"],
                tzinfo=current_reference.tzinfo,
            )
        except ValueError:
            self._normal_reference = current_reference
            return

        current += current_reference - self._normal_reference
        self._normal_fields.update(
            year=current.year,
            month=current.month,
            day=current.day,
            hour=current.hour,
            minute=current.minute,
            second=current.second,
            microsecond=current.microsecond,
        )
        self._normal_reference = current_reference


class MSM6242RTC:
    """OKI MSM6242-compatible direct-bus real-time clock/calendar."""

    def __init__(
        self,
        base_port: int = 0x60,
        now: Callable[[], datetime] | None = None,
    ):
        self.base_port = base_port
        self._now = now or datetime.now
        self._offset = timedelta()
        self._registers = [0] * 13
        self._registers_dirty = False
        self._hold = False
        self._control_e = 0
        self._control_f = 0x04  # BSP boots in 24-hour mode.
        self._frozen_fallback = self._now().replace(microsecond=0)
        self._set_registers_from_datetime(self._frozen_fallback)

    @property
    def mode_24_hour(self) -> bool:
        """Whether the clock is using its 24-hour register format."""
        return bool(self._control_f & 0x04)

    def read(self, port: int) -> int:
        """Read one of the sixteen four-bit RTC registers."""
        register = (port - self.base_port) & 0x0F
        if register <= 0x0C:
            if self._running and not self._registers_dirty:
                self._set_registers_from_datetime(self._current_datetime())
            return self._registers[register]
        if register == 0x0D:
            return int(self._hold)  # BUSY and IRQ are inactive.
        if register == 0x0E:
            return self._control_e
        return self._control_f

    def write(self, port: int, value: int) -> None:
        """Write one of the sixteen four-bit RTC registers."""
        register = (port - self.base_port) & 0x0F
        value &= 0x0F
        if register <= 0x0C:
            if self._running and not self._registers_dirty:
                self._set_registers_from_datetime(self._current_datetime())
            self._registers[register] = value
            self._registers_dirty = True
            if self._running:
                self._try_commit_registers()
            return
        if register == 0x0D:
            was_running = self._running
            self._hold = bool(value & 0x01)
            self._apply_running_transition(was_running)
            if value & 0x08:
                self._adjust_30_seconds()
            return
        if register == 0x0E:
            self._control_e = value
            return

        was_running = self._running
        reset_was_set = bool(self._control_f & 0x01)
        reset_is_set = bool(value & 0x01)
        mode_24 = self.mode_24_hour
        if reset_was_set or reset_is_set:
            mode_24 = bool(value & 0x04)
        if mode_24 != self.mode_24_hour:
            self._registers_dirty = True
        self._control_f = (value & 0x0B) | (0x04 if mode_24 else 0)
        self._apply_running_transition(was_running)

    @property
    def _running(self) -> bool:
        return not self._hold and not bool(self._control_f & 0x02)

    def _current_datetime(self) -> datetime:
        return (self._now() + self._offset).replace(microsecond=0)

    def _apply_running_transition(self, was_running: bool) -> None:
        if was_running and not self._running:
            self._frozen_fallback = self._current_datetime()
            self._set_registers_from_datetime(self._frozen_fallback)
        elif not was_running and self._running:
            self._commit_registers()

    def _set_registers_from_datetime(self, value: datetime) -> None:
        if self.mode_24_hour:
            hour = value.hour
            hour_tens = hour // 10
        else:
            hour = value.hour % 12 or 12
            hour_tens = hour // 10
            if value.hour >= 12:
                hour_tens |= 0x04

        year = value.year % 100
        self._registers[:] = (
            value.second % 10,
            value.second // 10,
            value.minute % 10,
            value.minute // 10,
            hour % 10,
            hour_tens,
            value.day % 10,
            value.day // 10,
            value.month % 10,
            value.month // 10,
            year % 10,
            year // 10,
            (value.weekday() + 1) % 7,
        )
        self._registers_dirty = False

    def _datetime_from_registers(self) -> datetime:
        second = self._registers[1] * 10 + self._registers[0]
        minute = self._registers[3] * 10 + self._registers[2]
        hour_ones = self._registers[4]
        hour_tens = self._registers[5]
        if self.mode_24_hour:
            hour = (hour_tens & 0x03) * 10 + hour_ones
        else:
            hour_12 = (hour_tens & 0x03) * 10 + hour_ones
            if not 1 <= hour_12 <= 12:
                raise ValueError("invalid 12-hour RTC value")
            hour = hour_12 % 12
            if hour_tens & 0x04:
                hour += 12
        day = self._registers[7] * 10 + self._registers[6]
        month = self._registers[9] * 10 + self._registers[8]
        year_2 = self._registers[11] * 10 + self._registers[10]
        year = 1900 + year_2 if year_2 >= 90 else 2000 + year_2
        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            tzinfo=self._now().tzinfo,
        )

    def _commit_registers(self) -> None:
        self._try_commit_registers()

    def _try_commit_registers(self) -> bool:
        try:
            value = self._datetime_from_registers()
        except ValueError:
            return False
        self._frozen_fallback = value
        self._offset = value - self._now().replace(microsecond=0)
        self._registers_dirty = False
        return True

    def _adjust_30_seconds(self) -> None:
        if self._running:
            value = self._current_datetime()
        else:
            try:
                value = self._datetime_from_registers()
            except ValueError:
                value = self._frozen_fallback
        if value.second < 30:
            value = value.replace(second=0)
        else:
            value += timedelta(seconds=60 - value.second)
        self._frozen_fallback = value
        self._set_registers_from_datetime(value)
        if self._running:
            self._offset = value - self._now().replace(microsecond=0)


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
        self._irq_callback = None  # Callback to trigger INT2

    def set_irq_callback(self, callback):
        """Set callback for triggering keyboard interrupt.

        Args:
            callback: Function(state) where state is 1=assert, 0=clear
        """
        self._irq_callback = callback

    def read(self, port: int) -> int:
        """Read current key state."""
        return self.dots

    def write(self, port: int, value: int):
        """Write to keyboard (latch clear)."""
        pass  # Keyboard port is input only

    def keyclr_read(self, port: int) -> int:
        """Read from keyclr port - clears keyboard latch."""
        self._clear_latch()
        return 0xFF

    def keyclr_write(self, port: int, value: int):
        """Write to keyclr port - clears keyboard latch."""
        self._clear_latch()

    def _clear_latch(self):
        """Clear the keyboard latch and interrupt."""
        if self.latched:
            self.latched = False
            if self._irq_callback:
                self._irq_callback(0)  # Clear INT2
        if not self._key_down:
            self.dots = 0x00

    def press(self, dots: int):
        """Simulate key press (dots as bitmask)."""
        self.dots = dots & 0xFF
        self._key_down = bool(self.dots)
        if self.dots and not self.latched:
            self.latched = True
            if self._irq_callback:
                self._irq_callback(1)  # Assert INT2

    def release(self):
        """Latch the completed chord and signal the key-up edge."""
        if not self._key_down:
            return
        self._key_down = False
        if not self.latched:
            self.latched = True
            if self._irq_callback:
                self._irq_callback(1)  # Assert INT2


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

    def transmit(self, value: int) -> None:
        """Accept one source-defined Braille Lite display command or cell."""
        value &= 0xFF
        if self._cell_follows:
            self.buffer[self.cursor] = value
            self.cursor = (self.cursor + 1) % self.cells
            self._cell_follows = False
        elif value == 0x81:
            self._response = self.status
        elif value == 0x82:
            self.buffer[:] = b"\0" * self.cells
            self.cursor = 0
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
