#!/usr/bin/env python3
"""Guided, science-faithful EOVSA flare self-calibration using cubevis.iclean."""

from __future__ import annotations

import csv
import json
import math
import os
import platform
import shutil
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits
from casatasks import applycal, clearcal, delmod, exportfits, gaincal, split, tclean
from casatools import msmetadata, table
from cubevis import iclean


def package_version(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return "missing"


def ask_choice(prompt, choices):
    while True:
        answer = input(prompt).strip().lower()
        if answer in choices:
            return answer
        print(f"Choose one of: {', '.join(choices)}")


def load_config(path):
    cfg_path = Path(path).expanduser().resolve()
    cfg = json.loads(cfg_path.read_text())
    vis = Path(cfg["input_ms"]).expanduser().resolve()
    if not vis.is_dir():
        raise SystemExit(f"Input MS not found: {vis}")
    if cfg.get("xycen_arcsec") in (None, [None, None]) or not cfg.get("phasecenter"):
        raise SystemExit(
            "xycen_arcsec and/or phasecenter are unset. Locate the radio source, then run "
            "derive_phasecenter.py in the SunCASA environment; gain solving is blocked."
        )
    return cfg_path, cfg, vis


def phasecenter_for(vis, cfg):
    del vis
    return cfg["phasecenter"]


def safe_new_run(cfg_path, cfg):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = cfg_path.parent.parent / "runs" / f'{cfg["event_id"]}-{stamp}'
    root.mkdir(parents=True, exist_ok=False)
    for name in ("masks", "models", "caltables", "qa", "final"):
        (root / name).mkdir()
    manifest = {
        "created_utc": stamp,
        "config": cfg,
        "versions": {name: package_version(name) for name in ("casatasks", "casatools", "cubevis")},
        "architecture": platform.machine(),
        "rounds": [],
    }
    save_manifest(root, manifest)
    return root, manifest


def save_manifest(root, manifest):
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def mask_for_spw(cfg, mask_map, spw):
    for group in cfg["mask_spw_groups"]:
        lo, hi = map(int, group.split("~"))
        if lo <= int(spw) <= hi:
            return mask_map.get(group, "")
    return ""


def antenna_for_spw(cfg, spw):
    value = int(spw)
    for span, selection in cfg.get("antenna_by_spw", {}).items():
        lo, hi = map(int, span.split("~"))
        if lo <= value <= hi:
            return selection
    return cfg["antenna"]


def apply_tables(vis, cfg, tables):
    """Apply tables by SPW-dependent antenna selection without flagging omitted antennas."""
    selections = {}
    for spw in cfg["selfcal_spws"]:
        selections.setdefault(antenna_for_spw(cfg, spw), []).append(str(spw))
    for antenna, spws in selections.items():
        applycal(vis=str(vis), gaintable=[str(x) for x in tables],
                 spw=",".join(spws), antenna=antenna, interp="nearest",
                 flagbackup=False, applymode="calonly", calwt=False)


def has_column(vis, column):
    tb = table()
    tb.open(str(vis), nomodify=True)
    try:
        return column in tb.colnames()
    finally:
        tb.close()


def draw_masks(vis, cfg, root, phasecenter, corrected=True):
    """One blocking browser session per broad SPW group."""
    mask_map = {}
    mask_dir = (root / "masks").resolve()
    all_freqs = frequencies(vis)
    for group in cfg["mask_spw_groups"]:
        group_lo, group_hi = map(int, group.split("~"))
        # CubeVis/CASA 6.7 can create a multi-SPW MFS residual but then fail
        # when its browser requests the next major cycle, because the restarted
        # image receives a different spectral LinearXform. Draw each broad
        # group's spatial mask on a representative SPW instead. The mask is
        # still assigned to every SPW in the group during model imaging.
        browser_spw = int(cfg.get("mask_browser_spw_by_group", {}).get(
            group, (group_lo + group_hi) // 2))
        # Pin both reference and active rest frequencies. CubeVis restarts
        # tclean between browser cycles; for multi-SPW MFS, an empty restfreq
        # can make CASA reject the model created by its immediately preceding
        # cycle even when reffreq itself is unchanged.
        group_reffreq = float(all_freqs[browser_spw])
        stem_name = f"mask_spw_{group.replace('~', '-')}"
        stem = mask_dir / stem_name
        print(f"\nOpening iclean for SPW group {group} using representative SPW {browser_spw}.")
        print("Draw/add the source mask, run enough cleaning to assess it, then stop the app.")
        # cubevis 1.0.14 builds its GUI lookup with the basename returned by
        # gclean but compares it with tclean's supplied imagename. An absolute
        # imagename therefore raises KeyError before the browser opens. Work in
        # the run-owned mask directory and supply a basename to keep both keys
        # identical. The MS path remains absolute.
        previous_dir = Path.cwd()
        try:
            os.chdir(mask_dir)
            iclean(
                vis=str(Path(vis).resolve()), imagename=stem_name, spw=str(browser_spw),
                antenna=antenna_for_spw(cfg, browser_spw), uvrange=cfg["uvrange"], specmode="mfs",
                reffreq=f"{group_reffreq:.9f}GHz",
                restfreq=[f"{group_reffreq:.9f}GHz"],
                timerange=cfg["timerange"], imsize=[cfg["imsize"]],
                cell=[f'{cfg["cell_arcsec"]}arcsec'], niter=1000, gain=cfg["gain"],
                stokes=cfg["correlation"], restoringbeam=["20arcsec"],
                phasecenter=phasecenter, weighting="briggs", robust=cfg["robust"],
                datacolumn="corrected" if corrected and has_column(vis, "CORRECTED_DATA") else "data",
                pbcor=False,
            )
        finally:
            os.chdir(previous_dir)
        mask = Path(str(stem) + ".mask")
        if not mask.is_dir():
            raise RuntimeError(f"iclean ended without creating expected mask: {mask}")
        for suffix in (".mask", ".residual", ".image"):
            casa_image = Path(str(stem) + suffix)
            if casa_image.is_dir():
                exportfits(imagename=str(casa_image),
                           fitsimage=str(stem) + suffix + ".fits", overwrite=True)
        mask_map[group] = str(mask)
    (root / "masks" / "mask_manifest.json").write_text(json.dumps(mask_map, indent=2) + "\n")
    return mask_map


def frequencies(vis):
    md = msmetadata()
    md.open(str(vis))
    try:
        return [md.meanfreq(i, unit="GHz") for i in range(md.nspw())]
    finally:
        md.done()


def clean_model(vis, cfg, root, phasecenter, mask_map, spw, round_index, niter, all_spws):
    target = int(spw)
    if round_index == 1:
        lo = max(target - cfg["neighbor_half_width"], cfg["spw_min"])
        hi = min(target + cfg["neighbor_half_width"], cfg["spw_max"])
        model_spw = f"{lo}~{hi}"
    else:
        model_spw = str(target)
    stem = root / "models" / f"round_{round_index:02d}_spw_{target:02d}"
    mask = mask_for_spw(cfg, mask_map, target)
    freq = all_spws[target]
    beam = max(cfg["sbeam_1ghz_arcsec"] / freq, 4.0)

    kwargs = dict(
        vis=str(vis), imagename=str(stem), antenna=antenna_for_spw(cfg, spw),
        uvrange=cfg["uvrange"], spw=model_spw, specmode="mfs",
        timerange=cfg["timerange"], imsize=[cfg["imsize"]],
        cell=[f'{cfg["cell_arcsec"]}arcsec'], niter=niter, gain=cfg["gain"],
        stokes=cfg["correlation"], weighting="briggs", robust=cfg["robust"],
        phasecenter=phasecenter, mask=mask, restoringbeam=[f"{beam}arcsec"],
        pbcor=False, interactive=False, savemodel="modelcolumn",
    )
    try:
        tclean(**kwargs)
    except Exception:
        lo = max(target - 2, cfg["spw_min"])
        hi = min(target + 2, cfg["spw_max"])
        kwargs["spw"] = f"{lo}~{hi}"
        print(f"Initial model failed; retrying SPWs {kwargs['spw']} (Bin fallback).")
        tclean(**kwargs)
    return model_spw


def remove_casa_image_products(stem):
    """Remove only products with an exact, run-owned image stem."""
    for suffix in (".mask", ".flux", ".model", ".psf", ".residual", ".image",
                   ".pb", ".image.pbcor", ".sumwt"):
        target = Path(str(stem) + suffix)
        if target.is_dir():
            shutil.rmtree(target)


def gain_qa(vis, caltable, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    tb = table()
    tb.open(str(caltable), nomodify=True)
    try:
        cp = tb.getcol("CPARAM")
        flags = tb.getcol("FLAG")
        snr = tb.getcol("SNR")
        ants = tb.getcol("ANTENNA1")
        spws = tb.getcol("SPECTRAL_WINDOW_ID")
    finally:
        tb.close()

    rows = []
    for row in range(cp.shape[-1]):
        for pol in range(cp.shape[0]):
            rows.append({
                "antenna_id": int(ants[row]), "spw": int(spws[row]), "pol_index": pol,
                "amplitude": float(abs(cp[pol, 0, row])),
                "phase_deg": float(np.angle(cp[pol, 0, row], deg=True)),
                "snr": float(snr[pol, 0, row]), "flagged": bool(flags[pol, 0, row]),
            })
    with (outdir / "gain_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader(); writer.writerows(rows)

    nants = max(r["antenna_id"] for r in rows) + 1
    ncols = 4; nrows = math.ceil(nants / ncols)
    for field, ylabel, ylim, filename in (
        ("phase_deg", "Phase (deg)", (-180, 180), "gains_phase.png"),
        ("amplitude", "Amplitude", (0.1, 3.0), "gains_amplitude.png"),
    ):
        fig, axes = plt.subplots(nrows, ncols, figsize=(12, 2.8 * nrows), squeeze=False)
        for ant in range(nants):
            ax = axes.flat[ant]
            selected = [r for r in rows if r["antenna_id"] == ant and not r["flagged"]]
            for pol, color in ((0, "tab:blue"), (1, "tab:red")):
                pr = [r for r in selected if r["pol_index"] == pol]
                ax.plot([r["spw"] for r in pr], [r[field] for r in pr], "o", ms=3, color=color)
            ax.set(title=f"CASA ant {ant}", xlabel="SPW", ylabel=ylabel, ylim=ylim)
        for ax in axes.flat[nants:]: ax.set_visible(False)
        fig.tight_layout(); fig.savefig(outdir / filename, dpi=160); plt.close(fig)


def qa_spws(cfg):
    """SPWs imaged for morphology/round comparison (all by default)."""
    return cfg.get("qa_spws", list(range(cfg["spw_min"], cfg["spw_max"] + 1)))


def make_image_montage(products, all_freqs, output, title):
    """Create Bin-style, fixed-layout per-SPW image summary for round comparison."""
    if not products:
        return None
    ncols = 10
    nrows = math.ceil(len(products) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(2.35 * ncols, 2.25 * nrows), squeeze=False)
    for ax, item in zip(axes.flat, products):
        path = Path(item["fits"])
        data = np.asarray(fits.getdata(path)).squeeze()
        finite = data[np.isfinite(data)]
        if finite.size:
            vmin, vmax = np.nanpercentile(finite, [1, 99.7])
            if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin == vmax:
                vmin, vmax = np.nanmin(finite), np.nanmax(finite)
            ax.imshow(data, origin="lower", cmap="jet", vmin=vmin, vmax=vmax)
        ax.set_title(f'SPW {item["spw"]}  {all_freqs[item["spw"]]:.2f} GHz', fontsize=8)
        ax.set_xticks([]); ax.set_yticks([])
    for ax in axes.flat[len(products):]:
        ax.set_visible(False)
    fig.suptitle(title, fontsize=16)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return str(output)


def image_qa(vis, cfg, root, phasecenter, mask_map, round_index, all_freqs, use_masks,
             spws=None, label=None):
    """Make the same per-SPW diagnostic images used to judge each round."""
    outdir = root / "qa" / f"round_{round_index:02d}" / "images"
    outdir.mkdir(parents=True, exist_ok=True)
    products = []
    selected_spws = qa_spws(cfg) if spws is None else spws
    for spw in selected_spws:
        beam = max(cfg["sbeam_1ghz_arcsec"] / all_freqs[int(spw)], 3.0)
        stem = outdir / f"spw_{int(spw):02d}"
        tclean(
            vis=str(vis), imagename=str(stem), antenna=antenna_for_spw(cfg, spw),
            uvrange=cfg["uvrange"], spw=str(spw), specmode="mfs", timerange="",
            imsize=[cfg["imsize"]], cell=[f'{cfg["cell_arcsec"]}arcsec'],
            niter=cfg["initial_image_niter"] if round_index == 0 else cfg["qa_image_niter"],
            gain=0.05 if round_index == 0 else 0.1, stokes=cfg["correlation"],
            weighting="briggs", robust=cfg["robust"], phasecenter=phasecenter,
            mask=mask_for_spw(cfg, mask_map, spw) if use_masks else "",
            restoringbeam=[f"{beam}arcsec"], pbcor=False, interactive=False,
        )
        image = Path(str(stem) + ".image")
        if image.is_dir():
            fits = Path(str(stem) + ".fits")
            exportfits(imagename=str(image), fitsimage=str(fits), overwrite=True)
            products.append({"spw": int(spw), "fits": str(fits)})
    montage = outdir / "all_spws.png"
    make_image_montage(products, all_freqs, montage,
                       label or f"EOVSA images after round {round_index}")
    return {"fits": products, "montage": str(montage)}


def survey(config_path):
    """Make the pre-mask all-SPW image survey used to choose mask groups."""
    cfg_path, cfg, full_ms = load_config(config_path)
    if platform.machine() != "arm64":
        raise SystemExit("Run the modern workflow in the native arm64 environment, not Rosetta.")
    root, manifest = safe_new_run(cfg_path, cfg)
    short_ms = root / "short_peak.ms"
    split(vis=str(full_ms), outputvis=str(short_ms), datacolumn="data",
          timerange=cfg["timerange"], correlation=cfg["correlation"], antenna=cfg["antenna"])
    clearcal(str(short_ms))
    all_freqs = frequencies(short_ms)
    manifest["mode"] = "pre_mask_spw_survey"
    manifest["survey_qa"] = image_qa(
        short_ms, cfg, root, phasecenter_for(full_ms, cfg), {}, 0, all_freqs,
        use_masks=False, label="Pre-mask per-SPW survey (use this to choose mask groups)"
    )
    save_manifest(root, manifest)
    print(f"\nSurvey montage: {manifest['survey_qa']['montage']}")
    print("Review adjacent SPWs, then update mask_spw_groups in the event config before running selfcal.")


def run(config_path):
    cfg_path, cfg, full_ms = load_config(config_path)
    if platform.machine() != "arm64":
        raise SystemExit("Run the modern workflow in the native arm64 environment, not Rosetta.")
    phasecenter = phasecenter_for(full_ms, cfg)
    root, manifest = safe_new_run(cfg_path, cfg)
    short_ms = root / "short_peak.ms"
    split(vis=str(full_ms), outputvis=str(short_ms), datacolumn="data",
          timerange=cfg["timerange"], correlation=cfg["correlation"], antenna=cfg["antenna"])
    clearcal(str(short_ms))
    mask_map = draw_masks(short_ms, cfg, root, phasecenter, corrected=True)
    all_freqs = frequencies(short_ms)
    manifest["initial_qa_images"] = image_qa(
        short_ms, cfg, root, phasecenter, mask_map, 0, all_freqs, use_masks=True
    )
    save_manifest(root, manifest)
    accepted = []

    for round_index in range(1, cfg["max_rounds"] + 1):
        calmode = ask_choice("Solve this round as phase (p), amplitude (a), or both (ap)? ", {"p", "a", "ap"})
        niter = int(input("Model-image iterations (for example 100): ").strip())
        caltable = root / "caltables" / f"round_{round_index:02d}.{calmode}.G"
        solved_any = False
        for spw in cfg["selfcal_spws"]:
            print(f"\nRound {round_index}; SPW {spw}")
            model_spw = clean_model(short_ms, cfg, root, phasecenter, mask_map, spw,
                                    round_index, niter, all_freqs)
            gaincal(
                vis=str(short_ms), refant=cfg["refant"], antenna=antenna_for_spw(cfg, spw),
                caltable=str(caltable), spw=str(spw),
                uvrange="" if calmode == "p" else cfg["uvrange"],
                gaintable=[str(x) for x in accepted], selectdata=True,
                timerange=cfg["timerange"], solint="inf", gaintype="G",
                calmode=calmode, combine="",
                minblperant=cfg.get("minblperant", 3),
                minsnr=cfg.get("minsnr", 2.0),
                append=solved_any,
            )
            solved_any = caltable.is_dir()
            print(f"Model SPW selection: {model_spw}")
            remove_casa_image_products(root / "models" / f"round_{round_index:02d}_spw_{int(spw):02d}")
        if not solved_any:
            raise RuntimeError(f"No gain solutions were written for round {round_index}")

        gain_qa(short_ms, caltable, root / "qa" / f"round_{round_index:02d}")
        clearcal(str(short_ms)); delmod(str(short_ms))
        candidate = accepted + [caltable]
        apply_tables(short_ms, cfg, candidate)
        qa_images = image_qa(short_ms, cfg, root, phasecenter, mask_map,
                             round_index, all_freqs, use_masks=False)

        print(f"\nQA is in {root / 'qa' / f'round_{round_index:02d}'}")
        decision = ask_choice("Accept this gain table (a), reject/stop (r), or accept and continue (c)? ", {"a", "r", "c"})
        if decision == "r":
            clearcal(str(short_ms)); delmod(str(short_ms))
            if accepted:
                apply_tables(short_ms, cfg, accepted)
            manifest["rounds"].append({"round": round_index, "calmode": calmode, "accepted": False})
            save_manifest(root, manifest)
            break
        accepted.append(caltable)
        manifest["rounds"].append({"round": round_index, "calmode": calmode,
                                   "niter": niter, "accepted": True,
                                   "caltable": str(caltable), "qa_images": qa_images})
        save_manifest(root, manifest)
        if decision == "a":
            break
        if ask_choice("Update masks before the next round? (y/n) ", {"y", "n"}) == "y":
            mask_map = draw_masks(short_ms, cfg, root, phasecenter, corrected=True)

    if not accepted:
        raise SystemExit(f"No accepted rounds. Run retained for diagnosis: {root}")
    final_short = root / "final" / "short_peak.selfcal.ms"
    split(vis=str(short_ms), outputvis=str(final_short), datacolumn="corrected")
    manifest["final_short_ms"] = str(final_short)
    save_manifest(root, manifest)
    print(f"\nFinal short self-calibrated MS: {final_short}")
    print("The original full MS was not modified.")
    print("Review all QA before applying these tables to the full-duration MS.")


def mask_only(config_path):
    cfg_path, cfg, vis = load_config(config_path)
    phasecenter = phasecenter_for(vis, cfg)
    root, manifest = safe_new_run(cfg_path, cfg)
    manifest["mask_only"] = True
    draw_masks(vis, cfg, root, phasecenter, corrected=True)
    save_manifest(root, manifest)
    print(f"Masks saved under: {root / 'masks'}")


def apply_full(config_path, run_dir):
    """Apply accepted short-interval tables to a copy, never to the input MS."""
    _, cfg, full_ms = load_config(config_path)
    root = Path(run_dir).expanduser().resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    tables = [r["caltable"] for r in manifest["rounds"] if r.get("accepted")]
    if not tables:
        raise SystemExit("Manifest contains no accepted gain tables.")
    print("This will copy the full input MS, apply the accepted tables, and write a final MS.")
    if input("Type APPLY to continue: ").strip() != "APPLY":
        raise SystemExit("Cancelled; no full-duration data were changed.")
    working = root / "final" / "full_duration.working.ms"
    final = root / "final" / "full_duration.selfcal.ms"
    if working.exists() or final.exists():
        raise SystemExit("Full-duration output already exists; refusing to overwrite it.")
    split(vis=str(full_ms), outputvis=str(working), datacolumn="data")
    clearcal(str(working))
    apply_tables(working, cfg, tables)
    split(vis=str(working), outputvis=str(final), datacolumn="corrected",
          spw=",".join(map(str, cfg["selfcal_spws"])),
          correlation=cfg["correlation"], antenna=cfg["antenna"])
    manifest["final_full_ms"] = str(final)
    manifest["full_apply_working_copy"] = str(working)
    save_manifest(root, manifest)
    print(f"Final full-duration self-calibrated MS: {final}")
    print(f"Working copy retained for recovery/audit: {working}")


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in {"survey", "mask", "run", "apply-full"}:
        raise SystemExit("usage: selfcal.py {survey|mask|run} CONFIG.json\n"
                         "   or: selfcal.py apply-full CONFIG.json RUN_DIR")
    if sys.argv[1] == "survey" and len(sys.argv) == 3: survey(sys.argv[2])
    elif sys.argv[1] == "mask" and len(sys.argv) == 3: mask_only(sys.argv[2])
    elif sys.argv[1] == "run" and len(sys.argv) == 3: run(sys.argv[2])
    elif sys.argv[1] == "apply-full" and len(sys.argv) == 4: apply_full(sys.argv[2], sys.argv[3])
    else: raise SystemExit("Wrong number of arguments; run without arguments for usage.")


if __name__ == "__main__":
    main()
