#!/usr/bin/env python3
"""Event-specific CASA 6.7 workflow for the 2020-12-07 EOVSA flare.

This intentionally leaves ``selfcal.py`` unchanged.  It follows the same
science sequence as the successful GitHub workflow:

1. draw one interactive iclean mask for each configured combined-SPW group;
2. make and inspect initial images for every QA SPW (1--40 for this event);
3. make a frequency-local model for every solve SPW using that group mask;
4. explicitly predict each model into MODEL_DATA before gaincal; and
5. image every QA SPW again before accepting or rejecting the gain table.

The explicit ``ft`` step is required because CASA 6.7 can create a valid
``.model`` image while leaving MODEL_DATA at its default value even when
``savemodel='modelcolumn'`` was requested.
"""

from __future__ import annotations

import json
import platform
import shutil
import sys
from pathlib import Path

import numpy as np
from casatasks import applycal, clearcal, delmod, ft, gaincal, split, tclean
from casatools import table

import selfcal as common


EXPECTED_EVENT = "2020-12-07-c7.4"


def require_2020_config(path):
    cfg_path, cfg, vis = common.load_config(path)
    if cfg.get("event_id") != EXPECTED_EVENT:
        raise SystemExit(
            f"This workflow requires event_id={EXPECTED_EVENT!r}; "
            f"received {cfg.get('event_id')!r}."
        )
    return cfg_path, cfg, vis


def model_data_stats(vis, spw):
    """Return simple audit statistics for one predicted MODEL_DATA SPW."""
    tb = table()
    tb.open(str(vis), nomodify=True)
    try:
        if "MODEL_DATA" not in tb.colnames():
            return {"present": False}
        ddid = np.asarray(tb.getcol("DATA_DESC_ID"), dtype=int)
        rows = np.where(ddid == int(spw))[0]
        values = np.asarray(tb.getcol("MODEL_DATA"))[:, :, rows]
    finally:
        tb.close()

    amplitude = np.abs(values[np.isfinite(values)])
    return {
        "present": True,
        "rows": int(rows.size),
        "samples": int(amplitude.size),
        "nondefault_fraction": (
            float(np.mean(~np.isclose(amplitude, 1.0))) if amplitude.size else 0.0
        ),
        "median_amplitude": float(np.median(amplitude)) if amplitude.size else 0.0,
        "maximum_amplitude": float(np.max(amplitude)) if amplitude.size else 0.0,
    }


def predict_and_validate(vis, model, spw, audit_dir):
    """Predict one CASA image model and refuse to solve on an empty model."""
    ft(
        vis=str(vis), spw=str(spw), model=str(model), usescratch=True,
        # Replace this SPW's scratch model.  This also prevents double model
        # flux if a CASA build unexpectedly honored tclean's savemodel first.
        incremental=False,
    )
    stats = model_data_stats(vis, spw)
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / f"model_data_spw_{int(spw):02d}.json").write_text(
        json.dumps(stats, indent=2) + "\n"
    )
    if (
        not stats.get("present")
        or stats.get("samples", 0) == 0
        or stats.get("maximum_amplitude", 0.0) <= 1.0
    ):
        raise RuntimeError(
            f"MODEL_DATA for SPW {spw} is empty/default after ft; "
            "gaincal is blocked for this round."
        )
    print(
        f"Verified SPW {spw} MODEL_DATA: median="
        f"{stats['median_amplitude']:.6g}, max={stats['maximum_amplitude']:.6g}"
    )


def apply_candidate(vis, cfg, tables):
    """Apply candidate tables to every self-cal SPW without flag-on-failure."""
    if not tables:
        return
    applycal(
        vis=str(vis), gaintable=[str(item) for item in tables],
        spw=",".join(str(item) for item in cfg["selfcal_spws"]),
        antenna="", interp="nearest", flagbackup=False,
        applymode="calonly", calwt=False,
    )


