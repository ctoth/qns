# SSI-263 reverse-engineering record

## Objective

Recover the SSI-263/SC-02 internal phoneme parameters, or enough equivalent
structure to implement register-driven software synthesis without substituting
an SC-01 parameter ROM or treating fixed PCM captures as a hardware oracle.

## Phase 1: available evidence inventory

Tasks:

1. Identify local primary chip documentation.
2. Identify local die imagery that could expose a parameter array.
3. Separate genuine SSI-263 reference audio from generated or differently
   sourced audio.
4. Record what the inventory can and cannot establish before interpretation.

Evidence:

- `datasheet_pages/page_00.png` through `page_07.png` are the local SSI-263
  datasheet page images. The prior visual review established the register
  formulas and the corrected 64-entry phoneme table from these pages.
- The only local JPEG candidates outside generated phoneme directories are
  `aicom/2018-12-18 23.32.27.jpg` (5,108,641 bytes),
  `aicom/2018-12-18 23.32.31.jpg` (4,442,901 bytes), and
  `aicom/2018-12-18 23.32.45.jpg` (4,140,415 bytes). Direct visual inspection
  shows that all three are photographs of the front, back, and angled views of
  a populated Ai Squared/AI Communication board. They show packaged ICs and
  PCB traces, not a decapsulated SSI-263 die, an exposed mask ROM, or readable
  internal parameter structures.
- `phoneme_dumps/` contains overlapping old-name and corrected-name WAV files
  for the same numeric codes. These are generated/reference outputs, not
  independent proof of internal parameters.
- `phoneme_test/` contains five generated category samples. It is not a chip
  characterization corpus.
- `aicom/demo*.mp3`, disk images, and `.DVC` files may contain product-level
  speech/software evidence, but none can command arbitrary SSI-263 registers
  or reveal the parameter ROM merely by existing.
- The tracked AppleWin-derived `qns/synth/phonemes.py` bank is credited SSI-263
  PCM at one undocumented operating point. It is a useful approximate backend
  and comparison reference, but it does not identify articulation, rate,
  inflection, filter-frequency, or per-phoneme target parameters.

Phase review:

1. The local SSI-263 datasheet page images are the primary chip documentation.
2. None of the inventoried local image candidates is die imagery, so this
   inventory exposes no parameter array to decode.
3. The AppleWin-derived PCM is genuine SSI-263 reference audio only at an
   undocumented fixed operating point; the other WAVs are generated outputs,
   not independent hardware evidence.
4. The available evidence establishes the external register contract and an
   approximate fixed-sample reference. It cannot establish the internal
   phoneme parameter ROM or a register-driven synthesis model.

Phase 1 is complete. The next task is a bounded check for the previously
referenced Visual6502 SSI-263 die assets at their exact likely local locations.
If those assets are absent, the missing die imagery or equivalent chip
characterization is an external evidence blocker for exact parameter recovery.

## Phase 2: die-image classification

Tasks:

1. Locate the previously referenced SSI-263 die imagery.
2. Classify the annotated overview and suspected-ROM crop visually.
3. Determine whether the image resolution and structure support bit extraction.
4. Record the exact next extraction target, or the evidence blocker.

Evidence:

- `C:\Users\Q\Temp\qns-ssi263-review` does not exist.
- `C:\Users\Q\AppData\Local\Temp\qns-ssi263-review` exists and contains:
  - `SSI_263P_20x_1a_7000w.jpg` (25,913,769 bytes)
  - `SSI_263P_20x_1a_map_7000w.png` (998,186 bytes)
  - `suspected-rom.png` (6,240,400 bytes)
  - `crop_center_zoom.png` (2,445,818 bytes)
  - `crop_left_zoom.png` (2,393,985 bytes)

The filenames and dimensions establish that the previously referenced assets
are present, but filenames alone do not establish that the crop is a ROM or
that individual stored bits are readable. The next task is direct visual
classification of the annotated overview and `suspected-rom.png`.

Visual classification:

- `SSI_263P_20x_1a_map_7000w.png` is not an annotated circuit map. It is an
  unlabeled color segmentation of die regions. It supplies no block names,
  signal labels, coordinates, or independently checkable identification of a
  phoneme ROM.
- `suspected-rom.png` is a detailed die crop containing a large rectangular,
  highly regular circuit array. Repeated vertical cells and horizontal control
  structures are clearly resolved, so it is a plausible ROM, PLA, or related
  control array rather than random logic.
- This first view does not yet show which visual feature, if any, represents a
  stored zero or one. Regular metal routing can resemble a mask-ROM matrix, so
  calling it the phoneme parameter ROM or extracting bits now would exceed the
  evidence.

