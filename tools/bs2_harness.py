"""Shared real-firmware harness for BS2 scenario tools and tests."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

from z180 import Reg

from qns.bns import BNS

BS2_IIB_PHYSICAL = 0x4327D


class SerialCapture(io.BytesIO):
    """Capture serial bytes with their emulated completion cycles."""

    def __init__(self, cycle_source: Callable[[], int]) -> None:
        super().__init__()
        self._cycle_source = cycle_source
        self.events: list[tuple[int, int]] = []

    def write(self, data: bytes) -> int:
        cycle = self._cycle_source()
        self.events.extend((cycle, byte) for byte in data)
        return super().write(data)

    def format_events(self, start: int = 0) -> str:
        """Format captured bytes from one event index onward."""
        return ",".join(f"{byte:02X}@{cycle}" for cycle, byte in self.events[start:])


class BS2Harness:
    """Own bounded timing and firmware-facing input/output mechanics."""

    def __init__(
        self,
        rom: Path,
        state: Path,
        *,
        cycle_limit: int,
        serial_channel: int | None = None,
        trace_writes: int | None = None,
    ) -> None:
        self.cycle_limit = cycle_limit
        self.serial = SerialCapture(lambda: self.bns.cpu.cycle_count())
        self.bns = BNS(
            model="bs2",
            trace_writes=trace_writes,
            stdin_device=None if serial_channel is None else f"serial{serial_channel}",
            serial_output=None if serial_channel is None else self.serial,
            serial_output_channel=serial_channel,
        )
        self.bns.load_rom(rom)
        self.bns.load_state(state)

    def advance(self, cycles: int = 1_000) -> None:
        """Advance the CPU and timed speech device together."""
        self.bns._execute_budget(cycles)
        current_cycle = self.bns.cpu.cycle_count()
        self.bns.ssi263.set_cycle_count(current_cycle)
        self.bns.ssi263.check_pending_irq(current_cycle)

    def run_until(
        self,
        predicate: Callable[[], bool],
        description: str,
        *,
        context: Callable[[], str] | None = None,
    ) -> None:
        """Advance until a predicate succeeds or the harness bound expires."""
        start_cycle = self.bns.cpu.cycle_count()
        while not predicate():
            if self.bns.cpu.cycle_count() - start_cycle >= self.cycle_limit:
                details = "" if context is None else f" {context()}"
                raise RuntimeError(
                    f"{description} not reached within {self.cycle_limit:,} cycles; "
                    f"cycle={self.bns.cpu.cycle_count()} "
                    f"pc={self.bns.cpu.reg(Reg.PC):04X}"
                    f"{details}"
                )
            self.advance()

    def chord(self, chord: int) -> None:
        """Deliver one raw chord through the firmware's two ISR phases."""
        self.bns.keyboard.press(chord)
        self.run_until(
            lambda: (
                not self.bns.keyboard.latched
                and self.bns.memory.read(BS2_IIB_PHYSICAL) == chord
            ),
            f"key-down firmware acceptance for {chord:02X}",
            context=lambda: (
                f"iib={self.bns.memory.read(BS2_IIB_PHYSICAL):02X}"
            ),
        )
        self.bns.keyboard.release()
        self.run_until(
            lambda: (
                not self.bns.keyboard.latched
                and self.bns.memory.read(BS2_IIB_PHYSICAL) == 0
            ),
            f"key-up firmware acceptance for {chord:02X}",
            context=lambda: (
                f"iib={self.bns.memory.read(BS2_IIB_PHYSICAL):02X}"
            ),
        )

    def wait_for_key(self) -> None:
        """Wait for a stable halted key loop after pending speech completes."""
        start_cycle = self.bns.cpu.cycle_count()
        while self.bns.cpu.cycle_count() - start_cycle < self.cycle_limit:
            self.advance()
            if self.bns.ssi263.irq_pending or not self.bns.cpu.halted():
                continue
            candidate_pc = self.bns.cpu.reg(Reg.PC)
            candidate_phonemes = len(self.bns.ssi263.phoneme_log)
            self.advance()
            if (
                not self.bns.ssi263.irq_pending
                and self.bns.cpu.halted()
                and self.bns.cpu.reg(Reg.PC) == candidate_pc
                and len(self.bns.ssi263.phoneme_log) == candidate_phonemes
            ):
                return
        pending_irq_text = "yes" if self.bns.ssi263.irq_pending else "none"
        raise RuntimeError(
            f"stable key wait not reached within {self.cycle_limit:,} cycles; "
            f"cycle={self.bns.cpu.cycle_count()} "
            f"pc={self.bns.cpu.reg(Reg.PC):04X} "
            f"halted={int(self.bns.cpu.halted())} "
            f"pending_speech_irq={pending_irq_text} "
            f"phonemes={len(self.bns.ssi263.phoneme_log)}"
        )

    def wait_for_speech(self) -> None:
        """Wait for speech to settle when the firmware key loop does not halt."""
        start_cycle = self.bns.cpu.cycle_count()
        while self.bns.cpu.cycle_count() - start_cycle < self.cycle_limit:
            self.advance()
            if self.bns.ssi263.irq_pending:
                continue
            candidate_phonemes = len(self.bns.ssi263.phoneme_log)
            self.advance(100_000)
            if (
                not self.bns.ssi263.irq_pending
                and len(self.bns.ssi263.phoneme_log) == candidate_phonemes
            ):
                return
        raise RuntimeError(f"speech did not settle within {self.cycle_limit:,} cycles")

    def select_serial(self, channel: int) -> None:
        """Route host input and captured output to one ASCI channel."""
        if channel not in (0, 1):
            raise ValueError(f"ASCI channel must be 0 or 1, got {channel}")
        self.bns.stdin_device = f"serial{channel}"
        self.bns.serial_output = self.serial
        self.bns.serial_output_channel = channel

    def queue_serial(self, data: bytes) -> None:
        """Make host bytes available to the selected ASCI receive callback."""
        for byte in data:
            self.bns._serial_input_queue.put(byte)

    def format_asci(self, channel: int) -> str:
        """Format one side-effect-free native ASCI snapshot."""
        if channel not in (0, 1):
            raise ValueError(f"ASCI channel must be 0 or 1, got {channel}")
        status = self.bns.cpu.io_reg_peek(0x04 + channel)
        cntla = self.bns.cpu.io_reg_peek(channel)
        tdr = self.bns.cpu.io_reg_peek(0x06 + channel)
        return (
            f"asci{channel}=stat:{status:02X},cntla:{cntla:02X},tdr:{tdr:02X}"
        )

    def wait_for_receive(
        self,
        channel: int,
        description: str,
        *,
        context: str = "",
    ) -> str:
        """Trace one host byte through callback, frame, IRQ, and ISR drain."""
        start_cycle = self.bns.cpu.cycle_count()
        trace_limit = 100_000
        events: list[str] = []
        callback_seen = frame_seen = False
        while self.bns.cpu.cycle_count() - start_cycle < trace_limit:
            status = self.bns.cpu.io_reg_peek(0x04 + channel)
            cycle = self.bns.cpu.cycle_count()
            pc = self.bns.cpu.reg(Reg.PC)
            if not callback_seen and self.bns._serial_input_queue.empty():
                callback_seen = True
                events.append(f"callback@{cycle}/pc={pc:04X}")
            if callback_seen and not frame_seen and status & 0x80:
                frame_seen = True
                events.append(f"frame@{cycle}/pc={pc:04X}")
            if frame_seen and not status & 0x80:
                events.append(f"drain@{cycle}/pc={pc:04X}")
                return f"{description}:" + ",".join(events)
            self.advance(1)
        raise RuntimeError(
            f"{description} did not cross the firmware receive path within "
            f"{trace_limit:,} cycles; events={','.join(events)} "
            f"{self.format_asci(channel)} pc={self.bns.cpu.reg(Reg.PC):04X} "
            f"context=[{context}]"
        )

    def wait_for_serial(
        self,
        channel: int,
        cursor: int,
        expected: bytes,
        description: str,
        *,
        context: str = "",
    ) -> int:
        """Wait for exact firmware output and return the new byte cursor."""
        start_cycle = self.bns.cpu.cycle_count()
        while self.bns.cpu.cycle_count() - start_cycle < self.cycle_limit:
            data = self.serial.getvalue()
            offset = data.find(expected, cursor)
            if offset >= 0:
                return offset + len(expected)
            cntla = self.bns.cpu.io_reg_peek(channel)
            tdr = self.bns.cpu.io_reg_peek(0x06 + channel)
            if (
                len(expected) == 1
                and tdr == expected[0]
                and not (cntla & 0x20)
            ):
                raise RuntimeError(
                    f"{description} is stuck in ASCI{channel} TDR with TE disabled; "
                    f"cycle={self.bns.cpu.cycle_count()} "
                    f"pc={self.bns.cpu.reg(Reg.PC):04X} "
                    f"{self.format_asci(channel)} context=[{context}]"
                )
            self.advance()
        tail = self.serial.getvalue()[cursor:]
        phonemes = self.bns.ssi263.get_phonemes(include_pauses=False)
        speech_tail = " ".join(phoneme.name for phoneme in phonemes[-80:])
        raise RuntimeError(
            f"{description} not received within {self.cycle_limit:,} cycles; "
            f"pc={self.bns.cpu.reg(Reg.PC):04X} "
            f"cbr={self.bns.cpu.io_reg_peek(0x38):02X} "
            f"bbr={self.bns.cpu.io_reg_peek(0x39):02X} "
            f"cbar={self.bns.cpu.io_reg_peek(0x3A):02X} "
            f"serial_tail={tail[-32:].hex(' ')} {self.format_asci(0)} "
            f"{self.format_asci(1)} context=[{context}] "
            f"speech_tail=[{speech_tail}]"
        )
