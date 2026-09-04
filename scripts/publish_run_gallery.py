#!/usr/bin/env python3
"""Copy a small, reviewable set of derived PNGs into the GitHub gallery."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def copy_if_present(source: Path, destination: Path) -> bool:
    if not source.is_file():
        print(f"SKIP (not found): {source}")
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    print(f"COPIED: {destination}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", help="Accepted timestamped run directory")
    parser.add_argument("destination", help="Gallery directory in examples/")
    args = parser.parse_args()
    run = Path(args.run_dir).expanduser().resolve()
    destination = Path(args.destination).expanduser().resolve()
    if not (run / "manifest.json").is_file():
        raise SystemExit(f"Not a self-cal run directory: {run}")

    requested = []
    for round_index in range(3):
        base = run / "qa" / f"round_{round_index:02d}"
        requested.append((base / "images" / "all_spws.png",
                          destination / f"round_{round_index:02d}_all_spws.png"))
        if round_index:
            requested.extend([
                (base / "gains_phase.png",
                 destination / f"round_{round_index:02d}_gains_phase.png"),
                (base / "gains_amplitude.png",
                 destination / f"round_{round_index:02d}_gains_amplitude.png"),
            ])
    imaging = run / "qa" / "tutorial_imaging"
    requested.extend([
        (imaging / "dynamic_spectrum_after.png", destination / "dynamic_spectrum_after.png"),
        (imaging / "multiband_aia171_before.png", destination / "multiband_aia171_before.png"),
        (imaging / "multiband_aia171_after.png", destination / "multiband_aia171_after.png"),
        (imaging / "tutorial_summary_before_10_to_12.png",
         destination / "tutorial_summary_before_10_to_12.png"),
        (imaging / "tutorial_summary_after_10_to_12.png",
         destination / "tutorial_summary_after_10_to_12.png"),
    ])
    copied = sum(copy_if_present(source, target) for source, target in requested)
    print(f"\nCopied {copied} PNGs. Review every image before git add.")


if __name__ == "__main__":
    main()
