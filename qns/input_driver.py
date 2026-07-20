"""Stdin chord input driver for the BNS keyboard.

Converts host characters to firmware chords or TNS keyboard-PIC scans
and drives them through the emulated keyboard's press/release handshake,
observing firmware acceptance through the profile's chord input buffer
and command-loop timer.
"""

from __future__ import annotations

import queue
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bns import BNS

# Raw English BNS keyboard chords from BSTABLES.ASM's regular English TABLE.
# A terminal newline represents the BNS carriage-return chord, and a terminal
# space represents the physical space-bar chord before firmware translation.
ASCII_TO_BNS_KEY = bytes((
    0x88, 0x81, 0x83, 0x89, 0x99, 0x91, 0x8B, 0x9B,
    0x93, 0x8A, 0x8D, 0x85, 0x87, 0x8D, 0x9D, 0x95,
    0x8F, 0x9F, 0x97, 0x8E, 0x9E, 0xA5, 0xA7, 0xBA,
    0xAD, 0xBD, 0xB5, 0xAA, 0xB3, 0xBB, 0x98, 0xB8,
    0x40, 0x2E, 0x10, 0x3C, 0x2B, 0x29, 0x2F, 0x04,
    0x37, 0x3E, 0x21, 0x2C, 0x20, 0x24, 0x28, 0x0C,
    0x34, 0x02, 0x06, 0x12, 0x32, 0x22, 0x16, 0x36,
    0x26, 0x14, 0x31, 0x30, 0x23, 0x3F, 0x1C, 0x39,
    0x48, 0x41, 0x43, 0x49, 0x59, 0x51, 0x4B, 0x5B,
    0x53, 0x4A, 0x5A, 0x45, 0x47, 0x4D, 0x5D, 0x55,
    0x4F, 0x5F, 0x57, 0x4E, 0x5E, 0x65, 0x67, 0x7A,
    0x6D, 0x7D, 0x75, 0x6A, 0x73, 0x7B, 0x58, 0x38,
    0x08, 0x01, 0x03, 0x09, 0x19, 0x11, 0x0B, 0x1B,
    0x13, 0x0A, 0x1A, 0x05, 0x07, 0x0D, 0x1D, 0x15,
    0x0F, 0x1F, 0x17, 0x0E, 0x1E, 0x25, 0x27, 0x3A,
    0x2D, 0x3D, 0x35, 0x2A, 0x33, 0x3B, 0x18, 0x78,
))

ASCII_TO_TNS_SCAN = {
    "q": 0x90, "w": 0x98, "e": 0xB0, "r": 0xB8, "t": 0xB5,
    "y": 0xBD, "u": 0xC5, "i": 0xCD, "o": 0xD5, "p": 0xDD,
    "a": 0x94, "s": 0xAC, "d": 0xB4, "f": 0xBC, "g": 0xC0,
    "h": 0xC8, "j": 0xC4, "k": 0xCC, "l": 0xD4,
    "z": 0x92, "x": 0xAA, "c": 0xB2, "v": 0xAB, "b": 0xB3,
    "n": 0xBB, "m": 0xC3,
    "1": 0x8B, "2": 0x8D, "3": 0x95, "4": 0xAD, "5": 0x97,
    "6": 0xAF, "7": 0xB7, "8": 0xBF, "9": 0xC7, "0": 0xCF,
    "-": 0xD7, "=": 0xDF, "[": 0xD0, "]": 0xD8,
    ";": 0xDC, "'": 0xD3, ",": 0xCB, ".": 0xC2,
    "/": 0xCA, "\\": 0xE0, "`": 0xB9,
    "\t": 0x91, "\b": 0xED, "\x7f": 0xED,
    " ": 0xA9, "\n": 0xDB, "\r": 0xDB,
}

SHIFTED_ASCII_TO_TNS_SCAN = {
    "!": 0x8B, "@": 0x8D, "#": 0x95, "$": 0xAD, "%": 0x97,
    "^": 0xAF, "&": 0xB7, "*": 0xBF, "(": 0xC7, ")": 0xCF,
    "_": 0xD7, "+": 0xDF, "{": 0xD0, "}": 0xD8,
    ":": 0xDC, '"': 0xD3, "<": 0xCB, ">": 0xC2,
    "?": 0xCA, "|": 0xE0, "~": 0xB9,
}

TNS_LEFT_SHIFT_SCAN = 0xE1
TNS_ALT_SCAN = 0xA1

BS2_POWER_ON_INITIALIZE_CHORD = 0x4A


def keyboard_input_chord(value: str | int, model: str = "bsp") -> int:
    """Convert one terminal character or raw JSONL chord to firmware dots."""
    if isinstance(value, int):
        return value
    if model == "tns":
        return tns_input_scan(value)[0]
    codepoint = ord(value)
    if codepoint >= len(ASCII_TO_BNS_KEY):
        raise ValueError(f"unsupported input character: U+{codepoint:04X}")
    return ASCII_TO_BNS_KEY[codepoint]


def tns_input_scan(value: str) -> tuple[int, bool]:
    """Return the TNS keyboard-PIC scan and physical shift state."""
    scan = ASCII_TO_TNS_SCAN.get(value)
    if scan is not None:
        return scan, False
    if len(value) == 1:
        scan = ASCII_TO_TNS_SCAN.get(value.lower())
        if scan is not None and value != value.lower():
            return scan, True
    scan = SHIFTED_ASCII_TO_TNS_SCAN.get(value)
    if scan is not None:
        return scan, True
    raise ValueError(f"unsupported TNS input character: {value!r}")


