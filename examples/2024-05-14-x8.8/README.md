# 2024-05-14 X8.8 calibration comparison gallery

The folders intentionally preserve two calibration generations:

- [`previous-calibration/`](previous-calibration/) is the accepted baseline
  already shown below.
- [`updated-calibration/`](updated-calibration/) receives only reviewed PNGs
  from the new PI-updated-calibration rerun.

Do not overwrite the baseline files. Keeping both generations lets the group
separate improvement caused by the revised upstream calibration from
improvement caused by each self-cal phase round.

These PNGs are a small review set from the accepted two-round phase-only run.
They are included so the workflow can be reviewed without publishing the raw
IDB files, Measurement Set, CASA images, or gain tables.

- `round_00_all_spws.png`: calibrated input before self-cal.
- `round_01_all_spws.png`: main image improvement after phase round 1.
- `round_02_all_spws.png`: convergence check; little change from round 1.
- `round_01_gains_phase.png` and `round_02_gains_phase.png`: accepted phase
  solutions. Empty panels are antennas deliberately unavailable in this MS.
- `dynamic_spectrum_8s.png`: median positive XX visibility diagnostic for the
  eight-second solve interval. This is not the 15-minute calibrated flare
  spectrum published on the EOVSA wiki.
- `before_after_10_to_12_dirty_diagnostic.png`: same-settings dirty-map QA.
  Diagonal stripes and negative bowls are synthesized-beam sidelobes, not
  additional solar sources or final restored imaging.
- `tutorial_summary_{before,after}_10_to_12.png`: tutorial-style AIA 171
  context with positive 60/75/90 percent radio contours. The similarity is
  expected for a phase-only solve that converged after its first round.
- `qlookplot_all_frequencies_aia171_{before,after}.png`: one tutorial-style
  multi-frequency quicklook figure for each calibration state.
- `multiband_frequency_outlines_aia171_{before,after}.png`: one contour per
  representative frequency (2.9, 3.5, 4.5, 5.1, 6.8, 8.4, 9.7, and 11.6
  GHz) over the same sharp AIA 171 frame.

The solve covered SPWs 3--31 (about 2.87--11.97 GHz). Thus 10--12 GHz is the
highest-frequency in-solve comparison. Products above 12 GHz are context only.

## Image progression

### Round 0: calibrated input before self-cal

![Round 0 SPW montage](previous-calibration/round_00_all_spws.png)

### Round 1: primary phase-only improvement

![Round 1 SPW montage](previous-calibration/round_01_all_spws.png)

### Round 2: convergence check

![Round 2 SPW montage](previous-calibration/round_02_all_spws.png)

## Gain solutions

### Round 1

![Round 1 phase gains](previous-calibration/round_01_gains_phase.png)

### Round 2

![Round 2 phase gains](previous-calibration/round_02_gains_phase.png)

## Spectrum and solar context

![Eight-second XX spectrum](previous-calibration/dynamic_spectrum_8s.png)

![10–12 GHz dirty-map comparison](previous-calibration/before_after_10_to_12_dirty_diagnostic.png)

### Tutorial-style AIA/radio overlay before self-cal

![Tutorial summary before](previous-calibration/tutorial_summary_before_10_to_12.png)

### Tutorial-style AIA/radio overlay after self-cal

![Tutorial summary after](previous-calibration/tutorial_summary_after_10_to_12.png)

### Original-calibration all-frequency quicklook before and after

![Original calibration quicklook before](previous-calibration/qlookplot_all_frequencies_aia171_before.png)

![Original calibration quicklook after](previous-calibration/qlookplot_all_frequencies_aia171_after.png)

### Original-calibration representative-frequency outlines

![Original calibration outlines before](previous-calibration/multiband_frequency_outlines_aia171_before.png)

![Original calibration outlines after](previous-calibration/multiband_frequency_outlines_aia171_after.png)

## Updated-calibration results

The PI-updated calibration rerun passed preflight and two accepted phase-only
self-cal rounds. Its separate gallery is documented in
[`updated-calibration/README.md`](updated-calibration/README.md).
