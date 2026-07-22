"""Local evaluator for Task 2 online queue-propagation forecasting."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from task1.baseline_task1_historical_mean import HERE


REQUIRED = {"window_id", "timestamp", "link_id", "queue_pred"}


def read_submission(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Queue submission not found: {path}")
    d = pd.read_csv(path)
    missing = sorted(REQUIRED - set(d.columns))
    if missing:
        raise ValueError(f"Queue submission missing columns: {missing}")
    d = d.copy()
    d["window_id"] = d.window_id.astype(str)
    d["link_id"] = d.link_id.astype(str)
    d["timestamp"] = pd.to_datetime(d.timestamp, utc=True, errors="coerce")
    if d.timestamp.isna().any():
        raise ValueError("Queue submission contains unparseable timestamps")
    d["queue_pred"] = pd.to_numeric(d.queue_pred, errors="coerce")
    # queue_pred must be binary 0/1 (contract). Reject non-binary rather than
    # silently rounding, which would let a team hedge with probabilities and
    # have the evaluator pick a favourable 0.5 threshold.
    vals = d.queue_pred.dropna()
    bad = vals[~vals.isin([0, 1])]
    if len(bad):
        raise ValueError(
            f"queue_pred must be binary 0/1; found {len(bad)} non-binary values "
            f"(e.g. {sorted(bad.unique())[:5]}). Threshold your predictions before submitting.")
    # Reject duplicate cell keys (they would break the one_to_one scoring merge).
    dkeys = ["window_id", "timestamp", "link_id"]
    dup = int(d.duplicated(dkeys).sum())
    if dup:
        raise ValueError(f"Queue submission has {dup} duplicate keys over {dkeys}; each cell must appear once.")
    return d


def score_window(target: pd.DataFrame, submission: pd.DataFrame) -> tuple[float, int, int]:
    keys = ["window_id", "timestamp", "link_id"]
    eligible = target[target.is_score_eligible.astype(bool)].copy()
    pred = submission[keys + ["queue_pred"]] if not submission.empty else pd.DataFrame(columns=keys + ["queue_pred"])
    merged = eligible.merge(pred, on=keys, how="left", validate="one_to_one")
    missing = int(merged.queue_pred.isna().sum())
    values = pd.to_numeric(merged.queue_pred, errors="coerce")
    invalid = int((values.notna() & ~values.isin([0, 1])).sum())
    values = values.fillna(0).clip(0, 1).round().astype(bool).to_numpy()
    truth = merged.queue_true.astype(bool).to_numpy()
    inter = int(np.logical_and(values, truth).sum())
    union = int(np.logical_or(values, truth).sum())
    iou = 1.0 if union == 0 else inter / union
    return float(iou), missing, invalid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", type=Path, required=True)
    ap.add_argument("--release-root", type=Path, default=HERE / "data_public" / "kaggle_release")
    ap.add_argument("--split", choices=["train", "validation"], default="validation")
    ap.add_argument(
        "--truth-file",
        type=Path,
        help="Organizer-local queue truth parquet. Defaults to the public-release path if present.",
    )
    ap.add_argument("--panel", action="append")
    ap.add_argument("--output", type=Path, default=HERE / "reports" / "task2_eval_validation.csv")
    args = ap.parse_args()
    submission = read_submission(args.submission.resolve())
    target_path = args.truth_file.resolve() if args.truth_file else args.release_root.resolve() / "task2" / args.split / "queue_targets.parquet"
    if not target_path.exists():
        raise FileNotFoundError(
            f"Queue truth not found: {target_path}. Public validation truth is intentionally withheld; "
            "organizers must pass --truth-file pointing to their private local copy."
        )
    target = pd.read_parquet(target_path)
    target["window_id"] = target.window_id.astype(str)
    target["link_id"] = target.link_id.astype(str)
    target["timestamp"] = pd.to_datetime(target.timestamp, utc=True)
    windows = pd.read_csv(args.release_root.resolve() / "task2" / "window_index.csv")
    windows = windows[windows.split == args.split].copy()
    panels = sorted(windows.panel.unique().tolist())
    if args.panel:
        panels = [p for p in panels if p in set(args.panel)]
        windows = windows[windows.panel.isin(panels)]
        target = target[target.panel.isin(panels)]
    rows = []
    for w in windows.itertuples(index=False):
        t = target[target.window_id == w.window_id]
        s = submission[submission.window_id == w.window_id]
        iou, missing, invalid = score_window(t, s)
        rows.append({"level": "window", "window_id": w.window_id, "panel": w.panel, "family_id": w.family_id, "condition": w.condition, "IoU_ST": iou, "n_target_rows": len(t), "missing_predictions": missing, "invalid_predictions": invalid})
    detail = pd.DataFrame(rows)
    panel_rows = []
    for (panel, condition), g in detail.groupby(["panel", "condition"], sort=True):
        panel_rows.append({"level": "panel_condition", "window_id": None, "panel": panel, "family_id": g.family_id.iloc[0], "condition": condition, "IoU_ST": float(g.IoU_ST.mean()), "n_target_rows": int(g.n_target_rows.sum()), "missing_predictions": int(g.missing_predictions.sum()), "invalid_predictions": int(g.invalid_predictions.sum())})
    pc = pd.DataFrame(panel_rows)
    panel_mean = []
    for panel, g in pc.groupby("panel", sort=True):
        panel_mean.append({"level": "panel", "window_id": None, "panel": panel, "family_id": g.family_id.iloc[0], "condition": "equal_mean", "IoU_ST": float(g.IoU_ST.mean()), "n_target_rows": int(g.n_target_rows.sum()), "missing_predictions": int(g.missing_predictions.sum()), "invalid_predictions": int(g.invalid_predictions.sum())})
    pm = pd.DataFrame(panel_mean)
    family_rows = []
    for family, g in pm.groupby("family_id", sort=True):
        family_rows.append({"level": "family", "window_id": None, "panel": None, "family_id": family, "condition": "equal_mean", "IoU_ST": float(g.IoU_ST.mean()), "n_target_rows": int(g.n_target_rows.sum()), "missing_predictions": int(g.missing_predictions.sum()), "invalid_predictions": int(g.invalid_predictions.sum())})
    fam = pd.DataFrame(family_rows)
    overall = {"level": "overall", "window_id": None, "panel": None, "family_id": "ALL", "condition": "equal_mean", "IoU_ST": float(fam.IoU_ST.mean()), "n_target_rows": int(fam.n_target_rows.sum()), "missing_predictions": int(fam.missing_predictions.sum()), "invalid_predictions": int(fam.invalid_predictions.sum())}
    result = pd.concat([detail, pc, pm, fam, pd.DataFrame([overall])], ignore_index=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f"Wrote {args.output}")
    print(f"Overall S_queue = {overall['IoU_ST']:.6f}")


if __name__ == "__main__":
    main()
