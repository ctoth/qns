"""Shared real-firmware harness for BS2 scenario tools and tests."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

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
        self.serial = SerialCapture(lambda: self.bns.cpu.cycle_count)
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
        self.bns.cpu.run(cycles)
        current_cycle = self.bns.cpu.cycle_count
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
        start_cycle = self.bns.cpu.cycle_count
        while not predicate():
            if self.bns.cpu.cycle_count - start_cycle >= self.cycle_limit:
                details = "" if context is None else f" {context()}"
                raise RuntimeError(
                    f"{description} not reached within {self.cycle_limit:,} cycles; "
                    f"cycle={self.bns.cpu.cycle_count} pc={self.bns.cpu.pc:04X}"
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
        start_cycle = self.bns.cpu.cycle_count
        while self.bns.cpu.cycle_count - start_cycle < self.cycle_limit:
            self.advance()
            if self.bns.ssi263.irq_pending or not self.bns.cpu.halted:
                continue
            candidate_pc = self.bns.cpu.pc
            candidate_phonemes = len(self.bns.ssi263.phoneme_log)
            self.advance()
            if (
                not self.bns.ssi263.irq_pending
                and self.bns.cpu.halted
                and self.bns.cpu.pc == candidate_pc
                and len(self.bns.ssi263.phoneme_log) == candidate_phonemes
            ):
                return
        pending_irq_text = "yes" if self.bns.ssi263.irq_pending else "none"
        raise RuntimeError(
            f"stable key wait not reached within {self.cycle_limit:,} cycles; "
            f"cycle={self.bns.cpu.cycle_count} pc={self.bns.cpu.pc:04X} "
            f"halted={int(self.bns.cpu.halted)} "
            f"pending_speech_irq={pending_irq_text} "
            f"phonemes={len(self.bns.ssi263.phoneme_log)}"
        )

    def wait_for_speech(self) -> None:
        """Wait for speech to settle when the firmware key loop does not halt."""
        start_cycle = self.bns.cpu.cycle_count
        while self.bns.cpu.cycle_count - start_cycle < self.cycle_limit:
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
        state = self.bns.cpu.asci_debug_state(channel)
        return (
            f"asci{channel}=stat:{state['status']:02X},"
            f"bits:{state['rx_bits_remaining']},fifo:{state['rx_fifo_depth']},"
            f"irq:{int(state['irq_pending'])},cntla:{state['cntla']:02X},"
            f"txbits:{state['tx_bits_remaining']},"
            f"tsr:{state['tx_shift_register']:02X},"
            f"tdr:{state['tx_data_register']:02X},"
            f"div:{state['brg_divisor']},frame:{state['frame_bits']},"
            f"rie:+{state['rie_set_count']}/-{state['rie_clear_count']}@"
            f"{state['rie_last_pc']:04X}/{state['rie_last_cycle']},"
            f"statw:{state['stat_write_count']}:{state['stat_last_write']:02X}@"
            f"{state['stat_last_write_pc']:04X}/{state['stat_last_write_cycle']}"
        )

    def wait_for_receive(
        self,
        channel: int,
        description: str,
        *,
        context: str = "",
    ) -> str:
        """Trace one host byte through callback, frame, IRQ, and ISR drain."""
        start_cycle = self.bns.cpu.cycle_count
        configured = self.bns.cpu.asci_debug_state(channel)
        trace_limit = max(
            100_000,
            16 * int(configured["brg_divisor"]) * (int(configured["frame_bits"]) + 2),
        )
        events: list[str] = []
        callback_seen = shift_seen = frame_seen = irq_seen = False
        while self.bns.cpu.cycle_count - start_cycle < trace_limit:
            state = self.bns.cpu.asci_debug_state(channel)
            cycle = self.bns.cpu.cycle_count
            pc = self.bns.cpu.pc
            if not callback_seen and self.bns._serial_input_queue.empty():
                callback_seen = True
                events.append(f"callback@{cycle}/pc={pc:04X}")
            if callback_seen and not shift_seen and state["rx_bits_remaining"]:
                shift_seen = True
                events.append(f"shift@{cycle}/pc={pc:04X}/bits={state['rx_bits_remaining']}")
            if shift_seen and not frame_seen and (state["status"] & 0x80 or state["rx_fifo_depth"]):
                frame_seen = True
                events.append(f"frame@{cycle}/pc={pc:04X}/fifo={state['rx_fifo_depth']}")
            if frame_seen and not irq_seen and state["irq_pending"]:
                irq_seen = True
                events.append(f"irq@{cycle}/pc={pc:04X}")
            if frame_seen and not (state["status"] & 0x80) and not state["rx_fifo_depth"]:
                events.append(f"drain@{cycle}/pc={pc:04X}")
                return f"{description}:" + ",".join(events)
            self.advance(1)
        raise RuntimeError(
            f"{description} did not cross the firmware receive path within "
            f"{trace_limit:,} cycles; events={','.join(events)} "
            f"{self.format_asci(channel)} pc={self.bns.cpu.pc:04X} "
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
        start_cycle = self.bns.cpu.cycle_count
        while self.bns.cpu.cycle_count - start_cycle < self.cycle_limit:
            data = self.serial.getvalue()
            offset = data.find(expected, cursor)
            if offset >= 0:
                return offset + len(expected)
            state = self.bns.cpu.asci_debug_state(channel)
            if (
                len(expected) == 1
                and state["tx_data_register"] == expected[0]
                and state["tx_bits_remaining"] == 0
                and not (state["cntla"] & 0x20)
            ):
                raise RuntimeError(
                    f"{description} is stuck in ASCI{channel} TDR with TE disabled; "
                    f"cycle={self.bns.cpu.cycle_count} pc={self.bns.cpu.pc:04X} "
                    f"{self.format_asci(channel)} context=[{context}]"
                )
            self.advance()
        tail = self.serial.getvalue()[cursor:]
        phonemes = self.bns.ssi263.get_phonemes(include_pauses=False)
        speech_tail = " ".join(phoneme.name for phoneme in phonemes[-80:])
        raise RuntimeError(
            f"{description} not received within {self.cycle_limit:,} cycles; "
            f"pc={self.bns.cpu.pc:04X} cbr={self.bns.cpu.cbr:02X} "
            f"bbr={self.bns.cpu.bbr:02X} cbar={self.bns.cpu.cbar:02X} "
            f"serial_tail={tail[-32:].hex(' ')} {self.format_asci(0)} "
            f"{self.format_asci(1)} context=[{context}] "
            f"speech_tail=[{speech_tail}]"
        )
