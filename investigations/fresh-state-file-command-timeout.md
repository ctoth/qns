# Investigation: fresh-state file-command timeout

## Facts (verified)

- The same marker-gated command timed out twice before program import while
  waiting 60 seconds for `FILE_COMMAND_PROMPT`.
- Both failures emitted the speech tail
  `N T ER W AH E OU ER EH N I N I SCH AE1 L AH E1 Z F L AE SCH S I S T EH M EH N T ER W AH E OU ER EH N`.
- Both failures left the emulator running and reported no BNS event during the
  final approximately 59 seconds.
- The generated external program was not imported or launched in either failed
  run, so neither failure tests the Phase 3 program.

## Theories (plausible)

1. Fresh nonvolatile-state initialization requires an input acknowledgement
   that the verifier does not send before waiting for `FILE_COMMAND_PROMPT`.
2. The verifier waits for the wrong speech boundary after fresh-state
   initialization, even though the firmware is ready for the next input.
3. The emulator or firmware stalls during fresh nonvolatile-state
   initialization and cannot accept the file workflow input.

## Tests Run

| Test | Hypothesis | Result | Rules Out | Supports |
|---|---|---|---|---|
| Exact marker-gated rerun with a fresh state path | A transient startup race caused the first timeout | The second run timed out at the identical speech tail before import | A one-off transient startup failure | A deterministic initialization workflow defect |
| Focused event-order regression test | `ready` can arrive before the complete prompt and the helper returns early | The current helper failed before observing the delayed prompt because it uses a separate caller-owned send and `wait_for_keyboard` sequence | A wrong prompt constant as the cause of this failure | Split ownership and separate event waits permit the observed race |
| Real fresh-state run with PC watch sent before I-chord | The command-loop watch can be armed before power-on input | The child exited immediately with `power-on input requires a keyboard JSONL event` | A watch request as the first input event | The keyboard chord must be first, while subsequent output events still need one retained state machine |
| Real fresh-state run after first-event correction | One retained startup predicate completes fresh initialization | Firmware reached `Enter file command` and the `send or receive` transfer prompt | A remaining fresh-state initialization defect | The same unmatched-event loss recurs later when serial waits precede a separate keyboard-ready wait |
| Real run after pre-transfer boundary correction | Retaining T acceptance, ready, and ASCI1 ENQ advances YMODEM | Firmware spoke `transfer complete` and `Enter file command`, then timed out on the separate post-import ready wait | A serial or YMODEM transfer failure | The speech wait consumed post-import ready before the exact prompt suffix completed |
| Real run with joined post-import speech/ready wait after YMODEM | Joining speech and ready after `transfer_stdio_ymodem` retains the needed ready event | The same timeout and completed-transfer prompt recurred | A post-YMODEM join as early enough | The final serial-ACK wait inside YMODEM consumes ready before returning |
| Real run with ready retained only during final empty-batch wait | The ready event occurs during the final ACK/prompt phase | Final ACK and prompt completed but the predicate never observed ready | Final-phase-only ready retention | Ready is emitted during an earlier YMODEM serial phase, likely after Y-chord, and must survive the whole transfer |
| Real run with ready retained across every YMODEM phase | One transfer-wide ready state survives independent serial boundaries | The command imported 306 bytes, hit `PC=1000`/`CBAR=21`, observed program speech, and accepted E-chord after exit | Remaining initialization or transfer defects | The unmatched-event consumption model explains every observed timeout and the fix addresses the root cause |

## Current Best Theory

Resolved. The JSONL client consumes unmatched events, so workflow code that
split causally related keyboard, speech, CPU-watch, and serial authorities
across independent waits lost early events. The corrected startup and transfer
boundaries retain their required event state across the complete causal phase.
The real fresh-state run imported and executed the generated program and
accepted a firmware key after exit.

## Open Questions

- None for this investigation.

## Next Action

None. The complete program phoneme sequence is now the repeatable Phase 3 gate,
and the documented clean rebuild passed that gate.