The next task is to compare the raw die photograph and the two supplied zoom
crops against this array, looking for consistent per-cell presence/absence
features and its physical row/column extent.

Raw/zoom comparison:

- The raw 7000-pixel die photograph places the candidate array in the lower
  central portion of the die. It has regular circuitry on all four sides and
  is not an image-processing artifact introduced by `suspected-rom.png`.
- `crop_center_zoom.png` and `crop_left_zoom.png` resolve repeated vertical
  columns with fixed row positions. At those positions, elongated
  contact-like structures are present in some cells and absent in others.
  Their presence pattern varies from column to column while the cell pitch
  remains regular.
- The consistent presence/absence variation is a potentially bit-readable
  physical encoding. The image quality therefore does not itself block an
  extraction attempt.
- The images still do not establish array orientation, logical row/column
  grouping, bit polarity, address order, or whether this array stores phoneme
  parameters rather than microcode or another control function.

The next task is to measure the full candidate grid and test whether its
physical dimensions have a defensible relationship to the documented 64
phoneme addresses and SSI-263 parameter fields. No logical values will be
assigned before that structural check.

Grid-pitch measurement:

- `tools/measure_ssi263_array.py` reads the crop through ImageMagick and uses
  NumPy edge-profile autocorrelation. It does not classify or assign bits.
- On the visually bounded regular region (`x=0..1329`, `y=350..1269`), the
  horizontal profile has a 19-pixel fundamental with strong peaks at 38, 56,
  75, and 94 pixels. The one-pixel deviations are consistent with image
  perspective or resampling across the crop.
- The vertical profile has a 13-pixel fundamental with repeated peaks at 27,
  40, 54, and 67 pixels.
- The candidate cell lattice is therefore approximately 19 pixels horizontally
  by 13 pixels vertically. The visible array extent is compatible with roughly
  64 cells on each axis, but that count is not yet established because the
  measurement crop includes peripheral structures and partial cells.

The next task is to locate the first and last complete lattice lines on both
axes and count intervals. A confirmed 64-cell axis would support, but would not
alone prove, a relationship to the 64 documented phoneme addresses.

Primary-source check:

- The Visual6502 SSI-263P die-shot page confirms that the image is a surface
  die photograph assembled from 203 microscope images and offers the
  7000-by-5803 image plus SSI-263 documentation.
- That page does not publish an SSI-263 block map, polygon/vector model,
  transistor netlist, ROM extraction, or labels identifying this candidate
  array. The local color map and `suspected-rom.png` are therefore derived
  working artifacts, not primary-source annotations.
- No published block identity is available to replace the required structural
  and connectivity checks. The next task remains exact local lattice-boundary
  measurement.

Fractional lattice fit and overlay:

- Fractional fitting gives a horizontal pitch of 18.7725 pixels and a stable
  repeated-feature origin at 13.2923 pixels within the measurement crop.
- The dominant coarse vertical spacing is 40.25 pixels with origin 4.25 pixels
  within the measurement crop. This is approximately three times the finer
  13-to-13.5-pixel circuit pitch and follows recurring contact bands.
- An overlay of these fitted lines visually tracks the repeated physical
  features across the crop. The measured pitches are therefore real array
  geometry rather than an autocorrelation artifact.
- `suspected-rom.png` cuts through the regular vertical-strip structure at both
  horizontal image edges. Counting fitted lines in that derived crop would not
  establish the full physical word width. The upper and lower portions also
  contain peripheral structures, so coarse green-line count alone is not a
  logical bit count.

The next task is to locate the derived crop within the complete 7000-by-5803
die image and remeasure through the actual left, right, top, and bottom array
boundaries.

Rejected localization method:

- ImageMagick normalized subimage search between the full 7000-by-5803 JPEG and
  `suspected-rom.png` ran for more than one minute without producing an offset.
- The derived crop is contrast/processing-different enough, or the search is
  computationally large enough, that full-resolution exhaustive matching is
  not a proportionate localization method here.
- The exact `magick.exe` comparison process was identified and stopped; it
  changed no project or evidence files.

The next task remains localization, using a bounded source crop selected from
the clearly visible candidate-array coordinates in the complete die image.

Source localization:

- A bounded source crop at original-die coordinates
  `x=1900..4099`, `y=2800..4399` contains the complete candidate array and
  visible peripheral circuitry on all four sides.
