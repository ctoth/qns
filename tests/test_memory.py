"""Tests for BNS memory and nonvolatile state."""

import pytest

from qns.memory import Memory


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
