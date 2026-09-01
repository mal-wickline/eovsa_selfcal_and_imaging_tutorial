#!/usr/bin/env python3
"""Read-only plotms-style diagnostics for an EOVSA Measurement Set."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from astropy.time import Time
from casatools import table


def antenna_ids(selection: str) -> list[int]:
    result = []
    for part in selection.split(","):
        if "~" in part:
            lo, hi = map(int, part.split("~"))
            result.extend(range(lo, hi + 1))
        else:
            result.append(int(part))
    return sorted(set(result))


def circular_mean_deg(values):
    values = np.asarray(values)
    if not values.size:
        return np.nan
    return float(np.angle(np.nanmean(np.exp(1j * np.deg2rad(values))), deg=True))


def open_metadata(ms):
    tb = table()
    tb.open(str(ms / "DATA_DESCRIPTION"))
    dd_spw = np.asarray(tb.getcol("SPECTRAL_WINDOW_ID"), dtype=int)
    dd_pol = np.asarray(tb.getcol("POLARIZATION_ID"), dtype=int)
    tb.close()
    tb.open(str(ms / "POLARIZATION"))
    corr_types = [np.asarray(tb.getcell("CORR_TYPE", row), dtype=int) for row in range(tb.nrows())]
    tb.close()
    tb.open(str(ms / "SPECTRAL_WINDOW"))
    mean_freq = np.asarray(tb.getcol("REF_FREQUENCY"), dtype=float)
    tb.close()
    tb.open(str(ms / "ANTENNA"))
    names = list(tb.getcol("NAME"))
    tb.close()
    return dd_spw, dd_pol, corr_types, mean_freq, names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("output_dir")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).expanduser().resolve().read_text())
    ms = Path(cfg["input_ms"]).expanduser().resolve()
    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    selected = set(antenna_ids(cfg["antenna"]))
    spws = list(map(int, cfg["selfcal_spws"]))
    start, end = cfg["timerange"].split("~")
    t0, t1 = [Time.strptime(x, "%Y/%m/%d/%H:%M:%S", scale="utc").mjd * 86400
              for x in (start, end)]
    dd_spw, dd_pol, corr_types, mean_freq, names = open_metadata(ms)

    tb = table()
    tb.open(str(ms), nomodify=True)
    times = np.asarray(tb.getcol("TIME"), dtype=float)
    ddids_all = np.asarray(tb.getcol("DATA_DESC_ID"), dtype=int)
    a1_all = np.asarray(tb.getcol("ANTENNA1"), dtype=int)
    a2_all = np.asarray(tb.getcol("ANTENNA2"), dtype=int)
    records = []
    for spw in spws:
        allowed = set(antenna_ids(next((v for span, v in cfg.get("antenna_by_spw", {}).items()
                                        if int(span.split("~")[0]) <= spw <= int(span.split("~")[1])),
                                       cfg["antenna"])))
        ddids = np.flatnonzero(dd_spw == spw)
        rows = np.flatnonzero(
            (times >= t0) & (times <= t1) & np.isin(ddids_all, ddids)
            & np.isin(a1_all, list(allowed)) & np.isin(a2_all, list(allowed))
            & (a1_all != a2_all)
        )
        if not rows.size:
            continue
        q = tb.selectrows(rows.tolist())
        data = np.asarray(q.getcol("DATA"))
        flag = np.asarray(q.getcol("FLAG"), dtype=bool)
        weight = np.asarray(q.getcol("WEIGHT"), dtype=float)
        uvw = np.asarray(q.getcol("UVW"), dtype=float)
        a1 = np.asarray(q.getcol("ANTENNA1"), dtype=int)
        a2 = np.asarray(q.getcol("ANTENNA2"), dtype=int)
        rowtime = np.asarray(q.getcol("TIME"), dtype=float)
        rowdd = np.asarray(q.getcol("DATA_DESC_ID"), dtype=int)
        q.close()
        for row in range(data.shape[-1]):
            pol_id = dd_pol[rowdd[row]]
            indices = np.flatnonzero(corr_types[pol_id] == 9)  # CASA Stokes code 9 = XX
            pi = int(indices[0]) if indices.size else 0
            good = ~flag[pi, :, row]
            values = data[pi, good, row]
            if values.size:
                value = np.mean(values)
                amp = float(abs(value))
                phase = float(np.angle(value, deg=True))
            else:
                amp = phase = np.nan
            freq = float(mean_freq[spw])
            records.append({
                "spw": spw, "freq_ghz": freq / 1e9,
                "antenna1": int(a1[row]), "antenna2": int(a2[row]),
                "time_s": float(rowtime[row] - t0),
                "uv_lambda": float(np.hypot(uvw[0, row], uvw[1, row]) * freq / 299792458.0),
                "amplitude": amp, "phase_deg": phase,
                "good_fraction": float(np.mean(good)), "weight": float(weight[pi, row]),
            })
    tb.close()

    fields = list(records[0])
    with (out / "visibility_samples.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fields)
        writer.writeheader(); writer.writerows(records)

    ants = sorted(selected)
    ncols, nrows = 4, math.ceil(len(ants) / 4)

    def per_ant_plot(yfield, ylabel, filename, log=False):
        fig, axes = plt.subplots(nrows, ncols, figsize=(14, 3.1*nrows), squeeze=False)
        for ant, ax in zip(ants, axes.flat):
            rr = [r for r in records if ant in (r["antenna1"], r["antenna2"]) and np.isfinite(r[yfield])]
            ax.scatter([r["freq_ghz"] for r in rr], [r[yfield] for r in rr], s=3, alpha=.13)
            xs=[]; ys=[]
            for spw in spws:
                vals=[r[yfield] for r in rr if r["spw"]==spw]
                if vals:
                    xs.append(mean_freq[spw]/1e9)
                    ys.append(circular_mean_deg(vals) if yfield=="phase_deg" else np.nanmedian(vals))
            ax.plot(xs, ys, "o-", color="black", ms=3, lw=1)
            ax.set(title=f"CASA {ant} ({names[ant]})", xlabel="Frequency (GHz)", ylabel=ylabel)
            if log: ax.set_yscale("log")
            if yfield=="phase_deg": ax.set_ylim(-180,180)
        for ax in axes.flat[len(ants):]: ax.set_visible(False)
        fig.tight_layout(); fig.savefig(out/filename, dpi=170); plt.close(fig)

    per_ant_plot("amplitude", "|XX|", "amplitude_vs_frequency_by_antenna.png", log=True)
    per_ant_plot("phase_deg", "XX phase (deg)", "phase_vs_frequency_by_antenna.png")

    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 3.1*nrows), squeeze=False)
    for ant, ax in zip(ants, axes.flat):
        rr=[r for r in records if ant in (r["antenna1"],r["antenna2"]) and np.isfinite(r["amplitude"])]
        sc=ax.scatter([r["uv_lambda"] for r in rr],[r["amplitude"] for r in rr],c=[r["freq_ghz"] for r in rr],s=4,alpha=.3,cmap="viridis")
        ax.set(title=f"CASA {ant} ({names[ant]})",xlabel="UV distance (lambda)",ylabel="|XX|"); ax.set_yscale("log")
    for ax in axes.flat[len(ants):]: ax.set_visible(False)
    fig.colorbar(sc, ax=list(axes.flat[:len(ants)]), label="GHz", shrink=.7)
    fig.savefig(out/"amplitude_vs_uvdistance_by_antenna.png",dpi=170,bbox_inches="tight"); plt.close(fig)

    rep_spws=[s for s in (5,12,18,24,30) if s in spws]
    fig, axes = plt.subplots(nrows,ncols,figsize=(14,3.1*nrows),squeeze=False)
    for ant,ax in zip(ants,axes.flat):
        for s in rep_spws:
            rr=[r for r in records if r["spw"]==s and ant in (r["antenna1"],r["antenna2"]) and np.isfinite(r["phase_deg"])]
            ax.scatter([r["time_s"] for r in rr],[r["phase_deg"] for r in rr],s=6,alpha=.35,label=f"SPW {s}")
        ax.set(title=f"CASA {ant} ({names[ant]})",xlabel="Seconds from interval start",ylabel="Phase (deg)",ylim=(-180,180))
    axes.flat[0].legend(fontsize=7,ncol=2)
    for ax in axes.flat[len(ants):]: ax.set_visible(False)
    fig.tight_layout(); fig.savefig(out/"phase_vs_time_representative_spws.png",dpi=170); plt.close(fig)

    small=set(range(0,7)); large={8,10,11,12}
    classes={"small-small":lambda r:r["antenna1"] in small and r["antenna2"] in small,
             "small-large":lambda r:(r["antenna1"] in small) != (r["antenna2"] in small),
             "large-large":lambda r:r["antenna1"] in large and r["antenna2"] in large}
    fig,ax=plt.subplots(figsize=(9,5.5))
    for label,test in classes.items():
        xs=[];ys=[]
        for s in spws:
            vals=[r["amplitude"] for r in records if r["spw"]==s and test(r) and np.isfinite(r["amplitude"])]
            if vals: xs.append(mean_freq[s]/1e9);ys.append(np.median(vals))
        ax.plot(xs,ys,"o-",label=label)
    ax.set(xlabel="Frequency (GHz)",ylabel="Median |XX|",yscale="log",title="Baseline-class amplitude comparison")
    ax.legend();fig.tight_layout();fig.savefig(out/"amplitude_vs_frequency_by_baseline_class.png",dpi=180);plt.close(fig)

    fig,axes=plt.subplots(nrows,ncols,figsize=(14,3.1*nrows),squeeze=False)
    for ant,ax in zip(ants,axes.flat):
        xs=[];good=[];weights=[]
        for s in spws:
            rr=[r for r in records if r["spw"]==s and ant in (r["antenna1"],r["antenna2"])]
            if rr: xs.append(mean_freq[s]/1e9);good.append(np.mean([r["good_fraction"] for r in rr]));weights.append(np.median([r["weight"] for r in rr]))
        ax.plot(xs,good,"o-",label="unflagged fraction");ax.set_ylim(0,1.05);ax.set(title=f"CASA {ant} ({names[ant]})",xlabel="Frequency (GHz)",ylabel="Fraction")
        ax2=ax.twinx();ax2.plot(xs,weights,".-",color="tab:orange",alpha=.6);ax2.set_ylabel("Median weight",color="tab:orange")
    for ax in axes.flat[len(ants):]: ax.set_visible(False)
    fig.tight_layout();fig.savefig(out/"flags_and_weights_vs_frequency.png",dpi=170);plt.close(fig)

    print(f"Wrote read-only visibility QA to: {out}")


if __name__ == "__main__":
    main()
