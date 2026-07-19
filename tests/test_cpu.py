"""Tests for native Z180 peripheral callbacks."""

from hypothesis import given, settings
from hypothesis import strategies as st

from qns.cpu import CFFI_AVAILABLE, Z180


def _cpu_with_program(program: bytes, **callbacks) -> tuple[Z180, bytearray]:
    memory = bytearray(1 << 20)
    memory[:len(program)] = program

    def write_memory(address: int, value: int) -> None:
        memory[address] = value

    cpu = Z180(
        mem_read=memory.__getitem__,
        mem_write=write_memory,
        **callbacks,
    )
    return cpu, memory


def test_asci_transmit_reaches_python_byte_callback():
    """A real channel-0 frame must cross the native bridge after completion."""
    assert CFFI_AVAILABLE
    transmitted: list[tuple[int, int]] = []
    program = bytes((
        0x3E, 0x64,        # LD A,64h: 8-N-1, transmit and receive enabled
        0xED, 0x39, 0x00,  # OUT0 (CNTLA0),A
        0x3E, 0x02,        # LD A,2: BSP's initial 9600-baud divisor
        0xED, 0x39, 0x02,  # OUT0 (CNTLB0),A
        0x3E, 0x41,        # LD A,'A'
        0xED, 0x39, 0x06,  # OUT0 (TDR0),A
        0x18, 0xFE,        # JR $
    ))

    def transmit(channel: int, value: int) -> None:
        transmitted.append((channel, value))

    cpu, _ = _cpu_with_program(program, serial_tx=transmit)

    cpu.run(50_000)

    assert transmitted == [(0, 0x41)]


def test_asci_receive_consumes_python_byte_callback():
    """A received byte must traverse the ASCI frame and firmware-visible RDR."""
    assert CFFI_AVAILABLE
    pending = [0x5A]
    program = bytes((
        0x3E, 0x64,        # LD A,64h: 8-N-1, transmit and receive enabled
        0xED, 0x39, 0x00,  # OUT0 (CNTLA0),A
        0x3E, 0x02,        # LD A,2: BSP's initial 9600-baud divisor
        0xED, 0x39, 0x02,  # OUT0 (CNTLB0),A
        0xED, 0x38, 0x04,  # IN0 A,(STAT0)
        0xE6, 0x80,        # AND RDRF
        0x28, 0xF9,        # JR Z back to the status read
        0xED, 0x38, 0x08,  # IN0 A,(RDR0)
        0x32, 0x00, 0x01,  # LD (0100h),A
        0x76,              # HALT
    ))

    def receive(_channel: int) -> int:
        return pending.pop() if pending else -1

    cpu, memory = _cpu_with_program(program, serial_rx=receive)

    cpu.run(50_000)
    cpu.run(1_000)

    assert memory[0x100] == 0x5A


@settings(max_examples=32, deadline=None)
@given(channel=st.sampled_from((0, 1)), value=st.integers(min_value=0, max_value=255))
def test_asci_receive_interrupt_survives_disabled_interrupts(channel: int, value: int):
    """ASCI data received under DI must dispatch its interrupt after EI."""
    assert CFFI_AVAILABLE
    pending = [value]
    loop_address = 29
    vector_address = 0x4E + 2 * channel
    cntla_port = channel
    cntlb_port = 0x02 + channel
    stat_port = 0x04 + channel
    rdr_port = 0x08 + channel
    program = bytearray(0x20D)
    program[:31] = bytes((
        0x31, 0x00, 0x10,       # LD SP,1000h
        0x3E, 0x00,             # LD A,0
        0xED, 0x47,             # LD I,A
        0xED, 0x5E,             # IM 2
        0x3E, 0x40,             # LD A,40h
        0xED, 0x39, 0x33,       # OUT0 (IL),A
        0x3E, 0x64,             # LD A,64h: 8-N-1, transmit and receive enabled
        0xED, 0x39, cntla_port, # OUT0 (CNTLA),A
        0x3E, 0x02,             # LD A,2: BSP's initial 9600-baud divisor
        0xED, 0x39, cntlb_port, # OUT0 (CNTLB),A
        0x3E, 0x08,             # LD A,RIE
        0xED, 0x39, stat_port,  # OUT0 (STAT),A
        0x18, 0xFE,             # JR $ while IFF1 is disabled
    ))
    program[vector_address:vector_address + 2] = bytes((0x00, 0x02))
    program[0x200:0x20D] = bytes((
        0xED, 0x38, rdr_port,   # IN0 A,(RDR)
        0x32, 0x00, 0x01,       # LD (0100h),A
        0x3E, 0xA5,             # LD A,A5h
        0x32, 0x01, 0x01,       # LD (0101h),A
        0xED, 0x4D,             # RETI
    ))

    def receive(requested_channel: int) -> int:
        if requested_channel != channel or not pending:
            return -1
        return pending.pop()

    cpu, memory = _cpu_with_program(program, serial_rx=receive)

    cpu.run(50_000)
    assert pending == []
    assert cpu.pc == loop_address
    assert memory[0x101] == 0

    memory[loop_address:loop_address + 4] = bytes((
        0xFB,       # EI
        0x00,       # EI shadow
        0x18, 0xFE, # JR $
    ))
    cpu.run(10_000)

    assert memory[0x101] == 0xA5
    assert memory[0x100] == value


