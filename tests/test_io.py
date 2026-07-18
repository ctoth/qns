"""Tests for BNS peripheral contracts."""

from qns.io import BrailleKeyboard


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
