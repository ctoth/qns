"""Battery-backed BSNEW clock PIC connected through Z180 CSI/O."""

from collections import deque
from collections.abc import Callable
from datetime import datetime


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