def clean_2020_spw_model(
    vis, cfg, root, phasecenter, mask_map, spw, round_index, niter, all_freqs
):
    """Create a model on one target SPW, using its combined-group mask.

    Bin's round-1 neighbor-SPW model selection works for the 2024 MS.  In this
    older 2020 MS the SPWs have variable channel layouts; CASA 6.7 assigns an
    invalid MFS reference frequency when several of them are combined (seen in
    the log as ~1e243 Hz), so the major cycle returns a zero residual and an
    empty model.  Restricting only the *model imaging* to the target SPW avoids
    that CASA metadata bug.  The interactive mask is still made from the full
    configured combined-SPW range.
    """
    target = int(spw)
    stem = root / "models" / f"round_{round_index:02d}_spw_{target:02d}"
    beam = max(cfg["sbeam_1ghz_arcsec"] / all_freqs[target], 4.0)
    tclean(
        vis=str(vis), imagename=str(stem), antenna="",
        uvrange=cfg["uvrange"], spw=str(target), specmode="mfs",
        # short_peak.ms is already time-selected.
        timerange="", imsize=[cfg["imsize"]],
        cell=[f'{cfg["cell_arcsec"]}arcsec'], niter=niter,
        gain=cfg["gain"], stokes=cfg["correlation"],
        weighting="briggs", robust=cfg["robust"], phasecenter=phasecenter,
        mask=common.mask_for_spw(cfg, mask_map, target),
        restoringbeam=[f"{beam}arcsec"], pbcor=False, interactive=False,
        # CASA 6.7 model-column writing is unreliable for this MS.  The caller
        # performs and validates an explicit ft prediction instead.
        savemodel="none",
    )
    return str(target)


def copy_existing_masks(source_run, cfg, destination):
    """Copy only completed CASA mask images from an earlier diagnostic run."""
    source = Path(source_run).expanduser().resolve() / "masks"
    if not source.is_dir():
        raise SystemExit(f"Mask directory not found: {source}")
    mask_map = {}
    for group in cfg["mask_spw_groups"]:
        name = f"mask_spw_{group.replace('~', '-')}.mask"
        old = source / name
        new = destination / name
        if not old.is_dir():
            raise SystemExit(f"Completed mask not found: {old}")
        shutil.copytree(old, new)
        mask_map[group] = str(new.resolve())
    (destination / "mask_manifest.json").write_text(
        json.dumps(mask_map, indent=2) + "\n"
    )
    return mask_map


