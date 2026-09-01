# Viewing self-calibration products on macOS and in CARTA

Set the run directory once in the Terminal used for viewing:

```bash
cd /path/to/eovsa-selfcal-modern
RUN_DIR="$PWD/runs/<event-id-and-timestamp>"
```

## Quick PNG review with Preview

Open the three per-SPW montages in order:

```bash
open "$RUN_DIR/qa/round_00/images/all_spws.png"
open "$RUN_DIR/qa/round_01/images/all_spws.png"
open "$RUN_DIR/qa/round_02/images/all_spws.png"
```

Open gain-table QA:

```bash
open "$RUN_DIR/qa/round_01/gains_phase.png"
open "$RUN_DIR/qa/round_01/gains_amplitude.png"
open "$RUN_DIR/qa/round_01/gain_summary.csv"
```

For phase-only self-cal, amplitude points should remain at 1.0. An empty
antenna panel is acceptable only when that antenna was deliberately excluded
or had no valid solution and the reason is documented.

Open visibility-domain diagnostics:

```bash
open "$RUN_DIR/qa/visibility_input"
```

The directory contains amplitude/phase versus frequency by antenna, amplitude
versus UV distance, phase versus time, baseline-class amplitudes,
flags/weights, and `visibility_samples.csv`.

Open tutorial-style summaries:

```bash
open "$RUN_DIR/qa/tutorial_imaging/dynamic_spectrum_before.png"
open "$RUN_DIR/qa/tutorial_imaging/dynamic_spectrum_after.png"
open "$RUN_DIR/qa/tutorial_imaging/tutorial_summary_before_10_to_12.png"
open "$RUN_DIR/qa/tutorial_imaging/tutorial_summary_after_10_to_12.png"
```

## Open FITS in CARTA

Start CARTA:

```bash
open -a CARTA
```

Then:

1. Choose **File → Open**.
2. Browse to `$RUN_DIR/qa/round_00/images/`.
3. Open a representative FITS such as `spw_18.fits`.
4. Repeat for `round_01/images/spw_18.fits` and
   `round_02/images/spw_18.fits`.
5. Use spatial matching so the same helioprojective position is compared.
6. Apply the same percentile or manual clip limits to all three images. Do not
   judge improvement using unrelated autoscaling.
7. Inspect centroid, compactness, detached features, negative bowls, and
   sidelobes.
8. Use the same region for peak, integrated-flux, and off-source RMS statistics.

Recommended worked-event SPWs are 5, 12, 18, 24, and 30. SPWs 3–4 are useful
as a low-frequency warning case but should not drive acceptance alone.

## Inspect masks in CARTA

1. Open the corresponding `spw_XX.fits` image.
2. Open the exported mask FITS as a second image when present.
3. Apply spatial matching (`XY`).
4. Display the mask with a two-level colormap or contour at 0.5.
5. Confirm it contains connected source emission and excludes sidelobes/noise.

The authoritative editable masks remain CASA image directories under
`$RUN_DIR/masks/`. Return to the guided workflow and redraw them there rather
than editing post-solve products in CARTA.

## Before/after SunCASA FITS

Open a matching pair from `$RUN_DIR/qa/tutorial_imaging/`, such as:

```text
before_flare_mfs_10_to_12.fits
after_flare_mfs_10_to_12.fits
```

Match `XY` and color limits. These are shallow dirty-map diagnostics; diagonal
stripes and negative bowls are not additional flare sources. The per-SPW round
images are the primary image-quality evidence.
