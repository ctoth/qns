"""Host-directory implementation of the legacy Braille 'N Speak PC Disk."""

from __future__ import annotations

import binascii
from collections import deque
from pathlib import Path

ENQ = 0x05
ACK = 0x06
NAK = 0x15
SOH = 0x01
STX = 0x02
EOT = 0x04
CAN = 0x18
CTRL_Z = 0x1A
CR = 0x0D
CRC_REQUEST = ord("C")
CPM_EOF = 0x1A

_TEXT_COMMANDS = {ord(command) for command in "dLSTKHMXVFU"}
_WILDCARDS = "*?[]"


def _crc16_xmodem(data: bytes) -> int:
    return binascii.crc_hqx(data, 0)


def _ymodem_packet(block_number: int, payload: bytes) -> bytes:
    marker = SOH if len(payload) == 128 else STX
    crc = _crc16_xmodem(payload)
    return (
        bytes((marker, block_number & 0xFF, 0xFF - (block_number & 0xFF)))
        + payload
        + crc.to_bytes(2, "big")
    )


class PCDisk:
    """Serve one rooted host directory through the firmware's PC Disk protocol."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"PC Disk root is not a directory: {self.root}")

        self.current_directory = self.root
        self._reply: deque[int] = deque()
        self._state = "idle"
        self._command = 0
        self._argument = bytearray()
        self._text_data = bytearray()
        self._text_target: Path | None = None
        self._last_status = 0

        self._packet = bytearray()
        self._packet_size = 0
        self._receive_target: Path | None = None
        self._receive_size = 0
        self._receive_data = bytearray()
        self._receive_block = 1

        self._send_files: list[Path] = []
        self._send_file_index = 0
        self._send_data = b""
        self._send_offset = 0
        self._send_block = 1
        self._send_last = b""

    def receive(self) -> int:
        """Return one queued peer byte, or -1 when the device has nothing to send."""
        return self._reply.popleft() if self._reply else -1

    def transmit(self, value: int) -> None:
        """Consume one byte transmitted by the emulated notetaker."""
        value &= 0xFF

        if self._state == "idle":
            if value == ENQ:
                self._reply.append(ACK)
                self._state = "command"
            return

        if self._state == "command":
            if value == CRC_REQUEST:
                self._reply.append(ord("1"))
                self._state = "idle"
            elif value == ord("Y"):
                self._state = "ymodem-command"
            elif value in _TEXT_COMMANDS:
                self._command = value
                self._argument.clear()
                self._state = "argument"
            else:
                self._last_status = ord("?")
                self._state = "idle"
            return

        if self._state == "argument":
            if value == CR:
                self._execute_text_command()
            elif len(self._argument) < 4096:
                self._argument.append(value)
            else:
                self._fail(ord("&"))
            return

        if self._state == "text-receive":
            if value == CTRL_Z:
                self._finish_text_receive()
            else:
                self._text_data.append(value)
            return

        if self._state == "ymodem-command":
            if value == ord("R"):
                self._begin_ymodem_receive()
            elif value == ord("S"):
                self._argument.clear()
                self._state = "ymodem-path"
            elif value == ord("E"):
                self._reply.append(self._last_status)
                self._state = "idle"
            else:
                self._fail(ord("?"))
            return

        if self._state == "ymodem-path":
            if value == CR:
                self._begin_ymodem_send()
            elif len(self._argument) < 4096:
                self._argument.append(value)
            else:
                self._fail(ord("&"))
            return

        if self._state == "ymodem-receive":
            self._receive_ymodem_byte(value)
            return

        self._transmit_ymodem_control(value)

    def _argument_text(self) -> str:
        return self._argument.decode("latin-1").strip()

    def _resolve(self, value: str, *, base: Path | None = None) -> Path:
        normalized = value.replace("\\", "/")
        if ":" in normalized:
            raise ValueError("drive-qualified PC Disk paths are not allowed")
        anchor = self.root if normalized.startswith("/") else (base or self.current_directory)
        candidate = anchor.joinpath(*[part for part in normalized.split("/") if part]).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("PC Disk path escapes its configured root")
        return candidate

    def _matches(self, value: str) -> list[Path]:
        normalized = value.replace("\\", "/") or "*"
        parent_text, separator, pattern = normalized.rpartition("/")
        if not separator:
            parent_text, pattern = "", normalized
        parent = self._resolve(parent_text or ".")
        if not parent.is_dir():
            return []
        if pattern in ("", "*.*"):
            pattern = "*"
        if not any(character in pattern for character in _WILDCARDS):
            candidate = self._resolve(pattern, base=parent)
            return [candidate] if candidate.exists() else []
        return sorted(
            (path for path in parent.glob(pattern) if path.resolve().is_relative_to(self.root)),
            key=lambda path: path.name.casefold(),
        )

    def _execute_text_command(self) -> None:
        command = chr(self._command)
        argument = self._argument_text()
        self._last_status = 0
        try:
            if command == "d":
                self._send_directory(argument)
            elif command == "L":
                self._send_text_file(argument)
            elif command in ("S", "T"):
                self._text_target = self._resolve(argument)
                if not self._text_target.parent.is_dir():
                    raise FileNotFoundError(argument)
                self._text_data.clear()
                self._state = "text-receive"
            elif command == "K":
                matches = [path for path in self._matches(argument) if path.is_file()]
                if not matches:
                    raise FileNotFoundError(argument)
                for path in matches:
                    path.unlink()
                self._state = "idle"
            elif command == "H":
                directory = self._resolve(argument)
                if not directory.is_dir():
                    raise FileNotFoundError(argument)
                self.current_directory = directory
                self._state = "idle"
            elif command == "M":
                self._resolve(argument).mkdir()
                self._state = "idle"
            elif command == "X":
                self._resolve(argument).rmdir()
                self._state = "idle"
            elif command == "V":
                self._state = "idle"
            elif command in ("F", "U"):
                self._fail(ord("?"))
        except FileExistsError:
            self._fail(ord("+"))
        except FileNotFoundError:
            self._fail(ord("#"))
        except (OSError, ValueError):
            self._fail(ord("&"))

    def _send_directory(self, argument: str) -> None:
        matches = self._matches(argument or "*")
        listing = bytearray()
        for path in matches:
            name = path.name + ("\\" if path.is_dir() else "")
            listing.extend(name.encode("latin-1", errors="replace"))
            listing.append(CR)
        if not listing:
            listing.extend(b".\r")
        listing.append(CTRL_Z)
        self._reply.extend(listing)
        self._state = "idle"

    def _send_text_file(self, argument: str) -> None:
        matches = [path for path in self._matches(argument) if path.is_file()]
        if not matches:
            raise FileNotFoundError(argument)
        self._reply.extend(matches[0].read_bytes())
        self._state = "idle"

    def _finish_text_receive(self) -> None:
        assert self._text_target is not None
        try:
            self._text_target.write_bytes(self._text_data)
        except OSError:
            self._last_status = ord("&")
            self._reply.append(self._last_status)
        else:
            self._last_status = 0
        self._text_target = None
        self._text_data.clear()
        self._state = "idle"

    def _fail(self, status: int) -> None:
        self._last_status = status
        self._reply.append(status)
        self._state = "idle"

    def _begin_ymodem_receive(self) -> None:
        self._packet.clear()
        self._packet_size = 0
        self._receive_target = None
        self._receive_size = 0
        self._receive_data.clear()
        self._receive_block = 1
        self._last_status = 0
        self._reply.append(CRC_REQUEST)
        self._state = "ymodem-receive"

    def _receive_ymodem_byte(self, value: int) -> None:
        if not self._packet:
            if value == EOT:
                self._finish_received_file()
                self._reply.extend((ACK, CRC_REQUEST))
                return
            if value not in (SOH, STX):
                return
            self._packet_size = 133 if value == SOH else 1029
        self._packet.append(value)
        if len(self._packet) != self._packet_size:
            return

        packet = bytes(self._packet)
        self._packet.clear()
        block = packet[1]
        payload = packet[3:-2]
        valid = (
            packet[2] == 0xFF - block
            and int.from_bytes(packet[-2:], "big") == _crc16_xmodem(payload)
        )
        if not valid:
            self._reply.append(NAK)
            return

        if block == 0:
            self._receive_header(payload)
        elif block == self._receive_block:
            self._receive_data.extend(payload)
            self._receive_block = (self._receive_block + 1) & 0xFF
            self._reply.append(ACK)
        elif block == (self._receive_block - 1) & 0xFF:
            self._reply.append(ACK)
        else:
            self._reply.append(NAK)

    def _receive_header(self, payload: bytes) -> None:
        filename, _, remainder = payload.partition(b"\0")
        if not filename:
            self._reply.append(ACK)
            self._state = "idle"
            return
        size_text = remainder.partition(b"\0")[0].partition(b" ")[0]
        try:
            target = self._resolve(filename.decode("latin-1"))
            if not target.parent.is_dir():
                raise FileNotFoundError(target.parent)
            size = int(size_text or b"0")
        except (OSError, ValueError):
            self._last_status = ord("&")
            self._reply.extend((CAN, CAN))
            self._state = "idle"
            return
        self._receive_target = target
        self._receive_size = size
        self._receive_data.clear()
        self._receive_block = 1
        self._reply.extend((ACK, CRC_REQUEST))

    def _finish_received_file(self) -> None:
        if self._receive_target is None:
            return
        try:
            self._receive_target.write_bytes(self._receive_data[: self._receive_size])
        except OSError:
            self._last_status = ord("&")
        self._receive_target = None
        self._receive_data.clear()

    def _begin_ymodem_send(self) -> None:
        try:
            self._send_files = [
                path for path in self._matches(self._argument_text()) if path.is_file()
            ]
        except (OSError, ValueError):
            self._send_files = []
        self._send_file_index = 0
        self._send_data = b""
        self._send_offset = 0
        self._send_block = 1
        self._send_last = b""
        self._last_status = 0 if self._send_files else ord("#")
        self._state = "ymodem-send-request"

    def _transmit_ymodem_control(self, value: int) -> None:
        if self._state in ("ymodem-send-request", "ymodem-send-next"):
            if value == CRC_REQUEST:
                self._send_header()
            return
        if self._state == "ymodem-send-header-ack":
            if value == ACK:
                self._state = "ymodem-send-data-request"
            elif value == NAK:
                self._reply.extend(self._send_last)
            return
        if self._state == "ymodem-send-data-request":
            if value == CRC_REQUEST:
                self._send_data_block()
            return
        if self._state == "ymodem-send-data-ack":
            if value == ACK:
                self._send_data_block()
            elif value == NAK:
                self._reply.extend(self._send_last)
            return
        if self._state == "ymodem-send-eot-ack":
            if value == ACK:
                self._send_file_index += 1
                self._state = "ymodem-send-next"
            elif value == NAK:
                self._reply.append(EOT)
            return
        if self._state == "ymodem-send-final-ack" and value == ACK:
            self._state = "idle"

    def _send_header(self) -> None:
        if self._send_file_index >= len(self._send_files):
            payload = bytes(128)
            self._send_last = _ymodem_packet(0, payload)
            self._reply.extend(self._send_last)
            self._state = "ymodem-send-final-ack"
            return
        path = self._send_files[self._send_file_index]
        self._send_data = path.read_bytes()
        self._send_offset = 0
        self._send_block = 1
        header = (
            path.name.encode("latin-1", errors="replace")
            + b"\0"
            + str(len(self._send_data)).encode("ascii")
            + b"\0"
        ).ljust(128, b"\0")
        self._send_last = _ymodem_packet(0, header)
        self._reply.extend(self._send_last)
        self._state = "ymodem-send-header-ack"

    def _send_data_block(self) -> None:
        if self._send_offset >= len(self._send_data):
            self._reply.append(EOT)
            self._state = "ymodem-send-eot-ack"
            return
        payload = self._send_data[self._send_offset : self._send_offset + 1024]
        self._send_offset += len(payload)
        payload = payload.ljust(1024, bytes((CPM_EOF,)))
        self._send_last = _ymodem_packet(self._send_block, payload)
        self._send_block = (self._send_block + 1) & 0xFF
        self._reply.extend(self._send_last)
        self._state = "ymodem-send-data-ack"