- Within that 2200-by-1600 crop, the repeated vertical matrix spans
  approximately `x=490..1710`, `y=280..1020`. The regular horizontal structures
  below approximately `y=1020` are physically separate peripheral rows and
  must not be included in the matrix count.
- Both horizontal edges of the matrix are visible in this source crop, unlike
  `suspected-rom.png`.

The next task is to fit and overlay the lattice only within these complete
matrix boundaries, then count the aligned vertical strips and recurring
programmed-feature rows.

Complete horizontal count:

- A wider source overlay (`x=300..1899`, `y=3050..3849` in original-die
  coordinates) exposes the left and right transitions between decoder wiring
  and the repeated matrix.
- The fitted red lattice line at local `x=188.4` is the first complete repeated
  vertical strip and the line at local `x=1446.0` is the last. These are fitted
  indices 10 through 77 inclusive: **68 physical vertical strips**.
- The count is not 64. It therefore does not, by itself, identify the strips as
  the documented phoneme-address dimension. Four strips may have a different
  role, or the address and parameter axes may be oriented differently; either
  is still only a hypothesis.

The next task is to count the physically programmed row structures and compare
the resulting 68-by-N organization with the SSI-263 programming documentation.

Programming-guide provenance:

- No local file matches the SSI-263A Programming Guide; only the datasheet and
  derived reports are present in the repository.
- The Visual6502 page's exact guide link is
  `../263P/SSI_263A_Programming_Guide.pdf`, resolving under the primary
  Visual6502 domain.
- The site's TLS certificate is currently expired/untrusted, so the link was
  extracted from the already verified exact page with certificate checking
  disabled. No alternate mirror or guessed filename is being substituted.

The next task is to retrieve this exact primary guide into the existing
temporary SSI-263 review directory, render its pages, and inspect only the
sections that can constrain the physical array organization.

Programming-guide findings:

- The exact five-page guide was retrieved at 1,543,965 bytes with SHA-256
  `1AABDADE78793A50C9A8489CAD74D3EAC83BB6BE5BD5FDF80DB3D663E15BA9A4` and read
  from rendered page images.
- Page 1 states that the SSI-263A phonetic alphabet contains 64 symbols: 34
  basic American-English sounds and 30 allophone/no-sound symbols.
- Page 2 states that there are no duplicate resident sounds.
- Page 3 calls duration, inflection, amplitude, articulation, slope, rate,
  pitch extension/range, and filter frequency the eight programmable
  parameters. Pages 4 and 5 show that these are host register assignments and
  nominal host-programmed values, not disclosed internal per-phoneme synthesis
  coefficients.
- The guide therefore confirms exactly 64 externally addressable resident
  sound codes, but it does not disclose internal formant/noise targets, ROM
  word width, bit polarity, or array organization.
- The measured 68 physical strips cannot all be selected by the six-bit
  phoneme address. At least four strips must be non-address, dummy, test,
  reference, or otherwise differently purposed if this axis is the address
  axis. That role remains unproven.

The next task is to inspect the primary datasheet block/functional diagrams for
named internal stores or signal groupings that could identify the candidate
array and constrain its other axis.

Datasheet functional findings:

- Page 1's internal block diagram explicitly names a **Phoneme Characteristics
  ROM**. It feeds transition controllers; separate blocks handle inflection
  ramping, phoneme timing, closure-ramp timing, clock/speech timing, and host
  registers.
- Page 2 states that the vocal tract is five cascaded programmable low-pass
  filter sections controlled by a digital controller. Phoneme selection causes
  a linear transition to new vocal-tract resonator filter settings, excitation
  source type, and source amplitude.
- Page 3 separately states that every phoneme has a preset amplitude.
- These primary statements establish that an internal multi-field phoneme ROM
  exists and must supply substantially more than the six-bit phoneme code.
- The datasheet does not state the ROM word width, physical organization,
  coefficient quantization, bit order, polarity, or location. The measured
  68-strip array is structurally compatible with a wide characteristics ROM,
  but the block diagram alone cannot prove that physical identity.

The next task is to locate a primary SSI/Votrax patent or design disclosure
that names the internal characteristic fields or ROM organization, then use it
to test the 68-strip hypothesis and the unresolved physical row count.

Primary patent lead:

- US Patent 4,829,573, *Speech synthesizer*, was filed by Votrax inventors
  Richard T. Gagnon and Duane W. Houck and assigned to Votrax International.
- Its abstract describes a phonetically driven speech synthesizer embodied
  substantially entirely in a programmed microprocessor, with control
  parameters for each phoneme stored in a selectable phoneme parameter matrix.
