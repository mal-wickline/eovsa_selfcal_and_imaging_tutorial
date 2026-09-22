#!/usr/bin/env python3
"""Create the pre-self-calibration spectrum and full-disk location checks."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
RUNTIME = PROJECT / ".runtime"
os.environ.setdefault("CASA_DATA_UPDATE_CHECK", "0")
os.environ.setdefault("MPLCONFIGDIR", str(RUNTIME / "matplotlib"))
os.environ.setdefault("SUNPY_CONFIGDIR", str(RUNTIME / "sunpy"))
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["SUNPY_CONFIGDIR"]).mkdir(parents=True, exist_ok=True)

# Import CASA first: loading Matplotlib first can preload an incompatible SSL
# library in some SunCASA installations.
from casatasks import tclean
from casatools import table
import astropy.units as u
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from astropy.time import Time
from sunpy.coordinates import sun
import sunpy.map
from suncasa.utils import helioimage2fits as hf


def parse_timerange(value: str) -> tuple[Time, Time]:
    start, stop = value.split("~", 1)
    fmt = "%Y/%m/%d/%H:%M:%S"
    return Time.strptime(start, fmt), Time.strptime(stop, fmt)


def offline_ephemeris(midpoint: Time) -> dict:
    """Return the solar ephemeris fields required by SunCASA imreg()."""
    ra, dec = sun.sky_position(midpoint)
    return {
        "time": [float(midpoint.mjd)],
        "ra": [ra.to_value(u.rad)],
        "dec": [dec.to_value(u.rad)],
        "p0": [sun.P(midpoint).to_value(u.deg)],
        "delta": [sun.earth_distance(midpoint).to_value(u.au)],
    }


def spw_metadata(ms: Path) -> tuple[np.ndarray, np.ndarray]:
    tb = table()
    tb.open(str(ms / "DATA_DESCRIPTION"), nomodify=True)
    dd_to_spw = np.asarray(tb.getcol("SPECTRAL_WINDOW_ID"), dtype=int)
    tb.close()
    tb.open(str(ms / "SPECTRAL_WINDOW"), nomodify=True)
    frequencies = np.asarray(tb.getcol("REF_FREQUENCY"), dtype=float)
    tb.close()
    return dd_to_spw, frequencies


def read_cross_power_spectrum(ms: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read median positive XX cross-power for every SPW and integration."""
    dd_to_spw, frequencies = spw_metadata(ms)
    tb = table()
    tb.open(str(ms), nomodify=True)
    all_times = np.unique(np.asarray(tb.getcol("TIME"), dtype=float))
    time_lookup = {value: index for index, value in enumerate(all_times)}
    spectrum = np.full((len(frequencies), len(all_times)), np.nan)

    for ddid, spw in enumerate(dd_to_spw):
        selected = tb.query(
            f"DATA_DESC_ID=={ddid} && ANTENNA1!=ANTENNA2 && !FLAG_ROW")
        try:
            times = np.asarray(selected.getcol("TIME"), dtype=float)
            data = np.asarray(selected.getcol("DATA"))
            flags = np.asarray(selected.getcol("FLAG"), dtype=bool)
        finally:
            selected.close()
        by_time: dict[int, list[float]] = {}
        for row, value in enumerate(times):
            good = (~flags[0, :, row]) & np.isfinite(data[0, :, row])
            samples = np.abs(data[0, good, row])
            # Some calibrated MSs contain literal zero placeholders that are
            # not flagged; exclude them from the quick-look statistic.
            samples = samples[samples > 0]
            if samples.size:
                by_time.setdefault(time_lookup[value], []).append(
                    float(np.nanmedian(samples)))
        for index, samples in by_time.items():
            spectrum[int(spw), index] = np.nanmedian(samples)
    tb.close()
    return all_times, frequencies, spectrum


