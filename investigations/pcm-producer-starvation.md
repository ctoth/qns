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
- The user's actual command includes `--speech-stream english`. That installs
  `english_callback`, which still forces the direct core through Python
  instruction stepping for the entire run.
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
4. Writes that build SPBUF precede every English capture boundary by enough
   cycles to arm exact instruction stepping only for the short preparation and
   capture window. This predicts a positive, repeatable lead on the supplied
   BS2 ROM and state.
5. No QNS-local precursor can preserve the exact `HL`/`BC`/MMU capture
   contract. This predicts that the pinned z-core needs a new stop/snapshot API
   before English streaming can use native execution.

## Tests Run

| Test | Hypothesis | Result | Rules Out | Supports |
|------|------------|--------|-----------|----------|
| Live `--audio-log` BS2 capture | Callback/device failure | Regular callback cadence, no status errors, 46.06 seconds of player-inserted silence | Irregular PortAudio callback cadence and PCM stretching | Producer-side starvation |
| `analyze_pcm_log.py` reduction | Emulator gaps vs re-priming vs bad chunks | 30 speech chunks were normal 35-108 ms PCM; enqueue gaps left 17.83 seconds uncovered, typically about 0.54 seconds per spoken phoneme | Pathological one-frame speech generation; re-priming as the sole cause | Emulator execution is much slower than the SSI-263 audio timeline |
| Combined red regressions | Coupled native-execution and player-state failure | Idle BS2 required stepping; post-start underrun re-entered priming and requested no run-ahead; native flash programming already passed | Either prior fix being sufficient by itself | Both production changes are required together |
| Real Windows combined run | Surviving combined theory | 100,000,002 cycles and 84 phonemes completed in 8.85 seconds; all events queued within 0.75 seconds; 2.983 seconds of PCM occupied a continuous 2.970-second callback span with zero internal silent callbacks | Remaining phoneme-scale silence in the callback output | Combined fix removes measured producer starvation and inserted gaps |
| Exact-command audit | English streaming is still on the fast path | `_requires_instruction_steps()` returns true whenever `english_callback` is installed | The previous live run as proof for the user's command | The user's exact command still takes the slow producer path |

## Current Best Theory

Incomplete for the user's exact command. The combined fix works when no
instruction-boundary observer is active, but `--speech-stream english` keeps
the producer on the slow path. QNS must preserve exact pre-translation English
capture while limiting stepping to the smallest causally required window.

## Open Questions

- How many cycles separate the first SPBUF write from the English capture
  boundary on the supplied BS2 ROM and state?
- Does every observed capture have a preceding SPBUF-write arm?

## Next Action

Measure SPBUF-write-to-capture ordering on the supplied BS2 ROM and `flash.bin`
without saving either state surface. Use the result to choose between dynamic
stepping and an explicitly authorized z-core API change.
