# Rerun after the 2024-05-14 calibration update

This procedure creates a second, independent data lineage. It never overwrites
the previously accepted MS, self-cal run, or GitHub gallery.

## 1. Rebuild the calibrated MS on pipeline

The raw scans are unchanged. Rerun them now so `calIDB` and `calibeovsa` read
the PI-updated calibration state. Use a new directory and output name:

```bash
ssh mw478@pipeline
mkdir -p /data1/mw478/selfcal_20240514_updated_cal/msdata
cd /data1/mw478/selfcal_20240514_updated_cal
source /home/user/.setenv_pyenv38
ipython
```

In IPython:

```python
import os
import numpy as np
if not hasattr(np, "float"):
    np.float = float

from eovsapy import flare_spec as fs

raw_idbs = [
    "/nas5/IDB/20240514/IDB20240514163948",
    "/nas5/IDB/20240514/IDB20240514164948",
]
corrected_idbs = fs.calIDB(raw_idbs)

local_idbs = [
    "/data1/mw478/selfcal_20240514_updated_cal/IDB20240514163948",
    "/data1/mw478/selfcal_20240514_updated_cal/IDB20240514164948",
]
for path in local_idbs:
    print(path, os.path.isdir(path))
```

Both checks must be `True`, and the log must say calibration was applied. Exit
and start the maintained SunCASA stack without personal site packages:

```bash
exit
source /home/user/.setenv_pyenv38
cd /data1/mw478/selfcal_20240514_updated_cal
PYTHONNOUSERSITE=1 ipython
```

In IPython:

```python
import os
from suncasa.suncasatasks import importeovsa, calibeovsa

local_idbs = [
    "/data1/mw478/selfcal_20240514_updated_cal/IDB20240514163948",
    "/data1/mw478/selfcal_20240514_updated_cal/IDB20240514164948",
]
outdir = "/data1/mw478/selfcal_20240514_updated_cal/msdata/"

msfiles = importeovsa(
    idbfiles=local_idbs, visprefix=outdir, ncpu=1,
    timebin="0s", width=1, doconcat=False, udb_corr=False,
)
print(*msfiles, sep="\n")

final_ms = os.path.join(
    outdir, "IDB20240514_163948-165948.updated-cal.ms")
result = calibeovsa(msfiles, doconcat=True, concatvis=final_ms)
print(result)
print("Final exists:", os.path.isdir(final_ms), final_ms)
```

`udb_corr=False` is required because `calIDB` already applied that correction.
The installed task does not accept `msoutdir`; the absolute `concatvis` path
is authoritative. Record the eovsapy/SunCASA git revision or package path and
the calibration-processing date in your lab notes and config.

With `doconcat=True`, SunCASA selects each calibrated intermediate
`CORRECTED_DATA` column and writes those values into the final concatenated MS
`DATA` column. It may then print:

```text
Column MODEL_DATA removed
Column CORRECTED_DATA removed
```

These are expected cleanup messages. They do not mean that calibration was
discarded, and the final concatenated MS does not need to retain a separate
`CORRECTED_DATA` column. Verify the final calibrated `DATA` before transfer:

```python
import numpy as np
from casatools import table

tb = table()
tb.open(final_ms)
try:
    columns = tb.colnames()
    nrows = tb.nrows()
    if "DATA" not in columns:
        raise RuntimeError("DATA is absent from the final concatenated MS")
    ncheck = min(nrows, 1000)
    if ncheck == 0:
        raise RuntimeError("Final concatenated MS contains no rows")
    nonzero_usable = 0
    for row in range(ncheck):
        data = np.asarray(tb.getcell("DATA", row))
        flags = np.asarray(tb.getcell("FLAG", row), dtype=bool)
        usable = np.isfinite(data) & ~flags
        nonzero_usable += int(np.count_nonzero(usable & (np.abs(data) > 0)))
finally:
    tb.close()

print("Rows:", nrows)
print("Columns:", columns)
print("CORRECTED_DATA present (not required):", "CORRECTED_DATA" in columns)
print("Nonzero, finite, unflagged samples in first", ncheck, "rows:",
      nonzero_usable)

if nonzero_usable == 0:
    raise RuntimeError("No usable visibility samples found in final DATA")
```

Also inspect the preceding `calibeovsa` log. It must identify the reference
and daily phase-calibration records that were selected or interpolated.
Investigate any message saying that no phase calibration was found or that a
calibration step was skipped or aborted. Column layout alone cannot prove
that every requested calibration product was available.

## 2. Download without touching the old MS

From the Mac:

