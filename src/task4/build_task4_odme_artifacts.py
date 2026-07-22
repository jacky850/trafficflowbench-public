"""Build public Task 4 ODME reference and train-only baseline artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from task1.baseline_task1_historical_mean import DEFAULT_RELEASE, HERE, files


PM_START, PM_END = 15, 19
REG_LAMBDA = 0.05


def counts_for_split(panel_dir: Path, split: str) -> pd.DataFrame:
    main_parts = []
    for path in files(panel_dir, split):
        d = pd.read_parquet(path, columns=["timestamp", "link_id", "flow_vph"])
        ts = pd.to_datetime(d.timestamp, utc=True)
        d = d[(ts.dt.hour >= PM_START) & (ts.dt.hour < PM_END)].copy()
        d["link_id"] = d.link_id.astype(str)
        d["flow_vph"] = pd.to_numeric(d.flow_vph, errors="coerce")
        main_parts.append(d[["link_id", "flow_vph"]])
    parts = main_parts
    ramp_dir = panel_dir / split / "ramp_states"
    ramp_map_path = panel_dir / "network" / "ramp_station_map.csv"
    ramp_map = None
    if ramp_map_path.exists():
        ramp_map = pd.read_csv(ramp_map_path, dtype={"station_id": str, "ramp_link_id": str})
        ramp_map = ramp_map[["station_id", "ramp_link_id"]].drop_duplicates("station_id")
    for path in sorted(ramp_dir.glob("**/*.parquet")):
        d = pd.read_parquet(path, columns=["timestamp", "station_id", "ramp_link_id", "flow_vph"])
        ts = pd.to_datetime(d.timestamp, utc=True)
        d = d[(ts.dt.hour >= PM_START) & (ts.dt.hour < PM_END)].copy()
        if ramp_map is not None:
            d["station_id"] = d.station_id.astype(str)
            d = d.merge(ramp_map, on="station_id", how="left", suffixes=("_raw", ""))
            d["link_id"] = d.ramp_link_id.fillna(d.ramp_link_id_raw)
        else:
            d["link_id"] = d.ramp_link_id
        d["link_id"] = d.link_id.astype(str)
        d["flow_vph"] = pd.to_numeric(d.flow_vph, errors="coerce")
        parts.append(d[["link_id", "flow_vph"]])
    if not parts:
        return pd.DataFrame(columns=["link_id", "count"])
    all_counts = pd.concat(parts, ignore_index=True).dropna(subset=["flow_vph"])
    return all_counts.groupby("link_id", as_index=False).flow_vph.mean().rename(columns={"flow_vph": "count"})


def load_operator(network: Path) -> tuple[list[str], list[str], np.ndarray, pd.DataFrame, pd.DataFrame]:
    paths = pd.read_csv(network / "path_set.csv")
    paths["path_id"] = paths.path_id.astype(str)
    incidence = pd.read_csv(network / "path_link_incidence.csv")
    incidence["path_id"] = incidence.path_id.astype(str)
    incidence["link_id"] = incidence.link_id.astype(str)
    path_ids = paths.path_id.tolist()
    link_ids = incidence.link_id.drop_duplicates().tolist()
    path_index = {x: i for i, x in enumerate(path_ids)}
    link_index = {x: i for i, x in enumerate(link_ids)}
    rr = incidence.link_id.map(link_index).to_numpy(dtype=np.int64)
    cc = incidence.path_id.map(path_index).to_numpy(dtype=np.int64)
    A = np.zeros((len(link_ids), len(path_ids)), dtype=np.float64)
    A[rr, cc] = 1.0
    base = pd.read_csv(network / "base_od.csv")
    base["path_id"] = base.path_id.astype(str)
    base = paths[["path_id", "origin_zone", "destination_zone"]].merge(base[["path_id", "departure_time", "base_flow"]], on="path_id", how="left")
    base = base.set_index("path_id").reindex(path_ids).reset_index()
    base["base_flow"] = pd.to_numeric(base.base_flow, errors="coerce").fillna(0.0)
    return path_ids, link_ids, A, paths, base


def solve(A: np.ndarray, counts: np.ndarray, base: np.ndarray) -> np.ndarray:
    aa = np.vstack([A, np.sqrt(REG_LAMBDA) * np.eye(A.shape[1])])
    bb = np.concatenate([counts, np.sqrt(REG_LAMBDA) * base])
    f, _ = nnls(aa, bb)
    return f


def build_panel(panel: str, release: Path, output_root: Path) -> tuple[int, int]:
    panel_dir = release / "corridors" / panel
    network = panel_dir / "network"
    path_ids, link_ids, A, paths, base = load_operator(network)
    base_values = base.base_flow.to_numpy(dtype=float)
    train_count_frame = counts_for_split(panel_dir, "train")
    val_count_frame = counts_for_split(panel_dir, "validation")
    train_counts = train_count_frame.set_index("link_id").reindex(link_ids).fillna(0.0)["count"].to_numpy(dtype=float)
    val_counts = val_count_frame.set_index("link_id").reindex(link_ids).fillna(0.0)["count"].to_numpy(dtype=float)
    # Public PeMS has counts only at detector links, while the released
    # incidence operator also contains unobserved connectors. Do not treat an
    # unobserved connector as a measured zero in the local ODME solve.
    # The public score domain is the validation measurement universe. A link
    # that appears only in train but has no validation count must not be turned
    # into an artificial validation zero.
    observed_links = set(val_count_frame.link_id)
    measured = np.array([link in observed_links for link in link_ids], dtype=bool)
    train_f = solve(A[measured], train_counts[measured], base_values)
    val_f = solve(A[measured], val_counts[measured], base_values)
    out = output_root
    out.mkdir(parents=True, exist_ok=True)
    def frame(f: np.ndarray) -> pd.DataFrame:
        x = paths[["path_id", "origin_zone", "destination_zone"]].copy()
        x["panel"] = panel
        x["departure_time"] = base.departure_time.fillna("PUBLIC-TRAIN-PM").iloc[0]
        x["path_flow"] = f
        return x[["panel", "departure_time", "path_id", "origin_zone", "destination_zone", "path_flow"]]
    frame(train_f).to_csv(out / f"{panel}_baseline_submission.csv", index=False)
    frame(val_f).to_csv(out / f"{panel}_public_reference.csv", index=False)
    pd.DataFrame({"panel": panel, "link_id": np.asarray(link_ids)[measured], "count": val_counts[measured]}).to_csv(out / f"{panel}_public_link_counts.csv", index=False)
    return len(path_ids), len(link_ids)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE)
    ap.add_argument("--output-root", type=Path, default=HERE / "reports" / "task4_odme")
    ap.add_argument("--panel", action="append")
    args = ap.parse_args()
    manifest = json.loads((HERE / "config" / "corridors.json").read_text(encoding="utf-8"))
    panels = [p["corridor_id"] for p in manifest["panels"]]
    if args.panel:
        requested = set(args.panel)
        unknown = sorted(requested - set(panels))
        if unknown:
            raise ValueError(f"unknown --panel values: {unknown}")
        panels = [p for p in panels if p in requested]
    args.output_root.mkdir(parents=True, exist_ok=True)
    for panel in panels:
        print(f"[Task4 ODME artifacts] {panel}", flush=True)
        npaths, nlinks = build_panel(panel, args.release_root.resolve(), args.output_root.resolve())
        print(f"  paths={npaths:,}, operator links={nlinks:,}", flush=True)
    # Convenience combined files for the evaluator and leaderboard smoke test.
    for suffix, name in [
        ("baseline_submission", "baseline_submission.csv"),
        ("public_reference", "public_reference.csv"),
        ("public_link_counts", "public_link_counts.csv"),
    ]:
        parts = [args.output_root / f"{p}_{suffix}.csv" for p in panels]
        pd.concat([pd.read_csv(p) for p in parts], ignore_index=True).to_csv(args.output_root / name, index=False)
    print(f"Wrote artifacts to {args.output_root.resolve()}")


if __name__ == "__main__":
    main()
