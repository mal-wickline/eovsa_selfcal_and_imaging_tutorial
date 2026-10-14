# Live EOVSA self-calibration tutorial — 2026-10-14

This is a short live demonstration using Mallory's MS and the accepted
Meiqi-comparison event configuration. It shows how to draw masks in `iclean`,
run two self-calibration rounds, and inspect the candidate products before
accepting either round.

The command creates and modifies only a new, time-selected `short_peak.ms`
inside a timestamped run directory. It does **not** modify the original
full-duration MS, and this demonstration does not run `apply-full`.

## Parameters used

| Setting | Value |
|---|---|
| Input MS | `/Users/mallorywickline/20260904_1915/IDB20260904_1904-1923XXYY.ms` |
| Solution interval in the data | `2026/09/04/19:14:48~2026/09/04/19:15:12` (24 s) |
| Gain solution interval | `solint='inf'` over that 24 s interval, independently for each SPW |
| Correlation | `XX` |
| Solve SPWs | `0~35` |
| Model selection | Each SPW uses itself (`neighbor_half_width=0`) |
| Imaging and solve baselines | `>500lambda` |
| Original-MS antenna selection | CASA IDs `0,2~5,7~10,12&` |
| Physical EOVSA antennas retained | `1, 3, 4, 5, 6, 8, 9, 10, 11, 13` |
| Reference antenna | original CASA ID `0` / EOVSA antenna 1 |
| Minimum baselines per antenna | `3` |
| Mask groups shown by `iclean` | `0~2`, `3~5`, `6~12`, `13~20`, `21~30`, `31~40` |
| Round 1 | `ap`, 100 model-image iterations |
| Round 2 | `p`, 100 model-image iterations |
| QA imaging after each round | 500 iterations, gain 0.1 |

The last mask group includes SPWs 36–40 as adjacent imaging context, but only
SPWs 0–35 receive gain solutions.

## Build the JSON for a different event (no Codex required)

Do not copy the scientific selections from this C6.7 event into another
event. The JSON is a record of measurements and choices made from the new
Measurement Set. Start from the supplied schema instead of writing it from
scratch:

```bash
cd /path/to/eovsa_selfcal_and_imaging_tutorial
source .venv/bin/activate

cp config/2024-05-14-x8.8.example.json config/my-event.json
CONFIG="$PWD/config/my-event.json"
open -e "$CONFIG"
```

Replace at least these event-dependent values:

| JSON field | How to determine it |
|---|---|
| `event_id` | Choose a short, unique event name. |
| `input_ms` | Use the absolute path to the calibrated EOVSA Measurement Set. |
| `timerange` | Choose a short, bright, structurally stable interval from the event spectrum. |
| `xycen_arcsec` | Measure the flare center in helioprojective Solar-X/Y arcseconds from the full-disk radio image and AIA/JHelioviewer. |
| `phasecenter` | Generate it from `xycen_arcsec` with `derive_phasecenter.py`; do not calculate it by hand. |
| `antenna`, `refant`, `antenna_by_spw` | Use the MS antenna mapping, flag fractions, visibility QA, and EOVSA observing log. These are zero-based CASA IDs, not one-based physical EOVSA labels. |
| `selfcal_spws` | Include only SPWs in which the source is identifiable and can be modeled reliably. |
| `mask_spw_groups` | Group adjacent SPWs with similar morphology; never cross an `antenna_by_spw` boundary. |
| `mask_browser_spw_by_group` | Choose one clean representative SPW on which to draw the spatial mask for each group. |
| `qa_spws` | Choose the SPWs that should be imaged in the QA montage; these do not control which SPWs are solved. |

### 1. Choose the flare interval

Enter an approximate interval in `timerange`, then make the dynamic spectrum:

```bash
python scripts/event_overview.py "$CONFIG" --spectrogram-only
```

Update `timerange` so it covers a bright compact feature without substantial
source evolution. A longer interval provides more data, but it is unsuitable
if the source morphology changes during that interval.

### 2. Locate the source and derive the phase center

Image a contiguous frequency band near the spectral peak. Replace `4~8GHz`
with the band appropriate for the event:

