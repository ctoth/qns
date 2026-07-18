"""Tests for BNS peripheral contracts."""

from datetime import datetime, timedelta

from qns.io import MSM6242RTC, BrailleKeyboard


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
