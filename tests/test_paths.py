"""Session state files resolve into one gitignored directory."""

from pathlib import Path

from qns.paths import SESSION_STATE_DIR, resolve_state_path


def test_bare_name_goes_in_the_session_state_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert resolve_state_path("flash.bin") == SESSION_STATE_DIR / "flash.bin"
    # Saving writes a sibling .tmp, so the directory has to exist already.
    assert (tmp_path / SESSION_STATE_DIR).is_dir()


def test_an_explicit_path_is_left_exactly_where_it_was_asked_for(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert resolve_state_path("./flash.bin") == Path("flash.bin")
    assert resolve_state_path("runs/a.bin") == Path("runs/a.bin")
    absolute = tmp_path / "elsewhere.bin"
    assert resolve_state_path(str(absolute)) == absolute
    # Nothing was created for a path that was not redirected.
    assert not (tmp_path / SESSION_STATE_DIR).exists()


def test_cli_saves_a_bare_state_name_into_the_directory(tmp_path, monkeypatch):
    """End to end: the run writes where resolve_state_path says, not the cwd."""
    import qns.cli

    rom = Path("roms/bspeng.bns").resolve()
    monkeypatch.chdir(tmp_path)

    qns.cli.main(["--cycles", "1000", "--input", "none",
                  "--state", "flash.bin", str(rom)])

    assert (tmp_path / SESSION_STATE_DIR / "flash.bin").stat().st_size > 0
    assert not (tmp_path / "flash.bin").exists()
