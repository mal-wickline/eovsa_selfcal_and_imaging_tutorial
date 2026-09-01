#!/usr/bin/env python3
"""Use SunCASA to convert a measured solar (x,y) center into CASA phasecenter."""

import json
import sys
from pathlib import Path

from suncasa.utils import helioimage2fits as hf


if len(sys.argv) != 2:
    raise SystemExit("usage: derive_phasecenter.py CONFIG.json")
path = Path(sys.argv[1]).expanduser().resolve()
cfg = json.loads(path.read_text())
xy = cfg.get("xycen_arcsec")
if xy in (None, [None, None]):
    raise SystemExit("Fill xycen_arcsec in the config first.")
phasecenter, midtime = hf.calc_phasecenter_from_solxy(
    cfg["input_ms"], timerange=cfg["timerange"], xycen=xy,
    usemsphacenter=False, observatory="EOVSA"
)
cfg["phasecenter"] = phasecenter
path.write_text(json.dumps(cfg, indent=2) + "\n")
print(f"phasecenter={phasecenter}")
print(f"midtime={midtime}")
print(f"Updated {path}")
