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

# CASA must be imported before Matplotlib/Astropy in the SunCASA conda
# environment.  Importing the astronomy/plotting stack first can preload an
# incompatible libssl, after which casatools' bundled libcurl fails with
# ``Symbol not found: _SSL_get0_group_name`` on macOS.
from casatasks import split
from casatools import table
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS


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


def render_frequency_outline_overlay(
        cube_path: Path, aia_path: Path, output: Path, cfg: dict, label: str) -> None:
    """Draw one compact, color-coded contour for each selected frequency.

    This is the line-contour companion to SunCASA's filled multi-SPW summary.
    It intentionally uses a small set of representative frequencies rather
    than drawing all 47 planes: all-plane outlines become unreadable and can
    make dirty-beam sidelobes look like solar structure.  Each contour level
    is a fraction of that frequency plane's *flare-region* positive peak, not
    its full-field peak.  That distinction is important for this limb event.
    """
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    from matplotlib.colors import BoundaryNorm
    from matplotlib.cm import ScalarMappable
    from scipy.ndimage import binary_dilation, label as label_components
    from skimage.measure import find_contours
    import sunpy.map

    with fits.open(cube_path) as hdus:
        image_hdu = next(hdu for hdu in hdus if hdu.data is not None and hdu.data.ndim >= 3)
        cube = np.asarray(image_hdu.data, dtype=float)
        cube_header = image_hdu.header.copy()
        table_hdu = next((hdu for hdu in hdus if hdu.data is not None and
                          getattr(hdu.data, "names", None) and "cfreqs" in hdu.data.names), None)
        if table_hdu is None:
            raise RuntimeError(f"No cfreqs table found in {cube_path}")
        frequencies = np.asarray(table_hdu.data["cfreqs"], dtype=float) / 1.0e9
    cube = np.squeeze(cube)
    if cube.ndim != 3 or cube.shape[0] != frequencies.size:
        raise RuntimeError(
            f"Unexpected multi-band cube shape {cube.shape} for {frequencies.size} frequencies")

    aia_map = sunpy.map.Map(str(aia_path))
    # A 1024x1024 AIA browse product has 2.4 arcsec pixels.  Enlarging its
    # small limb-event crop produces the blocky background that can easily be
    # mistaken for plotting blur.  Do not silently make that product.
    aia_scale = max(abs(aia_map.scale.axis1.to_value(u.arcsec / u.pix)),
                    abs(aia_map.scale.axis2.to_value(u.arcsec / u.pix)))
    if aia_scale > 1.0:
        raise RuntimeError(
            f"AIA input is only {aia_map.data.shape} at {aia_scale:.2f} arcsec/pixel. "
            "A publication-style flare crop requires a full-resolution AIA FITS "
            "(approximately 4096x4096 at 0.6 arcsec/pixel). Supply it with "
            "--aia-fits; the script will not enlarge this browse image.")
    radio_wcs = WCS(cube_header).celestial
    requested = cfg.get(
        "qlookplot_outline_frequencies_ghz",
        [2.9, 3.5, 4.5, 5.1, 6.8, 8.4, 9.7, 11.6])
    indices = []
    for value in requested:
        index = int(np.nanargmin(np.abs(frequencies - float(value))))
        if index not in indices:
            indices.append(index)
    selected = frequencies[indices]
    contour_fraction = float(cfg.get("qlookplot_outline_peak_fraction", 0.70))

    # Calculate thresholds only inside the requested flare-region field.  The
    # full 512-pixel radio cube contains far-field sidelobes that can otherwise
    # set the contour level and suppress the actual limb source.
    cx, cy = map(float, cfg["xycen_arcsec"])
    fx, fy = map(float, cfg.get("fov_arcsec", [256.0, 256.0]))
    ny, nx = cube.shape[-2:]
    yy, xx = np.mgrid[:ny, :nx]
    wx, wy = radio_wcs.pixel_to_world_values(xx, yy)
    # Astropy's WCS API returns celestial values in degrees even though the
    # FITS header stores the EOVSA axes in arcsec.
    wx, wy = np.asarray(wx) * 3600.0, np.asarray(wy) * 3600.0
    roi = ((np.abs(wx - cx) <= fx / 2.0) & (np.abs(wy - cy) <= fy / 2.0))

    fig = plt.figure(figsize=(8.4, 7.2), constrained_layout=True)
    ax = fig.add_subplot(111, projection=aia_map)
    finite_aia = aia_map.data[np.isfinite(aia_map.data)]
    lo, hi = np.nanpercentile(finite_aia, [1.0, 99.7])
    ax.imshow(aia_map.data, origin="lower", cmap="gray", vmin=lo, vmax=hi)

    # Deliberately avoid a rainbow map.  These warm, ordered colors follow the
    # visual language of the EOVSA flare-pipeline examples: low frequencies
    # are red/orange and high frequencies approach pale yellow/white.
    from matplotlib.colors import ListedColormap
    colors = [
        "#b32119", "#dc3b20", "#f05a28", "#f58b35",
        "#f6b94a", "#f4d875", "#fff0ad", "#fff8dc",
    ][:len(indices)]
    cmap = ListedColormap(colors)
    used_freqs = []
    bottom_left = SkyCoord((cx - fx / 2) * u.arcsec, (cy - fy / 2) * u.arcsec,
                           frame=aia_map.coordinate_frame)
    top_right = SkyCoord((cx + fx / 2) * u.arcsec, (cy + fy / 2) * u.arcsec,
                         frame=aia_map.coordinate_frame)
    px0, py0 = aia_map.world_to_pixel(bottom_left)
    px1, py1 = aia_map.world_to_pixel(top_right)
    for color, index in zip(colors, indices):
        plane = cube[index]
        values = plane[roi & np.isfinite(plane) & (plane > 0)]
        if not values.size:
            print(f"Skipping {frequencies[index]:.3f} GHz: no positive flare-region pixels")
            continue
        level = contour_fraction * float(np.nanmax(values))
        # Find the compact source island on the native EOVSA grid.  Reprojecting
        # a full radio plane before contouring can turn a compact source into a
        # narrow limb-aligned arc because the FITS stores HPC axes in arcsec
        # while Astropy exposes celestial WCS values in degrees.  qlookplot's
        # reliable pattern is the reverse: contour natively, transform only the
        # resulting vertices, and leave the AIA pixels untouched.
        components, count = label_components(
            np.isfinite(plane) & roi & (plane >= level))
        if not count:
            print(f"Skipping {frequencies[index]:.3f} GHz: no source island")
            continue
        peak_image = np.where(roi & np.isfinite(plane), plane, -np.inf)
        peak_y, peak_x = np.unravel_index(np.argmax(peak_image), plane.shape)
        selected_component = int(components[peak_y, peak_x])
        if selected_component == 0:
            print(f"Skipping {frequencies[index]:.3f} GHz: peak island not found")
            continue
        source_island = components == selected_component
        source_support = binary_dilation(source_island, iterations=2)
        contour_image = np.where(source_support, plane, np.nan)
        native_paths = find_contours(contour_image, level=level)
        if not native_paths:
            print(f"Skipping {frequencies[index]:.3f} GHz: contour not closed")
            continue
        for path in native_paths:
            # skimage returns vertices as (row, column).  Convert native radio
            # pixels to HPC, then HPC to the exact AIA detector-pixel grid.
            radio_x_deg, radio_y_deg = radio_wcs.pixel_to_world_values(
                path[:, 1], path[:, 0])
            contour_world = SkyCoord(
                np.asarray(radio_x_deg) * u.deg,
                np.asarray(radio_y_deg) * u.deg,
                frame=aia_map.coordinate_frame)
            aia_x, aia_y = aia_map.world_to_pixel(contour_world)
            ax.plot(aia_x.value, aia_y.value, color=color, linewidth=2.0)
        used_freqs.append(float(frequencies[index]))

    ax.set_xlim(sorted([px0.value, px1.value]))
    ax.set_ylim(sorted([py0.value, py1.value]))
    ax.coords[0].set_axislabel("Solar X [arcsec]")
    ax.coords[1].set_axislabel("Solar Y [arcsec]")
    ax.set_title(f"AIA 171 Å + EOVSA XX contours ({label})")

    if used_freqs:
        bounds = np.r_[selected[0] - 0.2, (selected[:-1] + selected[1:]) / 2,
                       selected[-1] + 0.2]
        norm = BoundaryNorm(bounds, cmap.N)
        scalar = ScalarMappable(norm=norm, cmap=cmap)
        scalar.set_array([])
        cbar = fig.colorbar(scalar, ax=ax, ticks=selected, pad=0.025)
        cbar.set_label("Representative frequency [GHz]")
        cbar.ax.set_yticklabels([f"{value:.1f}" for value in selected])
    # AIA is displayed with native detector pixels and no smoothing.  This
    # avoids making a 1024-pixel cached AIA frame look artificially blurred.
    for image_artist in ax.images:
        image_artist.set_interpolation("none")
    fig.savefig(output, dpi=160)
    plt.close(fig)
    print(f"Saved frequency-outline overlay: {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("run_dir")
    parser.add_argument("--spws", default="5,12,18,24,30",
                        help="Comma-separated representative flare-region SPWs")
    parser.add_argument(
        "--frequency-ranges",
        default="5~6GHz,7~8GHz,9~10GHz,10~12GHz,12~14GHz,10~14GHz",
        help="Comma-separated full-Sun/tutorial imaging frequency selections")
    parser.add_argument("--tutorial-summary", action="store_true",
                        help="Also download AIA 171 and save SunCASA summary figures")
    parser.add_argument(
        "--aia-fits", default=None,
        help="Optional local AIA 171 FITS; it is validated, cached in the run, and reused")
    parser.add_argument(
        "--multiband", action="store_true",
        help="Make tutorial-style, color-coded individual-SPW overlays on AIA 171")
    parser.add_argument(
        "--contour-overlay-only", action="store_true",
        help="Render frequency-outline PNGs from existing multi-band cubes; do no imaging")
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
    if args.contour_overlay_only:
        # Honour an explicit full-resolution file in the fast rendering path.
        # Otherwise inspect every cached FITS and choose the finest AIA plate
        # scale; filename sorting previously selected the 1024-pixel browse
        # product even when a full-resolution Level-1 file was available.
        if args.aia_fits:
            aia_path = Path(args.aia_fits).expanduser().resolve()
            if not aia_path.is_file():
                raise SystemExit(f"AIA FITS not found: {aia_path}")
        else:
            import astropy.units as u
            import sunpy.map
            candidates = []
            for candidate in sorted(out.glob("*.fits")):
                try:
                    candidate_map = sunpy.map.Map(str(candidate))
                    if "AIA" not in str(candidate_map.meta.get("instrume", "")).upper():
                        continue
                    scale = max(abs(candidate_map.scale.axis1.to_value(u.arcsec / u.pix)),
                                abs(candidate_map.scale.axis2.to_value(u.arcsec / u.pix)))
                    candidates.append((scale, candidate))
                except Exception:
                    continue
            if not candidates:
                raise SystemExit(f"No cached AIA 171 FITS found in {out}")
            aia_path = min(candidates)[1]
        print(f"Using AIA for contour overlays: {aia_path}")
        for label in ("before", "after"):
            cube = out / f"multiband_{label}.image.fits"
            if not cube.is_file():
                raise SystemExit(f"Existing multi-band cube not found: {cube}")
            render_frequency_outline_overlay(
                cube, aia_path,
                out / f"multiband_frequency_outlines_aia171_{label}.png",
                cfg, label)
        return
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
            # Keep the AIA file in the run directory.  JSOC/SDO exports can
            # time out even with a healthy local internet connection, and a
            # file kept only in TemporaryDirectory is lost after every run.
            aia_cache = out / "aia171_20240514T164721.fits"
            aia_downloads = []
            if args.aia_fits:
                aia_downloads = [Path(args.aia_fits).expanduser().resolve()]
            elif aia_cache.is_file():
                aia_downloads = [aia_cache]
                print(f"Reusing cached AIA 171 image: {aia_cache}")
            else:
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
            if aia_file != aia_cache.resolve():
                shutil.copy2(aia_file, aia_cache)
                aia_file = aia_cache.resolve()
                print(f"Cached AIA 171 image for future runs: {aia_file}")
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
                        "qlookplot_multiband_spws",
                        cfg.get("final_imaging_spws", cfg["selfcal_spws"]))
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
                multiband_niter = int(cfg.get("qlookplot_multiband_niter", 100))
                multiband_cell = float(cfg.get("qlookplot_multiband_cell_arcsec", 5.0))
                multiband_imsize = int(cfg.get("qlookplot_multiband_imsize", 512))
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
                            imsize=[multiband_imsize],
                            cell=[f'{multiband_cell}arcsec'],
                            niter=multiband_niter,
                            # Leave restoringbeam at SunCASA's default.  This
                            # release collapses explicit equal beam lists to a
                            # single entry and then indexes that entry once per
                            # SPW, causing an IndexError.  Its automatic EOVSA
                            # beam calculation returns one appropriate beam per
                            # frequency plane and follows qlookplot's documented
                            # multi-SPW behavior.
                            usemsphacenter=False,
                            # Three positive fractional contours per band make
                            # the source morphology visible without letting
                            # negative dirty-beam sidelobes dominate the AIA.
                            clevels=[0.50, 0.70, 0.90], calpha=0.55,
                        )
                        if not scratch_cube.is_file():
                            raise RuntimeError(
                                f"SunCASA did not create multi-band cube: {scratch_cube}")
                        shutil.copy2(scratch_cube, cube)
                        plt.gcf().savefig(summary, dpi=180)
                        # Descriptive aliases make the requested Meiqi-style
                        # qlookplot products immediately recognizable in the
                        # run directory and in a published GitHub gallery.
                        shutil.copy2(
                            summary,
                            out / f"qlookplot_all_frequencies_aia171_{label}.png")
                        plt.close(plt.gcf())
                        render_frequency_outline_overlay(
                            cube, aia_file,
                            out / f"multiband_frequency_outlines_aia171_{label}.png",
                            cfg, label)
                    finally:
                        os.chdir(starting_directory)
                (out / "multiband_spws.txt").write_text(
                    "Individual SPWs used: " + ",".join(spw_list) + "\n"
                    f"Antenna selection: {multiband_antenna}\n"
                    f"Timerange: {timerange}\n"
                    f"Stokes/correlation: {stokes}\n"
                    f"uvrange: {cfg['uvrange']}\n"
                    f"imsize: {multiband_imsize}\n"
                    f"cell: {multiband_cell}arcsec\n"
                    f"niter: {multiband_niter}\n"
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
