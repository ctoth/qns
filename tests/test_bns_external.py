"""Build authorities for external Blazie programs."""

import subprocess
from pathlib import Path
from shutil import copyfile

import pytest

from tools.bns_external import ExternalProgramInfo, inspect_external_program

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