```bash
python scripts/event_overview.py "$CONFIG" \
  --full-disk-only \
  --full-disk-frequency "4~8GHz"
```

Compare the radio source with AIA/JHelioviewer and write its Solar-X/Y location
to the JSON, for example:

```json
"xycen_arcsec": [-747.0, 123.0]
```

Then use the SunCASA environment to derive and write the corresponding CASA
phase center:

```bash
python scripts/derive_phasecenter.py "$CONFIG"
```

### 3. Select antennas from the data

Return to the primary project environment and inspect the MS:

```bash
source .venv/bin/activate
python scripts/preflight.py "$CONFIG"
```

The preflight report gives the SPW frequencies, available correlations, CASA
antenna ID-to-name mapping, and flag fraction for each antenna. After entering
a candidate antenna selection, make the read-only visibility diagnostics:

```bash
python scripts/visibility_qa.py "$CONFIG" qa/visibility_input
open qa/visibility_input
```

Retain antennas with usable coverage and plausible visibility behavior. Choose
a reliable retained antenna as `refant`. Do not infer CASA IDs from the EOVSA
hardware numbers.

### 4. Select solve SPWs and mask groups

For the first survey, let `qa_spws` cover all SPWs present in the MS, then run:

```bash
python scripts/selfcal.py survey "$CONFIG"

RUN_DIR="$(ls -td "$PWD"/runs/* | head -1)"
open "$RUN_DIR/qa/round_00/images/all_spws.png"
```

Use the montage to set:

- `selfcal_spws` to SPWs with a recognizable, modelable source;
- `mask_spw_groups` to adjacent bands with similar morphology;
- `mask_browser_spw_by_group` to one clean representative SPW per group;
- `qa_spws` to the bands that should appear in subsequent QA montages;
- `spw_min` and `spw_max` to the solve-range limits.

Use `neighbor_half_width=0` when every target SPW should use its own model.
Keep the compact-source baseline selection identical for model imaging and
gain solving; this workflow uses `uvrange=">500lambda"`.

### 5. Validate before self-calibration

```bash
python -m json.tool "$CONFIG" >/dev/null
python scripts/preflight.py "$CONFIG"
python scripts/selfcal.py survey "$CONFIG"
```

Review the preflight report and survey again. Only then begin the guided run:

```bash
python scripts/selfcal.py run "$CONFIG"
```

The template supplies the schema and normal imaging defaults. The spectrum,
full-disk localization, preflight report, visibility diagnostics, and SPW
survey supply the event-specific values.

## Terminal 1 — launch the guided run and `iclean`

Paste this entire block:

```bash
cd "/Users/mallorywickline/Library/Mobile Documents/com~apple~CloudDocs/Downloads/eovsa-selfcal-modern"
source .venv/bin/activate

CONFIG="$PWD/config/2026-09-04-c6.7-meiqi-ap.json"

python scripts/selfcal.py run "$CONFIG" 2>&1 \
  | tee "selfcal_live_tutorial_20261014.log"
```

Do not omit the word `run`. The correct CLI is:

```text
python scripts/selfcal.py run CONFIG.json
```

The workflow creates a new run and then opens one `iclean` browser session for
each mask group. Terminal 1 waits while the browser is open.

## Draw each mask in the browser

Repeat this for all six browser sessions:

1. Select **Lasso Mask** (the loop-shaped tool below Pan).
2. Draw one closed region around the connected bright source, with a small
   buffer. Do not include detached bright patches or broad sidelobes.
3. Click **Mask Add** or press `a`.
4. In the `iclean` parameter panel, use:

   | Browser field | Value |
   |---|---:|
   | `nmajor` | `-1` |
   | `niter` | `1000` |
   | `threshold` | `0.0` |
   | `nsigma` | `0.0` |
   | `gain` | `0.05` |
   | `cycleniter` | `-1` |
   | `cyclefactor` | `1.0` |

   These values control the interactive CLEAN preview used to assess and save
   the mask. The browser's `niter=1000` is **not** the answer to the later
   Terminal prompt for `p` or `ap` model-image iterations.
5. Click the **single circular-arrow** button once and inspect the result.
6. Revise with **Mask Add** or **Mask Sub** if needed.
7. Click the **red stop** button and confirm exit. This saves the mask and
   advances to the next SPW group.

