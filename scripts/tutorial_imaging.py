#!/usr/bin/env python3
"""SunCASA tutorial-style FITS and PNG imaging before/after self-cal."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

# Keep SunPy/Matplotlib caches inside this project.  This must happen before
# importing CASA/SunCASA because both may import Matplotlib during start-up.
PROJECT = Path(__file__).resolve().parents[1]
RUNTIME = PROJECT / ".runtime"
os.environ.setdefault("SUNPY_CONFIGDIR", str(RUNTIME / "sunpy"))
os.environ.setdefault("MPLCONFIGDIR", str(RUNTIME / "matplotlib"))
Path(os.environ["SUNPY_CONFIGDIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits
from astropy.time import Time
from casatasks import split
from casatools import table


def antenna_for_spw(cfg: dict, spw: int) -> str:
    for span, selection in cfg.get("antenna_by_spw", {}).items():
        lo, hi = map(int, span.split("~"))
        if lo <= spw <= hi:
            return selection
    return cfg["antenna"]


def make_qlook_spectrum(ms: Path, destination: Path) -> None:
    """Make a robust median XX spectrum without SunCASA's baseline-index bug.

    SunCASA 1.0.8.2's automatic Dspec baseline selection fails on this EOVSA
    MS because its antenna-pair index exceeds the compact baseline axis.  The
    quick-look CLEAN is independent of that spectrum.  This replacement still
    gives the tutorial summary a scientifically useful median cross-power panel.
    """
    tb = table()
    tb.open(str(ms))
    times_all = np.asarray(tb.getcol("TIME"), dtype=float)
    ddids = np.asarray(tb.getcol("DATA_DESC_ID"), dtype=int)
    ant1 = np.asarray(tb.getcol("ANTENNA1"), dtype=int)
    ant2 = np.asarray(tb.getcol("ANTENNA2"), dtype=int)
    data = np.asarray(tb.getcol("DATA"))
    flags = np.asarray(tb.getcol("FLAG"), dtype=bool)
    tb.close()
    tb.open(str(ms / "DATA_DESCRIPTION"))
    dd_spw = np.asarray(tb.getcol("SPECTRAL_WINDOW_ID"), dtype=int)
    tb.close()
    tb.open(str(ms / "SPECTRAL_WINDOW"))
    freqs = np.asarray(tb.getcol("REF_FREQUENCY"), dtype=float)
    tb.close()

    times = np.unique(times_all)
    time_index = {value: index for index, value in enumerate(times)}
    samples = [[[] for _ in times] for _ in freqs]
    for row in range(data.shape[-1]):
        if ant1[row] == ant2[row]:
            continue
        spw = int(dd_spw[ddids[row]])
        good = ~flags[0, :, row]
        values = np.abs(data[0, good, row])
        # EOVSA MS rows contain many literal zero placeholders that are not
        # marked by FLAG.  Including them made every SPW >=2 have median zero,
        # producing the black "spectrum" seen in early trial summaries.
        values = values[np.isfinite(values) & (values > 0)]
        if values.size:
            samples[spw][time_index[times_all[row]]].append(float(np.nanmedian(values)))
    plane = np.full((len(freqs), len(times)), np.nan)
    for spw in range(len(freqs)):
        for tidx in range(len(times)):
            if samples[spw][tidx]:
                plane[spw, tidx] = np.nanmedian(samples[spw][tidx])
    fill = np.nanmedian(plane[np.isfinite(plane)]) if np.any(np.isfinite(plane)) else 0.0
    plane[~np.isfinite(plane)] = fill
    spec = plane[None, None, :, :]
    np.savez(destination, spec=spec, tim=times, freq=freqs,
             bl="median cross-power", pol=np.asarray(["XX"]))


def render_spectrum(specfile: Path, output: Path, title: str) -> None:
    """Save an independently readable PNG of the real median-XX spectrum."""
    with np.load(specfile, allow_pickle=True) as payload:
        plane = np.asarray(payload["spec"])[0, 0]
        times = np.asarray(payload["tim"], dtype=float)
        freqs = np.asarray(payload["freq"], dtype=float) / 1.0e9
    positive = plane[np.isfinite(plane) & (plane > 0)]
    floor = np.nanpercentile(positive, 1) if positive.size else 1.0
    display = np.log10(np.maximum(plane, floor))
    seconds = times - times[0]
    fig, ax = plt.subplots(figsize=(8.5, 5), constrained_layout=True)
    image = ax.pcolormesh(seconds, freqs, display, shading="auto", cmap="inferno")
    for edge in (2, 4, 5, 6, 7, 8, 9, 10, 12, 14):
        ax.axhline(edge, color="white", alpha=0.18, linewidth=0.6)
    ax.set(title=title, xlabel="Seconds from 16:47:12 UT",
           ylabel="Frequency (GHz)")
    fig.colorbar(image, ax=ax, label="log10 median |XX| (native MS units)")
    fig.savefig(output, dpi=180)
    plt.close(fig)


def range_tag(selection: str) -> str:
    return selection.lower().replace("ghz", "").replace("~", "_to_").replace(".", "p")


def antenna_for_frequency_range(cfg: dict, selection: str) -> str:
    """Use the intersection of valid antennas across a GHz MFS range."""
    upper = float(selection.lower().replace("ghz", "").split("~")[-1])
    if upper > 9.3 and "23~49" in cfg.get("antenna_by_spw", {}):
        return cfg["antenna_by_spw"]["23~49"]
    return cfg["antenna"]


def image_plane(path: Path) -> tuple[np.ndarray, fits.Header]:
    with fits.open(path) as hdus:
        items = [(np.asarray(hdu.data), hdu.header.copy()) for hdu in hdus if hdu.data is not None]
    if not items:
        raise ValueError(f"No image array found in {path}")
    data, header = items[0]
    data = np.squeeze(data)
    while data.ndim > 2:
        data = data[0]
    return np.asarray(data, dtype=float), header


def solar_extent(header: fits.Header, shape: tuple[int, int]) -> list[float]:
    nx, ny = shape[1], shape[0]
    dx, dy = float(header["CDELT1"]), float(header["CDELT2"])
    x0 = float(header["CRVAL1"]) + (0.5 - float(header["CRPIX1"])) * dx
    x1 = float(header["CRVAL1"]) + (nx + 0.5 - float(header["CRPIX1"])) * dx
    y0 = float(header["CRVAL2"]) + (0.5 - float(header["CRPIX2"])) * dy
    y1 = float(header["CRVAL2"]) + (ny + 0.5 - float(header["CRPIX2"])) * dy
    return [x0, x1, y0, y1]


def render_pair(before: Path, after: Path, output: Path, title: str) -> None:
    """Render matched-scale diagnostic maps.

    These qlookplot products are deliberately shallow/dirty QA maps.  Their
    sidelobes must not be interpreted as solar sources or as final restored
    science imaging; the mask-guided round mosaics remain the image-quality
    test used to accept a self-cal round.
    """
    a, ah = image_plane(before)
    b, bh = image_plane(after)
    finite = np.concatenate((a[np.isfinite(a)], b[np.isfinite(b)]))
    if finite.size:
        vmin, vmax = np.nanpercentile(finite, [1.0, 99.7])
    else:
        vmin, vmax = 0.0, 1.0
    fig, axes = plt.subplots(1, 2, figsize=(11, 5), constrained_layout=True)
    for ax, data, header, label in zip(
            axes, (a, b), (ah, bh), ("Before: DATA", "After: CORRECTED_DATA")):
        extent = solar_extent(header, data.shape)
        im = ax.imshow(data, origin="lower", extent=extent, cmap="inferno",
                       vmin=vmin, vmax=vmax)
        rsun = float(header.get("RSUN_OBS", 0.0))
        if rsun > 0:
            ax.add_patch(plt.Circle((0, 0), rsun, fill=False, color="0.75",
                                    linewidth=1.4, linestyle="--"))
        ax.set_title(label)
        ax.set_xlabel("Solar X (arcsec)")
        ax.set_ylabel("Solar Y (arcsec)")
        ax.set_aspect("equal")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.suptitle(title)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("run_dir")
    parser.add_argument("--spws", default="5,12,18,24,30",
                        help="Comma-separated representative flare-region SPWs")
    parser.add_argument(
        "--frequency-ranges",
        default="2~4GHz,5~6GHz,7~8GHz,9~10GHz,10~12GHz,12~14GHz,10~14GHz",
        help="Comma-separated full-Sun/tutorial imaging frequency selections")
    parser.add_argument("--tutorial-summary", action="store_true",
                        help="Also download AIA 171 and save SunCASA summary figures")
    parser.add_argument(
        "--multiband", action="store_true",
        help="Make tutorial-style, color-coded individual-SPW overlays on AIA 171")
    parser.add_argument("--reimage", action="store_true",
                        help="Regenerate FITS even when completed products already exist")
    args = parser.parse_args()

    try:
        from suncasa.utils import qlookplot as ql
    except (ImportError, ModuleNotFoundError) as exc:
        raise SystemExit("Run with the verified x86 CASA/SunCASA Python; see README.") from exc

    cfg = json.loads(Path(args.config).expanduser().resolve().read_text())
    run = Path(args.run_dir).expanduser().resolve()
    source = run / "short_peak.ms"
    if not source.is_dir():
        raise SystemExit(f"Run short MS not found: {source}")

    out = run / "qa" / "tutorial_imaging"
    out.mkdir(parents=True, exist_ok=True)
    before_ms, after_ms = out / "before_data.ms", out / "after_corrected.ms"
    if not before_ms.exists():
        split(vis=str(source), outputvis=str(before_ms), datacolumn="data")
    if not after_ms.exists():
        split(vis=str(source), outputvis=str(after_ms), datacolumn="corrected")
    if not (before_ms.is_dir() and after_ms.is_dir()):
        raise SystemExit("Only one disposable split exists; move tutorial_imaging aside and rerun.")

    mfs = {"before": {}, "after": {}}
    flare = {"before": {}, "after": {}}
    representative_spws = [int(x) for x in args.spws.split(",") if x.strip()]
    frequency_ranges = [x.strip() for x in args.frequency_ranges.split(",") if x.strip()]
    # Old SunCASA uses unquoted shell `mv` commands internally.  Its temporary
    # and output paths therefore cannot contain spaces (the project lives under
    # iCloud's "Mobile Documents").  Work in /tmp and copy completed FITS back.
    with tempfile.TemporaryDirectory(prefix="eovsa_qlook_") as scratch_name:
        scratch = Path(scratch_name)
        specfiles = {}
        for label, vis in (("before", before_ms), ("after", after_ms)):
            specfiles[label] = scratch / f"{label}.dspec.npz"
            make_qlook_spectrum(vis, specfiles[label])
            render_spectrum(specfiles[label], out / f"dynamic_spectrum_{label}.png",
                            f"EOVSA median XX spectrum — {label.upper()}")
        timerange, stokes = cfg["timerange"], cfg["correlation"]
        common = dict(timerange=timerange, stokes=stokes, plotaia=False,
                      specfile=str(specfiles["after"]), workdir=str(scratch), quiet=True,
                      robust=cfg["robust"], gain=cfg["gain"], overwrite=True)

        def run_to(destination: Path, **kwargs) -> None:
            if destination.is_file() and not args.reimage:
                print(f"Reusing existing FITS: {destination}")
                return
            scratch_fits = scratch / destination.name
            # qlookplot changes the process working directory and does not put
            # it back.  Restore it even on failure so TemporaryDirectory never
            # removes the process's current directory underneath CASA.
            starting_directory = os.getcwd()
            try:
                ql.qlookplot(outfits=str(scratch_fits), **kwargs, **common)
            finally:
                os.chdir(starting_directory)
            if not scratch_fits.is_file():
                raise RuntimeError(f"SunCASA did not create expected FITS: {scratch_fits}")
            shutil.copy2(scratch_fits, destination)

        for label, vis in (("before", before_ms), ("after", after_ms)):
            for frequency_range in frequency_ranges:
                tag = range_tag(frequency_range)
                mfs[label][frequency_range] = out / f"{label}_flare_mfs_{tag}.fits"
                print(f"Making flare MFS {frequency_range} FITS: {mfs[label][frequency_range]}")
                # These MFS maps intentionally match the self-cal science:
                # flare-centered phase center, >500-lambda cutoff, event FOV,
                # and the SPW-dependent usable-antenna intersection.  Cleaning
                # an unmasked 2560-arcsec full disk created sidelobe contours
                # across the AIA disk and was not a fair self-cal comparison.
                run_to(mfs[label][frequency_range], vis=str(vis), spw=frequency_range,
                       antenna=antenna_for_frequency_range(cfg, frequency_range),
                       uvrange=cfg["uvrange"], xycen=cfg["xycen_arcsec"],
                       fov=cfg["fov_arcsec"], cell=[f'{cfg["cell_arcsec"]}arcsec'],
                       imsize=[cfg["imsize"]], niter=cfg["qa_image_niter"],
                       usemsphacenter=False)

            for spw in representative_spws:
                flare[label][spw] = out / f"{label}_flare_spw_{spw:02d}.fits"
                print(f"Making flare-region SPW {spw} FITS: {flare[label][spw]}")
                run_to(
                    flare[label][spw], vis=str(vis), spw=str(spw),
                    antenna=antenna_for_spw(cfg, spw), uvrange=cfg["uvrange"],
                    xycen=cfg["xycen_arcsec"], fov=cfg["fov_arcsec"],
                    cell=[f'{cfg["cell_arcsec"]}arcsec'], imsize=[cfg["imsize"]],
                    niter=cfg["qa_image_niter"], usemsphacenter=False)

        # Write the essential before/after products before optional network
        # downloads and the slow SunCASA summary loop.  A failed/interrupted
        # AIA or GOES request can therefore never suppress these PNGs again.
        for frequency_range in frequency_ranges:
            tag = range_tag(frequency_range)
            render_pair(
                mfs["before"][frequency_range], mfs["after"][frequency_range],
                out / f"before_after_flare_mfs_{tag}.png",
                f"EOVSA {frequency_range.replace('~', '–')} flare MFS dirty-map diagnostic")

        if args.tutorial_summary:
            # Reuse the already-created radio FITS and ask SunCASA only to make
            # the tutorial visualization: spectrum, GOES, AIA 171, full disk,
            # flare zoom, limb/grid, and radio contours.
            start_text, stop_text = timerange.split("~")
            to_isot = lambda value: value.replace("/", "-", 2).replace("/", "T", 1)
            endpoints = Time([to_isot(start_text), to_isot(stop_text)])
            aia_time = Time(np.mean(endpoints.jd), format="jd")
            # Prefer FITS through Fido.  The default SunCASA downloader returns
            # JP2, which this x86 CASA/SunPy build downloads but cannot decode.
            from astropy import units as u
            from sunpy import map as sunmap
            aia_downloads = ql.download_using_fido(
                Time(aia_time.jd - 6 / 86400, format="jd"),
                Time(aia_time.jd + 6 / 86400, format="jd"),
                [171], 12 * u.second, scratch)
            aia_files = []
            for item in aia_downloads:
                candidate = Path(str(item))
                if not candidate.is_file() or candidate.suffix.lower() not in (".fits", ".fts"):
                    continue
                try:
                    sunmap.Map(candidate)
                except Exception as exc:
                    print(f"Rejected unreadable AIA file {candidate}: {exc}")
                else:
                    aia_files.append(candidate)
            if not aia_files:
                raise RuntimeError(
                    "AIA 171 download failed. No tutorial summary was saved; "
                    "rerun with working network access and inspect the download error above.")
            aia_file = aia_files[0].resolve()
            print(f"Using validated AIA 171 image: {aia_file}")
            for label, vis in (("before", before_ms), ("after", after_ms)):
                for frequency_range in frequency_ranges:
                    tag = range_tag(frequency_range)
                    summary_fits = scratch / mfs[label][frequency_range].name
                    shutil.copy2(mfs[label][frequency_range], summary_fits)
                    starting_directory = os.getcwd()
                    try:
                        ql.qlookplot(
                            vis=str(vis), specfile=str(specfiles[label]), timerange=timerange,
                            spw=frequency_range, stokes=stokes,
                            antenna=antenna_for_frequency_range(cfg, frequency_range),
                            workdir=str(scratch), outfits=str(summary_fits),
                            overwrite=False, quiet=False, plotaia=True, aiawave=171,
                            aiafits=str(aia_file),
                            xycen=cfg["xycen_arcsec"], fov=cfg["fov_arcsec"],
                            usemsphacenter=False, dnorm="log",
                            # Positive high-level contours suppress sidelobes
                            # and match the tutorial's compact-source display.
                            clevels=[0.60, 0.75, 0.90], opencontour=True,
                            calpha=0.95)
                        plt.gcf().savefig(
                            out / f"tutorial_summary_{label}_{tag}.png", dpi=180)
                        plt.close(plt.gcf())
                    finally:
                        os.chdir(starting_directory)

            if args.multiband:
                # This follows the EOVSA tutorial's multi-band recipe: a list
                # of individual SPWs creates one frequency plane per SPW.  It
                # is intentionally different from strings such as '10~14GHz',
                # which combine a range into one MFS image.  Keep only SPWs
                # explicitly approved after the updated-calibration survey.
                multiband_spws = [
                    int(value) for value in cfg.get(
                        "final_imaging_spws", cfg["selfcal_spws"])
                ]
                if not multiband_spws:
                    raise RuntimeError("final_imaging_spws is empty")
                spw_list = [str(value) for value in multiband_spws]
                # One antenna selection must be valid for the whole cube.  Use
                # the conservative high-SPW override when the list crosses it.
                multiband_antenna = cfg["antenna"]
                if max(multiband_spws) >= 23:
                    multiband_antenna = cfg.get("antenna_by_spw", {}).get(
                        "23~49", multiband_antenna)
                for label, vis in (("before", before_ms), ("after", after_ms)):
                    cube = out / f"multiband_{label}.image.fits"
                    summary = out / f"multiband_aia171_{label}.png"
                    scratch_cube = scratch / cube.name
                    starting_directory = os.getcwd()
                    try:
                        ql.qlookplot(
                            vis=str(vis), specfile=str(specfiles[label]),
                            timerange=timerange, spw=spw_list, stokes=stokes,
                            antenna=multiband_antenna, uvrange=cfg["uvrange"],
                            workdir=str(scratch), outfits=str(scratch_cube),
                            overwrite=True, quiet=False, plotaia=True,
                            aiawave=171, aiafits=str(aia_file),
                            xycen=cfg["xycen_arcsec"], fov=cfg["fov_arcsec"],
                            imsize=[cfg["imsize"]],
                            cell=[f'{cfg["cell_arcsec"]}arcsec'],
                            usemsphacenter=False, restoringbeam=["6arcsec"],
                            clevels=[0.5, 1.0], calpha=0.35,
                        )
                        if not scratch_cube.is_file():
                            raise RuntimeError(
                                f"SunCASA did not create multi-band cube: {scratch_cube}")
                        shutil.copy2(scratch_cube, cube)
                        plt.gcf().savefig(summary, dpi=180)
                        plt.close(plt.gcf())
                    finally:
                        os.chdir(starting_directory)
                (out / "multiband_spws.txt").write_text(
                    "Individual SPWs used: " + ",".join(spw_list) + "\n"
                    "Bands outside selfcal_spws are pipeline-calibrated context only.\n")

    for spw in representative_spws:
        render_pair(flare["before"][spw], flare["after"][spw],
                    out / f"before_after_flare_spw_{spw:02d}.png",
                    f"EOVSA flare-region comparison — SPW {spw}")

    print(f"\nFITS and PNG products: {out}")
    print("PNG files:")
    for path in sorted(out.glob("*.png")):
        print(path)


if __name__ == "__main__":
    main()