def run(config_path, mask_run=None):
    cfg_path, cfg, full_ms = require_2020_config(config_path)
    if platform.machine() != "arm64":
        raise SystemExit("Run in the native arm64 environment, not Rosetta.")

    phasecenter = common.phasecenter_for(full_ms, cfg)
    root, manifest = common.safe_new_run(cfg_path, cfg)
    manifest["workflow"] = (
        "2020 iclean masks + per-SPW models + explicit CASA 6.7 ft prediction"
    )

    short_ms = root / "short_peak.ms"
    split(
        vis=str(full_ms), outputvis=str(short_ms), datacolumn="data",
        timerange=cfg["timerange"], correlation=cfg["correlation"],
        antenna=cfg["antenna"],
    )
    clearcal(str(short_ms))

    # split has already selected the requested physical antennas and then
    # renumbered the retained rows.  All subsequent short-MS operations must
    # therefore use every retained antenna, not the original CASA IDs.
    short_cfg = dict(cfg)
    short_cfg["antenna"] = ""
    short_cfg["antenna_by_spw"] = {}
    all_freqs = common.frequencies(short_ms)

    if mask_run:
        print(f"\nReusing the completed combined-SPW masks from: {mask_run}")
        mask_map = copy_existing_masks(mask_run, short_cfg, root / "masks")
        manifest["masks_reused_from"] = str(Path(mask_run).expanduser().resolve())
    else:
        print("\nDraw the combined-SPW masks once. They will be reused by every round.")
        mask_map = common.draw_masks(
            short_ms, short_cfg, root, phasecenter, corrected=True, timerange=""
        )

    print("\nCreating the round-0 QA survey for every configured QA SPW.")
    manifest["initial_qa_images"] = common.image_qa(
        short_ms, short_cfg, root, phasecenter, mask_map, 0, all_freqs,
        use_masks=True, label="EOVSA images before self-calibration (round 0)",
    )
    common.save_manifest(root, manifest)
    print(f"Round-0 montage: {manifest['initial_qa_images']['montage']}")

    accepted = []
    for round_index in range(1, cfg["max_rounds"] + 1):
        calmode = common.ask_choice(
            "Solve this round as phase (p), amplitude (a), or both (ap)? ",
            {"p", "a", "ap"},
        )
        niter = int(input("Model-image iterations (for example 100): ").strip())
        if niter < 0:
            raise ValueError("Model-image iterations must be zero or greater.")

        caltable = root / "caltables" / f"round_{round_index:02d}.{calmode}.G"
        audit_dir = root / "qa" / f"round_{round_index:02d}" / "model_audit"

        # Start each candidate round with an empty scratch model. Each SPW is
        # then populated explicitly from its own frequency-local image model.
        delmod(str(short_ms))
        solved_any = False
        for spw in cfg["selfcal_spws"]:
            print(f"\nRound {round_index}; imaging and solving SPW {spw}")
            model_selection = clean_2020_spw_model(
                short_ms, short_cfg, root, phasecenter, mask_map, spw,
                round_index, niter, all_freqs,
            )
            stem = root / "models" / f"round_{round_index:02d}_spw_{int(spw):02d}"
            model = Path(str(stem) + ".model")
            if not model.is_dir():
                raise RuntimeError(f"Model image was not created: {model}")

            predict_and_validate(short_ms, model, spw, audit_dir)
            gaincal(
                vis=str(short_ms), refant=short_cfg["refant"], antenna="",
                caltable=str(caltable), spw=str(spw),
                uvrange="" if calmode == "p" else short_cfg["uvrange"],
                gaintable=[str(item) for item in accepted], selectdata=True,
                timerange="", solint="inf", gaintype="G", calmode=calmode,
                combine="", minblperant=short_cfg.get("minblperant", 3),
                minsnr=short_cfg.get("minsnr", 2.0), append=solved_any,
            )
            solved_any = caltable.is_dir()
            print(f"Model visibility selection: {model_selection}")
            common.remove_casa_image_products(stem)

        if not solved_any:
            raise RuntimeError(f"No gain solutions were written for round {round_index}.")

        qa_dir = root / "qa" / f"round_{round_index:02d}"
        common.gain_qa(short_ms, caltable, qa_dir)
        clearcal(str(short_ms))
        delmod(str(short_ms))
        candidate = accepted + [caltable]
        apply_candidate(short_ms, short_cfg, candidate)

        print("\nCreating candidate QA images for every configured QA SPW.")
        qa_images = common.image_qa(
            short_ms, short_cfg, root, phasecenter, mask_map, round_index,
            all_freqs, use_masks=False,
            label=f"EOVSA images after round {round_index}",
        )
        print(f"\nQA is in {qa_dir}")
        print(f"All-SPW montage: {qa_images['montage']}")
        decision = common.ask_choice(
            "Accept this gain table (a), reject/stop (r), or accept and continue (c)? ",
            {"a", "r", "c"},
        )

        if decision == "r":
            clearcal(str(short_ms))
            delmod(str(short_ms))
            apply_candidate(short_ms, short_cfg, accepted)
            manifest["rounds"].append({
                "round": round_index, "calmode": calmode,
                "niter": niter, "accepted": False,
                "caltable": str(caltable), "qa_images": qa_images,
            })
            common.save_manifest(root, manifest)
            break

        accepted.append(caltable)
        manifest["rounds"].append({
            "round": round_index, "calmode": calmode, "niter": niter,
            "accepted": True, "caltable": str(caltable),
            "qa_images": qa_images,
            "model_source": "per-SPW model image explicitly predicted with ft",
        })
        common.save_manifest(root, manifest)
        if decision == "a":
            break

        # Masks are intentionally reused. Redrawing is available only when
        # explicitly requested after accepting a round.
        if common.ask_choice("Update masks before the next round? (y/n) ", {"y", "n"}) == "y":
            mask_map = common.draw_masks(
                short_ms, short_cfg, root, phasecenter,
                corrected=True, timerange="",
            )

    if not accepted:
        raise SystemExit(f"No accepted rounds. Run retained for diagnosis: {root}")

    final_short = root / "final" / "short_peak.selfcal.ms"
    split(vis=str(short_ms), outputvis=str(final_short), datacolumn="corrected")
    manifest["final_short_ms"] = str(final_short)
    common.save_manifest(root, manifest)
    print(f"\nFinal short self-calibrated MS: {final_short}")
    print("The original full MS was not modified.")


