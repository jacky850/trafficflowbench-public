"""Local evaluator for Task 1 masked state reconstruction.

The scorer uses the public validation labels as truth.  It creates the frozen
R1/R2/R3 target masks, joins the submitted speed/flow values, scores only
eligible target cells, and aggregates direction -> corridor family -> overall
state score with equal weights.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from task1.baseline_task1_historical_mean import (
    DEFAULT_RELEASE,
    FLOW_NORMALIZER,
    FLOW_WEIGHT,
    HERE,
    REGIMES,
    SPEED_NORMALIZER,
    SPEED_WEIGHT,
    stable_mask,
)


REQUIRED_COLUMNS = {"panel", "timestamp", "station_id", "link_id", "mask_regime", "speed_kmh", "flow_vph"}


def release_files(release: Path, panel: str, split: str) -> list[Path]:
    return sorted((release / "corridors" / panel / split / "mainline_states").glob("**/*.parquet"))


def read_submission(path: Path) -> tuple[pd.DataFrame, list[str]]:
    if not path.exists():
        raise FileNotFoundError(
            f"submission file not found: {path}\n"
            "Replace the example path with the actual CSV file path."
        )
    frame = pd.read_csv(path)
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"submission is missing required columns: {missing}")
    frame = frame.copy()
    frame["panel"] = frame["panel"].astype(str)
    frame["station_id"] = frame["station_id"].astype(str)
    frame["link_id"] = frame["link_id"].astype(str)
    frame["mask_regime"] = frame["mask_regime"].astype(str)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if frame["timestamp"].isna().any():
        raise ValueError("submission contains unparseable timestamps")
    duplicate_keys = ["panel", "timestamp", "station_id", "link_id", "mask_regime"]
    duplicates = int(frame.duplicated(duplicate_keys).sum())
    errors = []
    if duplicates:
        # Duplicate cell keys would break the one_to_one truth/prediction merge
        # later with an opaque pandas MergeError, so reject them up front.
        sample = frame[frame.duplicated(duplicate_keys, keep=False)].head(3)
        raise ValueError(
            f"submission contains {duplicates} duplicate cell keys over "
            f"{duplicate_keys}; each target cell must appear exactly once. "
            f"First duplicated rows:\n{sample.to_string(index=False)}"
        )
    for col in ("speed_kmh", "flow_vph"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    invalid_regimes = sorted(set(frame.mask_regime) - set(REGIMES))
    if invalid_regimes:
        errors.append(f"unknown mask_regime values: {invalid_regimes}")
    return frame, errors


def score_panel(panel: str, release: Path, split: str, submission: pd.DataFrame) -> list[dict]:
    paths = release_files(release, panel, split)
    if not paths:
        raise FileNotFoundError(f"{panel}: no {split} mainline partitions")
    panel_submission = submission[submission.panel == panel].copy()
    rows = []
    for regime in REGIMES:
        total_sq_speed = 0.0
        total_sq_flow = 0.0
        n_target = 0
        n_missing = 0
        n_invalid = 0
        for path in paths:
            frame = pd.read_parquet(
                path,
                columns=["date", "timestamp", "station_id", "link_id", "speed_kmh", "flow_vph", "is_score_eligible"],
            )
            frame["link_id"] = frame.link_id.astype(str)
            # Preserve the release's canonical timestamp text for the stable
            # mask hash. Converting to a different datetime string first would
            # silently generate a different R1/R2/R3 mask.
            mask_timestamp = frame.timestamp.astype(str)
            frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
            target = frame.is_score_eligible.astype(bool).to_numpy() & stable_mask(
                panel, regime, frame.date, mask_timestamp, frame.link_id
            )
            truth = frame.loc[target, ["timestamp", "station_id", "link_id", "speed_kmh", "flow_vph"]].copy()
            if truth.empty:
                continue
            truth["timestamp"] = pd.to_datetime(truth.timestamp, utc=True)
            truth["station_id"] = truth.station_id.astype(str)
            truth["link_id"] = truth.link_id.astype(str)
            truth = truth.rename(columns={"speed_kmh": "true_speed", "flow_vph": "true_flow"})
            pred = panel_submission[panel_submission.mask_regime == regime][
                ["timestamp", "station_id", "link_id", "speed_kmh", "flow_vph"]
            ].rename(columns={"speed_kmh": "pred_speed", "flow_vph": "pred_flow"})
            merged = truth.merge(pred, on=["timestamp", "station_id", "link_id"], how="left", validate="one_to_one")
            pred_speed = pd.to_numeric(merged.pred_speed, errors="coerce").to_numpy(dtype=float)
            pred_flow = pd.to_numeric(merged.pred_flow, errors="coerce").to_numpy(dtype=float)
            true_speed = pd.to_numeric(merged.true_speed, errors="coerce").to_numpy(dtype=float)
            true_flow = pd.to_numeric(merged.true_flow, errors="coerce").to_numpy(dtype=float)
            missing = ~np.isfinite(pred_speed) | ~np.isfinite(pred_flow)
            invalid_truth = ~np.isfinite(true_speed) | ~np.isfinite(true_flow)
            # Missing predictions are counted in the denominator and receive a
            # zero prediction, so dropping rows cannot improve the score.
            pred_speed = np.where(np.isfinite(pred_speed), pred_speed, 0.0)
            pred_flow = np.where(np.isfinite(pred_flow), pred_flow, 0.0)
            usable = ~invalid_truth
            ds = pred_speed[usable] - true_speed[usable]
            dq = pred_flow[usable] - true_flow[usable]
            total_sq_speed += float(np.sum(ds * ds))
            total_sq_flow += float(np.sum(dq * dq))
            n_target += int(usable.sum())
            n_missing += int(missing[usable].sum())
            n_invalid += int(invalid_truth.sum())

        n = max(n_target, 1)
        rmse_speed = float(np.sqrt(total_sq_speed / n))
        rmse_flow = float(np.sqrt(total_sq_flow / n))
        speed_score = max(0.0, 1.0 - rmse_speed / SPEED_NORMALIZER)
        flow_score = max(0.0, 1.0 - rmse_flow / FLOW_NORMALIZER)
        state_score = SPEED_WEIGHT * speed_score + FLOW_WEIGHT * flow_score
        rows.append(
            {
                "level": "panel_regime",
                "panel": panel,
                "family_id": None,
                "regime": regime,
                "n_target_cells": n_target,
                "n_missing_predictions": n_missing,
                "n_invalid_truth": n_invalid,
                "rmse_speed_kmh": rmse_speed,
                "rmse_flow_vph": rmse_flow,
                "S_speed": speed_score,
                "S_flow": flow_score,
                "S_state": state_score,
            }
        )
    panel_rows = [r for r in rows if r["level"] == "panel_regime"]
    rows.append(
        {
            "level": "panel",
            "panel": panel,
            "family_id": None,
            "regime": "macro_mean",
            "n_target_cells": sum(r["n_target_cells"] for r in panel_rows),
            "n_missing_predictions": sum(r["n_missing_predictions"] for r in panel_rows),
            "n_invalid_truth": sum(r["n_invalid_truth"] for r in panel_rows),
            "rmse_speed_kmh": np.nan,
            "rmse_flow_vph": np.nan,
            "S_speed": np.nan,
            "S_flow": np.nan,
            "S_state": float(np.mean([r["S_state"] for r in panel_rows])) if panel_rows else 0.0,
        }
    )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", type=Path, required=True)
    ap.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE)
    ap.add_argument("--split", choices=["validation", "train"], default="validation")
    ap.add_argument("--output", type=Path, default=HERE / "reports" / "task1_eval_validation.csv")
    ap.add_argument("--panel", action="append", help="score only selected panel(s), mainly for smoke tests")
    args = ap.parse_args()
    manifest = json.loads((HERE / "config" / "corridors.json").read_text(encoding="utf-8"))
    panels = [p["corridor_id"] for p in manifest["panels"]]
    if args.panel:
        requested = set(args.panel)
        unknown_requested = sorted(requested - set(panels))
        if unknown_requested:
            raise ValueError(f"unknown --panel values: {unknown_requested}")
        panels = [p for p in panels if p in requested]
    families = {p["corridor_id"]: p["family_id"] for p in manifest["panels"]}
    submission, errors = read_submission(args.submission.resolve())
    if errors:
        print("Submission warnings:")
        for error in errors:
            print("  -", error)
    unknown_panels = sorted(set(submission.panel) - set(panels))
    if unknown_panels:
        print("Submission warnings:")
        print("  - unknown panels ignored:", unknown_panels)
    rows = []
    for panel in panels:
        print(f"[Task1 evaluator] {panel}", flush=True)
        rows.extend(score_panel(panel, args.release_root.resolve(), args.split, submission))
    detail = pd.DataFrame(rows)
    panel_scores = detail[detail.level == "panel"].copy()
    panel_scores["family_id"] = panel_scores.panel.map(families)
    family_rows = []
    for family_id, group in panel_scores.groupby("family_id", sort=True):
        family_rows.append(
            {
                "level": "family",
                "panel": None,
                "family_id": family_id,
                "regime": "macro_mean",
                "n_target_cells": int(group.n_target_cells.sum()),
                "n_missing_predictions": int(group.n_missing_predictions.sum()),
                "n_invalid_truth": int(group.n_invalid_truth.sum()),
                "rmse_speed_kmh": np.nan,
                "rmse_flow_vph": np.nan,
                "S_speed": np.nan,
                "S_flow": np.nan,
                "S_state": float(group.S_state.mean()),
            }
        )
    family_df = pd.DataFrame(family_rows)
    overall = pd.DataFrame(
        [
            {
                "level": "overall",
                "panel": None,
                "family_id": "ALL",
                "regime": "macro_mean",
                "n_target_cells": int(family_df.n_target_cells.sum()),
                "n_missing_predictions": int(family_df.n_missing_predictions.sum()),
                "n_invalid_truth": int(family_df.n_invalid_truth.sum()),
                "rmse_speed_kmh": np.nan,
                "rmse_flow_vph": np.nan,
                "S_speed": np.nan,
                "S_flow": np.nan,
                "S_state": float(family_df.S_state.mean()),
            }
        ]
    )
    result = pd.concat([detail, family_df, overall], ignore_index=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f"Wrote {args.output}")
    print(f"Overall S_state = {float(overall.S_state.iloc[0]):.6f}")


if __name__ == "__main__":
    main()
