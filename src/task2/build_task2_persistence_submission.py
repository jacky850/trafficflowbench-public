"""Build the simple queue-persistence baseline for Task 2."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from task1.baseline_task1_historical_mean import DEFAULT_RELEASE, HERE
from task2.queue_utils import thresholds


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE)
    ap.add_argument("--split", choices=["train", "validation", "all"], default="all")
    ap.add_argument("--output", type=Path, default=HERE / "reports" / "task2_persistence_submission.csv")
    args = ap.parse_args()
    task2 = args.release_root.resolve() / "task2"
    windows = pd.read_csv(task2 / "window_index.csv")
    splits = ["train", "validation"] if args.split == "all" else [args.split]
    windows = windows[windows.split.isin(splits)].copy()
    template_path = task2 / "sample_submission_queue.csv"
    if not template_path.exists():
        template_path = args.release_root.resolve() / "submission_templates" / "sample_submission_queue.csv"
    if not template_path.exists():
        raise FileNotFoundError(
            "Task 2 submission template not found. Expected "
            f"{task2 / 'sample_submission_queue.csv'} or {template_path}"
        )
    template = pd.read_csv(template_path, usecols=["window_id", "timestamp", "link_id"])
    template["window_id"] = template.window_id.astype(str)
    template["link_id"] = template.link_id.astype(str)
    template["timestamp"] = pd.to_datetime(template.timestamp, utc=True)
    targets = []
    for (panel, split), wg in windows.groupby(["panel", "split"], sort=True):
        panel_dir = args.release_root.resolve() / "corridors" / panel
        links = pd.read_csv(panel_dir / "network" / "links.csv")
        links["link_id"] = links.link_id.astype(str)
        threshold, _ = thresholds(panel_dir, links)
        files = sorted((panel_dir / split / "mainline_states").glob("**/*.parquet"))
        by_date = {pd.Timestamp(path.stem.split("_")[-1]).date(): path for path in files if path.stem.split("_")[-1].count("-") == 2}
        # Filename parsing differs between D7 and D12; use a date lookup from
        # the first row when the stem convention is not directly parseable.
        if len(by_date) < len(files) // 2:
            by_date = {}
            for path in files:
                date = pd.read_parquet(path, columns=["date"]).date.iloc[0]
                by_date[pd.Timestamp(date).date()] = path
        for date, dw in wg.groupby("date"):
            day = pd.Timestamp(date).date()
            path = by_date.get(day)
            if path is None:
                continue
            origin_times = pd.to_datetime(dw.forecast_origin, utc=True).unique()
            frame = pd.read_parquet(path, columns=["timestamp", "link_id", "speed_kmh", "is_score_eligible"])
            frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
            frame["link_id"] = frame.link_id.astype(str)
            frame["speed_kmh"] = pd.to_numeric(frame.speed_kmh, errors="coerce")
            for origin in origin_times:
                at = frame[frame.timestamp == origin].copy()
                at["queue_now"] = False
                at["queue_now"] = at.speed_kmh <= at.link_id.map(threshold).fillna(63.0)
                at["queue_now"] &= at.is_score_eligible.astype(bool)
                q = at.groupby("link_id").queue_now.any().to_dict()
                window_ids = dw.loc[pd.to_datetime(dw.forecast_origin, utc=True) == origin, "window_id"].tolist()
                for window_id in window_ids:
                    target = template[template.window_id == str(window_id)][["window_id", "timestamp", "link_id"]].copy()
                    target["queue_pred"] = target.link_id.map(q).fillna(False).astype(int)
                    targets.append(target)
    if not targets:
        raise RuntimeError("No queue persistence rows were generated")
    out = pd.concat(targets, ignore_index=True).drop_duplicates(["window_id", "timestamp", "link_id"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(f"Wrote {len(out):,} rows to {args.output.resolve()}")


if __name__ == "__main__":
    main()
