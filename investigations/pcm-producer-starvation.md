# Investigation: PCM producer starvation

## Facts (verified)

- The Windows BS2 startup run took 49.37 wall seconds for the full
  100,000,000-cycle startup phrase.
- The PortAudio callback ran approximately every 93 ms without status errors.
- Callback output contained 65,771 queued PCM frames (2.98 seconds at
  22,050 Hz) and 1,015,573 inserted-silence frames (46.06 seconds).
- The last callback containing queued PCM occurred at wall time 21.224 seconds.
  The stream closed at wall time 49.366 seconds.
- The first queued chunks in the captured run were one frame each. The player
  waited through four callback blocks before releasing those two frames.
- Removing callback re-priming alone was previously rejected after listening
  produced no audible improvement; that code change was reverted.
- Native bulk execution for BS2 was previously rejected after listening was
  inconsistent and still unacceptably slow; that code change was reverted.

## Theories (plausible)

1. Emulator execution between SSI-263 writes is slower than real time. This
   predicts enqueue intervals that directly account for the long phrase even
   before callback re-priming delay is considered.
2. AudioPlayer's 400 ms re-priming after every dry callback dominates the
   audible gaps. This predicts regular groups of four silent callbacks between
   an enqueue and delivery even when producer enqueue intervals are short.
3. PCM synthesis generates pathological one-frame chunks for ordinary spoken
   phonemes. This predicts that enqueue sizes, rather than enqueue intervals,
   account for the missing audible duration.

## Tests Run

| Test | Hypothesis | Result | Rules Out | Supports |
|------|------------|--------|-----------|----------|
| Live `--audio-log` BS2 capture | Callback/device failure | Regular callback cadence, no status errors, 46.06 seconds of player-inserted silence | Irregular PortAudio callback cadence and PCM stretching | Producer-side starvation |

## Current Best Theory

Not yet determined. The existing CSV must be reduced into per-enqueue intervals,
chunk sizes, and enqueue-to-delivery latency before changing code.

## Open Questions

- How much wall time lies between ordinary phoneme enqueues?
- Which enqueued chunks are real speech and which are one-frame control/reset
  artifacts?
- Does the emulator spend the gaps executing, sleeping, or waiting for the
  player reservoir?

## Next Action

Analyze the retained CSV per enqueue and callback delivery, then instrument the
SSI-263 write/emulator boundary only if the CSV cannot distinguish the theories.
