"""Keep the project guide aligned with tracked paths, CLI help, and audio timing."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_GUIDE = REPO_ROOT / "CLAUDE.md"
LPC_REPORT = REPO_ROOT / "docs" / "reports" / "lpc-backend-investigation.md"
RENDER_BACKEND = REPO_ROOT / "tools" / "render_backend.py"

REQUIRED_STRUCTURE_PATHS = {
    Path("docs"),
    Path("docs/reports"),
    Path("investigations"),
    Path("qns/pc_disk.py"),
    Path("qns/synth/timing.py"),
    Path("tools/bns_external.py"),
    Path("tools/bs2_harness.py"),
    Path("tools/bs2_stdio_harness.py"),
    Path("tools/verify_bs2_dictionary.py"),
    Path("tools/verify_bs2_external_program.py"),
    Path("tools/verify_bs2_help.py"),
    Path("tools/verify_bs2_pc_disk.py"),
}

RETIRED_AUDIO_CLAIMS = (
    "audio cannot drift against the emulated clock",
    "every backend renders each phoneme for exactly",
    "every backend renders a phoneme for exactly",
    "same length as the live audio",
)

RETIRED_SLEEP_CLAIMS = (
    "a sleeping core advances no cycles",
    "the scheduled wake was never reached",
    "the loop span forever",
    "sleep-jump",
    "time-jump",
    "jump time directly",
)


def _project_structure_paths(document: str) -> set[Path]:
    match = re.search(
        r"^## Project Structure\s*$\s*^```[^\n]*$\n(?P<tree>.*?)^```$",
        document,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "CLAUDE.md has no fenced Project Structure tree"

    paths: set[Path] = set()
    stack: list[str] = []
    for line in match.group("tree").splitlines():
        node = re.match(
            r"^(?P<indent>(?:(?:│   )|(?:    ))*)(?:├──|└──) "
            r"(?P<name>[^#]+?)(?:\s+#.*)?$",
            line,
        )
        if node is None:
            continue
        depth = len(node.group("indent")) // 4
        name = node.group("name").strip().rstrip("/")
        stack[depth:] = [name]
        paths.add(Path(*stack))
    return paths


def _documented_qns_flags(document: str) -> set[str]:
    # Standalone tools have their own parsers. Ignore their command lines while
    # checking prose and qns.bns examples against the main parser.
    qns_document = "\n".join(
        line for line in document.splitlines() if not re.search(r"uv run (?:python )?tools/", line)
    )
    return set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", qns_document))


def _tracked_project_paths() -> set[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    tracked: set[Path] = set()
    for name in result.stdout.decode().split("\0"):
        if not name:
            continue
        path = Path(name)
        tracked.add(path)
        tracked.update(parent for parent in path.parents if parent != Path("."))
    return tracked


def test_project_structure_names_only_existing_tracked_paths() -> None:
    structure_paths = _project_structure_paths(PROJECT_GUIDE.read_text(encoding="utf-8"))
    missing = sorted(path for path in structure_paths if not (REPO_ROOT / path).exists())
    untracked = sorted(structure_paths - _tracked_project_paths())

    assert not missing
    assert not untracked
    assert REQUIRED_STRUCTURE_PATHS <= structure_paths


def test_project_guide_flags_exist_in_qns_help() -> None:
    documented = _documented_qns_flags(PROJECT_GUIDE.read_text(encoding="utf-8"))
    result = subprocess.run(
        [sys.executable, "-m", "qns.bns", "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    available = set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", result.stdout))

    assert documented <= available


def test_audio_docs_do_not_repeat_retired_timing_invariants() -> None:
    relevant = {
        path: path.read_text(encoding="utf-8").casefold()
        for path in (PROJECT_GUIDE, LPC_REPORT, RENDER_BACKEND)
    }
    violations = {
        path.relative_to(REPO_ROOT): sorted(
            claim for claim in RETIRED_AUDIO_CLAIMS if claim in text
        )
        for path, text in relevant.items()
        if any(claim in text for claim in RETIRED_AUDIO_CLAIMS)
    }

    assert not violations


def test_docs_state_the_current_audio_reset_and_cli_contracts() -> None:
    guide = PROJECT_GUIDE.read_text(encoding="utf-8").casefold()
    report = LPC_REPORT.read_text(encoding="utf-8").casefold()
    renderer = RENDER_BACKEND.read_text(encoding="utf-8").casefold()

    assert "modeled candidate audio" in guide
    assert "end_phoneme" in guide
    assert "elapsed emulated time" in guide
    assert "warm reset legitimately reverts retained speech settings" in guide
    assert "argparse is the project cli framework" in guide
    assert "modeled candidate audio" in report
    assert "elapsed emulated time" in report
    assert "offline renderer" in renderer
    assert "trace timing and gaps" in renderer
    assert "does not prove live or audible behavior" in renderer


def test_obsolete_sleep_jump_and_click_guidance_is_gone() -> None:
    relevant = (
        PROJECT_GUIDE.read_text(encoding="utf-8")
        + "\n"
        + (REPO_ROOT / "qns" / "bns.py").read_text(encoding="utf-8")
    ).casefold()

    assert "add click commands" not in relevant
    assert not {claim for claim in RETIRED_SLEEP_CLAIMS if claim in relevant}
