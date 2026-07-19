"""Tests for BNS peripheral contracts."""

from datetime import datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from qns.io import (
    MSM6242RTC,
    BQ2010GasGauge,
    BrailleDisplay,
    BrailleKeyboard,
    ParallelBrailleDisplay,
    PIC16C56Clock,
)


def _shift_parallel_display_byte(
    display: ParallelBrailleDisplay,
    value: int,
) -> None:
    for bit in range(8):
        display.write_control(1 if value & (1 << bit) else 0)
        display.write_control(2)
        display.write_control(3)


def test_braille_lite_display_returns_source_defined_status_values():
    """BSL commands expose idle keys, full battery, and no charging current."""
    display = BrailleDisplay()

    for command, expected in ((0x81, 0x0A), (0x85, 238), (0x86, 0xFF)):
        display.transmit(command)
        assert display.receive() == expected
        assert display.receive() == -1


@given(cells=st.binary(min_size=1, max_size=18))
def test_braille_lite_display_captures_command_prefixed_cells(cells: bytes):
    """Each 0x83 command makes exactly the following byte one display cell."""
    display = BrailleDisplay()
    display.transmit(0x82)

    for cell in cells:
        display.transmit(0x83)
        display.transmit(cell)

    assert display.buffer[:len(cells)] == cells
    assert display.cursor == len(cells) % display.cells


def test_braille_lite_display_emits_each_complete_frame():
    display = BrailleDisplay()
    frames: list[bytes] = []
    display.set_frame_callback(frames.append)
    cells = bytes(range(18))

    for cell in cells:
        display.transmit(0x83)
        display.transmit(cell)

    assert frames == [cells]


@given(cells=st.binary(min_size=40, max_size=40))
def test_parallel_40_cell_display_latches_source_order(cells: bytes):
    """BL4 shifts cells right-to-left and exposes them on the C2 strobe."""
    display = ParallelBrailleDisplay(cells=40)
    frames: list[bytes] = []
    display.set_frame_callback(frames.append)
    display.write_control(0xA2)

    for cell in reversed(cells):
        _shift_parallel_display_byte(display, cell)
    display.write_control(5)

    assert display.buffer == cells
    assert frames == [cells]


@given(cells=st.binary(min_size=18, max_size=18))
def test_parallel_18_cell_display_removes_source_spacers(cells: bytes):
    """BL2's 24-cell chain exposes its 18 data cells in logical order."""
    display = ParallelBrailleDisplay(cells=18)
    frames: list[bytes] = []
    display.set_frame_callback(frames.append)
    physical_frame: list[int] = []
    reversed_cells = bytes(reversed(cells))
    for offset in range(0, 18, 6):
        physical_frame.extend(reversed_cells[offset:offset + 6])
        physical_frame.extend((0, 0))

    for cell in physical_frame:
        _shift_parallel_display_byte(display, cell)
    display.write_control(5)

    assert display.buffer == cells
    assert frames == [cells]


def test_bq2010_decodes_bs2_pulses_and_returns_battery_registers():
    """BSNEW must exchange literal LSB-first return-to-one gauge frames."""
    gauge = BQ2010GasGauge()

    def read_register(command: int, start_cycle: int) -> tuple[int, int]:
        cycle = start_cycle
        gauge.write_line(False, cycle)
        cycle += 18_020
        gauge.write_line(True, cycle)
        cycle += 5_992

        for bit in range(8):
            gauge.write_line(False, cycle)
            cycle += 324 if command & (1 << bit) else 12_820
            gauge.write_line(True, cycle)
            cycle += 20_290 - (324 if command & (1 << bit) else 12_820)

        value = 0
        for bit in range(8):
            while gauge.read_line(cycle):
                cycle += 100
            if gauge.read_line(cycle + 4_500):
                value |= 1 << bit
            cycle += 12_000
        return value, cycle

    nac, cycle = read_register(0x03, 0)
    lmd, cycle = read_register(0x05, cycle + 20_000)
    flags, _ = read_register(0x01, cycle + 20_000)

    assert nac == 100
    assert lmd == 100
    assert flags == 0
    assert gauge.command_log == [0x03, 0x05, 0x01]