def apply_full(config_path, run_dir):
    """Transfer accepted 2020 gain tables to a full-duration MS copy.

    The gain tables contain solutions only for ``selfcal_spws`` (currently
    SPWs 3--31).  ``clearcal`` first initializes CORRECTED_DATA from DATA for
    the complete copied observation, then ``apply_candidate`` changes only
    those solved SPWs.  The final split deliberately has no SPW selection so
    all original SPWs and their original IDs remain available for imaging.
    """
    _, cfg, full_ms = require_2020_config(config_path)
    root = Path(run_dir).expanduser().resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Run manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text())
    tables = [
        Path(item["caltable"]).expanduser().resolve()
        for item in manifest.get("rounds", [])
        if item.get("accepted")
    ]
    if not tables:
        raise SystemExit("Manifest contains no accepted gain tables.")
    missing = [str(item) for item in tables if not item.is_dir()]
    if missing:
        raise SystemExit("Accepted gain table(s) not found: " + ", ".join(missing))

    print(f"Full input MS: {full_ms}")
    print("Accepted tables, in application order:")
    for item in tables:
        print(f"  {item}")
    print(
        "Solutions will be applied only to configured self-cal SPWs "
        f"{min(cfg['selfcal_spws'])}--{max(cfg['selfcal_spws'])}."
    )
    print("The final MS will retain every original SPW; unsolved SPWs remain unchanged.")
    if input("Type APPLY to continue: ").strip() != "APPLY":
        raise SystemExit("Cancelled; no full-duration data were changed.")

    final_dir = root / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    working = final_dir / "full_duration.working.ms"
    final = final_dir / "full_duration.selfcal.ms"
    if working.exists() or final.exists():
        raise SystemExit(
            "Full-duration output already exists; refusing to overwrite it. "
            "Move the existing output aside only after verifying what it contains."
        )

    # Select the same physical antennas used to make short_peak.ms. CASA then
    # renumbers both datasets identically, so the antenna rows in the accepted
    # gain tables map to the intended physical antennas.
    split(
        vis=str(full_ms), outputvis=str(working), datacolumn="data",
        correlation=cfg["correlation"], antenna=cfg["antenna"],
    )
    clearcal(str(working))
    working_cfg = dict(cfg)
    working_cfg["antenna"] = ""
    working_cfg["antenna_by_spw"] = {}
    apply_candidate(working, working_cfg, tables)

    # Do not select SPWs here. Selecting 3--31 would both drop the diagnostic
    # bands and renumber the remaining SPWs, breaking the event imaging config.
    split(
        vis=str(working), outputvis=str(final), datacolumn="corrected",
        correlation=cfg["correlation"],
    )
    manifest["final_full_ms"] = str(final)
    manifest["full_apply_working_copy"] = str(working)
    manifest["full_apply_tables"] = [str(item) for item in tables]
    manifest["full_apply_solved_spws"] = list(cfg["selfcal_spws"])
    manifest["full_apply_preserved_all_spws"] = True
    common.save_manifest(root, manifest)
    print(f"\nFinal full-duration self-calibrated MS: {final}")
    print(f"Working copy retained for audit/recovery: {working}")
    print("The original full input MS was not modified.")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: selfcal_2020_iclean.py run CONFIG.json [RUN_WITH_MASKS]\n"
            "   or: selfcal_2020_iclean.py apply-full CONFIG.json RUN_DIR"
        )
    if sys.argv[1] == "run" and len(sys.argv) in (3, 4):
        run(sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else None)
    elif sys.argv[1] == "apply-full" and len(sys.argv) == 4:
        apply_full(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(
            "usage: selfcal_2020_iclean.py run CONFIG.json [RUN_WITH_MASKS]\n"
            "   or: selfcal_2020_iclean.py apply-full CONFIG.json RUN_DIR"
        )


if __name__ == "__main__":
    main()
