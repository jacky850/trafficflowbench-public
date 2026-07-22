"""Task 1 stronger baseline: historical mean + same-day temporal/spatial fill.

For each public-validation day and masking regime, the baseline hides the target
cells, uses the remaining same-day cells for interpolation, and falls back to the
public-train time-of-week profile when local observations are unavailable.
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
    build_profile,
    files,
    slot_values,
    stable_mask,
)


def link_order(panel_dir: Path, path: Path) -> list[str]:
    frame = pd.read_parquet(path, columns=["link_id", "milepost"])
    order = frame.drop_duplicates("link_id").sort_values("milepost")
    if panel_dir.name.endswith(("_W", "_S")):
        order = order.iloc[::-1]
    return order.link_id.astype(str).tolist()


def local_matrix(frame: pd.DataFrame, link_ids: list[str], target: np.ndarray):
    link_index = {x: i for i, x in enumerate(link_ids)}
    # A release should normally have the same links in train and validation,
    # but keep the baseline robust to a link appearing only in validation.
    li_raw = frame.link_id.map(link_index)
    li = li_raw.fillna(-1).to_numpy(dtype=np.int64)
    ts = pd.to_datetime(frame.timestamp, utc=True)
    ti = (ts.dt.hour * 12 + ts.dt.minute // 5).to_numpy(dtype=np.int16)
    n_links = len(link_ids)
    speed_sum = np.zeros((n_links, 288), dtype=float)
    flow_sum = np.zeros((n_links, 288), dtype=float)
    speed_n = np.zeros((n_links, 288), dtype=np.int32)
    flow_n = np.zeros((n_links, 288), dtype=np.int32)
    valid = frame.is_score_eligible.astype(bool).to_numpy()
    speed = pd.to_numeric(frame.speed_kmh, errors="coerce").to_numpy(dtype=float)
    flow = pd.to_numeric(frame.flow_vph, errors="coerce").to_numpy(dtype=float)
    observed = valid & ~target
    known = li >= 0
    ok_speed = observed & known & np.isfinite(speed)
    ok_flow = observed & known & np.isfinite(flow)
    np.add.at(speed_sum, (li[ok_speed], ti[ok_speed]), speed[ok_speed])
    np.add.at(flow_sum, (li[ok_flow], ti[ok_flow]), flow[ok_flow])
    np.add.at(speed_n, (li[ok_speed], ti[ok_speed]), 1)
    np.add.at(flow_n, (li[ok_flow], ti[ok_flow]), 1)
    return li, ti, valid, speed_sum, speed_n, flow_sum, flow_n


def interpolate(values: np.ndarray, counts: np.ndarray, fallback: np.ndarray, neighbor_radius: int = 2) -> np.ndarray:
    n_links, n_time = values.shape
    out = np.zeros_like(values)
    for i in range(n_links):
        observed = counts[i] > 0
        if observed.any():
            x = np.flatnonzero(observed)
            y = values[i, x] / counts[i, x]
            out[i] = np.interp(np.arange(n_time), x, y)
        else:
            out[i] = fallback[i]
    # For links with no same-day observation, borrow nearby links at each time.
    for i in range(n_links):
        if counts[i].sum() > 0:
            continue
        lo, hi = max(0, i - neighbor_radius), min(n_links, i + neighbor_radius + 1)
        neighbor_values = []
        for j in range(lo, hi):
            if j != i and counts[j].sum() > 0:
                neighbor_values.append(out[j])
        if neighbor_values:
            out[i] = np.mean(neighbor_values, axis=0)
    return out


def evaluate_panel(panel: str, release: Path, output_root: Path) -> list[dict]:
    panel_dir = release / "corridors" / panel
    speed_profile, flow_profile, profile_counts = build_profile(panel, panel_dir)
    link_ids = speed_profile["link_ids"]
    link_index = speed_profile["link_index"]
    sums = {r: {"speed_sq": 0.0, "flow_sq": 0.0, "n": 0} for r in REGIMES}
    for path in files(panel_dir, "validation"):
        frame = pd.read_parquet(
            path,
            columns=["date", "timestamp", "link_id", "speed_kmh", "flow_vph", "is_score_eligible"],
        )
        frame["link_id"] = frame.link_id.astype(str)
        li = frame.link_id.map(link_index).fillna(-1).to_numpy(dtype=np.int64)
        known = li >= 0
        weekday, tod = slot_values(frame)
        slot = weekday * 288 + tod
        true_speed = pd.to_numeric(frame.speed_kmh, errors="coerce").to_numpy(dtype=float)
        true_flow = pd.to_numeric(frame.flow_vph, errors="coerce").to_numpy(dtype=float)
        valid_base = frame.is_score_eligible.astype(bool).to_numpy().copy()
        for regime in REGIMES:
            target = valid_base & stable_mask(panel, regime, frame.date, frame.timestamp, frame.link_id)
            # Unknown links use historical fallback and are not eligible for the
            # local matrix; they are still handled safely below.
            safe_li = np.where(known, li, 0)
            local = local_matrix(frame, link_ids, target)
            _, _, valid, speed_sum, speed_n, flow_sum, flow_n = local
            speed_fallback = speed_profile["mean"][safe_li, slot]
            flow_fallback = flow_profile["mean"][safe_li, slot]
            speed_no_profile = profile_counts["speed_count"][safe_li, slot] == 0
            flow_no_profile = profile_counts["flow_count"][safe_li, slot] == 0
            speed_fallback = np.where(speed_no_profile, speed_profile["fallback"][safe_li], speed_fallback)
            flow_fallback = np.where(flow_no_profile, flow_profile["fallback"][safe_li], flow_fallback)
            speed_local = interpolate(speed_sum, speed_n, speed_profile["fallback"])
            flow_local = interpolate(flow_sum, flow_n, flow_profile["fallback"])
            # The local matrix is a within-day (288 five-minute slots) matrix;
            # the historical fallback uses the full weekday×time-of-day slot.
            pred_speed = np.where(known, speed_local[safe_li, tod], speed_fallback)
            pred_flow = np.where(known, flow_local[safe_li, tod], flow_fallback)
            mask = target & np.isfinite(true_speed) & np.isfinite(true_flow) & np.isfinite(pred_speed) & np.isfinite(pred_flow)
            ds = pred_speed[mask] - true_speed[mask]
            dq = pred_flow[mask] - true_flow[mask]
            sums[regime]["speed_sq"] += float(np.sum(ds * ds))
            sums[regime]["flow_sq"] += float(np.sum(dq * dq))
            sums[regime]["n"] += int(mask.sum())
    rows = []
    for regime, s in sums.items():
        n = max(s["n"], 1)
        rmse_speed = float(np.sqrt(s["speed_sq"] / n))
        rmse_flow = float(np.sqrt(s["flow_sq"] / n))
        speed_score = max(0.0, 1.0 - rmse_speed / SPEED_NORMALIZER)
        flow_score = max(0.0, 1.0 - rmse_flow / FLOW_NORMALIZER)
        rows.append(
            {
                "panel": panel,
                "regime": regime,
                "n_cells": s["n"],
                "rmse_speed_kmh": rmse_speed,
                "rmse_flow_vph": rmse_flow,
                "S_speed": speed_score,
                "S_flow": flow_score,
                "S_state_regime": SPEED_WEIGHT * speed_score + FLOW_WEIGHT * flow_score,
            }
        )
    rows.append(
        {
            "panel": panel,
            "regime": "macro_mean",
            "n_cells": sum(s["n"] for s in sums.values()),
            "rmse_speed_kmh": np.nan,
            "rmse_flow_vph": np.nan,
            "S_speed": np.nan,
            "S_flow": np.nan,
            "S_state_regime": float(np.mean([r["S_state_regime"] for r in rows])),
        }
    )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE)
    ap.add_argument("--panel", action="append")
    args = ap.parse_args()
    contract = json.loads((HERE / "config" / "corridors.json").read_text(encoding="utf-8"))
    panels = [p["corridor_id"] for p in contract["panels"]]
    selected = [p for p in panels if not args.panel or p in set(args.panel)]
    rows = []
    for panel in selected:
        print(f"[Task1 enhanced baseline] {panel}", flush=True)
        rows.extend(evaluate_panel(panel, args.release_root.resolve(), HERE / "baselines" / "task1_enhanced"))
    out = HERE / "reports" / "baseline_task1_enhanced.csv"
    out.parent.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
