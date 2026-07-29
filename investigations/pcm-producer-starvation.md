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
| Exact ROM SPBUF lead measurement | SPBUF writes can arm exact stepping | The valid startup message had 57 SPBUF writes; the first preceded capture by 1,469,173 cycles, while the last preceded it by only 374 cycles | Delayed capture after a native chunk | Arm on the first SPBUF write, then step through the exact boundary |
| First dynamic-arm implementation | Every SPBUF write can arm capture | The exact callback log still had a 25.83-second audio span and 216 internal silent callbacks; 75 post-capture SPBUF writes began 2,630 cycles after capture and left the arm true | Simple arm-on-any-SPBUF-write state | Pre-capture text construction must be distinguished from post-capture translation |
| SPBUF writer-PC split | Pre- and post-capture phases have distinct writers | Pre-capture writes came from `78C4`, `78C7`, `78E0`, `78E4`, `78EB`, `78FA`, `790B`, `7A6C`, `BC5F`, `BF2B`, `BFB1`, and `BFBC`; post-capture writes came from `3CFC`, `9869`, `9D97`, `A184`, `A189`, and `A2D6`, with no overlap | Writer identity as a possible exact phase discriminator | Summarize each writer's offsets, values, and temporal position before choosing an arming predicate |
| Per-utterance precursor test | The write at `capture_addr - 0x11` is a repeatable early precursor | Rejected: `BC5F` occurred only before startup and did not precede the next four captures | ROM-relative precursor | Use the exact SPBUF-start write instead |
| Exact SPBUF-start lead | A bounded native chunk can expose the exact buffer-start write before capture | Five real captures (`initialize...`, `Braille...ready`, `help`, `1`, `page`) had first-SPBUF-write leads of 5,783, 5,505, 571, 424, and 755 cycles; the post-capture translation writes started above SPBUF, never at its exact address | Unbounded 12,288-cycle observation and broad 256-byte arming range | Observe in 256-cycle native chunks and arm only on the exact physical SPBUF address |
| Exact-command callback log after narrow arming | The bounded exact-address observer removes producer starvation | Enqueue span fell from 26.12 to 3.37 seconds, callback span fell from 25.83 to 3.14 seconds, and internal silent callbacks fell from 216 to 1 | English-observer producer starvation | Keep the bounded observer slice; isolate the one remaining callback |
| Remaining callback location | One phoneme gap remains | The sole internal silent callback was at 0.592 seconds, after a callback played only the ten accumulated one-frame control samples and before the first 2,301-frame speech enqueue at 0.629 seconds | Phoneme starvation | No phoneme PCM is separated by silence; the remaining raw gap is initial priming releasing on control samples |
| Initial priming fallback | One-frame control samples should not start the short-utterance timeout | After the fallback timer was deferred until a chunk longer than one frame, the exact-command log retained all 2.983 seconds of PCM in a continuous 2.956-second callback span with zero internal silent callbacks | Current fallback counts callbacks before real PCM exists | Keep the deferred fallback |

## Current Best Theory

The exact-address observer fixes the English-path producer starvation, and
deferring the player's bounded short-utterance fallback until substantive PCM
exists fixes the pre-speech control-sample release. The exact command now has
zero internal silent callbacks across its complete startup phrase.

## Open Questions

- Physical listening remains the audible oracle; callback continuity cannot
  assess the PCM backend's independently diagnosed lack of pitch inflection.

## Next Action

Commit the deferred-fallback slice after its 350-passed, 8-skipped full suite,
passing Ruff gate, clean CRLF-aware diff audit, and zero-gap exact-command log.
Then request the user's physical listening result.
