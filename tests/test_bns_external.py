"""Build authorities for external Blazie programs."""

import subprocess
from pathlib import Path
from shutil import copyfile

import pytest

from tools.bns_external import (
    ExternalProgramInfo,
    inspect_external_program,
    pack_external_program,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
Z88DK_ASSEMBLER = REPO_ROOT / ".toolchain" / "z88dk-2.4" / "bin" / "z88dk-z80asm.exe"
BS2_FIXTURE_ROOT = REPO_ROOT / "roms" / "NFB99" / "BS2ENG"


def minimal_external_program() -> bytearray:
    """Return a structurally valid one-byte external program."""
    return bytearray(
        b"\x18\x0cBNS\0"
        b"\x01\x00"
        b"\x01\x00"
        b"\x00\x00"
        b"\x00\x10"
        b"\x00"
        b"\xaa"
    )


def build_pack_fixture(build_root: Path) -> tuple[bytes, str]:
    """Assemble the symbol-bearing raw image in a fresh directory."""
    assert Z88DK_ASSEMBLER.is_file(), "run toolchain/setup-z88dk.ps1 first"
    build_root.mkdir()
    source = REPO_ROOT / "tests" / "fixtures" / "bns_pack_image.asm"
    temporary_source = build_root / source.name
    copyfile(source, temporary_source)
    output = build_root / "bns_pack_image.bin"
    subprocess.run(
        [
            Z88DK_ASSEMBLER,
            "-mz180",
            "-b",
            "-m",
            f"-o={output}",
            temporary_source,
        ],
        check=True,
        cwd=build_root,
        capture_output=True,
        text=True,
    )
    return output.read_bytes(), output.with_suffix(".map").read_text()


def test_pinned_assembler_emits_z180_mlt(tmp_path: Path) -> None:
    """The selected backend must assemble a real Z180-only instruction."""
    assert Z88DK_ASSEMBLER.is_file(), "run toolchain/setup-z88dk.ps1 first"
    source = REPO_ROOT / "tests" / "fixtures" / "z180_mlt.asm"
    temporary_source = tmp_path / source.name
    copyfile(source, temporary_source)
    output = tmp_path / "z180_mlt.bin"

    subprocess.run(
        [
            Z88DK_ASSEMBLER,
            "-mz180",
            "-b",
            f"-o={output}",
            temporary_source,
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert output.read_bytes() == bytes((0xED, 0x4C))


def test_inspect_accepts_minimal_external_program() -> None:
    assert inspect_external_program(minimal_external_program()) == ExternalProgramInfo(
        file_size=16,
        code_size=1,
        program_length=1,
        crc=0,
        stack=0x1000,
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "bsname.bns",
            ExternalProgramInfo(
                file_size=25_108,
                code_size=0x1AEF,
                program_length=0x6205,
                crc=0x6E8A,
                stack=0x7213,
            ),
        ),
        (
            "calsort.bns",
            ExternalProgramInfo(
                file_size=17_092,
                code_size=0x2EDE,
                program_length=0x42B5,
                crc=0x0F57,
                stack=0x52C3,
            ),
        ),
    ],
)
def test_inspect_matches_supplied_programs(name: str, expected: ExternalProgramInfo) -> None:
    path = BS2_FIXTURE_ROOT / name
    if not path.is_file():
        pytest.skip(f"local research fixture is unavailable: {path}")
    assert inspect_external_program(path.read_bytes()) == expected


def test_inspect_rejects_covered_code_corruption() -> None:
    program = minimal_external_program()
    program[0x0E] ^= 0x01
    with pytest.raises(ValueError, match="code CRC"):
        inspect_external_program(program)


def test_inspect_rejects_code_past_program_bounds() -> None:
    program = minimal_external_program()
    program[6:8] = (2).to_bytes(2, "little")
    with pytest.raises(ValueError, match="code_size 2 exceeds program_length 1"):
        inspect_external_program(program)


def test_inspect_rejects_program_length_size_mismatch() -> None:
    program = minimal_external_program()
    program[8:10] = (2).to_bytes(2, "little")
    with pytest.raises(ValueError, match=r"does not equal program_length \+ 15"):
        inspect_external_program(program)


def test_inspect_rejects_wrong_end_marker() -> None:
    program = minimal_external_program()
    program[-1] = 0
    with pytest.raises(ValueError, match="not the 0xaa end marker"):
        inspect_external_program(program)


def test_inspect_rejects_stack_below_application_space() -> None:
    program = minimal_external_program()
    program[12:14] = (0x0FFF).to_bytes(2, "little")
    with pytest.raises(ValueError, match="below logical address 0x1000"):
        inspect_external_program(program)


def test_inspect_rejects_nonportable_identifier() -> None:
    program = minimal_external_program()
    program[2:6] = b"TNS\0"
    with pytest.raises(ValueError, match="identifier is not BNS"):
        inspect_external_program(program)


def test_inspect_rejects_wrong_entry_jump() -> None:
    program = minimal_external_program()
    program[1] = 0
    with pytest.raises(ValueError, match="entry instruction"):
        inspect_external_program(program)


def test_inspect_rejects_firmware_update_package() -> None:
    path = BS2_FIXTURE_ROOT / "bs2eng.bns"
    if not path.is_file():
        pytest.skip(f"local research fixture is unavailable: {path}")
    with pytest.raises(ValueError):
        inspect_external_program(path.read_bytes())


def test_pack_derives_header_from_real_link_symbols(tmp_path: Path) -> None:
    raw_image, map_text = build_pack_fixture(tmp_path / "build")
    program = pack_external_program(raw_image, map_text)

    assert program[6:14] == bytes(
        (
            0x01,
            0x00,
            0x05,
            0x00,
            0x00,
            0x00,
            0x13,
            0x10,
        )
    )
    assert inspect_external_program(program) == ExternalProgramInfo(
        file_size=20,
        code_size=1,
        program_length=5,
        crc=0,
        stack=0x1013,
    )


def test_two_clean_builds_are_byte_identical(tmp_path: Path) -> None:
    first_raw, first_map = build_pack_fixture(tmp_path / "first")
    second_raw, second_map = build_pack_fixture(tmp_path / "second")

    assert pack_external_program(first_raw, first_map) == pack_external_program(
        second_raw,
        second_map,
    )


@pytest.mark.parametrize(
    "missing_symbol",
    [
        "__bns_entry",
        "__bns_code_end",
        "__bns_end_marker",
        "__bns_stack_top",
    ],
)
def test_pack_rejects_missing_link_symbol(tmp_path: Path, missing_symbol: str) -> None:
    raw_image, map_text = build_pack_fixture(tmp_path / "build")
    altered_map = "\n".join(
        line for line in map_text.splitlines() if not line.startswith(missing_symbol)
    )
    with pytest.raises(ValueError, match=missing_symbol):
        pack_external_program(raw_image, altered_map)


def test_pack_rejects_entry_at_wrong_logical_address(tmp_path: Path) -> None:
    raw_image, map_text = build_pack_fixture(tmp_path / "build")
    altered_map = "\n".join(
        "__bns_entry = $100f ; altered"
        if line.startswith("__bns_entry")
        else line
        for line in map_text.splitlines()
    )
    with pytest.raises(ValueError, match="__bns_entry is 0x100f, not 0x100e"):
        pack_external_program(raw_image, altered_map)


def test_pack_rejects_marker_symbol_not_at_final_byte(tmp_path: Path) -> None:
    raw_image, map_text = build_pack_fixture(tmp_path / "build")
    altered_map = "\n".join(
        "__bns_end_marker = $1012 ; altered"
        if line.startswith("__bns_end_marker")
        else line
        for line in map_text.splitlines()
    )
    with pytest.raises(ValueError, match="not final offset"):
        pack_external_program(raw_image, altered_map)


def test_pack_rejects_marker_symbol_not_naming_aa(tmp_path: Path) -> None:
    raw_image, map_text = build_pack_fixture(tmp_path / "build")
    altered_image = bytearray(raw_image)
    altered_image[-1] = 0
    with pytest.raises(ValueError, match="does not identify a 0xaa byte"):
        pack_external_program(altered_image, map_text)