```bash
mkdir -p ~/20240514_x8_updated_cal/msdata
ssh mw478@pipeline \
  'ls -ld /data1/mw478/selfcal_20240514_updated_cal/msdata/IDB20240514_163948-165948.updated-cal.ms'
rsync -avP \
  mw478@pipeline:/data1/mw478/selfcal_20240514_updated_cal/msdata/IDB20240514_163948-165948.updated-cal.ms \
  ~/20240514_x8_updated_cal/msdata/
du -sh ~/20240514_x8_updated_cal/msdata/IDB20240514_163948-165948.updated-cal.ms
```

Do not use macOS-incompatible `--info=progress2`.

## 3. Create the independent event config

From this repository:

```bash
cp config/2024-05-14-x8.8-updated-cal.example.json \
   config/2024-05-14-x8.8-updated-cal.json
```

Edit `input_ms` and replace the placeholder `calibration_generation`. Do not
assume the old antenna/SPW choices remain valid merely because the date is the
same.

## 4. Repeat the evidence chain

```bash
source .venv/bin/activate
python scripts/preflight.py config/2024-05-14-x8.8-updated-cal.json
python scripts/selfcal.py survey config/2024-05-14-x8.8-updated-cal.json
```

Set `SURVEY_DIR` to the printed directory, then inspect and run visibility QA:

```bash
SURVEY_DIR="/absolute/path/printed/by/the/survey"
open "$SURVEY_DIR/qa/round_00/images/all_spws.png"
python scripts/visibility_qa.py config/2024-05-14-x8.8-updated-cal.json \
  "$SURVEY_DIR/qa/visibility_input"
open "$SURVEY_DIR/qa/visibility_input"
```

Edit SPWs, groups, browser representatives, antennas, and overrides only if
the new evidence requires it. Then run the same mask-and-solve science:

```bash
python scripts/selfcal.py run config/2024-05-14-x8.8-updated-cal.json
```

Use the prior event choices as a starting hypothesis: compact masks for
`3~6`, `7~14`, `15~22`, `23~31`; browser SPWs 5, 12, 18, 24; one assessment
cycle with `niter=100`, `cycleniter=25`, and `gain=0.05`; then phase-only
round 1 with 100 iterations. Run phase-only round 2 with 50 iterations only
if round 1 QA supports continuing. Amplitude self-cal remains optional, never
automatic.

## 5. Compare every generation and round

For the new authoritative `RUN_DIR`:

```bash
open "$RUN_DIR/qa/round_00/images/all_spws.png"
open "$RUN_DIR/qa/round_01/images/all_spws.png"
open "$RUN_DIR/qa/round_01/gains_phase.png"
open "$RUN_DIR/qa/round_01/gains_amplitude.png"
open "$RUN_DIR/qa/round_01/gain_summary.csv"
```

If round 2 exists, open the analogous five products. Compare:

1. old calibration round 0 versus updated calibration round 0;
2. updated round 0 versus updated round 1;
3. updated round 1 versus updated round 2; and
4. old accepted final versus updated accepted final.

This ordering prevents attributing an upstream calibration improvement to
self-calibration.

## 6. Make AIA 171 and nearly-50-band final products

First edit `final_imaging_spws` to include every band that the updated survey
shows is imageable. The default requests SPWs 1–49 as a test, not a promise
that all 49 will pass. Then use the verified SunCASA Python:

```bash
CASAPY="/absolute/path/to/the/working/suncasa/python"
"$CASAPY" scripts/tutorial_imaging.py \
  config/2024-05-14-x8.8-updated-cal.json "$RUN_DIR" \
  --tutorial-summary --multiband
```

The `--multiband` product passes a list of individual SPWs to `qlookplot`, as
in the official EOVSA tutorial. This creates a frequency-axis FITS cube and
frequency-colored radio contours over AIA 171. A range such as `10~14GHz`
would instead make one MFS plane and is not the requested all-band display.

Open the results:

```bash
open "$RUN_DIR/qa/tutorial_imaging/multiband_aia171_before.png"
open "$RUN_DIR/qa/tutorial_imaging/multiband_aia171_after.png"
open "$RUN_DIR/qa/tutorial_imaging/multiband_spws.txt"
open -a CARTA "$RUN_DIR/qa/tutorial_imaging/multiband_after.image.fits"
```

Only `selfcal_spws` were self-calibrated. Any other displayed band is still a
useful pipeline-calibrated context plane but must be labeled that way.

## 7. Publish selected PNGs, not data products

```bash
python scripts/publish_run_gallery.py "$RUN_DIR" \
  examples/2024-05-14-x8.8/updated-calibration
open examples/2024-05-14-x8.8/updated-calibration
git status --short
```

Review the copied PNGs, update the gallery prose with the result, then commit.
Do not upload the MS, gain tables, masks, FITS, logs, `.netrc`, or `runs/`.
