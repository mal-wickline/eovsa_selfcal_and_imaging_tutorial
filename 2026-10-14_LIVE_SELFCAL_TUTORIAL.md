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
| Round 1 | `ap`, 1000 model-image iterations |
| Round 2 | `p`, 1000 model-image iterations |
| QA imaging after each round | 500 iterations, gain 0.1 |

The last mask group includes SPWs 36–40 as adjacent imaging context, but only
SPWs 0–35 receive gain solutions.

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
4. Set `niter=100`, `cycleniter=25`, and `gain=0.05` for the mask-assessment
   cycle. Leave `nmajor=-1`, `threshold=0`, `nsigma=0`, and `cyclefactor=1`.
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
1000
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
1000
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
Round 1 model iterations: 1000
Round 1 decision:          c    # accept and continue
Update masks:              n
Round 2 solve:             p
Round 2 model iterations: 1000
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

