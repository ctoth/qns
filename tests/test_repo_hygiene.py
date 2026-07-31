"""Regression guards for repository-local binary and generated artifacts."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TRACKED_SUFFIXES = {".bin", ".exe", ".ima", ".zip"}
MAX_TRACKED_FILE_SIZE = 512 * 1024
LARGE_FILE_ALLOWLIST: set[Path] = set()
REPRESENTATIVE_LOCAL_ARTIFACTS = {
    Path("aicom/disk.ima"),
    Path("audio-captures/capture.wav"),
    Path("bns.bat"),
    Path("datasheet.pdf"),
    Path("datasheet_pages/page.png"),
    Path("flash.bin"),
    Path("phoneme_dumps/capture.bin"),
    Path("phoneme_test/capture.wav"),
    Path("pyghidra_mcp_projects/project.gpr"),
    Path("ram_dump.bin"),
    Path("reports/brlterm.zip"),
    Path("reports/vendor.exe"),
    Path("sc01a.bin"),
    Path("test.txt"),
}
HISTORICAL_LEGACY_RECORD = Path("notes-software-bns.md")
HISTORICAL_LEGACY_BOUNDARY = "<!-- issue-27-historical-legacy-boundary -->"
HISTORICAL_LEGACY_PREFIX_SHA256 = "d61c6c95910bd95bf1170364e9a16f950e5ddf901f99119d577ad6936f512001"
RETIRED_CURRENT_POINTERS = {
    "build_ffi",
    "cffi_available",
    "qns.cpu",
    "qns/cpu",
    r"qns\cpu",
    "interrupt-tracing-tool-report",
    "interrupt-tracing-tool.md",
    "z180emu",
    "_z180_cffi",
}


def _git_paths(*args: str) -> set[Path]:
    output = subprocess.check_output(["git", *args, "-z"], cwd=REPO_ROOT)
    return {Path(os.fsdecode(path)) for path in output.split(b"\0") if path}


def _assert_no_retired_pointers(documents: dict[Path, str]) -> None:
    violations = {
        path: sorted(pointer for pointer in RETIRED_CURRENT_POINTERS if pointer in text.casefold())
        for path, text in documents.items()
        if any(pointer in text.casefold() for pointer in RETIRED_CURRENT_POINTERS)
    }
    assert not violations


def _assert_historical_record_is_sealed(text: str) -> None:
    assert text.count(HISTORICAL_LEGACY_BOUNDARY) == 1
    prefix, appended = text.split(HISTORICAL_LEGACY_BOUNDARY)
    assert hashlib.sha256(prefix.encode()).hexdigest() == HISTORICAL_LEGACY_PREFIX_SHA256
    _assert_no_retired_pointers({HISTORICAL_LEGACY_RECORD: appended})


def test_binary_or_ignored_artifacts_are_not_tracked() -> None:
    tracked = _git_paths("ls-files")
    ignored_and_tracked = _git_paths(
        "ls-files",
        "--cached",
        "--ignored",
        "--exclude-standard",
    )
    forbidden_binaries = {
        path for path in tracked if path.suffix.casefold() in FORBIDDEN_TRACKED_SUFFIXES
    }

    assert not ignored_and_tracked, f"ignored files are tracked: {sorted(ignored_and_tracked)}"
    assert not forbidden_binaries, f"binary artifacts are tracked: {sorted(forbidden_binaries)}"


def test_local_binary_corpus_stays_ignored() -> None:
    candidates = b"\0".join(os.fsencode(path.as_posix()) for path in REPRESENTATIVE_LOCAL_ARTIFACTS)
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=REPO_ROOT,
        input=candidates + b"\0",
        stdout=subprocess.PIPE,
        check=False,
    )
    ignored = {Path(os.fsdecode(path)) for path in result.stdout.split(b"\0") if path}

    assert ignored == REPRESENTATIVE_LOCAL_ARTIFACTS


def test_tracked_files_stay_below_the_repository_size_limit() -> None:
    oversized = {
        path: (REPO_ROOT / path).stat().st_size
        for path in _git_paths("ls-files")
        if path not in LARGE_FILE_ALLOWLIST
        and (REPO_ROOT / path).is_file()
        and (REPO_ROOT / path).stat().st_size > MAX_TRACKED_FILE_SIZE
    }

    assert not oversized, f"tracked files exceed {MAX_TRACKED_FILE_SIZE} bytes: {oversized}"


def test_retired_cffi_benchmark_surfaces_are_deleted() -> None:
    retired = {
        Path("qns/cpu.py"),
        Path("tests/test_cpu.py"),
        Path("tools/build_ffi.py"),
    }

    assert not {path for path in retired if (REPO_ROOT / path).exists()}

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lockfile = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    project_guide = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "cffi" not in pyproject.casefold()
    assert "setuptools" not in pyproject.casefold()
    assert 'name = "setuptools"' not in lockfile
    assert "build_ffi.py" not in project_guide
    assert "_z180_cffi" not in project_guide
    assert "legacy CFFI benchmark" not in project_guide


def test_retired_cpu_core_cannot_return_as_current_guidance() -> None:
    tracked = _git_paths("ls-files")
    current_text: dict[Path, str] = {}
    excluded = {HISTORICAL_LEGACY_RECORD, Path(__file__).relative_to(REPO_ROOT)}
    for path in tracked - excluded:
        source = REPO_ROOT / path
        if not source.is_file():
            continue
        try:
            current_text[path] = source.read_text(encoding="utf-8").casefold()
        except UnicodeDecodeError:
            continue

    _assert_no_retired_pointers(current_text)

    historical = (REPO_ROOT / HISTORICAL_LEGACY_RECORD).read_text(encoding="utf-8")
    assert "historical execution record" in historical.casefold()
    assert "not operational guidance" in historical.casefold()
    _assert_historical_record_is_sealed(historical)


def test_retired_pointer_guard_rejects_dotted_slash_and_deleted_doc_mutations() -> None:
    mutations = (
        "Use qns.cpu.Z180 for register access.",
        "Import qns/cpu.py before running this command.",
        r"Modify qns\cpu.py to add the callback.",
        "Regenerate with tools/build_ffi.py.",
        "Continue in prompts/interrupt-tracing-tool.md.",
        "Write results to reports/interrupt-tracing-tool-report.md.",
    )
    for mutation in mutations:
        with pytest.raises(AssertionError):
            _assert_no_retired_pointers({Path("current-guide.md"): mutation})


def test_historical_boundary_rejects_appended_legacy_guidance() -> None:
    historical = (REPO_ROOT / HISTORICAL_LEGACY_RECORD).read_text(encoding="utf-8")
    for pointer in RETIRED_CURRENT_POINTERS:
        mutated = f"{historical}\nNext action: use {pointer} as the current owner.\n"
        with pytest.raises(AssertionError):
            _assert_historical_record_is_sealed(mutated)
