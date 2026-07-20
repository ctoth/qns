"""Authorities for driving the shipped JSONL subprocess boundary."""

import pytest

from tools.stdio_process import BNSStdioProcess


def test_stdio_process_round_trips_binary_serial_through_real_cli(tmp_path):
    echo_rom = tmp_path / "serial-echo.bin"
    echo_rom.write_bytes(bytes((
        0x3E, 0x64,
        0xED, 0x39, 0x00,
        0x3E, 0x02,
        0xED, 0x39, 0x02,
        0xED, 0x38, 0x04,
        0xE6, 0x80,
        0x28, 0xF9,
        0xED, 0x38, 0x08,
        0xED, 0x39, 0x06,
        0x18, 0xF0,
    )))

    with BNSStdioProcess(echo_rom, model="bsp", cycles=200_000) as bns:
        bns.send_serial(0, b"\x00\xffZ")
        cursor = bns.wait_for_serial(
            0,
            0,
            b"\x00\xffZ",
            "three echoed binary bytes",
            timeout=10,
        )

        assert cursor == 3
        assert bytes(bns.serial[0]) == b"\x00\xffZ"
        assert bns.serial[1] == b""
        assert "Input: STDIN (jsonl)" in bns.stderr()


def test_stdio_process_requires_one_keyboard_representation(tmp_path):
    idle_rom = tmp_path / "idle.bin"
    idle_rom.write_bytes(bytes((0x18, 0xFE)))

    with BNSStdioProcess(idle_rom, model="bsp", cycles=1_000) as bns:
        with pytest.raises(ValueError, match="exactly one"):
            bns.send_keyboard()
        with pytest.raises(ValueError, match="exactly one"):
            bns.send_keyboard(text="a", chord=1)


def test_stdio_process_arms_and_observes_native_pc_watch(tmp_path):
    watch_rom = tmp_path / "watch.bin"
    watch_rom.write_bytes(
        bytes((0xC3, 0x10, 0x00))
        + bytes(13)
        + bytes((0x18, 0xFE))
    )

    with BNSStdioProcess(watch_rom, model="bsp", cycles=500_000) as bns:
        bns.arm_pc_watch(0x10, timeout=10)
        event = bns.wait_for_pc_watch(0x10, timeout=10)

        assert event["cycle"] > 0
        assert event["cbar"] == 0xF0
