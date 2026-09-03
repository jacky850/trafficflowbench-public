"""Merge the task-specific submissions into one long-table file.

This adapter is deliberately independent of hidden truth.  It validates the
participant files, adds a globally unique submission_id, and concatenates the
task rows vertically.

Task 3 is scored on the Task 1 state file and has no submission of its own, so
--physics is optional and left over for internal pipelines that still produce a
self-contained physics frame.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

UNIFIED_COLUMNS = [
    "submission_id", "task", "panel", "timestamp", "station_id", "link_id", "mask_regime",
    "window_id", "departure_time", "path_id", "origin_zone", "destination_zone",
    "speed_kmh", "flow_vph", "density_vpkm", "inflow_vph", "outflow_vph",
    "on_ramp_flow_vph", "off_ramp_flow_vph", "on_ramp_valid", "off_ramp_valid",
    "accumulation_N", "queue_pred", "path_flow",
]
REQUIRED = {
    "state": ["panel", "timestamp", "station_id", "link_id", "mask_regime", "speed_kmh", "flow_vph"],
    "queue": ["window_id", "timestamp", "link_id", "queue_pred"],
    "physics": [
        "panel", "timestamp", "link_id", "mask_regime", "speed_kmh", "flow_vph", "density_vpkm",
        "inflow_vph", "outflow_vph", "on_ramp_flow_vph", "off_ramp_flow_vph",
        "on_ramp_valid", "off_ramp_valid", "accumulation_N",
    ],
    "odme": ["panel", "departure_time", "path_id", "origin_zone", "destination_zone", "path_flow"],
}
KEYS = {
    "state": ["panel", "timestamp", "station_id", "link_id", "mask_regime"],
    "queue": ["window_id", "timestamp", "link_id"],
    "physics": ["panel", "timestamp", "link_id", "mask_regime"],
    "odme": ["panel", "departure_time", "path_id"],
}


def read_task(path: Path, task: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{task} submission not found: {path}")
    frame = pd.read_csv(path)
    missing = sorted(set(REQUIRED[task]) - set(frame.columns))
    if missing:
        raise ValueError(f"{task} submission is missing required columns: {missing}")
    dup = int(frame.duplicated(KEYS[task]).sum())
    if dup:
        raise ValueError(f"{task} submission contains {dup} duplicate rows over {KEYS[task]}")
    if task == "queue":
        values = pd.to_numeric(frame.queue_pred, errors="coerce")
        bad = values.notna() & ~values.isin([0, 1])
        if int(bad.sum()):
            raise ValueError("queue_pred must contain only binary 0/1 values")
    if task == "odme":
        values = pd.to_numeric(frame.path_flow, errors="coerce")
        if int((values.notna() & (values < 0)).sum()):
            raise ValueError("path_flow must be nonnegative")
    return frame


def to_unified(frame: pd.DataFrame, task: str) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    for column in UNIFIED_COLUMNS:
        out[column] = ""
    out["task"] = task
    for column in REQUIRED[task]:
        out[column] = frame[column].to_numpy()
    if task == "state":
        out["submission_id"] = (
            "state:" + frame.panel.astype(str) + ":" + frame.timestamp.astype(str) + ":" +
            frame.station_id.astype(str) + ":" + frame.link_id.astype(str) + ":" + frame.mask_regime.astype(str)
        ).to_numpy()
    elif task == "physics":
        out["submission_id"] = (
            "physics:" + frame.panel.astype(str) + ":" + frame.timestamp.astype(str) + ":" +
            frame.link_id.astype(str) + ":" + frame.mask_regime.astype(str)
        ).to_numpy()
    elif task == "queue":
        out["submission_id"] = (
            "queue:" + frame.window_id.astype(str) + ":" + frame.timestamp.astype(str) + ":" + frame.link_id.astype(str)
        ).to_numpy()
    else:
        out["submission_id"] = (
            "odme:" + frame.panel.astype(str) + ":" + frame.departure_time.astype(str) + ":" + frame.path_id.astype(str)
        ).to_numpy()
    return out[UNIFIED_COLUMNS]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", type=Path, required=True)
    ap.add_argument("--queue", type=Path, required=True)
    ap.add_argument("--physics", type=Path,
                    help="optional; Task 3 is scored on --state and needs no file of its own")
    ap.add_argument("--odme", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    frames = [
        to_unified(read_task(args.state.resolve(), "state"), "state"),
        to_unified(read_task(args.queue.resolve(), "queue"), "queue"),
        to_unified(read_task(args.odme.resolve(), "odme"), "odme"),
    ]
    if args.physics is not None:
        frames.insert(2, to_unified(read_task(args.physics.resolve(), "physics"), "physics"))
    result = pd.concat(frames, ignore_index=True)
    if result.submission_id.duplicated().any():
        raise ValueError("merged submission contains duplicate submission_id values")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output.resolve(), index=False)
    print(f"Wrote {len(result):,} rows to {args.output.resolve()}")
    print(result.groupby("task", sort=True).size().to_string())


if __name__ == "__main__":
    main()
