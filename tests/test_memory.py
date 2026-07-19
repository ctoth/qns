"""Tests for BNS memory and nonvolatile state."""

import pytest

from qns.memory import Memory


def _program_flash_byte(memory: Memory, offset: int, value: int) -> None:
    page, page_offset = divmod(offset, 0x80000)
    memory.set_high_bank_latch(0x08 | page)
    memory.write(0x85555, 0xAA)
    memory.write(0x82AAA, 0x55)
    memory.write(0x85555, 0xA0)
    memory.write(0x80000 + page_offset, value)


def test_nonvolatile_state_preserves_shadow_ram_written_addresses(tmp_path):
    """Written zeroes must still override ROM after a state round trip."""
    state_path = tmp_path / "bsp.state"
    memory = Memory(ram_size=32, rom_size=16)
    memory.load_rom(bytes((0xAA,)) * 16)
    memory.write(0, 0)
    memory.write(20, 0x5A)

    memory.save_state(state_path)

    restored = Memory(ram_size=32, rom_size=16)
    restored.load_rom(bytes((0xAA,)) * 16)
    restored.load_state(state_path)

    assert restored.read(0) == 0
    assert restored.read(1) == 0xAA
    assert restored.read(20) == 0x5A
    assert not state_path.with_name(f".{state_path.name}.tmp").exists()


def test_shadow_ram_writes_are_silent(capsys):
    """Ordinary firmware memory traffic must not leak debugging to stdout."""
    memory = Memory()

    memory.write(0x4215C, 0xFF)

    assert capsys.readouterr().out == ""


def test_nonvolatile_state_rejects_wrong_ram_size(tmp_path):
    """A state image cannot be silently truncated or extended."""
    state_path = tmp_path / "bsp.state"
    Memory(ram_size=16).save_state(state_path)

    with pytest.raises(ValueError, match="state RAM size is 16 bytes"):
        Memory(ram_size=32).load_state(state_path)


def test_nonvolatile_state_rejects_unknown_format(tmp_path):
    """Raw RAM dumps are not accepted as versioned state files."""
    state_path = tmp_path / "bsp.state"
    state_path.write_bytes(b"not a state file")

    with pytest.raises(ValueError, match="not a QNS nonvolatile RAM state file"):
        Memory(ram_size=32).load_state(state_path)


def test_bsnew_high_bank_latch_selects_flash_pages():
    memory = Memory(flash_size=2 * 1024 * 1024)

    _program_flash_byte(memory, 0x1234, 0x5A)
    _program_flash_byte(memory, 0x80000 + 0x1234, 0xA5)

    memory.set_high_bank_latch(0x08)
    assert memory.read(0x81234) == 0x5A
    memory.set_high_bank_latch(0x09)
    assert memory.read(0x81234) == 0xA5
    memory.set_high_bank_latch(0)
    assert memory.read(0x81234) == 0xFF


def test_bsnew_flash_program_and_erase_sequences():
    memory = Memory(flash_size=2 * 1024 * 1024)
    _program_flash_byte(memory, 0x01234, 0x00)
    _program_flash_byte(memory, 0x11234, 0x00)

    memory.write(0x85555, 0xAA)
    memory.write(0x82AAA, 0x55)
    memory.write(0x85555, 0x80)
    memory.write(0x85555, 0xAA)
    memory.write(0x82AAA, 0x55)
    memory.write(0x95555, 0x30)

    assert memory.read(0x81234) == 0x00
    assert memory.read(0x91234) == 0xFF

    memory.write(0x85555, 0xAA)
    memory.write(0x82AAA, 0x55)
    memory.write(0x85555, 0x80)
    memory.write(0x85555, 0xAA)
    memory.write(0x82AAA, 0x55)
    memory.write(0x85555, 0x10)

    assert memory.read(0x81234) == 0xFF
    assert memory.read(0x85555) == 0xFF
    assert memory.read(0x82AAA) == 0xFF


def test_nonvolatile_state_preserves_bsnew_flash(tmp_path):
    state_path = tmp_path / "bs2.state"
    memory = Memory(flash_size=2 * 1024 * 1024)
    _program_flash_byte(memory, 0x101234, 0x5A)

    memory.save_state(state_path)

    restored = Memory(flash_size=2 * 1024 * 1024)
    restored.load_state(state_path)
    restored.set_high_bank_latch(0x0A)
    assert restored.read(0x81234) == 0x5A