class ChordInputDriver:
    """Drive queued host input through the keyboard press/release handshake.

    The firmware acknowledges a BNS chord by copying it into the
    profile's chord input buffer and clearing that buffer once consumed;
    TNS scans are acknowledged by the keyboard-PIC latch alone.  One
    ``tick`` runs after each CPU chunk: it advances any in-flight chord,
    then starts the next queued one when the firmware is ready.
    """

    def __init__(self, bns: BNS) -> None:
        self._bns = bns
        self._tns = bns.profile.family == "tns"
        self.queue: queue.Queue[str | int] = queue.Queue()
        self._phase: str | None = None
        self._chord: int | None = None
        self._shifted = False
        self._alt = False
        self._ready_reported = False
        self._power_on_combyt_writes = bns._combyt_writes
        self._power_on_bl4_key_samples = bns._bl4_key_samples
        self._command_loop_writes = bns._command_loop_write_count

    def hold_power_on_chord(self, value: str | int) -> None:
        """Convert the first chord and hold it down through power-on."""
        bns = self._bns
        try:
            chord = keyboard_input_chord(value, bns.model)
        except ValueError as error:
            raise RuntimeError(str(error)) from error
        if bns.model == "bs2" and chord != BS2_POWER_ON_INITIALIZE_CHORD:
            raise RuntimeError("power-on input must begin with uppercase I")
        self._chord = chord
        bns.keyboard.press(chord)
        self._phase = "power-on"

    def tick(self, stable_key_wait: bool) -> None:
        """Advance the in-flight chord, then start the next queued one."""
        self._advance_phase()
        if self._phase is None:
            self._start_next_chord(stable_key_wait)

    def _advance_phase(self) -> None:
        bns = self._bns
        keyboard = bns.keyboard

        if self._phase == "power-on":
            # Each model proves power-on acceptance through a different
            # observable: BS2 by its COMBYT write, BL2 by the cleared
            # keyboard latch, BL4 by its space-bar port being sampled.
            if (
                (
                    bns.model == "bs2"
                    and bns._combyt_writes > self._power_on_combyt_writes
                )
                or (bns.model == "bl2" and not keyboard.latched)
                or (
                    bns.model == "bl4"
                    and bns._bl4_key_samples > self._power_on_bl4_key_samples
                )
            ):
                keyboard.release()
                self._accept()
            return

        if self._phase is None or keyboard.latched:
            return

        if self._phase == "tns-shift-down" and self._chord is not None:
            if self._alt:
                keyboard.press(TNS_ALT_SCAN)
                self._phase = "tns-alt-down"
            else:
                keyboard.press(self._chord)
                self._phase = "down"
        elif self._phase == "tns-alt-down" and self._chord is not None:
            keyboard.press(self._chord)
            self._phase = "down"
        elif (
            self._phase == "down"
            and self._chord is not None
            and (self._tns or self._input_buffer() == self._chord)
        ):
            keyboard.release()
            self._phase = "up"
        elif self._phase == "up" and (self._tns or self._input_buffer() == 0):
            if self._tns and self._alt:
                keyboard.release(TNS_ALT_SCAN)
                self._phase = "tns-alt-up"
            elif self._tns and self._shifted:
                keyboard.release(TNS_LEFT_SHIFT_SCAN)
                self._phase = "tns-shift-up"
            else:
                self._accept()
        elif self._phase == "tns-alt-up":
            if self._shifted:
                keyboard.release(TNS_LEFT_SHIFT_SCAN)
                self._phase = "tns-shift-up"
            else:
                self._accept()
        elif self._phase == "tns-shift-up":
            self._accept()

    def _start_next_chord(self, stable_key_wait: bool) -> None:
        bns = self._bns
        if not (
            stable_key_wait
            or bns._command_loop_write_count > self._command_loop_writes
        ):
            return

        try:
            character = self.queue.get_nowait()
        except queue.Empty:
            if bns.stdio_output is not None and not self._ready_reported:
                bns.stdio_output.emit("keyboard", state="ready")
                self._ready_reported = True
            return

        try:
            if self._tns and isinstance(character, str):
                self._chord, self._shifted = tns_input_scan(character)
                self._alt = character in ("`", "~")
            else:
                self._chord = keyboard_input_chord(character, bns.model)
                self._shifted = False
                self._alt = False
        except ValueError as error:
            print(f"[Input] {error}")
            return

        if self._tns and self._shifted:
            bns.keyboard.press(TNS_LEFT_SHIFT_SCAN)
            self._phase = "tns-shift-down"
        elif self._tns and self._alt:
            bns.keyboard.press(TNS_ALT_SCAN)
            self._phase = "tns-alt-down"
        else:
            bns.keyboard.press(self._chord)
            self._phase = "down"
        self._ready_reported = False
        self._command_loop_writes = bns._command_loop_write_count

    def _accept(self) -> None:
        """Report the completed chord and return to the idle phase."""
        chord = self._chord
        self._phase = None
        self._chord = None
        self._shifted = False
        self._alt = False
        if self._bns.stdio_output is not None:
            self._bns.stdio_output.emit(
                "keyboard",
                state="accepted",
                chord=chord,
            )

    def _input_buffer(self) -> int:
        """Read the firmware's chord input buffer for acceptance checks."""
        boundary = self._bns._input_boundary
        assert boundary is not None  # non-TNS drivers require discovery
        return self._bns.memory.read(boundary.keyboard_input_buffer)
