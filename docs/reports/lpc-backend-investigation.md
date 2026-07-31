# The LPC speech backend: what was built, what broke, what is still open

Companion to `speech-pipeline-investigation.md`, which covers the two
blockers that had to fall before any of this was audible. This report covers
making `--audio` selectable and adding a third voice, and it records the
wrong turns as carefully as the right ones - four of the five theories in
here were refuted, and each was refuted by a measurement that is cheap to
repeat and expensive to reinvent.

## Status

`--audio pcm|lpc|formant` works. `lpc` is a live backend, not a script.

By ear, on the greeting, **`pcm` is still the most accurate voice**. `lpc` is
smoother across phoneme boundaries but loses stop consonants. The idea that
looks most likely to beat both is in `tools/lpc_track_experiment.py` and is
not wired to `--audio`.

## What the three backends are

| backend | timbre | continuity | real time |
|---|---|---|---|
| `pcm` | the chip's own, exactly | 62 isolated recordings, so an edge at every boundary | 12.8M cycles/s |
| `lpc` | the chip's, resynthesized | one continuous gliding filter | 13.5M cycles/s |
| `formant` | SC-01 - a different chip | continuous by construction | 8.3M cycles/s |

All three exceed the corrected 6.144M phi cycles/s real-time need. Measured
over 50M cycles with `--input none`.

Each backend produces modeled candidate audio. The SSI-263 owns completion
timing and passes the actual elapsed emulated time to `end_phoneme`. Queued
output is then truncated or zero-padded to that span. This also applies to
pauses and to phonemes ended early by supersession or interruption.

The by-ear findings below are observations from listening trials. Automated
tests enforce samples, callback delivery, and timing; they do not establish
that output is audible or subjectively fluent on a live sound device.

## Theories that were wrong

Recorded because each cost real time, and because the pattern is the point:
every one of them was plausible from reading the code, and every one died to
a five-line measurement.

**"The pure-Python filter loop will be too slow for real time."** It runs at
0.03x real time - about 8 ms of work per 110 ms phoneme. No scipy, no
vectorising, no new dependency. The instinct that a per-sample Python loop
cannot be real time is usually right and was wrong here, because the loop
only runs while the chip is actually speaking and the CPU sleeps between
phonemes.

**"Boundary discontinuity will show up as a sample-to-sample step."** It does
not. The captures fade to near zero at both ends, so their joins are
*value*-continuous; measuring `np.diff` at the joins showed pcm no worse than
lpc and would have hidden the real defect entirely. Choppiness here is an
amplitude-envelope phenomenon, not a click. Measure short-window RMS.

**"The analysis window misses the stop burst."** `analyse_phoneme` takes the
middle half of each capture, and a stop is a closure followed by a burst, so
this looked obvious. Quarter-by-quarter RMS refuted it - P is `1.00 0.78
0.90 0.41`, energy spread across the whole capture. The window was fine.

**"Gliding the filter across boundaries will reduce choppiness."** Refuted by
ear: choppiness *increased* with glide length. Filter gliding cannot fix an
amplitude hole, and blending two spectra while the level is dipping appears
to add its own artifact. See the envelope finding below.

The one theory that survived: **a stop's transient cannot be represented by
one stationary frame.** LPC replaced a 41 ms burst with stationary noise at
the same average level - RMS preserved, peak gone, which is exactly "it ate
the /p/".

| stop | pcm peak | lpc peak |
|---|---|---|
| B | 0.294 | 0.097 |
| D | 0.361 | 0.051 |
| P | 0.278 | 0.047 |
| T | 0.265 | 0.034 |
| K | 0.244 | 0.021 |

P and K do not improve even when the residual is played in captured order,
because the periodicity test classifies them as *voiced* and hands them a
pitch-pulse train. Three separate mechanisms - the voicing test, the pulse
template, and the random noise draw - all mishandle stops.

## Defects found and fixed

**Truncated pulse tails.** A glottal period at 60 Hz is over 350 samples
against a 110-sample synthesis frame, so a pulse starting near the end of a
phoneme ran past the buffer and was discarded. Pitch *phase* was carried
across phonemes but pulse *energy* was not. This cost amplitude at every
join, leaving the new backend measurably worse than the captures it replaced
- 30% of normal level at joins against pcm's 37%. Carrying the tail takes it
to 61%. Regression test in `tests/test_lpc_backend.py`.

