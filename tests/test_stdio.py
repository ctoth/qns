"""Authorities for the structured standard-I/O event protocol."""

import base64
import json
from io import StringIO

import pytest
from hypothesis import given
from hypothesis import strategies as st

from qns.stdio import (
    JSONLOutput,
    KeyboardInput,
    SerialInput,
    WatchPCInput,
    parse_input_event,
)


@pytest.mark.parametrize(
    ("line", "expected"),
    (
        ('{"device":"keyboard","text":"Of"}', KeyboardInput("Of")),
        ('{"device":"keyboard","chord":74}', KeyboardInput(0x4A)),
        ('{"device":"cpu","watch_pc":4096}', WatchPCInput(0x1000)),
    ),
)
def test_keyboard_events_preserve_text_and_raw_chords(line, expected):
    assert parse_input_event(line) == expected


@given(
    channel=st.integers(min_value=0, max_value=1),
    data=st.binary(),
)
def test_serial_events_preserve_arbitrary_binary_data(channel: int, data: bytes):
    line = json.dumps(
        {
            "device": f"serial{channel}",
            "data": base64.b64encode(data).decode("ascii"),
        }
    )

    assert parse_input_event(line) == SerialInput(channel=channel, data=data)


@pytest.mark.parametrize(
    ("line", "message"),
    (
        ("[]", "JSON object"),
        ('{"device":"keyboard"}', "exactly one"),
        ('{"device":"keyboard","text":"a","chord":1}', "exactly one"),
        ('{"device":"keyboard","chord":256}', "0 through 255"),
        ('{"device":"serial0","data":"%%%"}', "valid base64"),
        ('{"device":"serial2","data":""}', "device must be"),
        ('{"device":"cpu","watch_pc":65536}', "logical address"),
    ),
)
def test_input_events_reject_ambiguous_or_invalid_values(line: str, message: str):
    with pytest.raises(ValueError, match=message):
        parse_input_event(line)


def test_output_events_are_compact_and_flushed_immediately():
    class FlushCountingStream(StringIO):
        def __init__(self):
            super().__init__()
            self.flush_count = 0

        def flush(self):
            self.flush_count += 1
            super().flush()

    stream = FlushCountingStream()
    output = JSONLOutput(stream)

    output.emit("speech", code=1, name="E", ipa="i:", example="MEET")
    output.emit_serial(0, b"\x00\xff")

    assert stream.getvalue().splitlines() == [
        '{"device":"speech","code":1,"name":"E","ipa":"i:","example":"MEET"}',
        '{"device":"serial0","data":"AP8="}',
    ]
    assert stream.flush_count == 2