def recommend_frequency_band(all_times: np.ndarray, frequencies: np.ndarray,
                             spectrum: np.ndarray,
                             timerange: str) -> tuple[float, float, np.ndarray]:
    """Recommend a 4 GHz band centered on the selected flare enhancement."""
    start, stop = parse_timerange(timerange)
    mjd = all_times / 86400.0
    on_flare = (mjd >= start.mjd) & (mjd <= stop.mjd)
    background = ((mjd >= start.mjd - 180.0 / 86400.0) &
                  (mjd <= start.mjd - 10.0 / 86400.0))
    if not np.any(background):
        background = ~on_flare
    baseline = np.nanmedian(spectrum[:, background], axis=1)
    excess = np.nanmedian(spectrum[:, on_flare], axis=1) - baseline
    freq_ghz = frequencies / 1e9
    usable = (freq_ghz >= 2.0) & (freq_ghz <= 16.0) & np.isfinite(excess)
    peak = freq_ghz[np.where(usable)[0][np.nanargmax(excess[usable])]]
    center = float(np.clip(np.round(peak), 4.0, 14.0))
    return center - 2.0, center + 2.0, baseline


def make_spectrogram(all_times: np.ndarray, frequencies: np.ndarray,
                     spectrum: np.ndarray, timerange: str, event_label: str,
                     output: Path) -> tuple[float, float]:
    """Make the EOVSA-style dynamic spectrum and frequency light curves."""
    dates = Time(all_times / 86400.0, format="mjd").to_datetime()
    positive = spectrum[np.isfinite(spectrum) & (spectrum > 0)]
    floor = np.nanpercentile(positive, 1) if positive.size else 1.0
    display = np.log10(np.maximum(spectrum, floor))
    start, stop = parse_timerange(timerange)
    low_ghz, high_ghz, baseline = recommend_frequency_band(
        all_times, frequencies, spectrum, timerange)
    freq_ghz = frequencies / 1e9

    fig, (ax_spec, ax_lc) = plt.subplots(
        2, 1, figsize=(11, 8), sharex=True, constrained_layout=True,
        gridspec_kw={"height_ratios": [1.35, 1.0]})
    mesh = ax_spec.pcolormesh(dates, freq_ghz, display,
                              shading="nearest", cmap="viridis")
    for ax in (ax_spec, ax_lc):
        ax.axvspan(start.datetime, stop.datetime, color="cyan", alpha=0.22,
                   label="configured self-cal solve interval")
    ax_spec.axhspan(low_ghz, high_ghz, facecolor="none", edgecolor="white",
                    linewidth=1.4, linestyle="--",
                    label=f"recommended imaging band: {low_ghz:g}–{high_ghz:g} GHz")
    ax_spec.set(title=f"{event_label} calibrated-MS XX spectrogram",
                ylabel="SPW reference frequency (GHz)")
    ax_spec.legend(loc="upper right")
    fig.colorbar(mesh, ax=ax_spec,
                 label="log10 median |XX| (native MS units)")

    # Representative curves make the peak and source evolution easier to
    # assess than the color image alone, as in the official EOVSA example.
    for target in [4.5, 7.5, 10.5, 13.5]:
        index = int(np.nanargmin(np.abs(freq_ghz - target)))
        ax_lc.plot(dates, spectrum[index] - baseline[index], linewidth=1.1,
                   label=f"{freq_ghz[index]:.2f} GHz")
    ax_lc.axhline(0, color="0.5", linewidth=0.7)
    ax_lc.set(xlabel="Time (UT)",
              ylabel="Background-subtracted median |XX|\n(native MS units)")
    ax_lc.legend(loc="upper right", ncol=2)
    ax_lc.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.savefig(output, dpi=180)
    plt.close(fig)
    print(f"Saved {output}")
    print(f"Recommended full-disk imaging band: {low_ghz:g}~{high_ghz:g}GHz")
    return low_ghz, high_ghz


