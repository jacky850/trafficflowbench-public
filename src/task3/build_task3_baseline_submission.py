"""Build a complete V1 Task 3 physics baseline from a Task 1 submission."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from task1.baseline_task1_historical_mean import DEFAULT_RELEASE, HERE, REGIMES
from task3.score_task3 import PHYS_COLUMNS, network_parameters, read_csv_checked, state_for_regime


OUTPUT_COLUMNS = [
    "panel", "timestamp", "link_id", "mask_regime", "speed_kmh", "flow_vph",
    "density_vpkm", "inflow_vph", "outflow_vph", "on_ramp_flow_vph",
    "off_ramp_flow_vph", "on_ramp_valid", "off_ramp_valid", "accumulation_N",
]
DT_H = 5.0 / 60.0

def load_ramp_flows(panel_dir: Path) -> pd.DataFrame:
    """Aggregate valid released ramp observations to attached mainline links."""
    amap_path = panel_dir / "network" / "ramp_attachment_map.csv"
    ramp_root = panel_dir / "validation" / "ramp_states"
    if not amap_path.exists() or not ramp_root.exists():
        return pd.DataFrame(columns=["timestamp", "link_id", "on_ramp_flow_vph", "off_ramp_flow_vph"])
    amap = pd.read_csv(amap_path, dtype=str)
    amap = amap.rename(columns={"nearest_mainline_link_id": "link_id"})
    amap["ramp_link_id"] = amap.ramp_link_id.astype(str)
    amap["link_id"] = amap.link_id.astype(str)
    pieces = []
    for path in sorted(ramp_root.glob("**/*.parquet")):
        f = pd.read_parquet(path, columns=["timestamp", "ramp_link_id", "ramp_type", "flow_vph", "pct_observed", "is_score_eligible"])
        f["ramp_link_id"] = f.ramp_link_id.astype(str)
        f["timestamp"] = pd.to_datetime(f.timestamp, utc=True)
        f["flow_vph"] = pd.to_numeric(f.flow_vph, errors="coerce")
        f["pct_observed"] = pd.to_numeric(f.pct_observed, errors="coerce")
        f = f[f.is_score_eligible.astype(bool) & (f.pct_observed >= 75) & f.flow_vph.notna()]
        if f.empty:
            continue
        f = f.merge(amap[["ramp_link_id", "link_id"]], on="ramp_link_id", how="inner")
        f["_is_on"] = f.ramp_type.astype(str).str.upper().isin(["OR", "ON"])
        f["_is_off"] = f.ramp_type.astype(str).str.upper().isin(["FR", "OFF"])
        f["on_ramp_flow_vph"] = np.where(f._is_on, f.flow_vph, 0.0)
        f["off_ramp_flow_vph"] = np.where(f._is_off, f.flow_vph, 0.0)
        f["on_ramp_valid"] = f._is_on.astype(int)
        f["off_ramp_valid"] = f._is_off.astype(int)
        pieces.append(f[["timestamp", "link_id", "on_ramp_flow_vph", "off_ramp_flow_vph", "on_ramp_valid", "off_ramp_valid"]])
    if not pieces:
        return pd.DataFrame(columns=["timestamp", "link_id", "on_ramp_flow_vph", "off_ramp_flow_vph"])
    return (pd.concat(pieces, ignore_index=True)
            .groupby(["timestamp", "link_id"], as_index=False)
            .agg(on_ramp_flow_vph=("on_ramp_flow_vph", "sum"),
                 off_ramp_flow_vph=("off_ramp_flow_vph", "sum"),
                 on_ramp_valid=("on_ramp_valid", "max"),
                 off_ramp_valid=("off_ramp_valid", "max"))
            )

def topology_boundary_flows(state: pd.DataFrame, panel_dir: Path) -> pd.DataFrame:
    """Compute total mainline boundary flows from the released topology."""
    topo_path = panel_dir / "network" / "lwr_mainline_topology.csv"
    if not topo_path.exists():
        return pd.DataFrame(columns=["timestamp", "link_id", "inflow_vph", "outflow_vph"])
    topo = pd.read_csv(topo_path, dtype=str)
    topo["link_id"] = topo.link_id.astype(str)
    topo = topo.drop_duplicates("link_id").set_index("link_id")
    pivot = state.pivot_table(index="timestamp", columns="link_id", values="flow_vph", aggfunc="mean")
    known = set(pivot.columns.astype(str))
    rows = []
    for link in state.link_id.astype(str).drop_duplicates():
        if link not in pivot.columns:
            continue
        if link in topo.index:
            incoming = [x for x in str(topo.loc[link].get("incoming_link_ids", "")).split(";") if x in known]
            outgoing = [x for x in str(topo.loc[link].get("outgoing_link_ids", "")).split(";") if x in known]
        else:
            incoming, outgoing = [], []
        inflow = pivot[incoming].sum(axis=1) if incoming else pivot[link]
        outflow = pivot[outgoing].sum(axis=1) if outgoing else pivot[link]
        rows.append(pd.DataFrame({"timestamp": pivot.index, "link_id": link,
                                  "inflow_vph": inflow.to_numpy(),
                                  "outflow_vph": outflow.to_numpy()}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["timestamp", "link_id", "inflow_vph", "outflow_vph"])


def link_order(panel_dir: Path) -> list[str]:
    files = sorted((panel_dir / "validation" / "mainline_states").glob("**/*.parquet"))
    first = pd.read_parquet(files[0], columns=["link_id", "milepost"])
    order = first.drop_duplicates("link_id").copy()
    order["link_id"] = order.link_id.astype(str)
    order["milepost"] = pd.to_numeric(order.milepost, errors="coerce")
    return order.sort_values(["milepost", "link_id"]).link_id.tolist()


def build_panel(panel: str, release: Path, split: str, state_panel: pd.DataFrame, output: Path, first_write: bool, project_conservation: bool = False) -> tuple[int, bool]:
    panel_dir = release / "corridors" / panel
    params = network_parameters(panel_dir)
    params = params.set_index("link_id")
    order = link_order(panel_dir)
    ramp_flows = load_ramp_flows(panel_dir)
    rows_written = 0
    for regime in REGIMES:
        state, missing = state_for_regime(panel, panel_dir, split, regime, state_panel)
        if missing:
            raise ValueError(f"{panel} {regime}: Task 1 submission is missing {missing} target values")
        state = state.merge(params.reset_index(), on="link_id", how="left")
        state["speed_kmh"] = pd.to_numeric(state.speed_kmh, errors="coerce")
        state["flow_vph"] = pd.to_numeric(state.flow_vph, errors="coerce")
        state = state.dropna(subset=["speed_kmh", "flow_vph", "length_km", "capacity_vph", "critical_density", "k_jam"])
        state["density_vpkm"] = state.flow_vph / state.speed_kmh.clip(lower=1.0)
        state["accumulation_N"] = state.density_vpkm * state.length_km

        # Use the corridor link order to define a simple upstream discharge.
        rank = {link: i for i, link in enumerate(order)}
        state["_rank"] = state.link_id.map(rank).fillna(len(rank)).astype(int)
        state = state.sort_values(["timestamp", "_rank", "link_id"])
        # Organizer baseline: ramp flows are zero rather than fabricated. The
        # evaluator treats these as explicit participant fields; a participant
        # may estimate non-zero on/off flows from the released ramp states.
        if not ramp_flows.empty:
            state = state.merge(ramp_flows, on=["timestamp", "link_id"], how="left")
        if "on_ramp_flow_vph" not in state:
            state["on_ramp_flow_vph"] = 0.0
        if "off_ramp_flow_vph" not in state:
            state["off_ramp_flow_vph"] = 0.0
        if "on_ramp_valid" not in state:
            state["on_ramp_valid"] = False
        if "off_ramp_valid" not in state:
            state["off_ramp_valid"] = False
        state["on_ramp_flow_vph"] = pd.to_numeric(state["on_ramp_flow_vph"], errors="coerce").fillna(0.0)
        state["off_ramp_flow_vph"] = pd.to_numeric(state["off_ramp_flow_vph"], errors="coerce").fillna(0.0)
        # For links without that ramp type, zero is a valid structural value;
        # for attached ramps, only a released >=75%-observed cell is valid.
        topo = pd.read_csv(panel_dir / "network" / "lwr_mainline_topology.csv", dtype=str)
        topo["link_id"] = topo.link_id.astype(str)
        on_attached = set(topo.loc[topo.on_ramp_link_ids.fillna("").astype(str).str.len() > 0, "link_id"])
        off_attached = set(topo.loc[topo.off_ramp_link_ids.fillna("").astype(str).str.len() > 0, "link_id"])
        state["on_ramp_valid"] = state.on_ramp_valid.astype(bool) | ~state.link_id.isin(on_attached)
        state["off_ramp_valid"] = state.off_ramp_valid.astype(bool) | ~state.link_id.isin(off_attached)

        # Topology-aware boundary flows, after ramp observations are joined.
        boundaries = topology_boundary_flows(state, panel_dir)
        state = state.drop(columns=["inflow_vph", "outflow_vph"], errors="ignore")
        state = state.merge(boundaries, on=["timestamp", "link_id"], how="left")
        state["inflow_vph"] = state.inflow_vph.fillna(state.flow_vph)
        state["outflow_vph"] = state.outflow_vph.fillna(state.flow_vph)
        # Keep mainline boundary flows separate from attached-ramp flows.
        # The Task 3 evaluator applies the conservation equation as
        #   dN = dt * (inflow + on_ramp - outflow - off_ramp).
        # Adding ramps here would count every valid ramp twice.

        # Optional reference baseline: project the submitted boundary flows
        # onto the discrete conservation equation. This is intentionally
        # opt-in; the default baseline remains the unprojected historical
        # reconstruction. The correction is minimum-norm and symmetric:
        # residual = dN - dt*(in + on - out - off),
        # in += residual/(2*dt), out -= residual/(2*dt).
        state = state.sort_values(["link_id", "timestamp"])
        next_n = state.groupby("link_id").accumulation_N.shift(-1)
        next_t = state.groupby("link_id").timestamp.shift(-1)
        dt = (next_t - state.timestamp).dt.total_seconds() / 3600.0
        residual = next_n - state.accumulation_N - dt * (
            state.inflow_vph + state.on_ramp_flow_vph
            - state.outflow_vph - state.off_ramp_flow_vph
        )
        valid = dt.gt(0) & dt.le(5.1 / 60.0) & residual.notna()
        if project_conservation:
            correction = residual.where(valid, 0.0) / (2.0 * dt.where(valid, np.nan))
            correction = correction.replace([np.inf, -np.inf], np.nan).fillna(0.0)
            state["inflow_vph"] = state.inflow_vph + correction
            state["outflow_vph"] = state.outflow_vph - correction
        state = state.sort_values(["timestamp", "_rank", "link_id"])
        out = pd.DataFrame(
            {
                "panel": panel,
                "timestamp": state.timestamp.astype(str),
                "link_id": state.link_id.astype(str),
                "mask_regime": regime,
                "speed_kmh": state.speed_kmh,
                "flow_vph": state.flow_vph,
                "density_vpkm": state.density_vpkm,
                "inflow_vph": state.inflow_vph,
                "outflow_vph": state.outflow_vph,
                "on_ramp_flow_vph": state.on_ramp_flow_vph,
                "off_ramp_flow_vph": state.off_ramp_flow_vph,
                "on_ramp_valid": state.on_ramp_valid.astype(int),
                "off_ramp_valid": state.off_ramp_valid.astype(int),
                "accumulation_N": state.accumulation_N,
            },
            columns=OUTPUT_COLUMNS,
        )
        out.to_csv(output, mode="w" if first_write else "a", header=first_write, index=False)
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
    state = read_csv_checked(args.state_submission.resolve(), {"panel", "timestamp", "station_id", "link_id", "mask_regime", "speed_kmh", "flow_vph"}, "Task 1 state submission")
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
