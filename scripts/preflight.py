#!/usr/bin/env python3
"""Read-only EOVSA MS inspection before any self-calibration."""

from __future__ import annotations

import json
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np
from casatools import msmetadata, table


def pkg(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "NOT INSTALLED"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: preflight.py CONFIG.json")
    cfg_path = Path(sys.argv[1]).expanduser().resolve()
    cfg = json.loads(cfg_path.read_text())
    vis = Path(cfg["input_ms"]).expanduser().resolve()
    if not vis.is_dir():
        raise SystemExit(f"Measurement Set not found: {vis}")

    out = cfg_path.parent.parent / "preflight"
    out.mkdir(exist_ok=True)
    report_path = out / f'{cfg["event_id"]}.txt'
    lines: list[str] = []

    def emit(value=""):
        value = str(value)
        print(value)
        lines.append(value)

    emit(f"MS: {vis}")
    emit(f"host architecture: {platform.machine()}")
    emit(f"Python: {platform.python_version()}")
    for name in ("casatasks", "casatools", "cubevis", "suncasa"):
        emit(f"{name}: {pkg(name)}")

    md = msmetadata()
    md.open(str(vis))
    try:
        emit(f"nspw: {md.nspw()}")
        emit(f"nantennas: {md.nantennas()}")
        emit("SPW mean frequencies (GHz):")
        for spw in range(md.nspw()):
            emit(f"  {spw:02d}: {md.meanfreq(spw, unit='GHz'):.6f}")
    finally:
        md.done()

    tb = table()
    tb.open(str(vis / "ANTENNA"), nomodify=True)
    try:
        names = tb.getcol("NAME")
        stations = tb.getcol("STATION") if "STATION" in tb.colnames() else [""] * len(names)
        emit("CASA antenna ID -> NAME / STATION:")
        for idx, (name, station) in enumerate(zip(names, stations)):
            emit(f"  {idx:02d} -> {name} / {station}")
    finally:
        tb.close()

    tb.open(str(vis / "POLARIZATION"), nomodify=True)
    try:
        emit(f"POLARIZATION CORR_TYPE codes: {tb.getcol('CORR_TYPE').tolist()}")
        emit("CASA codes: XX=9, XY=10, YX=11, YY=12")
    finally:
        tb.close()

    tb.open(str(vis), nomodify=True)
    try:
        emit(f"main columns: {', '.join(tb.colnames())}")
        nrows = tb.nrows()
        first_time = tb.getcell("TIME", 0)
        last_time = tb.getcell("TIME", nrows - 1)
        emit(f"rows: {nrows}; TIME first/last (MJD seconds): {first_time} / {last_time}")
        flagged = total = 0
        ant_flagged = {}; ant_total = {}; ant_xx_flagged = {}; ant_xx_total = {}; ant_rows = {}
        ddids = np.unique(tb.getcol("DATA_DESC_ID"))
        chunk = 10000
        for ddid in ddids:
            subtb = tb.query(f"DATA_DESC_ID == {int(ddid)}")
            try:
                subrows = subtb.nrows()
                for start in range(0, subrows, chunk):
                    count = min(chunk, subrows - start)
                    flags = subtb.getcol("FLAG", startrow=start, nrow=count)
                    ant1 = subtb.getcol("ANTENNA1", startrow=start, nrow=count)
                    ant2 = subtb.getcol("ANTENNA2", startrow=start, nrow=count)
                    flagged += int(flags.sum()); total += flags.size
                    for ant in set(ant1.tolist()) | set(ant2.tolist()):
                        selection = (ant1 == ant) | (ant2 == ant)
                        subset = flags[:, :, selection]
                        ant_flagged[ant] = ant_flagged.get(ant, 0) + int(subset.sum())
                        ant_total[ant] = ant_total.get(ant, 0) + subset.size
                        xx = subset[0]
                        ant_xx_flagged[ant] = ant_xx_flagged.get(ant, 0) + int(xx.sum())
                        ant_xx_total[ant] = ant_xx_total.get(ant, 0) + xx.size
                        ant_rows[ant] = ant_rows.get(ant, 0) + int(selection.sum())
            finally:
                subtb.close()
        emit(f"overall flagged fraction: {flagged / total:.6f}")
        emit("flagged fraction by CASA antenna ID (all correlations; XX separately):")
        for ant in sorted(ant_total):
            emit(f"  {ant:02d}: all={ant_flagged[ant] / ant_total[ant]:.6f}; "
                 f"XX={ant_xx_flagged[ant] / ant_xx_total[ant]:.6f} ({ant_rows[ant]} rows)")
    finally:
        tb.close()

    emit("")
    emit(f"configured antenna selection: {cfg['antenna']}")
    emit(f"configured SPW-dependent antenna overrides: {cfg.get('antenna_by_spw', {})}")
    emit(f"configured reference antenna: {cfg['refant']}")
    emit(f"configured self-cal SPWs: {cfg['selfcal_spws']}")
    emit(f"configured mask groups: {cfg['mask_spw_groups']}")
    emit(f"configured timerange: {cfg['timerange']}")
    emit(f"configured HPC xy center (arcsec): {cfg.get('xycen_arcsec')}")
    emit(f"derived CASA phasecenter: {cfg.get('phasecenter')}")
    emit("ACTION: inspect the first radio image and refine the center/masks if necessary.")
    report_path.write_text("\n".join(lines) + "\n")
    print(f"\nSaved: {report_path}")


if __name__ == "__main__":
    main()
