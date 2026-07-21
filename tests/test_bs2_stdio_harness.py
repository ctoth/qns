"""Authorities for reusable real-firmware BS2 stdio workflows."""

import binascii

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from qns.input_driver import ASCII_TO_BNS_KEY
from tools.bs2_stdio_harness import (
    E_CHORD,
    FILE_COMMAND_PROMPT,
    FLASH_INITIALIZATION_PROMPT,
    FLASH_INITIALIZATION_Y_KEY,
    POWER_ON_INITIALIZE_CHORD,
    R_KEY,
    SOH,
    STX,
    T_CHORD,
    X_CHORD,
    Y_KEY,
    crc16_xmodem,
    execute_selected_stdio_program,
    reach_stdio_editor_command_loop,
    receive_stdio_file,
    transfer_stdio_ymodem,
    ymodem_packet,
)


def test_flash_initialization_uses_firmware_brlyes_chord():
    """The English ROM's BRLYES is lowercase y, not uppercase Y."""
    assert FLASH_INITIALIZATION_Y_KEY == ASCII_TO_BNS_KEY[ord("y")]
    assert FLASH_INITIALIZATION_Y_KEY != ASCII_TO_BNS_KEY[ord("Y")]


def test_stdio_initialization_waits_for_prompt_after_keyboard_ready():
    """A ready event before complete prompt speech must not end first boot."""
    outbound = []
    boundaries = []

    class Process:
        speech_names = []

        @staticmethod
        def send_keyboard(*, chord):
            outbound.append(("keyboard", {"chord": chord}))

        @staticmethod
        def send_event(device, **payload):
            outbound.append((device, payload))

        def wait_for(self, predicate, description, **kwargs):
            boundaries.append((description, kwargs))
            if len(boundaries) == 1:
                events = (
                    {
                        "device": "keyboard",
                        "state": "accepted",
                        "chord": POWER_ON_INITIALIZE_CHORD,
                    },
                    {"device": "cpu", "event": "watch-armed", "pc": 0xD657},
                    {"device": "keyboard", "state": "ready"},
                    {"device": "speech"},
                )
                for event in events[:-1]:
                    assert not predicate(event)
                self.speech_names.extend(FLASH_INITIALIZATION_PROMPT)
                assert predicate(events[-1])
                return events[-1]

            events = (
                {
                    "device": "keyboard",
                    "state": "accepted",
                    "chord": FLASH_INITIALIZATION_Y_KEY,
                },
                {"device": "cpu", "event": "pc-watch", "pc": 0xD657},
                {"device": "keyboard", "state": "ready"},
            )
            for event in events[:-1]:
                assert not predicate(event)
            assert predicate(events[-1])
            return events[-1]

    reach_stdio_editor_command_loop(Process())

    assert outbound == [
        ("keyboard", {"chord": POWER_ON_INITIALIZE_CHORD}),
        ("cpu", {"watch_pc": 0xD657}),
        ("keyboard", {"chord": FLASH_INITIALIZATION_Y_KEY}),
    ]
    assert boundaries == [
        ("BS2 initialization prompt or editor command loop", {"timeout": 60}),
        ("BS2 initialization prompt or editor command loop", {"timeout": 60}),
    ]


def test_explicit_speech_marker_requires_post_exit_key_acceptance():
    chords = []
    speech_waits = []
    keyboard_waits = []

    class Process:
        @staticmethod
        def arm_pc_watch(address, **kwargs):
            assert address == 0x1000
            assert kwargs == {"timeout": 60}

        @staticmethod
        def wait_for_pc_watch(address, **kwargs):
            assert address == 0x1000
            assert kwargs == {"timeout": 60}
            return {"cycle": 123, "pc": 0x1000, "cbar": 0x21}

        @staticmethod
        def send_keyboard(*, chord):
            chords.append(chord)

        @staticmethod
        def wait_for_speech_suffix(suffix, description, **kwargs):
            speech_waits.append((suffix, description, kwargs))

        @staticmethod
        def wait_for_keyboard(state, **kwargs):
            keyboard_waits.append((state, kwargs))

    marker = ("D", "UH1", "N")
    entry = execute_selected_stdio_program(
        Process(),
        0x21,
        marker,
        require_return_key=True,
    )

    assert entry == {"cycle": 123, "pc": 0x1000, "cbar": 0x21}
    assert chords == [X_CHORD, E_CHORD]
    assert speech_waits == [(marker, "external program speech", {"timeout": 60})]
    assert keyboard_waits == [
        ("accepted", {"chord": E_CHORD, "timeout": 60}),
        ("ready", {"timeout": 60}),
    ]


