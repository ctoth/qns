"""Tests for SSI-263 phoneme capture."""

import sys

import pytest

from qns.bns import BNS
from qns.bns import main as bns_main
from qns.ssi263 import SSI263, Phoneme


def test_chip_writes_are_silent_and_capture_named_phonemes(capsys) -> None:
    chip = SSI263()

    chip.write(chip.base_port + chip.REG_RATEINF, 0x80)
    chip.write(chip.base_port + chip.REG_CTRLAMP, 0x0F)
    chip.write(chip.base_port + chip.REG_DURPHON, 0xC1)

    assert capsys.readouterr().out == ""
    assert chip.get_phonemes() == (
        Phoneme(code=0x00, name="PA", example="pause", ipa=""),
        Phoneme(code=0x01, name="E", example="MEET", ipa="i:"),
    )
    assert chip.get_phonemes(include_pauses=False) == (
        Phoneme(code=0x01, name="E", example="MEET", ipa="i:"),
    )


def test_bns_run_retains_capture_without_repeated_speech_output(capsys) -> None:
    bns = BNS()
    bns.ssi263.phoneme_log.extend((0x01, 0x02))
    capsys.readouterr()

    bns.run(max_cycles=1)

    assert bns.ssi263.phoneme_log == [0x01, 0x02]
    assert bns.stats["phonemes"] == 2
    assert "[Speech]" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("speech_format", "expected"),
    (
        ("codes", "01 02"),
        ("names", "E E1"),
        ("ipa", "i: ɛ"),
        ("examples", "MEET BENT"),
    ),
)
def test_cli_can_print_retained_phonemes(
    monkeypatch,
    tmp_path,
    capsys,
    speech_format: str,
    expected: str,
) -> None:
    rom_path = tmp_path / "test.bns"
    rom_path.write_bytes(b"\x00")

    def capture_speech(bns: BNS, max_cycles: int = 0) -> None:
        bns.ssi263.phoneme_log.extend((0x00, 0x01, 0x02))

    monkeypatch.setattr(BNS, "run", capture_speech)
    monkeypatch.setattr(
        sys,
        "argv",
        ["qns.bns", str(rom_path), "--cycles", "1", "--speech", speech_format],
    )

    bns_main()

    assert capsys.readouterr().out.endswith(f"Speech {speech_format}: {expected}\n")


def test_cli_can_print_retained_english_firmware_speech(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    rom_path = tmp_path / "test.bns"
    rom_path.write_bytes(b"\x00")

    def capture_speech(bns: BNS, max_cycles: int = 0) -> None:
        bns._english_callback("help is open")
        bns._english_callback("enter file command")

    monkeypatch.setattr(BNS, "run", capture_speech)
    monkeypatch.setattr(
        sys,
        "argv",
        ["qns.bns", str(rom_path), "--cycles", "1", "--speech", "english"],
    )

    bns_main()

    assert capsys.readouterr().out.endswith(
        "Speech english: help is open enter file command\n"
    )


@pytest.mark.parametrize(
    ("speech_format", "expected"),
    (
        ("codes", "01"),
        ("names", "E"),
        ("ipa", "i:"),
        ("examples", "MEET"),
    ),
)
def test_cli_streams_each_non_pause_phoneme_before_run_returns(
    monkeypatch,
    tmp_path,
    capsys,
    speech_format: str,
    expected: str,
) -> None:
    rom_path = tmp_path / "test.bns"
    rom_path.write_bytes(b"\x00")

    def produce_speech(bns: BNS, max_cycles: int = 0) -> None:
        bns.ssi263.write(bns.ssi263.base_port + bns.ssi263.REG_CTRLAMP, 0x0F)
        bns.ssi263.write(bns.ssi263.base_port + bns.ssi263.REG_DURPHON, 0xC1)
        print("Run returned")

    monkeypatch.setattr(BNS, "run", produce_speech)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qns.bns",
            str(rom_path),
            "--cycles",
            "1",
            "--speech-stream",
            speech_format,
        ],
    )

    bns_main()

    assert capsys.readouterr().out.endswith(
        f"Speech {speech_format}: {expected}\nRun returned\n"
    )


def test_cli_streams_english_firmware_speech_before_run_returns(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    rom_path = tmp_path / "test.bns"
    rom_path.write_bytes(b"\x00")

    def produce_speech(bns: BNS, max_cycles: int = 0) -> None:
        bns._english_callback("enter file command")
        print("Run returned")

    monkeypatch.setattr(BNS, "run", produce_speech)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qns.bns",
            str(rom_path),
            "--cycles",
            "1",
            "--speech-stream",
            "english",
        ],
    )

    bns_main()

    assert capsys.readouterr().out.endswith(
        "Speech english: enter file command\nRun returned\n"
    )
