# Task: Add Interrupt Tracing CLI Tool

## Context

QNS is a Braille 'N Speak emulator. The firmware uses interrupt-driven speech:
- SSI-263 chip triggers INT1 when ready for next phoneme
- Keyboard triggers INT2 on keypress
- Currently only pause phonemes (0x00) are output, suggesting interrupts aren't working

We need tooling to understand what's happening with interrupts before attempting a fix.

## Objective

Add `--trace-interrupts` CLI option to `qns/bns.py` that logs:
- When `cpu.set_irq(line, state)` is called (which line, what state)
- Timestamp/cycle count when interrupt occurs
- Any interrupt-related I/O (ITC register reads/writes at port 0x34)

## Files to Read
- `qns/bns.py` - main emulator, has existing trace options as pattern
- `qns/cpu.py` - Z180 wrapper, has `set_irq()` method
- `qns/io.py` - I/O handlers, keyboard already uses irq callback

## Files to Modify
- `qns/bns.py` - add --trace-interrupts option and logging

## Implementation Notes

1. Add `--trace-interrupts` argparse flag
2. Wrap `cpu.set_irq()` calls to log when invoked
3. Log ITC register I/O (port 0x34) if trace enabled
4. Follow existing trace option patterns (--trace-io, --trace-writes)

ITC register bits (for reference):
- Bit 0: INT0 enable
- Bit 1: INT1 enable
- Bit 2: INT2 enable

## Test Command
```bash
uv run python -m qns.bns --trace-interrupts --cycles 100000 roms/NFB99/BSPENG/bspeng.bns 2>&1 | head -50
```

## Output
Write findings/status to `./reports/interrupt-tracing-tool-report.md`

## CRITICAL: File Modified Error Workaround

If Edit/Write fails with "file unexpectedly modified":
1. Read the file again with Read tool
2. Retry the Edit
3. Try path formats: `./relative`, `C:/forward/slashes`, `C:\back\slashes`
4. NEVER use cat, sed, echo - always Read/Edit/Write
5. If all formats fail, STOP and report - do not use bash workarounds

## CRITICAL: Parallel Swarm Awareness

You may be running alongside other agents in parallel.
- NEVER use git restore, git checkout, git reset, git clean
- If you mess up a file beyond repair: STOP, write what happened to your report, exit
- Do NOT try to "fix" or "clean up"
