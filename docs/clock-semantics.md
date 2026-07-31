# HD64180 clock semantics

QNS configures z-core with the HD64180 **phi/system-clock frequency**:
6,144,000 Hz. The 12,288,000 Hz figure associated with the original
Braille 'n Speak board is its crystal input. The HD64180 divides that input
by two to produce phi. Instruction cycle counts and the programmable reload
timer's phi/20 input are therefore converted to seconds using 6.144 MHz.

No z-core timer adjustment is required. z-core already advances the PRT once
per 20 phi cycles, including while `SLP` is active. The defect was QNS passing
and pacing the crystal frequency as though it were phi.

## Live-ROM verdict

`tools/measure_speech_power_timeout.py` boots a BSP ROM, records the last
SSI-263 phoneme at its exact native I/O event cycle, then records the exact
port 80h write where firmware clears the speech-power latch. Both available
firmware links seed the same power timeout value, 100.

| BSP ROM | last phoneme | speech power off | delta cycles | old 12.288 MHz interpretation | corrected 6.144 MHz interpretation |
|---|---:|---:|---:|---:|---:|
| NFB99 English | 36,139,636 | 97,002,369 | 60,862,733 | 4.953021891 s | — |
| 2003 English | 36,121,287 | 97,006,311 | 60,885,024 | 4.954835938 s | — |
| NFB99 English, corrected clock | 19,554,370 | 80,413,029 | 60,858,659 | — | 9.905380697 s |
| 2003 English, corrected clock | 19,535,673 | 80,416,971 | 60,881,298 | — | 9.909065430 s |

The pre-fix integration assertion required `10.0 ± 0.2 s` and failed for
both ROMs at 4.953 and 4.955 seconds. With phi configured at 6.144 MHz, both
links pass at 9.905 and 9.909 seconds. Proprietary ROMs are not committed;
the integration test skips cleanly when they are absent.

Reproduce locally:

```powershell
$env:QNS_ROM_ROOT = 'C:\Users\Q\code\qns\roms'
uv run pytest tests/test_bns.py::test_real_bsp_speech_power_timeout_uses_ten_seconds_of_hardware_time -q
uv run python tools/measure_speech_power_timeout.py "$env:QNS_ROM_ROOT\bspeng.bns"
uv run python tools/measure_speech_power_timeout.py "$env:QNS_ROM_ROOT\bns640\BSPENG.BNS"
```