- The patent description states that matrix parameters include constants that
  define vocal-tract resonant-filter poles and parameters for vocal/fricative
  interaction between successive phonemes.
- This is a primary Votrax design disclosure and may provide either the actual
  software-equivalent coefficient table or enough field definitions to decode
  the SSI-263 characteristics ROM. It is not yet established that its parameter
  matrix is identical to the SSI-263's mask ROM.

The next task is to inspect this patent's figures, detailed description, and
any source/table appendices for explicit field widths and per-phoneme values.

US 4,829,573 findings and boundary:

- The disclosed working embodiment is a later Votrax software synthesizer with
  an **eighth-order time-domain lattice filter**, not the SSI-263's five
  cascaded switched-capacitor low-pass sections.
- Its per-phoneme matrix has 17 named parameters: `K1` through `K8`, vocal
  amplitude/delay (`VA`, `VD`), fricative amplitude/delay (`FA`, `FD`), stop
  amplitude/delay (`ST`, `SD`), transition rate (`TR`), time (`TI`), and pitch
  modification (`PI`).
- The patent says its microfiche appendix frame 24 contains a complete
  hexadecimal parameter table for 63 selectable phonemes. That appendix is not
  present in the accessible Google patent text.
- Those values could support a distinct later Votrax software voice, but they
  are not evidence of SSI-263 mask-ROM contents and must not be substituted for
  them.
- The patent's background directly identifies US 3,836,717 as the six-bit
  phoneme-addressed ROM-matrix design with resonant vocal-tract filters, and US
  3,908,085 as the improvement using series-connected tunable filters driven by
  duty-cycle control signals. Those are architecturally closer to the SSI-263.

The next task is to inspect US 3,836,717 and US 3,908,085 for the ROM output
fields, word width, and filter-control encoding that can be tested against the
68-strip die array.

Early-patent architecture findings:

- US 3,836,717 uses six phoneme-address bits and a ROM matrix with 32 parallel
  output bits distributed into ten ladder/control groups.
- US 3,908,085 retains the six-bit phoneme address but adds two timing-address
  signals. For each parameter output, those timing phases select four stored
  bits in binary-weighted 8/4/2/1 time order, directly generating a four-bit
  duty-cycle value.
- US 3,908,085 explicitly states that two ROM units provide eight parameter
  outputs each: **16 parameters times four bits = 64 stored bits per phoneme**.
  It also states that a fully parallel alternative would generate all 64 bits
  simultaneously.
- The patented vocal tract uses series-connected tunable filters and variable
  duty-cycle control signals, making it architecturally close to the SSI-263
  datasheet's cascaded programmable filters and transition controls.

Structural inference to test:

- The measured 68 vertical strips are consistent with 64 phoneme-address
  columns plus four edge/dummy/reference strips.
- The 40.25-pixel vertical supercell repeats approximately 16 times across the
  programmed region. If each supercell contains the patented four binary rows,
  the matrix is 16 parameters by four bits = 64 data rows.
- Together, these dimensions are a strong physical match for a 64-phoneme by
  64-parameter-bit ROM. This remains an inference until individual row
  features, the exact boundaries, and field routing are verified.

The next task is to inspect the US 3,908,085 figures directly to enumerate the
16 parameter outputs, determine the two eight-output banks and their physical
ordering, and then compare those signals with the SSI-263 datasheet blocks.

US 3,908,085 figure findings:

- The primary patent PDF was verified at 1,093,002 bytes with SHA-256
  `C23C412E4979CD617A8E94ADDDC786A0237D3B7D238BAEDAD41DC4CC0846A413` and its
  drawing pages were read directly.
- Figure 1 labels ROM bank 12's eight long-transition outputs as `F1`, `F2`,
  `F3`, nasal closure, nasal frequency, fricative frequency, fricative
  low-pass, and transition rate.
- Figure 1 labels ROM bank 14's eight short-transition/control outputs as
  timing, vocal amplitude, vocal delay, vocal spectral contour, closure,
  `F2Q` (the second-formant bandwidth/Q control), fricative amplitude, and
  closure delay.
- Figure 2 shows a vocal oscillator/noise source feeding a five-section series
  vocal tract (`F1` through `F5`) plus a closure gate, with the ROM-derived
  controls applied to filter, amplitude, spectral-contour, nasal, fricative,
  and closure blocks.
- Figure 3 directly shows the six weighted phoneme-address inputs and the MSB/
  LSB timing inputs entering a ROM decoder/matrix and producing eight serialized
  outputs. The timing waveforms select the four binary bits in 8/4/2/1 order.

