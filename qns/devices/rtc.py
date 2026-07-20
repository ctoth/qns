"""OKI MSM6242-compatible direct-bus real-time clock/calendar."""

from collections.abc import Callable
from datetime import datetime, timedelta


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
