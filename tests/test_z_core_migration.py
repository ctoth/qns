"""Real-ROM compatibility versus direct z-core conformance authorities."""

import os
import time
from pathlib import Path
from shutil import copyfile

import pytest

from qns.bns import BNS
from qns.input_driver import ASCII_TO_BNS_KEY
from tools.bs2_stdio_harness import FILE_COMMAND_PROMPT, FLASH_INITIALIZATION_PROMPT
from tools.stdio_process import BNSStdioProcess
from tools.verify_bs2_external_program import F_KEY, O_CHORD

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_CONFORMANCE = os.environ.get("QNS_Z_CORE_REAL_CONFORMANCE") == "1"

PROFILE_ROMS = (
    ("bsp", Path("roms/NFB99/BSPENG/bspeng.bns"), 0x7F),
    ("bs2", Path("roms/NFB99/BS2ENG/bs2eng.bns"), 0x7F),
    ("bsl", Path("roms/NFB99/BSLENG/bsleng.bns"), 0x7F),
    ("bl2", Path("roms/NFB99/BL2ENG/bl2eng.bns"), 0x7F),
    ("bl4", Path("roms/NFB99/BL4ENG/bl4eng.bns"), 0x7F),
    ("tns", Path("roms/NFB99/TNSENG/tnseng.tns"), 0x81),
)

BS2_2003_ROM = Path("roms/bns2000/BS2ENG.BNS")


def _run_to_input_acceptance(
    rom: Path,
    state: Path,
    *,
    model: str,
    core: str,
    expected_chord: int,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    accepted = False
    deadline = time.monotonic() + 120

    with BNSStdioProcess(
        rom,
        model=model,
        core=core,
        state=state,
        reset="warm",
    ) as process:
        while not accepted:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                pytest.fail(
                    f"{model} {core} did not accept warm-reset input; "
                    f"stderr=[{process.stderr()}]"
                )
            try:
                event = process.next_event(min(30, remaining))
            except TimeoutError:
                if process.process.poll() is not None:
                    pytest.fail(
                        f"{model} {core} exited before accepting input; "
                        f"stderr=[{process.stderr()}]"
                    )
                continue
            events.append(event)
            if event.get("device") != "keyboard":
                continue
            if (
                event.get("state") == "accepted"
                and event.get("chord") == expected_chord
            ):
                accepted = True

    return events


@pytest.mark.skipif(
    not REAL_CONFORMANCE,
    reason="set QNS_Z_CORE_REAL_CONFORMANCE=1 for the six real-ROM comparisons",
)
@pytest.mark.parametrize(("model", "relative_rom", "warm_chord"), PROFILE_ROMS)
def test_real_profile_boot_matches_compat_with_same_state(
    tmp_path,
    model,
    relative_rom,
    warm_chord,
):
    """Visible boot output and accepted input match from one persisted state."""
    rom = REPO_ROOT / relative_rom
    if not rom.is_file():
        pytest.fail(f"required real-ROM authority is unavailable: {rom}")

    seed_state = tmp_path / f"{model}-seed.state"
    seed = BNS(model=model, core="compat")
    seed.load_rom(rom)
    seed.save_state(seed_state)

    compat_state = tmp_path / f"{model}-compat.state"
    direct_state = tmp_path / f"{model}-direct.state"
    copyfile(seed_state, compat_state)
    copyfile(seed_state, direct_state)
    assert compat_state.read_bytes() == direct_state.read_bytes()

    compat_events = _run_to_input_acceptance(
        rom,
        compat_state,
        model=model,
        core="compat",
        expected_chord=warm_chord,
    )
    direct_events = _run_to_input_acceptance(
        rom,
        direct_state,
        model=model,
        core="direct",
        expected_chord=warm_chord,
    )

    assert direct_events == compat_events


@pytest.mark.skipif(
    not REAL_CONFORMANCE,
    reason="set QNS_Z_CORE_REAL_CONFORMANCE=1 for real-ROM input conformance",
)
@pytest.mark.parametrize("core", ("compat", "direct"))
def test_real_bs2_fresh_start_reaches_file_command(tmp_path, core):
    """A real fresh start accepts n, Shift+O, and f through application use."""
    rom = REPO_ROOT / BS2_2003_ROM
    if not rom.is_file():
        pytest.fail(f"required real-ROM authority is unavailable: {rom}")

    with BNSStdioProcess(
        rom,
        model="bs2",
        core=core,
        state=tmp_path / f"bs2-{core}.state",
    ) as process:
        process.wait_for_speech_suffix(
            FLASH_INITIALIZATION_PROMPT,
            "initialize flash system prompt",
            timeout=120,
        )
        process.send_keyboard(text="n")
        process.wait_for_keyboard(
            "accepted",
            chord=ASCII_TO_BNS_KEY[ord("n")],
            timeout=60,
        )
        if process.speech_texts[-1:] != ["page"]:
            process.wait_for(
                lambda _event: process.speech_texts[-1:] == ["page"],
                "post-initialization page speech",
                timeout=60,
            )
        process.send_keyboard(text="O")
        process.wait_for_keyboard("accepted", chord=O_CHORD, timeout=60)
        process.wait_for_keyboard("ready", timeout=60)
        process.send_keyboard(text="f")
        process.wait_for_keyboard("accepted", chord=F_KEY, timeout=60)
        process.wait_for_keyboard("ready", timeout=60)
        process.wait_for_speech_suffix(
            FILE_COMMAND_PROMPT,
            "file command prompt",
            timeout=60,
        )
        process.send_keyboard(text="Z")
        process.wait_for_keyboard(
            "accepted",
            chord=ASCII_TO_BNS_KEY[ord("Z")],
            timeout=60,
        )
        process.wait_for_keyboard("ready", timeout=60)
        if process.speech_texts[-1:] != ["exit"]:
            process.wait_for(
                lambda _event: process.speech_texts[-1:] == ["exit"],
                "file command exit speech",
                timeout=60,
            )