def test_bq2010_break_resynchronizes_after_partial_boot_frame():
    """A real break must discard incomplete latch activity left by boot."""
    gauge = BQ2010GasGauge()

    gauge.write_line(False, 0)
    gauge.write_line(True, 18_020)
    cycle = 24_012
    for _ in range(3):
        gauge.write_line(False, cycle)
        gauge.write_line(True, cycle + 324)
        cycle += 20_290

    cycle += 500_000
    gauge.write_line(False, cycle)
    gauge.write_line(True, cycle + 18_024)
    cycle += 24_017
    for bit in range(8):
        low_cycles = 315 if 0x03 & (1 << bit) else 12_820
        gauge.write_line(False, cycle)
        gauge.write_line(True, cycle + low_cycles)
        cycle += 20_290

    assert gauge.command_log == [0x03]

    value = 0
    for bit in range(8):
        while gauge.read_line(cycle):
            cycle += 100
        if gauge.read_line(cycle + 4_500):
            value |= 1 << bit
        cycle += 12_000
    assert value == 100


def test_msm6242_exposes_bsp_bcd_clock_registers():
    """The BSP clock window uses MSM6242 BCD fields and Sunday-zero weeks."""
    current = datetime(2026, 7, 18, 23, 45, 56)
    rtc = MSM6242RTC(now=lambda: current)

    assert [rtc.read(0x60 + register) for register in range(13)] == [
        6, 5, 5, 4, 3, 2, 8, 1, 7, 0, 6, 2, 6,
    ]
    assert rtc.read(0x6D) == 0
    assert rtc.read(0x6E) == 0
    assert rtc.read(0x6F) == 0x04


def test_pic16c56_clock_returns_field_bytes_after_command_strobe():
    """BSNEW's clock PIC must latch command 4 and return year last."""
    current = datetime(2020, 7, 18, 19, 45, 0)
    clock = PIC16C56Clock(now=lambda: current)

    clock.transmit(4)
    assert clock.receive() == -1

    clock.strobe()

    assert [clock.receive() for _ in range(6)] == [
        0x2D,  # minute low five bits
        0x05,  # add the sixth minute bit
        0x47,  # month
        0x72,  # day
        0xB3,  # hour
        0x9F,  # year 2020, the completion sentinel
    ]
    assert clock.receive() == -1


def test_pic16c56_clock_sets_and_returns_normal_datetime_fields():
    """Command 2 must select normal clock fields for writes and command 4."""
    clock = PIC16C56Clock(now=lambda: datetime(2020, 7, 18, 19, 45, 0))

    def send(value: int) -> None:
        clock.transmit(value)
        clock.strobe()

    send(2)
    send(0x2D)  # minute low five bits: 13
    send(0x05)  # add the sixth minute bit: 45
    send(0x4C)  # month: 12
    send(0x7F)  # day: 31
    send(0xA3)  # hour: 3
    send(0x9E)  # year: 2019 (30 years after 1989)
    send(4)

    assert [clock.receive() for _ in range(6)] == [
        0x2D,
        0x05,
        0x4C,
        0x7F,
        0xA3,
        0x9E,
    ]
    assert clock.receive() == -1


def test_pic16c56_clock_keeps_alarm_fields_separate_from_normal_time():
    """Commands 3 and 2 must select isolated alarm and normal value banks."""
    clock = PIC16C56Clock(now=lambda: datetime(2020, 7, 18, 19, 45, 0))

    def send(value: int) -> None:
        clock.transmit(value)
        clock.strobe()

    send(3)
    send(0x2F)  # minute: 15
    send(0x45)  # month: 5
    send(0x66)  # day: 6
    send(0xA7)  # hour: 7
    send(0x9D)  # year: 2018
    send(4)

    assert [clock.receive() for _ in range(5)] == [
        0x2F,
        0x45,
        0x66,
        0xA7,
        0x9D,
    ]

    send(2)
    send(4)
    assert [clock.receive() for _ in range(6)] == [
        0x2D,
        0x05,
        0x47,
        0x72,
        0xB3,
        0x9F,
    ]


def test_pic16c56_clock_reports_due_exact_alarm_once_per_minute():
    """A due exact alarm must produce the PIC's raw 0x0A notification once."""
    current = [datetime(2019, 12, 31, 3, 44, 0)]
    clock = PIC16C56Clock(now=lambda: current[0])

    def send(value: int) -> None:
        clock.transmit(value)
        clock.strobe()

    send(3)
    send(0x2D)  # minute low five bits: 13
    send(0x05)  # add the sixth minute bit: 45
    send(0x4C)  # month: 12
    send(0x7F)  # day: 31
    send(0xA3)  # hour: 3
    send(0x9E)  # year: 2019

    assert clock.receive() == -1

    current[0] = datetime(2019, 12, 31, 3, 45, 0)
    assert clock.receive() == 0x0A
    assert clock.receive() == -1