def test_csio_exchange_crosses_native_callback_boundary():
    """CSI/O must deliver transmit data and return a received byte to firmware."""
    assert CFFI_AVAILABLE
    transmitted: list[int] = []
    pending = [0x0A]
    program = bytes((
        0x3E, 0x81,        # LD A,81h
        0xED, 0x39, 0x0B,  # OUT0 (TRDR),A
        0x3E, 0x10,        # LD A,TE
        0xED, 0x39, 0x0A,  # OUT0 (CNTR),A
        0xED, 0x38, 0x0A,  # IN0 A,(CNTR)
        0xE6, 0x10,        # AND TE
        0x20, 0xF9,        # JR NZ back to the control read
        0x3E, 0x20,        # LD A,RE
        0xED, 0x39, 0x0A,  # OUT0 (CNTR),A
        0xED, 0x38, 0x0A,  # IN0 A,(CNTR)
        0xE6, 0x20,        # AND RE
        0x20, 0xF9,        # JR NZ back to the control read
        0xED, 0x38, 0x0B,  # IN0 A,(TRDR)
        0x32, 0x00, 0x01,  # LD (0100h),A
        0x76,              # HALT
    ))

    def receive() -> int:
        return pending.pop() if pending else -1

    cpu, memory = _cpu_with_program(
        program,
        csio_rx=receive,
        csio_tx=transmitted.append,
    )

    cpu.run(1_000)

    assert transmitted == [0x81]
    assert memory[0x100] == 0x0A


def test_io_callbacks_observe_exact_accumulated_cycle_positions():
    """Timed peripherals must see each I/O instruction's starting cycle."""
    assert CFFI_AVAILABLE
    observed: list[int] = []
    cpu: Z180
    program = bytes((
        0x3E, 0x00,        # LD A,00h (6 cycles)
        0xED, 0x39, 0xA0,  # OUT0 (A0h),A (callback at cycle 6; 13 cycles)
        0x00,              # NOP (3 cycles)
        0x00,              # NOP (3 cycles)
        0x3E, 0x20,        # LD A,20h (6 cycles)
        0xED, 0x39, 0xA0,  # OUT0 (A0h),A (callback at cycle 31)
        0x76,              # HALT
    ))

    def write_io(_port: int, _value: int) -> None:
        observed.append(cpu.cycle_count)

    cpu, _ = _cpu_with_program(program, io_write=write_io)

    cpu.run(100)
    assert observed == [6, 31]
    assert cpu.cycle_count == 100

    cpu.run(25)
    assert cpu.cycle_count == 125

    cpu.reset()
    assert cpu.cycle_count == 0


def test_csio_receive_raises_internal_interrupt():
    """CSI/O completion must dispatch the IL+0Ch internal interrupt vector."""
    assert CFFI_AVAILABLE
    pending = [0x8A]
    program = bytearray(0x204)
    program[:23] = bytes((
        0x31, 0x00, 0x10,  # LD SP,1000h
        0x3E, 0x00,        # LD A,0
        0xED, 0x47,        # LD I,A
        0xED, 0x5E,        # IM 2
        0x3E, 0x40,        # LD A,40h
        0xED, 0x39, 0x33,  # OUT0 (IL),A
        0x3E, 0x67,        # LD A,EIE|RE|external clock
        0xED, 0x39, 0x0A,  # OUT0 (CNTR),A
        0xFB,              # EI
        0x00,              # EI shadow
        0x18, 0xFE,        # JR $
    ))
    program[0x4C:0x4E] = bytes((0x00, 0x02))
    program[0x200:0x208] = bytes((
        0xED, 0x38, 0x0B,  # IN0 A,(TRDR)
        0x32, 0x00, 0x01,  # LD (0100h),A
        0xED, 0x4D,        # RETI
    ))

    def receive() -> int:
        return pending.pop() if pending else -1

    cpu, memory = _cpu_with_program(program, csio_rx=receive)

    cpu.run(1_000)

    assert memory[0x100] == 0x8A


def test_slp_interrupt_wake_resumes_at_instruction_after_slp():
    """SLP wake must execute the following RET, not skip past it."""
    assert CFFI_AVAILABLE
    program = bytearray(0x3A)
    program[:18] = bytes((
        0x31, 0x00, 0x10,  # LD SP,1000h
        0xED, 0x56,        # IM 1
        0xCD, 0x0E, 0x00,  # CALL sleep_then_return
        0x3E, 0x42,        # LD A,42h
        0x32, 0x00, 0x01,  # LD (0100h),A
        0x76,              # HALT
        0xFB,              # sleep_then_return: EI
        0xED, 0x76,        # SLP
        0xC9,              # RET
    ))
    program[0x38:0x3A] = bytes((0xED, 0x4D))  # IM1 handler: RETI
    cpu, memory = _cpu_with_program(program)

    for _ in range(5):
        cpu.step()
    assert cpu.pc == 0x0011

    cpu.set_irq(Z180.IRQ0, Z180.ASSERT)
    cpu.step()
    cpu.set_irq(Z180.IRQ0, Z180.CLEAR)
    cpu.run(100)

    assert memory[0x100] == 0x42
