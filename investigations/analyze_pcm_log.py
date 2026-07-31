"""Reduce a QNS --audio-log CSV into producer-gap timing evidence."""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path

SAMPLE_RATE = 22_050


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    args = parser.parse_args()

    with args.log.open(newline="", encoding="utf-8") as log_file:
        rows = list(csv.DictReader(log_file))

    enqueues = [
        (float(row["wall_seconds"]), int(row["frames"]))
        for row in rows
        if row["event"] == "enqueue"
    ]
    callbacks = [row for row in rows if row["event"] == "callback"]
    non_pause = [(wall, frames) for wall, frames in enqueues if frames > 1]
    audio_callback_indexes = [
        index for index, row in enumerate(callbacks) if int(row["audio_frames"]) > 0
    ]

    gaps = [
        current_wall - previous_wall
        for (previous_wall, _), (current_wall, _) in zip(enqueues, enqueues[1:])
    ]
    uncovered = [
        current_wall - previous_wall - previous_frames / SAMPLE_RATE
        for (previous_wall, previous_frames), (current_wall, _) in zip(
            enqueues,
            enqueues[1:],
        )
    ]
    silent_callbacks = sum(int(row["audio_frames"]) == 0 for row in callbacks)
    first_audio_index = audio_callback_indexes[0]
    last_audio_index = audio_callback_indexes[-1]
    first_audio_wall = float(callbacks[first_audio_index]["wall_seconds"])
    last_audio_wall = float(callbacks[last_audio_index]["wall_seconds"])
    internal_silent_callbacks = sum(
        int(row["audio_frames"]) == 0 for row in callbacks[first_audio_index : last_audio_index + 1]
    )

    print(f"enqueues: {len(enqueues)}")
    print(f"one-frame enqueues: {sum(frames == 1 for _, frames in enqueues)}")
    print(f"speech enqueues: {len(non_pause)}")
    print(f"queued seconds: {sum(frames for _, frames in enqueues) / SAMPLE_RATE:.6f}")
    print(f"enqueue span: {enqueues[-1][0] - enqueues[0][0]:.6f}")
    print(f"median enqueue gap: {statistics.median(gaps):.6f}")
    print(f"maximum enqueue gap: {max(gaps):.6f}")
    print(f"positive uncovered time: {sum(max(0.0, gap) for gap in uncovered):.6f}")
    print(f"silent callbacks: {silent_callbacks}/{len(callbacks)}")
    print(f"audio callback span: {last_audio_wall - first_audio_wall:.6f}")
    print(f"internal silent callbacks: {internal_silent_callbacks}")
    print()
    print("index wall_seconds gap_seconds frames playable_seconds uncovered_seconds")
    for index, (wall, frames) in enumerate(enqueues):
        if index == 0:
            gap = 0.0
            deficit = 0.0
        else:
            previous_wall, previous_frames = enqueues[index - 1]
            gap = wall - previous_wall
            deficit = gap - previous_frames / SAMPLE_RATE
        print(
            f"{index:>5} {wall:>12.6f} {gap:>11.6f} {frames:>6} "
            f"{frames / SAMPLE_RATE:>16.6f} {deficit:>17.6f}"
        )


if __name__ == "__main__":
    main()
