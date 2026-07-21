"""Protocol authorities for the host-rooted PC Disk device."""

import binascii
import subprocess
import sys

from qns.bns import BNS
from qns.cli import build_parser
from qns.pc_disk import ACK, CRC_REQUEST, ENQ, EOT, SOH, STX, PCDisk


def _drain(device: PCDisk) -> bytes:
    reply = bytearray()
    while (value := device.receive()) >= 0:
        reply.append(value)
    return bytes(reply)


def _transmit(device: PCDisk, data: bytes) -> bytes:
    for value in data:
        device.transmit(value)
    return _drain(device)


def _packet(block: int, payload: bytes) -> bytes:
    marker = SOH if len(payload) == 128 else STX
    crc = binascii.crc_hqx(payload, 0)
    return (
        bytes((marker, block & 0xFF, 0xFF - (block & 0xFF)))
        + payload
        + crc.to_bytes(2, "big")
    )


def _begin_command(device: PCDisk) -> None:
    assert _transmit(device, bytes((ENQ,))) == bytes((ACK,))


def test_pc_disk_discovery_advertises_supported_drive(tmp_path):
    device = PCDisk(tmp_path)

    _begin_command(device)

    assert _transmit(device, b"C") == b"1"


def test_pc_disk_directory_and_text_load_use_host_files(tmp_path):
    (tmp_path / "alpha.txt").write_bytes(b"alpha")
    (tmp_path / "beta.brl").write_bytes(b"beta")
    device = PCDisk(tmp_path)

    _begin_command(device)
    listing = _transmit(device, b"d*.txt\r")
    _begin_command(device)
    loaded = _transmit(device, b"Lalpha.txt\r")

    assert listing == b"alpha.txt\r\x1a"
    assert loaded == b"alpha"


def test_pc_disk_text_save_writes_only_inside_root(tmp_path):
    device = PCDisk(tmp_path)

    _begin_command(device)
    assert _transmit(device, b"Snotes.txt\rhello\x1a") == b""
    _begin_command(device)
    traversal_reply = _transmit(device, b"S..\\outside.txt\r")

    assert (tmp_path / "notes.txt").read_bytes() == b"hello"
    assert traversal_reply == b"&"
    assert not (tmp_path.parent / "outside.txt").exists()


def test_pc_disk_directory_management_is_rooted(tmp_path):
    device = PCDisk(tmp_path)

    _begin_command(device)
    assert _transmit(device, b"Mbooks\r") == b""
    _begin_command(device)
    assert _transmit(device, b"Hbooks\r") == b""
    _begin_command(device)
    assert _transmit(device, b"Sindex.txt\rentry\x1a") == b""
    _begin_command(device)
    assert _transmit(device, b"H..\r") == b""
    _begin_command(device)
    assert _transmit(device, b"Kbooks\\index.txt\r") == b""
    _begin_command(device)
    assert _transmit(device, b"Xbooks\r") == b""

    assert list(tmp_path.iterdir()) == []


def test_pc_disk_receives_guest_ymodem_batch_into_host_root(tmp_path):
    device = PCDisk(tmp_path)
    content = b"guest file contents"
    header = (b"guest.bns\0" + str(len(content)).encode() + b"\0").ljust(128, b"\0")
    payload = content.ljust(1024, b"\x1a")

    _begin_command(device)
    assert _transmit(device, b"YR") == bytes((CRC_REQUEST,))
    assert _transmit(device, _packet(0, header)) == bytes((ACK, CRC_REQUEST))
    assert _transmit(device, _packet(1, payload)) == bytes((ACK,))
    assert _transmit(device, bytes((EOT,))) == bytes((ACK, CRC_REQUEST))
    assert _transmit(device, _packet(0, bytes(128))) == bytes((ACK,))

    assert (tmp_path / "guest.bns").read_bytes() == content


def test_pc_disk_sends_host_file_as_ymodem_batch(tmp_path):
    content = b"host file contents"
    (tmp_path / "host.bns").write_bytes(content)
    device = PCDisk(tmp_path)

    _begin_command(device)
    assert _transmit(device, b"YShost.bns\r") == b""
    header_packet = _transmit(device, bytes((CRC_REQUEST,)))
    data_packet = _transmit(device, bytes((ACK, CRC_REQUEST)))
    eot = _transmit(device, bytes((ACK,)))
    assert _transmit(device, bytes((ACK,))) == b""
    final_header = _transmit(device, bytes((CRC_REQUEST,)))
    assert _transmit(device, bytes((ACK,))) == b""

    assert header_packet[0] == SOH
    assert header_packet[1:3] == b"\x00\xff"
    assert header_packet[3:12] == b"host.bns\0"
    assert int.from_bytes(header_packet[-2:], "big") == binascii.crc_hqx(
        header_packet[3:-2], 0
    )
    assert data_packet[0] == STX
    assert data_packet[1:3] == b"\x01\xfe"
    assert data_packet[3 : 3 + len(content)] == content
    assert eot == bytes((EOT,))
    assert final_header == _packet(0, bytes(128))


def test_bns_routes_pc_disk_only_to_asci0(tmp_path):
    bns = BNS(pc_disk_dir=tmp_path)

    bns._serial_transmit(0, ENQ)
    bns._serial_transmit(1, ENQ)

    assert bns._serial_receive(0) == ACK
    assert bns._serial_receive(0) == -1
    assert bns._serial_receive(1) == -1


def test_cli_accepts_pc_disk_dir(tmp_path):
    args = build_parser().parse_args(
        (
            "firmware.bns",
            "--pc-disk-dir",
            str(tmp_path / "disk"),
        )
    )

    assert args.pc_disk_dir == str(tmp_path / "disk")


def test_cli_pc_disk_dir_creates_root_and_rejects_file(tmp_path):
    idle_rom = tmp_path / "idle.bin"
    idle_rom.write_bytes(bytes((0x18, 0xFE)))
    disk_root = tmp_path / "disk"

    created = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(idle_rom),
            "--cycles",
            "5000",
            "--pc-disk-dir",
            str(disk_root),
        ),
        capture_output=True,
        check=False,
        timeout=10,
    )

    not_a_directory = tmp_path / "regular-file"
    not_a_directory.write_text("not a directory")
    rejected = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(idle_rom),
            "--cycles",
            "1",
            "--pc-disk-dir",
            str(not_a_directory),
        ),
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert created.returncode == 0, created.stderr.decode(errors="replace")
    assert disk_root.is_dir()
    assert rejected.returncode == 2
    assert b"--pc-disk-dir is not a directory" in rejected.stderr


def test_cli_requires_power_on_input_for_fresh_bs2_pc_disk(tmp_path):
    rom = tmp_path / "idle.bin"
    rom.write_bytes(bytes((0x18, 0xFE)))

    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "qns.bns",
            str(rom),
            "--model",
            "bs2",
            "--pc-disk-dir",
            str(tmp_path / "disk"),
            "--cycles",
            "1",
        ),
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 2
    assert b"fresh BS2 PC Disk requires --power-on-input" in result.stderr
    assert b"enter uppercase I as the first input" in result.stderr