The groups appear in this order:

```text
0~2  →  3~5  →  6~12  →  13~20  →  21~30  →  31~40
```

After the sixth browser closes, the script makes the masked round-0 images and
then asks for the first solve.

At each Terminal solve prompt, enter **100** model-image iterations. Do not use
1000 for either the `ap` round or the `p` round; that deconvolves the gain-solve
model too deeply. In short: `iclean` browser `niter=1000`, but Terminal
model-image iterations `=100`.

## Terminal 2 — prepare the QA viewer

Open a second Terminal window after Terminal 1 has printed its new run path.
Paste:

```bash
cd "/Users/mallorywickline/Library/Mobile Documents/com~apple~CloudDocs/Downloads/eovsa-selfcal-modern"

# Select the newest run made by the live tutorial.
RUN_DIR="$(ls -td "$PWD"/runs/2026-09-04-c6.7-meiqi-ap-* | head -1)"
echo "$RUN_DIR"

qa_round () {
  ROUND=$(printf "%02d" "$1")
  QA="$RUN_DIR/qa/round_${ROUND}"

  open "$QA/images/selected_spws.png"
  open "$QA/images/all_spws.png"
  open "$QA/gains_phase.png"
  open "$QA/gains_amplitude.png"
  open "$QA/gain_summary.csv"
  open "$QA/gain_coverage.json"
}
```

Verify that `echo "$RUN_DIR"` shows the run just created in Terminal 1, not an
older run.

## Round 1

When Terminal 1 asks:

```text
Solve this round as phase (p), amplitude (a), or both (ap)?
```

enter:

```text
ap
```

At:

```text
Model-image iterations (for example 100):
```

enter:

```text
100
```

Wait until Terminal 1 prints the round-1 QA directory and pauses at the
accept/reject prompt. Then, in Terminal 2, run:

```bash
qa_round 1
```

Check:

- `selected_spws.png` and `all_spws.png`: the source should improve or remain
  stable without a centroid jump or new fragmentation.
- `gains_phase.png`: solutions should be reasonably smooth across neighboring
  SPWs, allowing normal phase wrapping.
- `gains_amplitude.png`: because this is an `ap` round, amplitudes must be
  finite and physically plausible rather than extreme.
- `gain_coverage.json`: `solved_spws` should contain 0–35 and `missing_spws`
  should be empty.
- `gain_summary.csv`: investigate missing antennas, flagged solutions, or
  outliers before accepting.

To accept round 1 and proceed, return to Terminal 1 and enter:

```text
c
```

At the mask-update prompt enter:

```text
n
```

This reuses the same masks for round 2.

## Round 2

At the next solve prompt enter:

```text
p
```

At the iteration prompt enter:

```text
100
```

When Terminal 1 reaches the round-2 accept/reject prompt, inspect the products
from Terminal 2:

```bash
qa_round 2
```

For this phase-only round, `gains_amplitude.png` should remain at amplitude
1.0. Recheck morphology, phase behavior, gain coverage, and the summary CSV.

If round 2 is good, return to Terminal 1 and enter:

```text
a
```

`a` accepts the round and finishes. The script writes:

```text
$RUN_DIR/final/short_peak.selfcal.ms
```

## Prompt cheat sheet

```text
Round 1 solve:             ap
Round 1 model iterations: 100
Round 1 decision:          c    # accept and continue
Update masks:              n
Round 2 solve:             p
Round 2 model iterations: 100
Round 2 decision:          a    # accept and finish
```

At either candidate prompt, enter `r` instead if the images or gain solutions
are not acceptable. Rejection restores the saved pre-candidate flags and any
previously accepted tables on the run-owned short MS.

## What the workflow is doing physically

The mask tells CLEAN where real compact solar emission is allowed. CLEAN builds
a per-SPW source model using only baselines longer than 500 wavelengths.
`gaincal` then solves antenna gains against that same compact-source baseline
selection for the full 24-second flare interval. Round 1 corrects both
amplitude and phase; round 2 refines phase while preserving the round-1
amplitude scale. Every candidate is applied only to the short copied MS before
its QA products are generated.

