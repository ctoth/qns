"""Reusable real-firmware BS2 workflows over the QNS JSONL boundary."""

from __future__ import annotations

from pathlib import Path

from tools.stdio_process import BNSStdioProcess

T_CHORD = 0x5E
R_KEY = 0x17
Y_KEY = 0x3D
E_CHORD = 0x51
X_CHORD = 0x6D
COLD_RESET_CHORD = 0x4A

SOH = 0x01
STX = 0x02
EOT = 0x04
ACK = 0x06
NAK = 0x15
CRC_REQUEST = ord("C")
CPM_EOF = 0x1A

FLASH_INITIALIZATION_Y_KEY = 0x3D
FLASH_INITIALIZATION_PROMPT = (
    "I",
    "N",
    "I",
    "SCH",
    "AE1",
    "L",
    "AH",
    "E1",
    "Z",
    "F",
    "L",
    "AE",
    "SCH",
    "S",
    "I",
    "S",
    "T",
    "EH",
    "M",
    "EH",
    "N",
    "T",
    "ER",
    "W",
    "AH",
    "E",
    "OU",
    "ER",
    "EH",
    "N",
)
FILE_INITIALIZATION_PROMPT = (
    "I",
    "N",
    "I",
    "SCH",
    "AE1",
    "L",
    "AH",
    "E1",
    "Z",
    "F",
    "AH",
    "E",
    "L",
    "S",
    "I",
    "S",
    "T",
    "EH",
    "M",
    "EH",
    "N",
    "T",
    "ER",
    "W",
    "AH",
    "E",
    "OU",
    "ER",
    "EH",
    "N",
)
FOLDER_INITIALIZATION_PROMPT = (
    "I",
    "N",
    "I",
    "SCH",
    "AE1",
    "L",
    "AH",
    "E1",
    "Z",
    "F",
    "O",
    "OU",
    "L",
    "D",
    "ER",
    "S",
    "I",
    "S",
    "T",
    "EH",
    "M",
    "EH",
    "N",
    "T",
    "ER",
    "W",
    "AH",
    "E",
    "OU",
    "ER",
    "EH",
    "N",
)
WIPEOUT_PROMPT = (
    "D",
    "I",
    "L",
    "E",
    "T",
    "AW",
    "LF",
    "D",
    "A",
    "E",
    "T",
    "UH1",
    "I",
    "N",
    "F",
    "AH",
    "E",
    "L",
    "EH",
    "R",
    "E",
    "UH1",
    "EH",
    "N",
    "T",
    "ER",
    "W",
    "AH",
    "E",
    "OU",
    "ER",
    "EH",
    "N",
)
FLASH_CONFIRMATION_PROMPT = (
    "AH",
    "ER",
    "YI",
    "U",
    "U",
    "SCH",
    "O",
    "ER",
    "EH",
    "N",
    "T",
    "ER",
    "W",
    "AH",
    "E",
    "OU",
    "ER",
    "EH",
    "N",
)
FILE_COMMAND_PROMPT = (
    "EH",
    "N",
    "T",
    "ER",
    "F",
    "AH",
    "E",
    "L",
    "K",
    "UH1",
    "M",
    "AE",
    "N",
    "D",
)


