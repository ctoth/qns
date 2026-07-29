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
| `analyze_pcm_log.py` reduction | Emulator gaps vs re-priming vs bad chunks | 30 speech chunks were normal 35-108 ms PCM; enqueue gaps left 17.83 seconds uncovered, typically about 0.54 seconds per spoken phoneme | Pathological one-frame speech generation; re-priming as the sole cause | Emulator execution is much slower than the SSI-263 audio timeline |

## Current Best Theory

The Windows direct core is forced through Python instruction stepping for this
BS2 profile, making ordinary SSI-263 events arrive about six times slower than
their PCM duration. AudioPlayer re-primes after every resulting underrun, so a
native-execution fix alone can still suffer a new 400 ms hold whenever a small
timing miss drains the queue. The two previously rejected changes addressed
these coupled causes separately; the evidence predicts that both are required
together.

## Open Questions

- Does the emulator spend the gaps executing, sleeping, or waiting for the
  player reservoir?
- Does combining safe native execution with continuous post-start playback keep
  the producer ahead of callbacks on the real Windows run?

## Next Action

Inspect the two reverted slices and current instruction-step authorities, then
write a regression for their combined requirement before changing production
code.
