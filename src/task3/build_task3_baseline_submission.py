"""Build a Task 3 physics frame from a Task 1 submission, for inspection.

Since Task 3 became anchored to Task 1, the evaluator derives this frame itself
and a participant no longer submits one. The script is kept because the frame is
useful to look at, and because ``--project-conservation`` produces the reference
baseline that shows what a perfectly conservative answer would score.
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

from task1.baseline_task1_historical_mean import DEFAULT_RELEASE, HERE, REGIMES
from task3.score_task3 import (
    derive_physics,
    link_order,
    load_ramp_flows,
    network_parameters,
    read_csv_checked,
)

OUTPUT_COLUMNS = [
    "panel", "timestamp", "link_id", "mask_regime", "speed_kmh", "flow_vph",
    "density_vpkm", "inflow_vph", "outflow_vph", "on_ramp_flow_vph",
    "off_ramp_flow_vph", "on_ramp_valid", "off_ramp_valid", "accumulation_N",
]


def project_onto_conservation(out: pd.DataFrame) -> pd.DataFrame:
    """Minimum-norm, symmetric correction of the boundary flows.

    residual = dN - dt*(in + on - out - off);  in += r/(2 dt),  out -= r/(2 dt).
    """
    out = out.sort_values(["link_id", "timestamp"]).copy()
    next_n = out.groupby("link_id").accumulation_N.shift(-1)
    next_t = out.groupby("link_id").timestamp.shift(-1)
    dt = (next_t - out.timestamp).dt.total_seconds() / 3600.0
    residual = next_n - out.accumulation_N - dt * (
        out.inflow_vph + out.on_ramp_flow_vph - out.outflow_vph - out.off_ramp_flow_vph
    )
    valid = dt.gt(0) & dt.le(5.1 / 60.0) & residual.notna()
    correction = residual.where(valid, 0.0) / (2.0 * dt.where(valid, np.nan))
    correction = correction.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out["inflow_vph"] = out.inflow_vph + correction
    out["outflow_vph"] = out.outflow_vph - correction
    return out


def build_panel(panel: str, release: Path, split: str, state_panel: pd.DataFrame,
                output: Path, first_write: bool, project_conservation: bool = False) -> tuple[int, bool]:
    panel_dir = release / "corridors" / panel
    params = network_parameters(panel_dir).set_index("link_id")
    order = link_order(panel_dir, split)
    ramp_flows = load_ramp_flows(panel_dir, split)
    rows_written = 0
    for regime in REGIMES:
        out, missing = derive_physics(panel, release, split, state_panel, regime,
                                      order, params, ramp_flows)
        if missing:
            raise ValueError(f"{panel} {regime}: Task 1 submission is missing {missing} target values")
        if out.empty:
            continue
        if project_conservation:
            out = project_onto_conservation(out)
        out = out.sort_values(["timestamp", "link_id"])
        out["timestamp"] = out.timestamp.astype(str)
        out[OUTPUT_COLUMNS].to_csv(output, mode="w" if first_write else "a",
                                   header=first_write, index=False)
        first_write = False
        rows_written += len(out)
    return rows_written, first_write


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-submission", type=Path, required=True)
    ap.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE)
    ap.add_argument("--split", choices=["validation", "train"], default="validation")
    ap.add_argument("--output", type=Path, default=HERE / "reports" / "task3_physics_baseline_submission.csv")
    ap.add_argument("--panel", action="append")
    ap.add_argument("--project-conservation", action="store_true",
                    help="diagnostic reference baseline: project inflow/outflow onto conservation")
    args = ap.parse_args()
    state = read_csv_checked(args.state_submission.resolve(),
                             {"panel", "timestamp", "station_id", "link_id", "mask_regime", "speed_kmh", "flow_vph"},
                             "Task 1 state submission")
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
    first_write = True
    for panel in panels:
        print(f"[Task3 baseline] {panel}", flush=True)
        n, first_write = build_panel(panel, args.release_root.resolve(), args.split,
                                     state[state.panel == panel], args.output.resolve(),
                                     first_write, args.project_conservation)
        total += n
        print(f"  wrote {n:,} physical rows", flush=True)
    print(f"Wrote {total:,} rows to {args.output.resolve()}")


if __name__ == "__main__":
    main()
