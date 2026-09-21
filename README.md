# EOVSA flare self-calibration with modern CASA and `iclean`

This repository is a guided, reproducible update of Bin Chen's 2023
`eovsa_flare_slfcal_example.py`. It preserves the calibration logic—grouped
masks, per-SPW models, iterative gain solving, gain-table inspection, and
before/after imaging—while replacing deprecated `tclean(interactive=True)` with
CASA's browser-based `iclean`.

The worked example is the **2024-05-14 X8.8 flare**. To use another event,
copy the example configuration and make the event decisions listed below.

## Start here

Follow the numbered [run order](#run-order) from a normal macOS Terminal. Do
not start in Jupyter or IPython: `iclean` opens its own browser application and
the Terminal process must remain alive.

Repository guides:

- [Exact `iclean` clicks](docs/iclean-mask-click-guide.md)
- [Worked-event decisions and limitations](docs/EVENT_2024-05-14.md)
- [Experimental 2020-12-07 C7.4 case study](docs/EVENT_2020-12-07.md)
- [Generated product tree](docs/PRODUCTS.md)
- [CARTA and macOS figure viewing](docs/VIEWING.md)
- [Selected example gallery](examples/2024-05-14-x8.8/README.md)
- [Updated-calibration rerun](docs/UPDATED_CALIBRATION_RERUN.md)
- [Preliminary GitHub upload](docs/GITHUB_UPLOAD.md)

## What to download

You need:

1. This repository.
2. One **calibrated, concatenated EOVSA CASA Measurement Set** covering the
   flare. The example filename is
   `IDB20240514_163948-165948.cal.ms`.
3. CARTA for detailed image inspection. Preview is sufficient for PNGs.
4. Internet access only for the optional AIA/GOES tutorial-summary products.

The self-cal scripts do **not** turn raw IDB files into a calibrated MS. Raw
IDB import requires EOVSAPY/SunCASA and calibration-database access; perform
that upstream on the EOVSA pipeline or obtain the calibrated MS from the group.
Do not put the MS inside this Git repository.

## Supported software

The primary solver is designed for an Apple-silicon Mac running native
`arm64` Python 3.12:

| Job | Environment | Required software |
|---|---|---|
| Preflight, survey, `iclean`, gain solving, QA | project `.venv`, native `arm64` | Python 3.12, CASA >=6.7.2, `cubevis==1.0.14` |
| Optional SunCASA tutorial imaging | separate existing x86_64/Rosetta environment | CASA 6.6.x, SunCASA 1.0.8.2 |
| Image inspection | macOS application | CARTA |

Check the Terminal architecture before setup:

```bash
uname -m
```

It must print `arm64` for the primary workflow. The older Rosetta environment
is used only where SunCASA is required; it is not used to run `iclean`.

### Modular CASA versus standalone CASA

The primary workflow uses **Modular CASA**: the `casatasks`, `casatools`, and
`casadata` Python packages installed into an ordinary Python environment. It
does **not** use the standalone/monolithic CASA application or its `casa`
executable. Both setup options below install the same Modular CASA packages
and run the same repository scripts.

A standalone CASA download bundles its own Python interpreter and application.
Do not launch the primary workflow inside that application or mix its packages
into the project environment. The optional legacy SunCASA imaging step is kept
in a separate CASA 6.6.x environment because its dependencies differ from the
native CASA 6.7 `iclean` environment.

## Create the environment

These steps assume macOS. Open **Terminal** from
**Finder → Applications → Utilities → Terminal**, or press Command-Space,
type `Terminal`, and press Return. Enter commands after the `%` prompt; do not
type the prompt itself.

### Download the repository

Choose one method:

1. On GitHub, select **Code → Download ZIP**, double-click the downloaded ZIP,
   and move the resulting folder somewhere permanent; or
2. if Git is installed, clone it in Terminal:

```bash
cd ~/Downloads
git clone https://github.com/mal-wickline/eovsa_selfcal_and_imaging_tutorial.git
```

Enter the repository directory. If its name differs, substitute its real path:

```bash
cd ~/Downloads/eovsa_selfcal_and_imaging_tutorial
pwd
ls
```

`pwd` should show the repository, and `ls` should include `README.md`,
`setup_macos.sh`, `scripts`, and `config`. Keep this Terminal open while
`iclean` is running; the browser window is only the graphical front end.

### Option A: Python virtual environment (`.venv`, recommended)

This is the setup used for the worked 2024 event. From the repository root:

```bash
chmod +x setup_macos.sh
./setup_macos.sh
source .venv/bin/activate
python -c 'import platform, casatasks; from importlib.metadata import version; print("architecture:", platform.machine()); print("CASA:", casatasks.version()); print("CubeVis:", version("cubevis"))'
```

Expected architecture: `arm64`. The setup is project-local and does not modify
old CASA or SunCASA environments. A successful activation normally adds
`(.venv)` to the Terminal prompt. In each new Terminal, return to the
repository and run `source .venv/bin/activate` again before using the scripts.

### Option B: Conda environment

Users who prefer Conda can create an isolated environment with the same
Python version and Modular CASA packages. Install a native Apple-silicon
Miniforge, Miniconda, or Anaconda distribution first, then open a new Terminal
and run these commands from the repository root:

```bash
uname -m
conda create --name eovsa-selfcal python=3.12 pip -y
conda activate eovsa-selfcal
python -m pip install --upgrade pip setuptools wheel
python -m pip install "casatasks>=6.7.2" "casatools>=6.7.2" \
  "cubevis==1.0.14" "bokeh>=3.8" matplotlib astropy numpy
python -c 'import platform, casatasks; from importlib.metadata import version; print("architecture:", platform.machine()); print("CASA:", casatasks.version()); print("CubeVis:", version("cubevis"))'
```

The first command must print `arm64`. A successful activation normally adds
`(eovsa-selfcal)` to the prompt. In each new Terminal, run
`conda activate eovsa-selfcal`; do not also activate `.venv`. All later
commands are identical for both environment options.

If `conda activate` says that the shell is not initialized, run
`conda init zsh`, close Terminal, open it again, and retry. If `python` reports
`x86_64`, stop and install/use a native Apple-silicon Conda distribution.

### Confirm the scripts are ready

From the repository root, with exactly one environment activated:

```bash
which python
python -m py_compile scripts/preflight.py scripts/selfcal.py
python scripts/selfcal.py
```

The last command prints usage information; that is expected. Repository
scripts do not need to be double-clicked or copied into CASA. Run them from
Terminal with `python scripts/<script-name>.py ...`, as shown below.

## Find flare peak time and find flare location





## Create an event configuration

```bash
cp config/2024-05-14-x8.8.example.json config/my-event.json
```

Edit `config/my-event.json`. At minimum, decide and document:

- `input_ms`: absolute path to the calibrated MS;
- `timerange`: short, bright, structurally stable solve interval;
- `correlation`: normally `XX` for this example;
- `xycen_arcsec`: helioprojective source center `(Solar X, Solar Y)` in arcsec;
- `phasecenter`: CASA J2000 phase center derived from that location;
- `antenna`: usable CASA antenna IDs—not 1-based EOVSA labels;
- `antenna_by_spw`: frequency-dependent outages or restrictions;
- `refant`: well-behaved reference antenna;
- `selfcal_spws`: SPWs containing a recognizable source and usable data;
- `mask_spw_groups`: adjacent SPWs with similar source morphology;
- field of view, pixel size, robust weighting, and UV cutoff.

Never copy antenna or SPW selections blindly between events. The preflight
report and survey images are the authority.

If `phasecenter` has not been derived, use a working SunCASA environment:

```bash
/path/to/suncasa/python scripts/derive_phasecenter.py config/my-event.json
```

Do not solve gains while `xycen_arcsec` or `phasecenter` is missing.

## Run order

All commands below start in the repository root.

### 1. Activate and preflight

```bash
source .venv/bin/activate
python scripts/preflight.py config/my-event.json
```

Read `preflight/<event_id>.txt`. Confirm:

- the MS exists and contains the expected number of SPWs;
- CASA antenna ID-to-name mapping;
- available polarization products;
- flagged fraction for every intended antenna;
- configured timerange, source location, reference antenna, and SPWs.

Stop and edit the configuration if these disagree with the event log.

### 2. Run the smoke test

The smoke test checks CASA, the browser, masking, gain solving, and output
creation using one representative SPW. It is an engineering test, not science.

Create a small config from your event config with one strong SPW, one mask
group, and `max_rounds: 1`, or use the supplied example smoke config after
fixing its `input_ms` path:

```bash
cp config/2024-05-14-x8.8-smoke-test.example.json config/my-event-smoke.json
# Edit input_ms, timerange, position, antenna selection, and representative SPW.
python scripts/selfcal.py run config/my-event-smoke.json
```

Smoke-test checklist:

- [ ] `iclean` opens in a browser.
- [ ] The source is inside the image and at the expected solar location.
- [ ] A compact mask can be added and saved.
- [ ] One 25-iteration test cycle completes.
- [ ] A phase table is written for the representative SPW.
- [ ] `gains_phase.png`, `gain_summary.csv`, and an SPW image are created.
- [ ] The test can be accepted and exits cleanly.

If this fails, do not start the multi-SPW science run.

### 3. Make the pre-mask SPW survey

```bash
python scripts/selfcal.py survey config/my-event.json
```

The command prints a new timestamped run directory. Open its survey montage:

```bash
RUN_DIR="runs/<event-id-and-timestamp>"
open "$RUN_DIR/qa/round_00/images/all_spws.png"
```

Use the montage to remove unusable SPWs and group adjacent SPWs with similar
source morphology. Update `selfcal_spws` and the event-dependent
`mask_spw_groups` in the configuration. The browser displays the complete
configured SPW range for each group, not a representative SPW.

### 4. Run visibility-domain diagnostics

```bash
python scripts/visibility_qa.py config/my-event.json \
  "$RUN_DIR/qa/visibility_input"
open "$RUN_DIR/qa/visibility_input"
```

Inspect amplitude and phase versus frequency by antenna, amplitude versus UV
distance, phase versus time, flags/weights, and baseline-class amplitudes.
These plots justify antenna selection; they do not modify the MS.

### 5. Run the guided self-calibration

```bash
python scripts/selfcal.py run config/my-event.json
```

This command creates a **new** timestamped run and performs the authoritative
masking. Record the new path printed by the script as `RUN_DIR`.

For each mask group, follow the [exact click guide](docs/iclean-mask-click-guide.md).
For the 2024 example, use `niter=100`, `cycleniter=25`, `gain=0.05`, and one
assessment cycle. Draw only around connected source emission, not sidelobes.

At each solve prompt:

- enter `p` for a phase-only round;
- enter the model iterations (the example used 100 for round 1 and 50 for
  round 2);
- wait for all configured SPWs to solve and for QA to finish;
- inspect the checklist below before entering `a`, `c`, or `r`.

Prompt meanings:

- `a`: accept this table and finish;
- `c`: accept this table and continue to another round;
- `r`: reject this candidate and stop, restoring previously accepted tables.

Amplitude (`a`) or amplitude-plus-phase (`ap`) remains available because it
was present in Bin's procedure, but it is optional and was not needed for the
worked X8.8 event. Never add amplitude self-cal automatically.

### 6. Accept or reject each round

Open the current QA directory:

```bash
open "$RUN_DIR/qa/round_01"
open "$RUN_DIR/qa/round_01/images/all_spws.png"
open "$RUN_DIR/qa/round_01/gains_phase.png"
open "$RUN_DIR/qa/round_01/gain_summary.csv"
```

Round acceptance checklist:

- [ ] Intended antennas have solutions; empty panels match deliberate exclusions.
- [ ] Phase versus SPW is plausible, without unexplained antenna jumps.
- [ ] Amplitudes remain 1.0 for a phase-only table.
- [ ] Flagged/missing solutions are understood.
- [ ] Source morphology improves or remains stable across adjacent SPWs.
- [ ] No new fragmentation, strong sidelobes, centroid jump, or large flux change.
- [ ] The mask contains plausible source emission and excludes noise/sidelobes.
- [ ] The candidate is better than, or has converged relative to, the prior round.

Reject a round if any important failure is unexplained. More rounds are not
automatically better; convergence is a valid stopping condition.

### 7. Inspect the accepted short MS

After acceptance:

```text
$RUN_DIR/final/short_peak.selfcal.ms
```

The input full-duration MS has not been modified. Review the manifest and every
accepted round before applying anything to the full observation.

### 8. Optional tutorial-style before/after imaging

Run this with the separate SunCASA environment, not the native `.venv`:

```bash
CASAPY="/path/to/suncasa/python"
"$CASAPY" scripts/tutorial_imaging.py config/my-event.json "$RUN_DIR"
```

To also make the tutorial-style individual-band cube and color-coded EOVSA
contours over AIA 171, add both flags:

```bash
"$CASAPY" scripts/tutorial_imaging.py config/my-event.json "$RUN_DIR" \
  --tutorial-summary --multiband
```

`final_imaging_spws` controls that cube. It can contain nearly all 50 bands,
but must be edited after inspecting the new MS. Bands outside `selfcal_spws`
are pipeline-calibrated context; they are not silently promoted to
self-calibrated data.

## Repeating the event after an upstream calibration change

Never replace the old input MS or gallery. Follow
[`UPDATED_CALIBRATION_RERUN.md`](docs/UPDATED_CALIBRATION_RERUN.md), use the
`updated-cal` example configuration, and publish the approved new PNGs beside
the previous-calibration gallery. This keeps upstream-calibration changes
separate from self-calibration changes.

To add AIA 171, GOES, disk/grid, flare zoom, and radio contours:

```bash
"$CASAPY" scripts/tutorial_imaging.py config/my-event.json "$RUN_DIR" \
  --frequency-ranges '2~4GHz,5~6GHz,7~8GHz,9~10GHz,10~12GHz' \
  --tutorial-summary
```

The script writes essential radio PNGs before network-dependent AIA/GOES work.
Its MFS pairs are shallow dirty-map diagnostics: diagonal stripes and negative
bowls are synthesized-beam sidelobes, not additional solar sources. Use the
mask-guided per-SPW montages—not dirty MFS panels—to judge round acceptance.

### 9. Apply accepted tables to the full-duration MS

This is intentionally separate and confirmation-gated:

```bash
python scripts/selfcal.py apply-full config/my-event.json "$RUN_DIR"
```

Read the prompt, verify the run path, then type `APPLY`. The script copies the
input MS and writes `final/full_duration.selfcal.ms`; it does not overwrite the
original.

## Viewing figures on macOS and in CARTA

Use Preview/Finder for summary PNGs:

```bash
open "$RUN_DIR/qa/round_00/images/all_spws.png"
open "$RUN_DIR/qa/round_01/images/all_spws.png"
open "$RUN_DIR/qa/round_01/gains_phase.png"
open "$RUN_DIR/qa/tutorial_imaging/tutorial_summary_after_10_to_12.png"
```

Use CARTA for FITS images and WCS-aware inspection:

```bash
open -a CARTA
```

In CARTA choose **File → Open**, then open, for example,
`$RUN_DIR/qa/round_01/images/spw_18.fits`. Compare the same SPW from
`round_00`, `round_01`, and `round_02`; match spatial coordinates and color
limits before judging improvement. See [docs/VIEWING.md](docs/VIEWING.md) for
the complete procedure and recommended files.

## Decisions used for the worked event

The 2024-05-14 example used:

- solve interval `16:47:12–16:47:20 UT`;
- HPC center `(x,y)=(+902,-293)` arcsec;
- `XX`, SPWs 3–31, and mask groups `3~6`, `7~14`, `15~22`, `23~31`;
- CASA antennas `0~6,8,10~12`, with CASA 6 removed at SPW 23 and above;
- reference antenna 0 and `uvrange='>500lambda'`;
- two accepted phase-only rounds and no amplitude solve.

These choices and their evidence are documented in
[docs/EVENT_2024-05-14.md](docs/EVENT_2024-05-14.md). They are not universal
defaults.

## Experimental 2020-12-07 event workflow

The repository also includes a separate C7.4 case study for testing the same
scientific procedure on an older, 50-SPW observation. It is intentionally kept
apart from the main worked example:

- the **2024 configuration and `scripts/selfcal.py` remain the primary,
  published workflow**;
- `config/2020-12-07-c7.4.example.json` records the 2020 event decisions; and
- `scripts/selfcal_2020_iclean.py` contains only the event-specific CASA 6.7
  adjustments needed by that MS while retaining interactive `iclean`.

See [docs/EVENT_2020-12-07.md](docs/EVENT_2020-12-07.md) for the decisions,
commands, accepted procedure, and current limitations. Its AIA grayscale and
multiband contour figures are preliminary and are not yet publication-ready.

## Known quirks and safeguards

- `cubevis` 1.0.14 has an imagename lookup issue; `selfcal.py` works around it
  by running each mask in its own directory with a basename.
- Reusing stale CASA image products can cause spectral-coordinate mismatch
  errors. Every run uses a new timestamped directory; do not copy old mask
  working products into it.
- SunCASA's default JP2 AIA download was unreadable in the tested x86 build;
  `tutorial_imaging.py` downloads and validates a FITS through SunPy/Fido.
- This MS contains unflagged literal zero placeholders. The spectrum helper
  removes nonpositive samples before taking its median.
- SunCASA mishandles paths containing spaces during image registration. The
  wrapper uses a space-free temporary directory and copies completed FITS back.
- EOVSA has multiple antenna diameters, so CASA may warn that the primary beam
  could be wrong. This compact limb-source workflow does not treat the warning
  as proof that a solution is valid; image and gain QA remain mandatory.
- `minsnr=0` in the worked config is deliberately inclusive. It disables
  formal S/N rejection and therefore requires manual gain-table and image QA.

## Repository contents and data policy

`scripts/` contains the executable workflow; `config/` contains sanitized
examples; `docs/` contains task-specific guides; `examples/` contains selected
derived PNGs. Generated CASA products live under ignored `runs/` directories.

Commit source, Markdown, sanitized configuration, and approved example PNGs.
Do not commit IDBs, Measurement Sets, gain tables, CASA images/masks, FITS,
downloaded AIA data, `.netrc`, passwords, virtual environments, logs, or full
run directories.
