"""Build authorities for external Blazie programs."""

import subprocess
from pathlib import Path
from shutil import copyfile

REPO_ROOT = Path(__file__).resolve().parents[1]
Z88DK_ASSEMBLER = REPO_ROOT / ".toolchain" / "z88dk-2.4" / "bin" / "z88dk-z80asm.exe"


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