**Pause candidate length was mistaken for elapsed time.** Pause has no capture,
so its modeled candidate is silence. The SSI-263 now decides how much of that
candidate enters the queue when the pause ends. A pause superseded at the same
cycle contributes no samples; one that persists contributes silence for its
elapsed cycle span. This replaced the earlier behavior that either invented a
full modeled pause or returned an accidental one-sample placeholder.

**Pause was treated as an utterance boundary.** The greeting carries 88 pause
events around its 28 phonemes. LPC now stages pause state without resetting the
stream. The end lifecycle commits only the elapsed silent span, preserving
continuity when the pause has no elapsed time.

That last pair is why `--audio lpc` sounded worse than the same trace
rendered offline, and it went unnoticed because
`tools/render_backend.py` dropped pause events by default. **A preview that
omits 76% of the event stream is not a preview.** It now keeps them and uses
adjacent trace timestamps to preserve timing and gaps. It remains an offline
renderer: it does not exercise the live sound callback or prove audible
behavior.

## The finding that matters most, and is not addressed

The captures were recorded as isolated utterances, so each one fades in and
out. Across all 62:

- last 10% vs middle: median **0.34**, below 0.6 in **82%** of captures
- first 10% vs middle: median **0.57**, below 0.6 in **58%** of captures

Concatenating them modulates the amplitude at the phoneme rate. **That is the
choppiness**, in `pcm` and in `lpc` alike, and no amount of filter gliding
touches it. The real SSI-263 does not fade out between phonemes in connected
speech, so compensating this is restoring the chip's behaviour rather than
inventing one.

A per-phoneme gain compensation was tried and moved the envelope-flatness
metric only 0.38 -> 0.44. Not obviously audible. The untried alternative is
to overlap neighbouring phonemes so one's decay is filled by the next's
onset - a different mechanism, not a tuning of this one.

## The unfinished idea: time-varying LPC

`tools/lpc_track_experiment.py`, runnable, not wired to `--audio`.

Analyse each capture frame by frame rather than as one steady frame, and
inverse-filter it through its own time-varying filter. The residual that
falls out is exact - running it back through the same filter reconstructs the
capture sample for sample. The voice is then the capture's, bursts included,
and the only deliberate deviation is the boundary glide.

It deletes the voicing test, the pulse templates and the noise generator
outright, which is where all three stop failures live.

Measured:

- **stop bursts match `pcm` exactly** - 0.294 / 0.361 / 0.278 / 0.265 / 0.244
  for B D P T K, identical to three decimal places
- reconstruction error against the raw capture, glide off: S `0.00000`,
  AH `0.067`, P `0.082`, K `0.159` relative RMS

S being exact confirms the method. The non-zero cases are **frame
time-scaling misalignment when a phoneme's length is not a whole number of
frames** - arithmetic, not model error, and the first thing to fix.

Listener verdict so far: with a short glide it is indistinguishable from
`pcm`, which is the expected result and confirms fidelity; with longer glides
it gets choppier, consistent with the envelope finding above.

Not measured: throughput. It does more per-phoneme filtering than the shipped
model, so it needs checking against the 6.144M phi cycles/s budget before it
could ship.

## Recommended next steps

1. Fix the frame alignment in the track experiment so reconstruction is exact
   for every phoneme, then measure its throughput.
2. Attack the capture envelopes, which is the actual choppiness, most likely
   by overlapping neighbours rather than per-phoneme gain compensation.
3. Only then revisit the boundary glide - on current evidence it is a
   liability, not an asset, and the track model may not need it at all.
4. Unrelated to voice quality: command responses are gappier than the
   greeting because delivering a chord still needs the per-instruction path.
   Moving `keyboard_wait_pc` onto z-core's native PC watch should close it.

## Reproducing any of this

```bash
# Trace the greeting
uv run -m qns.bns --cycles 60000000 --input none --no-realtime \
    --trace-speech greeting.csv roms/bspeng.bns

# Render it offline with a backend candidate generator (keeps trace gaps)
uv run tools/render_backend.py greeting.csv out/lpc.wav --backend lpc

# The unfinished time-varying model, with its numbers
uv run tools/lpc_track_experiment.py greeting.csv out/track.wav --measure
```