def make_full_disk(cfg: dict, ms: Path, frequency_range: str, event_label: str,
                   output: Path) -> None:
    """Image the selected peak-frequency band and draw the solar limb."""
    timerange = cfg["timerange"]
    start, stop = parse_timerange(timerange)
    midpoint = start + (stop - start) / 2
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="eovsa-full-disk-") as scratch:
        imagename = str(Path(scratch) / "full_disk")
        fitsfile = str(Path(scratch) / "full_disk.helio.fits")
        tclean(
            vis=str(ms), imagename=imagename, timerange=timerange,
            spw=frequency_range, antenna=cfg.get("antenna", ""),
            uvrange=cfg.get("uvrange", ""), datacolumn="data", stokes="XX",
            specmode="mfs", deconvolver="hogbom", gridder="standard",
            imsize=[512, 512], cell=["5arcsec"], weighting="briggs",
            robust=float(cfg.get("robust", 1.0)), niter=300, gain=0.05,
            threshold="0Jy", interactive=False, pbcor=False,
            savemodel="none", calcres=True, calcpsf=True)
        hf.imreg(
            vis=str(ms), imagefile=imagename + ".image",
            timerange=timerange, fitsfile=fitsfile,
            ephem=offline_ephemeris(midpoint), usephacenter=True,
            overwrite=True)
        eomap = sunpy.map.Map(fitsfile)
        eomap.plot_settings["cmap"] = "inferno"
        fig = plt.figure(figsize=(8, 8), constrained_layout=True)
        ax = fig.add_subplot(projection=eomap)
        eomap.plot(axes=ax, clip_interval=(1, 99.8) * u.percent)
        eomap.draw_limb(axes=ax, color="white", linewidth=1.4)
        short_time = f"{start.datetime:%H:%M:%S}–{stop.datetime:%H:%M:%S}"
        ax.set_title(f"{event_label} EOVSA full-disk flare-location check\n"
                     f"{frequency_range.replace('~', '–')}, calibrated DATA, "
                     f"{short_time} UT")
        fig.savefig(output, dpi=180)
        plt.close(fig)
    print(f"Saved {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", help="Event JSON configuration")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--full-disk-frequency", default="auto",
        help="4--6 GHz range such as 6~10GHz; default derives it from the spectrum")
    parser.add_argument("--spectrogram-only", action="store_true")
    parser.add_argument("--full-disk-only", action="store_true")
    args = parser.parse_args()

    cfg_path = Path(args.config).expanduser().resolve()
    cfg = json.loads(cfg_path.read_text())
    ms = Path(cfg["input_ms"]).expanduser().resolve()
    if not ms.is_dir():
        raise SystemExit(f"Input MS not found: {ms}")
    example_id = cfg["event_id"].removesuffix("-updated-cal")
    output_dir = (Path(args.output_dir).expanduser().resolve()
                  if args.output_dir else
                  PROJECT / "examples" / example_id / "event-selection")
    output_dir.mkdir(parents=True, exist_ok=True)

    all_times = frequencies = spectrum = None
    recommended = None
    if not args.full_disk_only or args.full_disk_frequency == "auto":
        all_times, frequencies, spectrum = read_cross_power_spectrum(ms)
        recommended = recommend_frequency_band(
            all_times, frequencies, spectrum, cfg["timerange"])
    if not args.full_disk_only:
        recommended = make_spectrogram(
            all_times, frequencies, spectrum, cfg["timerange"], cfg["event_id"],
            output_dir / "updated_calibrated_ms_spectrogram.png")
    if not args.spectrogram_only:
        frequency_range = args.full_disk_frequency
        if frequency_range == "auto":
            frequency_range = f"{recommended[0]:g}~{recommended[1]:g}GHz"
        make_full_disk(cfg, ms, frequency_range, cfg["event_id"],
                       output_dir / "full_disk_flare_location.png")


if __name__ == "__main__":
    main()