def crc16_xmodem(data: bytes) -> int:
    """Return the CRC-16/XMODEM value used by the firmware."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = (
                ((crc << 1) ^ 0x1021) & 0xFFFF
                if crc & 0x8000
                else (crc << 1) & 0xFFFF
            )
    return crc


def ymodem_packet(block_number: int, payload: bytes, block_size: int) -> bytes:
    """Build one CRC-protected YMODEM packet."""
    if len(payload) != block_size:
        raise ValueError(f"payload is {len(payload)} bytes, expected {block_size}")
    marker = SOH if block_size == 128 else STX
    crc = crc16_xmodem(payload)
    return (
        bytes((marker, block_number, 0xFF - block_number))
        + payload
        + crc.to_bytes(2, "big")
    )


def send_stdio_chord(
    process: BNSStdioProcess,
    chord: int,
    *,
    wait_ready: bool = True,
) -> None:
    """Deliver one exact chord and require firmware acceptance."""
    process.send_keyboard(chord=chord)
    process.wait_for_keyboard("accepted", chord=chord, timeout=60)
    if wait_ready:
        process.wait_for_keyboard("ready", timeout=60)


def reach_stdio_editor_command_loop(process: BNSStdioProcess) -> None:
    """Complete real first-boot prompts using speech and keyboard events only."""
    editor_command_loop_pc = 0xD657
    initialization_prompts = (
        FLASH_INITIALIZATION_PROMPT,
        FILE_INITIALIZATION_PROMPT,
        FOLDER_INITIALIZATION_PROMPT,
        WIPEOUT_PROMPT,
        FLASH_CONFIRMATION_PROMPT,
    )
    expected_chord = COLD_RESET_CHORD
    speech_start = len(process.speech_names)
    process.send_event("cpu", watch_pc=editor_command_loop_pc)
    watch_armed = False

    for _ in range(12):
        accepted = False
        ready = False
        command_loop = False
        prompt_seen = False

        def reached_startup_boundary(event: dict[str, object]) -> bool:
            nonlocal accepted, ready, command_loop, prompt_seen, watch_armed
            if event.get("device") == "keyboard":
                if (
                    event.get("state") == "accepted"
                    and event.get("chord") == expected_chord
                ):
                    accepted = True
                elif event.get("state") == "ready":
                    ready = True
            elif event.get("device") == "cpu" and event.get("pc") == editor_command_loop_pc:
                if event.get("event") == "watch-armed":
                    watch_armed = True
                elif event.get("event") == "pc-watch":
                    command_loop = True

            names = process.speech_names
            prompt_seen = len(names) > speech_start and any(
                tuple(names[-len(prompt):]) == prompt
                for prompt in initialization_prompts
            )
            return watch_armed and accepted and ready and (command_loop or prompt_seen)

        process.wait_for(
            reached_startup_boundary,
            "BS2 initialization prompt or editor command loop",
            timeout=90,
        )
        if command_loop:
            return
        if not prompt_seen:
            raise RuntimeError("BS2 startup boundary lacked a recognized prompt")

        speech_start = len(process.speech_names)
        expected_chord = FLASH_INITIALIZATION_Y_KEY
        process.send_keyboard(chord=FLASH_INITIALIZATION_Y_KEY)
    raise RuntimeError("BS2 initialization exceeded 12 firmware prompts")


def transfer_stdio_ymodem(
    process: BNSStdioProcess,
    cursor: int,
    file_path: Path,
) -> None:
    """Transfer one file through structured ASCI0 events."""
    file_data = file_path.read_bytes()
    post_import_speech_start = len(process.speech_names)
    post_import_ready = False

    def wait_for_transfer_boundary(
        start: int,
        suffix: bytes,
        description: str,
        *,
        require_post_import_prompt: bool = False,
    ) -> int:
        nonlocal post_import_ready

        def reached_boundary(event: dict[str, object]) -> bool:
            nonlocal post_import_ready
            if event.get("device") == "keyboard" and event.get("state") == "ready":
                post_import_ready = True
            serial_seen = bytes(process.serial[0][start:]).endswith(suffix)
            if not require_post_import_prompt:
                return serial_seen
            names = process.speech_names
            prompt_seen = (
                len(names) > post_import_speech_start
                and tuple(names[-len(FILE_COMMAND_PROMPT):]) == FILE_COMMAND_PROMPT
            )
            return serial_seen and post_import_ready and prompt_seen

        process.wait_for(reached_boundary, description, timeout=60)
        return len(process.serial[0])

    header = (
        file_path.name.encode("ascii")
        + b"\0"
        + str(len(file_data)).encode("ascii")
        + b"\0"
    ).ljust(128, b"\0")

    cursor = wait_for_transfer_boundary(
        cursor,
        bytes((CRC_REQUEST,)),
        "initial YMODEM CRC request",
    )
    process.send_serial(0, ymodem_packet(0, header, 128))
    cursor = wait_for_transfer_boundary(
        cursor,
        bytes((ACK, CRC_REQUEST)),
        "header ACK and data CRC request",
    )

    for block_number, offset in enumerate(range(0, len(file_data), 1_024), start=1):
        payload = file_data[offset : offset + 1_024].ljust(1_024, bytes((CPM_EOF,)))
        process.send_serial(
            0,
            ymodem_packet(block_number & 0xFF, payload, 1_024),
        )
        cursor = wait_for_transfer_boundary(
            cursor,
            bytes((ACK,)),
            f"data block {block_number} ACK",
        )

    process.send_serial(0, bytes((EOT,)))
    cursor = wait_for_transfer_boundary(
        cursor,
        bytes((ACK, CRC_REQUEST)),
        "EOT ACK and batch CRC request",
    )
    process.send_serial(0, ymodem_packet(0, bytes(128), 128))
    wait_for_transfer_boundary(
        cursor,
        bytes((ACK,)),
        "empty batch ACK, post-import file command prompt, and keyboard ready",
        require_post_import_prompt=True,
    )


def receive_stdio_file(process: BNSStdioProcess, file_path: Path) -> None:
    """Receive one host file through the firmware's file-menu YMODEM path."""
    serial1_cursor = len(process.serial[1])
    serial0_cursor = len(process.serial[0])
    process.send_keyboard(chord=T_CHORD)
    accepted = False
    ready = False

    def reached_transfer_prompt(event: dict[str, object]) -> bool:
        nonlocal accepted, ready
        if event.get("device") == "keyboard":
            if event.get("state") == "accepted" and event.get("chord") == T_CHORD:
                accepted = True
            elif event.get("state") == "ready":
                ready = True
        asci1_probe = bytes(process.serial[1][serial1_cursor:]).endswith(bytes((0x05,)))
        return accepted and ready and asci1_probe

    process.wait_for(
        reached_transfer_prompt,
        "T-chord acceptance, transfer prompt ready, and ASCI1 disk-drive ENQ",
        timeout=60,
    )
    process.send_serial(1, bytes((NAK,)))

    process.wait_for(
        lambda _event: bytes(process.serial[0][serial0_cursor:]).endswith(
            bytes((0x05,))
        ),
        "ASCI0 disk-drive ENQ",
        timeout=60,
    )
    serial0_cursor = len(process.serial[0])
    process.send_serial(0, bytes((NAK,)))

    send_stdio_chord(process, R_KEY)
    send_stdio_chord(process, Y_KEY, wait_ready=False)
    transfer_stdio_ymodem(process, serial0_cursor, file_path)


def execute_selected_stdio_program(
    process: BNSStdioProcess,
    expected_cbar: int,
    speech_marker: tuple[str, ...] | None,
    *,
    require_return_key: bool = False,
) -> dict[str, object]:
    """Execute the selected program and prove entry, speech, and optional return."""
    process.arm_pc_watch(0x1000, timeout=60)
    process.send_keyboard(chord=X_CHORD)
    entry = process.wait_for_pc_watch(0x1000, timeout=60)
    if entry.get("cbar") != expected_cbar:
        raise RuntimeError(
            f"external program entered with CBAR {entry.get('cbar'):02X}; "
            f"expected {expected_cbar:02X}"
        )
    if speech_marker is not None:
        process.wait_for_speech_suffix(
            speech_marker,
            "external program speech",
            timeout=60,
        )
    if require_return_key:
        if speech_marker is None:
            raise ValueError("return-key proof requires an expected speech marker")
        send_stdio_chord(process, E_CHORD)
    return entry
