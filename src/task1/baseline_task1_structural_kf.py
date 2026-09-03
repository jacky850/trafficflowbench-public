"""Task 1 structural baseline: historical profile + Kalman-smoothed deviations.

This is the canonical structural state-space combination (Zhou & Mahmassani,
2007, Transportation Research Part B): the weekday x time-of-day profile
carries the regular pattern, and a local-level Kalman filter with an RTS
backward pass smooths the same-day deviations from that pattern. The
historical-mean baseline is the regular pattern used alone; the quickstart
notebook's filter is the deviation model used alone on the raw series. This
baseline combines the two halves, which the 2007 paper demonstrates dominates
either half by itself.

For each public-validation day and masking regime, the baseline hides the
target cells, forms link-level deviations (observation minus profile) from the
remaining same-day cells, smooths each link's 288-slot deviation series, and
predicts profile + smoothed deviation. Links with no usable same-day
observation fall back to the profile alone.
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
    build_profile,
    files,
    slot_values,
    lane_vector,
    stable_mask,
    station_lanes,
)


def kalman_smooth(y: np.ndarray, q: float, r: float) -> np.ndarray:
    """Local-level Kalman filter + RTS smoother; NaN entries are missing."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    finite = np.flatnonzero(np.isfinite(y))
    if len(finite) == 0:
        return np.zeros(n)
    x_f = np.zeros(n)
    p_f = np.zeros(n)
    x_p = np.zeros(n)
    p_p = np.zeros(n)
    x, p = y[finite[0]], r
    for t in range(n):
        if t > 0:
            p = p + q
        x_p[t], p_p[t] = x, p
        if np.isfinite(y[t]):
            k = p / (p + r)
            x = x + k * (y[t] - x)
            p = (1.0 - k) * p
        x_f[t], p_f[t] = x, p
    x_s = x_f.copy()
    for t in range(n - 2, -1, -1):
        g = p_f[t] / p_p[t + 1]
        x_s[t] = x_f[t] + g * (x_s[t + 1] - x_f[t + 1])
    return x_s


def smooth_deviation_rows(dev: np.ndarray) -> np.ndarray:
    """Smooth each link's within-day deviation series; all-NaN rows become 0."""
    out = np.zeros_like(dev)
    for i in range(dev.shape[0]):
        row = dev[i]
        if not np.isfinite(row).any():
            continue
        sd = max(float(np.nanstd(row)), 1e-3)
        out[i] = kalman_smooth(row, q=(0.35 * sd) ** 2, r=(0.8 * sd) ** 2)
    return out


def profile_rows(profile: dict, counts: np.ndarray, safe_li: np.ndarray, slot: np.ndarray) -> np.ndarray:
    values = profile["mean"][safe_li, slot]
    return np.where(counts[safe_li, slot] == 0, profile["fallback"][safe_li], values)


def evaluate_panel(panel: str, release: Path) -> list[dict]:
    panel_dir = release / "corridors" / panel
    lanes_by_station = station_lanes(panel_dir)
    speed_profile, flow_profile, profile_counts = build_profile(panel, panel_dir)
    link_ids = speed_profile["link_ids"]
    link_index = speed_profile["link_index"]
    n_links = len(link_ids)
    sums = {r: {"speed_sq": 0.0, "flow_sq": 0.0, "n": 0} for r in REGIMES}
    for path in files(panel_dir, "validation"):
        frame = pd.read_parquet(
            path,
            columns=["date", "timestamp", "station_id", "link_id", "speed_kmh", "flow_vph", "is_score_eligible"],
        )
        frame["link_id"] = frame.link_id.astype(str)
        li = frame.link_id.map(link_index).fillna(-1).to_numpy(dtype=np.int64)
        known = li >= 0
        safe_li = np.where(known, li, 0)
        weekday, tod = slot_values(frame)
        slot = weekday * 288 + tod
        true_speed = pd.to_numeric(frame.speed_kmh, errors="coerce").to_numpy(dtype=float)
        true_flow = pd.to_numeric(frame.flow_vph, errors="coerce").to_numpy(dtype=float)
        eligible = frame.is_score_eligible.astype(bool).to_numpy().copy()
        prof_speed = profile_rows(speed_profile, profile_counts["speed_count"], safe_li, slot)
        prof_flow = profile_rows(flow_profile, profile_counts["flow_count"], safe_li, slot)
        for regime in REGIMES:
            target = eligible & stable_mask(panel, regime, frame.date, frame.timestamp, frame.link_id)
            dev_speed = np.full((n_links, 288), np.nan)
            dev_flow = np.full((n_links, 288), np.nan)
            dev_speed_n = np.zeros((n_links, 288), dtype=np.int32)
            dev_flow_n = np.zeros((n_links, 288), dtype=np.int32)
            dev_speed_sum = np.zeros((n_links, 288), dtype=float)
            dev_flow_sum = np.zeros((n_links, 288), dtype=float)
            # Deviations come only from unmasked eligible cells: the target
            # values are hidden from the filter exactly as the evaluator hides
            # them from a participant.
            obs_speed = eligible & ~target & known & np.isfinite(true_speed) & np.isfinite(prof_speed)
            obs_flow = eligible & ~target & known & np.isfinite(true_flow) & np.isfinite(prof_flow)
            np.add.at(dev_speed_sum, (li[obs_speed], tod[obs_speed]), (true_speed - prof_speed)[obs_speed])
            np.add.at(dev_flow_sum, (li[obs_flow], tod[obs_flow]), (true_flow - prof_flow)[obs_flow])
            np.add.at(dev_speed_n, (li[obs_speed], tod[obs_speed]), 1)
            np.add.at(dev_flow_n, (li[obs_flow], tod[obs_flow]), 1)
            np.divide(dev_speed_sum, dev_speed_n, out=dev_speed, where=dev_speed_n > 0)
            np.divide(dev_flow_sum, dev_flow_n, out=dev_flow, where=dev_flow_n > 0)
            smooth_speed = smooth_deviation_rows(dev_speed)
            smooth_flow = smooth_deviation_rows(dev_flow)
            pred_speed = np.clip(prof_speed + smooth_speed[safe_li, tod], 0.0, None)
            pred_flow = np.clip(prof_flow + smooth_flow[safe_li, tod], 0.0, None)
            pred_speed = np.where(known, pred_speed, prof_speed)
            pred_flow = np.where(known, pred_flow, prof_flow)
            mask = target & np.isfinite(true_speed) & np.isfinite(true_flow) & np.isfinite(pred_speed) & np.isfinite(pred_flow)
            ds = pred_speed[mask] - true_speed[mask]
            # Flow is scored per lane; see station_lanes().
            dq = (pred_flow[mask] - true_flow[mask]) / lane_vector(frame.station_id, frame.link_id, lanes_by_station)[mask]
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
                "rmse_flow_vph_per_lane": rmse_flow,
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
            "rmse_flow_vph_per_lane": np.nan,
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
        print(f"[Task1 structural KF baseline] {panel}", flush=True)
        rows.extend(evaluate_panel(panel, args.release_root.resolve()))
    out = HERE / "reports" / "baseline_task1_structural_kf.csv"
    out.parent.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
