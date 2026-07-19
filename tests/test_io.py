"""Tests for BNS peripheral contracts."""

from datetime import datetime, timedelta

from qns.io import MSM6242RTC, BrailleKeyboard, PIC16C56Clock


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
