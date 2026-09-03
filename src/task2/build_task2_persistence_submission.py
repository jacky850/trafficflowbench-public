"""Build the simple queue-persistence baseline for Task 2."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# Make the sibling task packages importable when this file is run as a script,
# so no PYTHONPATH is needed.
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

from task1.baseline_task1_historical_mean import DEFAULT_RELEASE, HERE
from task2.queue_utils import thresholds



def _task2_parts(root: Path, splits: list[str], name: str) -> list[Path]:
    """Every per-corridor Task 2 file of a given name, for the chosen splits.

    Task 2 assets are published one directory per corridor and split. A flat
    file directly under ``task2/`` is accepted too, so a locally staged release
    still works.
    """
    parts = []
    for panel_dir in sorted(p for p in (root / "task2").glob("*") if p.is_dir()):
        for split in splits:
            candidate = panel_dir / split / name
            if candidate.exists():
                parts.append(candidate)
    return parts


def read_window_index(root: Path, splits: list[str]) -> pd.DataFrame:
    flat = root / "task2" / "window_index.csv"
    if flat.exists():
        frame = pd.read_csv(flat)
        return frame[frame.split.isin(splits)].copy()
    parts = _task2_parts(root, splits, "window_index.csv")
    if not parts:
        raise FileNotFoundError(f"no Task 2 window index under {root / 'task2'} for splits {splits}")
    return pd.concat([pd.read_csv(p) for p in parts], ignore_index=True)


def read_window_history(root: Path, splits: list[str]) -> pd.DataFrame:
    flat = root / "task2" / "window_history.parquet"
    columns = ["window_id", "timestamp", "link_id", "speed_kmh", "is_score_eligible"]
    if flat.exists():
        return pd.read_parquet(flat, columns=columns)
    parts = _task2_parts(root, splits, "window_history.parquet")
    if not parts:
        raise FileNotFoundError(f"no Task 2 window history under {root / 'task2'} for splits {splits}")
    return pd.concat([pd.read_parquet(p, columns=columns) for p in parts], ignore_index=True)


def read_queue_template(root: Path, splits: list[str]) -> pd.DataFrame:
    columns = ["window_id", "timestamp", "link_id"]
    for flat in (root / "task2" / "sample_submission_queue.csv",
                 root / "submission_templates_per_task" / "sample_submission_queue.csv"):
        if flat.exists():
            return pd.read_csv(flat, usecols=columns)
    parts = _task2_parts(root, splits, "sample_submission_queue.csv")
    if not parts:
        raise FileNotFoundError(f"no Task 2 submission template under {root / 'task2'} for splits {splits}")
    return pd.concat([pd.read_csv(p, usecols=columns) for p in parts], ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE)
    ap.add_argument("--network-release-root", type=Path,
                    help="optional corridor/network root when Task 2 artifacts are staged separately")
    ap.add_argument("--split", choices=["train", "validation", "private", "all"], default="all")
    ap.add_argument("--output", type=Path, default=HERE / "reports" / "task2_persistence_submission.csv")
    args = ap.parse_args()
    root = args.release_root.resolve()
    splits = ["train", "validation"] if args.split == "all" else [args.split]
    windows = read_window_index(root, splits)
    template = read_queue_template(root, splits)
    template["window_id"] = template.window_id.astype(str)
    template["link_id"] = template.link_id.astype(str)
    template["timestamp"] = pd.to_datetime(template.timestamp, utc=True)
    # Persistence must use only the released [T-60, T) window history.  The
    # old implementation re-read the corridor state at T, which is not part
    # of the Task 2 participant contract and leaked one extra observation.
    history = read_window_history(root, splits)
    history["window_id"] = history.window_id.astype(str)
    history["timestamp"] = pd.to_datetime(history.timestamp, utc=True)
    history["link_id"] = history.link_id.astype(str)
    history["speed_kmh"] = pd.to_numeric(history.speed_kmh, errors="coerce")
    panel_by_window = windows.set_index("window_id").panel.astype(str).to_dict()
    thresholds_by_panel = {}
    for panel in sorted(windows.panel.astype(str).unique()):
        network_root = args.network_release_root.resolve() if args.network_release_root else root
        panel_dir = network_root / "corridors" / panel
        links = pd.read_csv(panel_dir / "network" / "links.csv")
        links["link_id"] = links.link_id.astype(str)
        thresholds_by_panel[panel], _ = thresholds(panel_dir, links)
    targets = []
    for window_id, h in history.groupby("window_id", sort=True):
        panel = panel_by_window.get(str(window_id))
        if panel is None:
            continue
        last_time = h.timestamp.max()
        at = h[h.timestamp.eq(last_time)].copy()
        threshold = thresholds_by_panel[panel]
        at["queue_now"] = at.speed_kmh <= at.link_id.map(threshold).fillna(63.0)
        at["queue_now"] &= at.is_score_eligible.astype(bool)
        q = at.groupby("link_id").queue_now.any().to_dict()
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
