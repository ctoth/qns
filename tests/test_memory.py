"""Tests for BNS memory and nonvolatile state."""

import pytest

from qns.bns import BNS
from qns.memory import (
    _STATE_MAGIC_V1,
    _STATE_MAGIC_V2,
    _STATE_MAGIC_V3,
    Memory,
)


def _program_flash_byte(memory: Memory, offset: int, value: int) -> None:
    page, page_offset = divmod(offset, 0x80000)
    memory.set_high_bank_latch(0x08 | page)
    memory.write(0x85555, 0xAA)
    memory.write(0x82AAA, 0x55)
    memory.write(0x85555, 0xA0)
    memory.write(0x80000 + page_offset, value)


def _write_legacy_state(path, magic, ram, written, flash=b""):
    bitmap = bytearray((len(ram) + 7) // 8)
    for address in written:
        bitmap[address >> 3] |= 1 << (address & 7)
    header = magic + len(ram).to_bytes(4, "little")
    if magic == _STATE_MAGIC_V2:
        header += len(flash).to_bytes(4, "little")
    path.write_bytes(header + bytes(bitmap) + bytes(ram) + flash)


def test_v3_nonvolatile_state_preserves_effective_ram(tmp_path):
    """V3 stores the effective native RAM image without shadow metadata."""
    state_path = tmp_path / "bsp.state"
    memory = Memory(ram_size=32, rom_size=16)
    memory.load_rom(bytes((0xAA,)) * 16)
    memory.write(0, 0)
    memory.write(20, 0x5A)

    memory.save_state(state_path)
    data = state_path.read_bytes()
    assert data.startswith(_STATE_MAGIC_V3)
    assert len(data) == len(_STATE_MAGIC_V3) + 8 + 32

    restored = Memory(ram_size=32, rom_size=16)
    restored.load_rom(bytes((0xAA,)) * 16)
    restored.load_state(state_path)

    assert restored.read(0) == 0
    assert restored.read(1) == 0xAA
    assert restored.read(20) == 0x5A
    assert not state_path.with_name(f".{state_path.name}.tmp").exists()


@pytest.mark.parametrize("magic", [_STATE_MAGIC_V1, _STATE_MAGIC_V2])
def test_legacy_state_overlays_written_rom_and_all_ram_beyond_rom(tmp_path, magic):
    state_path = tmp_path / "legacy.state"
    legacy_ram = bytearray(32)
    legacy_ram[0] = 0x11
    legacy_ram[1] = 0x22
    legacy_ram[20] = 0x5A
    flash = bytes((0xA5,)) * 16 if magic == _STATE_MAGIC_V2 else b""
    _write_legacy_state(state_path, magic, legacy_ram, {0}, flash)

    restored = Memory(ram_size=32, rom_size=16, flash_size=len(flash))
    restored.load_rom(bytes((0xAA,)) * 16)
    restored.load_state(state_path)

    assert restored.read(0) == 0x11
    assert restored.read(1) == 0xAA
    assert restored.read(20) == 0x5A
    assert bytes(restored.flash) == flash


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


def test_nonvolatile_state_directory_preserves_effective_ram_and_flash(tmp_path):
    state_dir = tmp_path / "bs2-state"
    memory = Memory(ram_size=32, rom_size=16, flash_size=2 * 1024 * 1024)
    memory.load_rom(bytes((0xAA,)) * 16)
    memory.write(0, 0)
    memory.write(20, 0x5A)
    _program_flash_byte(memory, 0x101234, 0xA5)

    memory.save_state_dir(state_dir)

    assert state_dir.is_dir()
    assert {path.name for path in state_dir.iterdir()} == {
        "flash.bin",
        "ram.bin",
    }
    restored = Memory(ram_size=32, rom_size=16, flash_size=2 * 1024 * 1024)
    restored.load_rom(bytes((0xAA,)) * 16)
    restored.load_state_dir(state_dir)
    restored.set_high_bank_latch(0x0A)

    assert restored.read(0) == 0
    assert restored.read(1) == 0xAA
    assert restored.read(20) == 0x5A
    assert restored.read(0x81234) == 0xA5


def test_legacy_state_directory_converts_shadow_ram(tmp_path):
    state_dir = tmp_path / "legacy-state"
    state_dir.mkdir()
    legacy_ram = bytearray(32)
    legacy_ram[0] = 0x11
    legacy_ram[1] = 0x22
    legacy_ram[20] = 0x5A
    shadow = bytearray(4)
    shadow[0] = 0x01
    (state_dir / "ram.bin").write_bytes(legacy_ram)
    (state_dir / "shadow.bin").write_bytes(shadow)
    (state_dir / "flash.bin").write_bytes(b"")

    restored = Memory(ram_size=32, rom_size=16)
    restored.load_rom(bytes((0xAA,)) * 16)
    restored.load_state_dir(state_dir)

    assert restored.read(0) == 0x11
    assert restored.read(1) == 0xAA
    assert restored.read(20) == 0x5A


def test_new_directory_save_removes_stale_legacy_shadow_file(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "shadow.bin").write_bytes(b"legacy")

    Memory(ram_size=32).save_state_dir(state_dir)

    assert not (state_dir / "shadow.bin").exists()


def test_load_rom_rejects_images_beyond_ram_or_rom_contract():
    memory = Memory(ram_size=32, rom_size=16)

    with pytest.raises(ValueError, match="configured ROM size"):
        memory.load_rom(bytes(17))
    with pytest.raises(ValueError, match="configured RAM size"):
        memory.load_rom(bytes(16), offset=17)


@pytest.mark.parametrize("magic", [_STATE_MAGIC_V1, _STATE_MAGIC_V2])
def test_legacy_state_imports_into_direct_machine_ram(tmp_path, magic):
    """Legacy shadow state is converted into the live native RAM view."""
    bns = BNS(core="direct")
    bns.memory.load_rom(bytes((0xAA, 0xBB)))
    legacy_ram = bytearray(len(bns.memory.ram))
    legacy_ram[0] = 0x11
    legacy_ram[1] = 0x22
    legacy_ram[len(bns.memory.rom)] = 0x5A
    state_path = tmp_path / "legacy.state"
    _write_legacy_state(state_path, magic, legacy_ram, {0})

    bns.load_state(state_path)

    assert isinstance(bns.memory.ram, memoryview)
    assert bns.memory.ram[0] == 0x11
    assert bns.memory.ram[1] == 0xBB
    assert bns.memory.ram[len(bns.memory.rom)] == 0x5A


@pytest.mark.parametrize("model", ["bs2", "bl4"])
def test_v3_state_round_trip_preserves_direct_ram_and_flash(
    tmp_path,
    model,
):
    """V3 persists the native RAM view and each supported flash size."""
    state_path = tmp_path / f"{model}.state"
    bns = BNS(model=model, core="direct")
    bns.memory.load_rom(bytes((0xAA, 0xBB)))
    bns.memory.ram[0] = 0x11
    bns.memory.flash[-1] = 0x5A
    bns.save_state(state_path)

    restored = BNS(model=model, core="direct")
    restored.memory.load_rom(bytes((0xAA, 0xBB)))
    restored.load_state(state_path)

    assert isinstance(restored.memory.ram, memoryview)
    assert restored.memory.ram[0] == 0x11
    assert restored.memory.ram[1] == 0xBB
    assert restored.memory.flash[-1] == 0x5A
