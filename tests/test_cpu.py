"""Tests for native Z180 peripheral callbacks."""

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