def test_pic16c56_clock_matches_hour_month_and_day_alarm_wildcards():
    """Firmware wildcard field values must match any hour, month, or day."""
    current = [datetime(2020, 7, 18, 19, 44, 0)]
    clock = PIC16C56Clock(now=lambda: current[0])

    def send(value: int) -> None:
        clock.transmit(value)
        clock.strobe()

    send(3)
    send(0x2D)  # minute low five bits: 13
    send(0x05)  # add the sixth minute bit: 45
    send(0x40)  # any month
    send(0x60)  # any day
    send(0xBF)  # any hour (DONTCARE == 0x1F)
    send(0x9F)  # year: 2020

    assert clock.receive() == -1

    current[0] = datetime(2020, 7, 18, 19, 45, 0)
    assert clock.receive() == 0x0A

    current[0] = datetime(2020, 8, 19, 8, 45, 0)
    assert clock.receive() == 0x0A


def test_pic16c56_clock_matches_raw_06_any_minute_alarm():
    """Raw command 0x06 must make alarm minutes a don't-care field."""
    current = [datetime(2020, 7, 18, 19, 44, 0)]
    clock = PIC16C56Clock(now=lambda: current[0])

    def send(value: int) -> None:
        clock.transmit(value)
        clock.strobe()

    send(3)
    send(0x3F)  # low five bits sent before the don't-care command
    send(0x06)  # any minute
    send(0x47)  # month: 7
    send(0x72)  # day: 18
    send(0xB3)  # hour: 19
    send(0x9F)  # year: 2020

    assert clock.receive() == 0x0A

    current[0] = datetime(2020, 7, 18, 19, 45, 0)
    assert clock.receive() == 0x0A


def test_msm6242_hold_allows_atomic_clock_setting_and_resume():
    """HOLD freezes the BCD bank until BSP releases its completed writes."""
    current = [datetime(2026, 7, 18, 23, 45, 56)]
    rtc = MSM6242RTC(now=lambda: current[0])

    rtc.write(0x6D, 1)
    current[0] += timedelta(seconds=10)
    assert rtc.read(0x60) == 6
    assert rtc.read(0x61) == 5

    for register, value in enumerate((3, 0, 2, 0, 1, 0)):
        rtc.write(0x60 + register, value)
    rtc.write(0x6D, 0)

    assert [rtc.read(0x60 + register) for register in range(6)] == [3, 0, 2, 0, 1, 0]
    current[0] += timedelta(seconds=2)
    assert rtc.read(0x60) == 5


def test_msm6242_accepts_bsp_12_and_24_hour_control_sequences():
    """Register F follows BSP's reset-gated mode changes and hour rewrites."""
    current = datetime(2026, 7, 18, 13, 5, 0)
    rtc = MSM6242RTC(now=lambda: current)

    rtc.write(0x6D, 1)
    rtc.write(0x6F, 1)
    rtc.write(0x6F, 0)
    rtc.write(0x6D, 0)
    assert not rtc.mode_24_hour
    assert rtc.read(0x65) == 1
    assert rtc.read(0x64) == 3

    rtc.write(0x65, 0x04)
    rtc.write(0x64, 0x01)
    assert rtc.read(0x65) == 0x04
    assert rtc.read(0x64) == 0x01

    rtc.write(0x6D, 1)
    rtc.write(0x6F, 1)
    rtc.write(0x6F, 5)
    rtc.write(0x6F, 4)
    rtc.write(0x65, 0x01)
    rtc.write(0x64, 0x03)
    rtc.write(0x6D, 0)
    assert rtc.mode_24_hour
    assert rtc.read(0x6F) == 0x04
    assert rtc.read(0x65) == 0x01
    assert rtc.read(0x64) == 0x03


def test_keyboard_keydown_stays_visible_after_interrupt_acknowledge():
    """KEYCLR acknowledges the edge but held dots remain readable."""
    keyboard = BrailleKeyboard()
    irq_states: list[int] = []
    keyboard.set_irq_callback(irq_states.append)

    keyboard.press(0x13)

    assert keyboard.read(keyboard.port) == 0x13
    assert irq_states == [1]

    keyboard.keyclr_read(keyboard.keyclr_port)

    assert keyboard.read(keyboard.port) == 0x13
    assert irq_states == [1, 0]


def test_keyboard_release_latches_chord_until_interrupt_acknowledge():
    """The key-up ISR reads the completed chord before KEYCLR releases it."""
    keyboard = BrailleKeyboard()
    irq_states: list[int] = []
    keyboard.set_irq_callback(irq_states.append)

    keyboard.press(0x13)
    keyboard.keyclr_read(keyboard.keyclr_port)
    keyboard.release()

    assert keyboard.read(keyboard.port) == 0x13
    assert irq_states == [1, 0, 1]

    keyboard.keyclr_read(keyboard.keyclr_port)

    assert keyboard.read(keyboard.port) == 0x00
    assert irq_states == [1, 0, 1, 0]