def test_receive_stdio_file_uses_real_file_menu_and_ymodem_sequence(
    monkeypatch,
    tmp_path,
):
    file_path = tmp_path / "calsort.msg"
    file_path.write_bytes(b"messages")
    chords = []
    sent = []
    serial_responses = []
    transfers = []
    boundaries = []

    class Process:
        serial = (bytearray(b"zero"), bytearray(b"one"))

        def wait_for(self, predicate, description, **kwargs):
            boundaries.append((description, kwargs))
            if len(boundaries) == 1:
                events = (
                    {"device": "keyboard", "state": "ready"},
                    {"device": "keyboard", "state": "accepted", "chord": T_CHORD},
                    {"device": "serial1"},
                )
                for event in events[:-1]:
                    assert not predicate(event)
                self.serial[1].extend(bytes((0x05,)))
                assert predicate(events[-1])
                return events[-1]

            self.serial[0].extend(bytes((0x05,)))
            event = {"device": "serial0"}
            assert predicate(event)
            return event

        @staticmethod
        def send_keyboard(*, chord):
            sent.append(chord)

        @staticmethod
        def send_serial(channel, data):
            serial_responses.append((channel, data))

    monkeypatch.setattr(
        "tools.bs2_stdio_harness.send_stdio_chord",
        lambda _process, chord, **kwargs: chords.append((chord, kwargs)),
    )
    monkeypatch.setattr(
        "tools.bs2_stdio_harness.transfer_stdio_ymodem",
        lambda active_process, cursor, path: transfers.append(
            (active_process, cursor, path)
        ),
    )
    process = Process()

    receive_stdio_file(process, file_path)

    assert sent == [T_CHORD]
    assert chords == [
        (R_KEY, {}),
        (Y_KEY, {"wait_ready": False}),
    ]
    assert serial_responses == [
        (1, bytes((0x15,))),
        (0, bytes((0x15,))),
    ]
    assert boundaries == [
        (
            "T-chord acceptance, transfer prompt ready, and ASCI1 disk-drive ENQ",
            {"timeout": 60},
        ),
        ("ASCI0 disk-drive ENQ", {"timeout": 60}),
    ]
    assert transfers == [(process, 5, file_path)]


def test_ymodem_final_ack_retains_ready_before_file_command_prompt(tmp_path):
    program = tmp_path / "hello.bns"
    program.write_bytes(b"program")
    boundaries = []

    class Process:
        serial = (bytearray(), bytearray())
        speech_names = []

        @staticmethod
        def wait_for_serial(*_args, **_kwargs):
            raise AssertionError("independent serial wait would discard ready")

        @staticmethod
        def send_serial(_channel, _data):
            pass

        def wait_for(self, predicate, description, **kwargs):
            boundaries.append((description, kwargs))
            suffixes = (
                bytes((0x43,)),
                bytes((0x06, 0x43)),
                bytes((0x06,)),
                bytes((0x06, 0x43)),
                bytes((0x06,)),
            )
            if len(boundaries) == 1:
                ready = {"device": "keyboard", "state": "ready"}
                assert not predicate(ready)
            self.serial[0].extend(suffixes[len(boundaries) - 1])
            serial = {"device": "serial0"}
            if len(boundaries) < 5:
                assert predicate(serial)
                return serial
            assert not predicate(serial)
            self.speech_names.extend(FILE_COMMAND_PROMPT)
            speech = {"device": "speech"}
            assert predicate(speech)
            return speech

    transfer_stdio_ymodem(Process(), 0, program)

    assert boundaries == [
        ("initial YMODEM CRC request", {"timeout": 60}),
        ("header ACK and data CRC request", {"timeout": 60}),
        ("data block 1 ACK", {"timeout": 60}),
        ("EOT ACK and batch CRC request", {"timeout": 60}),
        (
            "empty batch ACK, post-import file command prompt, and keyboard ready",
            {"timeout": 60},
        ),
    ]


@settings(max_examples=100, deadline=None)
@given(data=st.binary(max_size=4096))
def test_crc16_xmodem_matches_standard_library(data: bytes):
    """Harness CRC must match an independent CRC-16/XMODEM implementation."""
    assert crc16_xmodem(data) == binascii.crc_hqx(data, 0)


@settings(max_examples=64, deadline=None)
@given(
    block_number=st.integers(min_value=0, max_value=255),
    block_size=st.sampled_from((128, 1024)),
    data=st.data(),
)
def test_ymodem_packet_has_valid_envelope_and_crc(
    block_number: int,
    block_size: int,
    data: st.DataObject,
):
    """Every generated packet must carry an exact payload and valid CRC."""
    payload = data.draw(st.binary(min_size=block_size, max_size=block_size))

    packet = ymodem_packet(block_number, payload, block_size)

    assert packet[0] == (SOH if block_size == 128 else STX)
    assert packet[1] == block_number
    assert packet[2] == 0xFF - block_number
    assert packet[3:-2] == payload
    assert int.from_bytes(packet[-2:], "big") == binascii.crc_hqx(payload, 0)
    assert len(packet) == block_size + 5


@given(
    payload=st.binary(max_size=64),
    block_size=st.sampled_from((128, 1024)),
)
def test_ymodem_packet_rejects_wrong_payload_size(payload: bytes, block_size: int):
    """Packet construction must reject every non-block-sized payload."""
    with pytest.raises(ValueError, match="expected"):
        ymodem_packet(0, payload, block_size)
