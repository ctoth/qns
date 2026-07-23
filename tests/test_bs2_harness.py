"""Authorities for the shared real-firmware BS2 harness."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from qns.bns import BNS
from tools.bs2_harness import BS2Harness, SerialCapture


@given(
    writes=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=10**9),
            st.binary(max_size=32),
        ),
        min_size=1,
        max_size=20,
    )
)
def test_serial_capture_preserves_bytes_and_completion_cycles(
    writes: list[tuple[int, bytes]],
):
    """Arbitrary serial writes must retain exact bytes and cycle attribution."""
    cycle = [0]
    capture = SerialCapture(lambda: cycle[0])
    expected_events: list[tuple[int, int]] = []

    for write_cycle, data in writes:
        cycle[0] = write_cycle
        assert capture.write(data) == len(data)
        expected_events.extend((write_cycle, byte) for byte in data)

    assert capture.getvalue() == b"".join(data for _cycle, data in writes)
    assert capture.events == expected_events
    assert capture.format_events() == ",".join(
        f"{byte:02X}@{write_cycle}" for write_cycle, byte in expected_events
    )


def test_wait_for_serial_reports_byte_stuck_in_disabled_transmitter(tmp_path):
    """An impossible pending byte must fail at its causal ASCI state."""
    rom = tmp_path / "stuck-enq.bin"
    rom.write_bytes(
        bytes(
            (
                0x3E,
                0x05,  # LD A,ENQ
                0xED,
                0x39,
                0x06,  # OUT0 (TDR0),A while reset CNTLA has TE clear
                0x18,
                0xFE,  # JR $
            )
        )
    )
    state = tmp_path / "bs2.state"
    BNS(model="bs2").save_state(state)
    harness = BS2Harness(
        rom,
        state,
        cycle_limit=10_000,
        serial_channel=0,
    )
    harness.advance(100)

    with pytest.raises(RuntimeError, match=r"ASCI0 TDR with TE disabled"):
        harness.wait_for_serial(0, 0, b"\x05", "disk ENQ")


def test_run_until_reports_lazy_failure_context(tmp_path):
    """A bounded wait must report causal state captured at timeout."""
    rom = tmp_path / "loop.bin"
    rom.write_bytes(bytes((0x18, 0xFE)))  # JR $
    state = tmp_path / "bs2.state"
    BNS(model="bs2").save_state(state)
    harness = BS2Harness(rom, state, cycle_limit=2_000)
    context_calls = 0

    def timeout_context() -> str:
        nonlocal context_calls
        context_calls += 1
        return f"marker={harness.bns.cpu.pc:04X}"

    with pytest.raises(RuntimeError, match=r"loop wait.*marker=0000"):
        harness.run_until(lambda: False, "loop wait", context=timeout_context)

    assert context_calls == 1

    with pytest.raises(
        RuntimeError,
        match=(
            r"cycle=4000 pc=0000 halted=0 "
            r"pending_speech_irq=none phonemes=0"
        ),
    ):
        harness.wait_for_key()