These figures make the 16-by-4 logical ROM organization primary-source fact
for the patented architecture. The next task is to verify that the die's 16
physical supercells each contain four distinct programmable rows, then extract
raw presence/absence bits without yet assigning field or address order.

Physical organization confirmation:

- Overlaying quarter divisions inside the fitted 40.25-pixel vertical
  supercells shows four distinct, consistently aligned cell sites per
  supercell. The subdivisions track repeated transistor/contact geometry rather
  than arbitrary locations.
- Seventeen supercell boundaries bracket 16 complete programmed groups. At
  four rows per group, the vertical matrix contains **64 physical data rows**.
- The full candidate matrix is therefore physically consistent with the patent
  organization: 64 phoneme-address columns by 64 data bits, arranged as 16
  four-bit parameters, plus four horizontal edge/dummy/reference strips.
- This confirms the array dimensions and makes the candidate identification as
  the phoneme characteristics ROM high-confidence. It does not yet determine
  which cell appearance is zero or one, the address direction/order, the
  parameter-bank order, or whether the SSI-263 retained every 1975 field name.

The next task is high-detail inspection of a small set of aligned cells to
identify the repeated presence/absence feature, then define a raw physical bit
extraction that preserves unknown polarity and logical ordering.

Measurement-tool checkpoint:

- `tools/measure_ssi263_array.py` passed scoped Ruff and was committed alone as
  `ce2ceaa` (`Measure SSI-263 die array geometry`).
- High-detail matched raw/overlay crops show column-varying elongated loop or
  contact structures aligned to the four-row grid. They are the likely
  programmed feature, but their span crosses more than one thin visual row and
  their exact logical sampling point is not yet established.

The next extraction slice must therefore preserve raw physical classifications
and confidence scores. It must not silently collapse ambiguous cells or assume
that a visible loop is logical one rather than zero.

First raw-classification result:

- `tools/extract_ssi263_rom.py` samples the measured 68-by-64 physical grid,
  clusters each of the four row phases independently, and writes arbitrary
  visual class IDs plus per-cell confidence. It explicitly marks the classes
  as non-logical.
- The first run classified rare/background counts by row phase as 83/1005,
  83/1005, 25/1063, and 17/1071. Median confidence was 0.57 to 0.68.
- Direct inspection of the eight class centers shows that the rare classes are
  the large elongated loop/contact structures and the common classes are the
  surrounding repeated cell background.
- Only 208 of 4,352 sampled cells contain the rare structure. Treating those as
  either logical polarity would yield implausibly sparse or dense four-bit
  parameter words across 16 parameters. This classification is therefore **not
  accepted as a ROM-bit extraction**.
- The large loops are likely routing/tap structures, or the logical bit site is
  smaller/differently registered within the physical cell. No logical values
  have been assigned from this output.

The next task is to determine whether Visual6502 exposes the original
17265-by-14313 stitched image rather than the 7000-pixel reduction. Higher
resolution may resolve the actual programmed implant/contact feature that the
current classifier cannot separate.

Full-resolution availability check:

- The primary Visual6502 page links only
  `SSI_263P_20x_1a_1600w.jpg`, `SSI_263P_20x_1a_7000w.jpg`, and the 7000-pixel
  stitch map. It does not link the stated 17265-by-14313 original stitch or a
  delayered/substrate image.
- Exact-name and exact-dimension web searches found no independently published
  original-resolution SSI-263 image.
- The local 7000-pixel file is therefore the highest-resolution exposed surface
  image currently identified. More classifier tuning cannot be treated as a
  substitute for a physically unresolved programming feature.

The next task is one bounded Internet Archive inventory of the exact
Visual6502 `images/263P/` directory. If no larger or delayered asset was ever
captured there, optical extraction from available imagery is externally
blocked unless the program feature can be proven visible in the 7000-pixel
surface image.

Archive inventory result:

- The Internet Archive CDX inventory for the exact Visual6502
  `images/263P/` prefix contains the 1600-pixel and 7000-pixel surface JPEGs,
  the 7000-pixel stitch map, package photographs, and the three published PDF
  documents.
- It contains no original 17265-by-14313 stitch, no higher-resolution ROM crop,
  and no delayered, substrate, diffusion, implant, or vectorized SSI-263 image.
- The missing evidence is therefore not merely an unlinked current-page asset
  preserved in that archive.

Exact optical bit recovery is externally blocked by the unavailable original
or delayered physical evidence unless a programmed bit feature can be proven
visible in the reduced surface image. The first raw classifier did not do so.
Its source slice must now be fully reverted before any different implementation
or approximation slice begins.
