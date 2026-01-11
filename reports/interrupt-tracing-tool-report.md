# Interrupt Tracing Tool Implementation Report

## Task Summary

Added `--trace-interrupts` CLI option to `qns/bns.py` to help debug interrupt-related issues in the BNS emulator.

## Changes Made

### File Modified: `qns/bns.py`

1. **Added `PORT_ITC` constant** (line 28):
   ```python
   PORT_ITC = 0x34
   ```

2. **Added `trace_interrupts` parameter** to `BNS.__init__()`:
   - New parameter: `trace_interrupts: bool = False`
   - Stored as instance variable: `self.trace_interrupts = trace_interrupts`

3. **Added `_make_irq_callback()` method** (lines 97-110):
   - Creates wrapped IRQ callback that logs when `trace_interrupts` is enabled
   - Logs: IRQ line number, state (ASSERT/CLEAR), source name, cycle count
   - Output format: `[IRQ] INT{line} {state} from {source} (cycle ~{cycles})`

4. **Updated keyboard IRQ connection** (line 95):
   - Changed from: `lambda state: self.cpu.set_irq(2, state)`
   - Changed to: `self._make_irq_callback(2, "keyboard")`

5. **Added ITC register tracing** in `_io_read()` and `_io_write()`:
   - Checks if port 0x34 (ITC) is accessed
   - Calls `_log_itc()` to decode and display the value

6. **Added `_log_itc()` method** (lines 155-162):
   - Decodes ITC register bits for INT0/INT1/INT2 enable status
   - Output format: `[ITC] {op} 0x{value:02X} INT0={en} INT1={en} INT2={en} (cycle ~{cycles})`

7. **Added CLI argument** (lines 358-359):
   ```python
   parser.add_argument("--trace-interrupts", action="store_true",
                       help="Log interrupt activity (IRQ lines, ITC register)")
   ```

8. **Passed `trace_interrupts` to BNS constructor** (line 384)

## Testing

### Test 1: CLI Help
```bash
uv run python -m qns.bns --help
```
Output confirms `--trace-interrupts` option is available.

### Test 2: IRQ Callback Tracing
```python
from qns.bns import BNS

bns = BNS(trace_interrupts=True)
bns.load_rom('roms/NFB99/BSPENG/bspeng.bns')

# Simulate keypress
bns.keyboard.press(0x01)
# Output: [IRQ] INT2 ASSERT from keyboard (cycle ~0)

bns.keyboard.keyclr_read(0x20)
# Output: [IRQ] INT2 CLEAR from keyboard (cycle ~0)
```

### Test 3: Full Emulation Run
```bash
uv run python -m qns.bns --trace-interrupts --cycles 100000 roms/NFB99/BSPENG/bspeng.bns
```
Runs successfully. No ITC register I/O observed during boot - this is expected because Z180 internal registers (ports 0x00-0x3F) are handled internally by z180emu and don't go through Python I/O callbacks.

## Important Finding

**ITC register access is not visible through Python I/O callbacks.**

The Z180 internal I/O registers (ports 0x00-0x3F, including ITC at 0x34) are handled internally by the z180emu C library. These accesses do not trigger the Python `io_read`/`io_write` callbacks.

This means:
- IRQ line state changes ARE traced (via the wrapped callback)
- ITC register reads/writes are NOT traced (unless z180emu is modified to expose them)

To trace ITC register access, the z180emu library would need to be modified to provide a callback or logging mechanism for internal I/O.

## Usage

```bash
# Basic interrupt tracing
uv run python -m qns.bns --trace-interrupts roms/NFB99/BSPENG/bspeng.bns

# Combined with other tracing options
uv run python -m qns.bns --trace-interrupts --trace-io --cycles 1000000 roms/NFB99/BSPENG/bspeng.bns

# With limited cycles for quick diagnosis
uv run python -m qns.bns --trace-interrupts --cycles 100000 roms/NFB99/BSPENG/bspeng.bns
```

## Output Format

### IRQ Line Changes
```
[IRQ] INT2 ASSERT from keyboard (cycle ~12345)
[IRQ] INT2 CLEAR from keyboard (cycle ~12400)
```

### ITC Register Access (if visible through external I/O)
```
[ITC] WRITE 0x07 INT0=EN INT1=EN INT2=EN (cycle ~1000)
[ITC] READ 0x07 INT0=EN INT1=EN INT2=EN (cycle ~1050)
```

## Extensibility

The `_make_irq_callback()` pattern can be reused for other interrupt sources. For example, if SSI-263 INT1 support is added:

```python
# Example future use:
self.ssi263.set_irq_callback(self._make_irq_callback(1, "ssi263"))
```

## Status

**COMPLETE** - The `--trace-interrupts` option is implemented and working. IRQ line changes are traced correctly. ITC register access tracing is implemented but will not produce output until z180emu exposes internal I/O callbacks.
