"""Build a complete Task 1 submission from the enhanced baseline.

The output contains one row for every eligible masked target cell in public
validation, for all three regimes.  It is suitable for score_task1.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from task1.baseline_task1_enhanced import interpolate, local_matrix
from task1.baseline_task1_historical_mean import (
    DEFAULT_RELEASE,
    HERE,
    REGIMES,
    build_profile,
    files,
    slot_values,
    stable_mask,
)


OUTPUT_COLUMNS = ["panel", "timestamp", "station_id", "link_id", "mask_regime", "speed_kmh", "flow_vph"]


def build_panel_submission(panel: str, release: Path, output: Path, write_header: bool) -> int:
    panel_dir = release / "corridors" / panel
    speed_profile, flow_profile, profile_counts = build_profile(panel, panel_dir)
    link_ids = speed_profile["link_ids"]
    link_index = speed_profile["link_index"]
    rows_written = 0
    for path in files(panel_dir, "validation"):
        frame = pd.read_parquet(
            path,
            columns=[
                "date", "timestamp", "station_id", "link_id", "speed_kmh",
                "flow_vph", "is_score_eligible",
            ],
        )
        frame["station_id"] = frame.station_id.astype(str)
        frame["link_id"] = frame.link_id.astype(str)
        weekday, tod = slot_values(frame)
        slot = weekday * 288 + tod
        li = frame.link_id.map(link_index).fillna(-1).to_numpy(dtype=np.int64)
        known = li >= 0
        safe_li = np.where(known, li, 0)
        base_speed = speed_profile["mean"][safe_li, slot]
        base_flow = flow_profile["mean"][safe_li, slot]
        base_speed = np.where(
            profile_counts["speed_count"][safe_li, slot] == 0,
            speed_profile["fallback"][safe_li],
            base_speed,
        )
        base_flow = np.where(
            profile_counts["flow_count"][safe_li, slot] == 0,
            flow_profile["fallback"][safe_li],
            base_flow,
        )
        valid_base = frame.is_score_eligible.astype(bool).to_numpy()

        for regime in REGIMES:
            target = valid_base & stable_mask(panel, regime, frame.date, frame.timestamp, frame.link_id)
            _, _, _, speed_sum, speed_n, flow_sum, flow_n = local_matrix(frame, link_ids, target)
            speed_local = interpolate(speed_sum, speed_n, speed_profile["fallback"])
            flow_local = interpolate(flow_sum, flow_n, flow_profile["fallback"])
            pred_speed = np.where(known, speed_local[safe_li, tod], base_speed)
            pred_flow = np.where(known, flow_local[safe_li, tod], base_flow)
            pred_speed = np.maximum(pred_speed, 0.0)
            pred_flow = np.maximum(pred_flow, 0.0)

            mask = target & np.isfinite(pred_speed) & np.isfinite(pred_flow)
            if not mask.any():
                continue
            out = pd.DataFrame(
                {
                    "panel": panel,
                    "timestamp": frame.loc[mask, "timestamp"].astype(str).to_numpy(),
                    "station_id": frame.loc[mask, "station_id"].to_numpy(),
                    "link_id": frame.loc[mask, "link_id"].to_numpy(),
                    "mask_regime": regime,
                    "speed_kmh": pred_speed[mask],
                    "flow_vph": pred_flow[mask],
                },
                columns=OUTPUT_COLUMNS,
            )
            out.to_csv(output, mode="w" if write_header else "a", header=write_header, index=False)
            write_header = False
            rows_written += len(out)
    return rows_written


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE)
    ap.add_argument("--output", type=Path, default=HERE / "reports" / "task1_enhanced_state_submission.csv")
    ap.add_argument("--panel", action="append", help="build only selected panel(s), mainly for smoke tests")
    args = ap.parse_args()
    manifest = json.loads((HERE / "config" / "corridors.json").read_text(encoding="utf-8"))
    panels = [p["corridor_id"] for p in manifest["panels"]]
    if args.panel:
        requested = set(args.panel)
        unknown = sorted(requested - set(panels))
        if unknown:
            raise ValueError(f"unknown --panel values: {unknown}")
        panels = [p for p in panels if p in requested]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        args.output.unlink()
    total = 0
    first = True
    for panel in panels:
        print(f"[Task1 submission] {panel}", flush=True)
        count = build_panel_submission(panel, args.release_root.resolve(), args.output.resolve(), first)
        total += count
        first = False
        print(f"  wrote {count:,} target rows", flush=True)
    print(f"Wrote {total:,} rows to {args.output.resolve()}")


if __name__ == "__main__":
    main()
