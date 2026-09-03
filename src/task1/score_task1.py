"""Local evaluator for Task 1 masked state reconstruction.

Truth is the unmasked observation layer, which only the train split ships, so
this evaluator runs on train. It reads the targets off the masked layer, joins
the submitted speed and flow, scores eligible target cells only, and aggregates
direction -> corridor family -> overall with equal weights.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

# Make the sibling task packages importable when this file is run as a script,
# so no PYTHONPATH is needed.
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

from task1.baseline_task1_historical_mean import (
    DEFAULT_RELEASE,
    FLOW_NORMALIZER,
    FLOW_WEIGHT,
    HERE,
    REGIMES,
    SPEED_NORMALIZER,
    SPEED_WEIGHT,
    lane_vector,
    station_lanes,
)


REQUIRED_COLUMNS = {"panel", "timestamp", "station_id", "link_id", "mask_regime", "speed_kmh", "flow_vph"}


def release_files(release: Path, panel: str, split: str) -> list[Path]:
    """The unmasked observation layer, which is the truth Task 1 is scored against.

    Only ``train`` ships it. On the scored splits the answers are withheld, so
    self-scoring runs on ``train``.
    """
    return sorted((release / "corridors" / panel / split / "mainline_states").glob("**/*.parquet"))


def masked_files(release: Path, panel: str, split: str, regime: str) -> list[Path]:
    """The masked partitions published under one regime.

    The release applies the Task 1 masks ahead of time and publishes each
    calendar day under exactly one regime, so which cells are targets - and
    under which regime - is read off the release rather than recomputed from a
    hash. The masked layer is partitioned by regime, the unmasked one by month,
    so the two are paired by file name.
    """
    root = release / "corridors" / panel / split / "mainline_states_masked" / f"mask_regime={regime}"
    return sorted(root.glob("*.parquet"))


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
        raise FileNotFoundError(
            f"{panel}: no unmasked {split} partitions. Only the train split ships the "
            "answers; validation and private are scored on the leaderboard."
        )
    truth_by_name = {p.name: p for p in paths}
    lanes_by_station = station_lanes(release / "corridors" / panel)
    panel_submission = submission[submission.panel == panel].copy()
    rows = []
    for regime in REGIMES:
        total_sq_speed = 0.0
        total_sq_flow = 0.0
        n_target = 0
        n_missing = 0
        n_invalid = 0
        for masked_path in masked_files(release, panel, split, regime):
            path = truth_by_name.get(masked_path.name)
            if path is None:
                continue
            frame = pd.read_parquet(
                path,
                columns=["date", "timestamp", "station_id", "link_id", "speed_kmh", "flow_vph", "is_score_eligible"],
            )
            frame["link_id"] = frame.link_id.astype(str)
            frame["station_id"] = frame.station_id.astype(str)
            frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
            blanked = pd.read_parquet(
                masked_path,
                columns=["timestamp", "station_id", "link_id", "speed_kmh", "flow_vph"],
            )
            blanked["link_id"] = blanked.link_id.astype(str)
            blanked["station_id"] = blanked.station_id.astype(str)
            blanked["timestamp"] = pd.to_datetime(blanked.timestamp, utc=True)
            blanked = blanked[blanked.speed_kmh.isna() & blanked.flow_vph.isna()][
                ["timestamp", "station_id", "link_id"]
            ]
            if blanked.empty:
                continue
            eligible = frame[frame.is_score_eligible.astype(bool)]
            target_frame = eligible.merge(
                blanked, on=["timestamp", "station_id", "link_id"], how="inner", validate="one_to_one"
            )
            truth = target_frame[["timestamp", "station_id", "link_id", "speed_kmh", "flow_vph"]].copy()
            if truth.empty:
                continue
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
            # Flow is scored per lane: FLOW_NORMALIZER is a single lane's scale,
            # so dividing by the station's lane count is what makes a 4-lane and
            # an 8-lane panel comparable.
            lanes = lane_vector(merged.station_id, merged.link_id, lanes_by_station)
            ds = pred_speed[usable] - true_speed[usable]
            dq = (pred_flow[usable] - true_flow[usable]) / lanes[usable]
            total_sq_speed += float(np.sum(ds * ds))
            total_sq_flow += float(np.sum(dq * dq))
            n_target += int(usable.sum())
            n_missing += int(missing[usable].sum())
            n_invalid += int(invalid_truth.sum())

        if n_target == 0:
            # No scoreable cell means no evidence, not a perfect answer. The old
            # guard divided by max(n_target, 1) to avoid a zero division, but the
            # numerator is zero too, so an empty panel scored RMSE 0 and took
            # S_state = 1.0 - a generation failure or a panel whose cells all
            # became ineligible would have been rewarded instead of surfaced.
            # score_task3.score_panel already returns 0.0 in this situation.
            rmse_speed = rmse_flow = float("nan")
            speed_score = flow_score = state_score = 0.0
        else:
            rmse_speed = float(np.sqrt(total_sq_speed / n_target))
            rmse_flow = float(np.sqrt(total_sq_flow / n_target))
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
                "rmse_flow_vph_per_lane": rmse_flow,
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
            "rmse_flow_vph_per_lane": np.nan,
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
    ap.add_argument("--split", choices=["validation", "train", "private"], default="validation")
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
                "rmse_flow_vph_per_lane": np.nan,
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
                "rmse_flow_vph_per_lane": np.nan,
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
