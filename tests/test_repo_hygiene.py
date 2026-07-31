"""Regression guards for repository-local binary and generated artifacts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TRACKED_SUFFIXES = {".bin", ".exe", ".ima", ".zip"}
MAX_TRACKED_FILE_SIZE = 512 * 1024
# Issue #27 removes this exception when the generated Python data is split out.
LARGE_FILE_ALLOWLIST = {Path("qns/synth/phonemes.py")}
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


def _git_paths(*args: str) -> set[Path]:
    output = subprocess.check_output(["git", *args, "-z"], cwd=REPO_ROOT)
    return {Path(os.fsdecode(path)) for path in output.split(b"\0") if path}


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
        and (REPO_ROOT / path).stat().st_size > MAX_TRACKED_FILE_SIZE
    }

    assert not oversized, f"tracked files exceed {MAX_TRACKED_FILE_SIZE} bytes: {oversized}"
