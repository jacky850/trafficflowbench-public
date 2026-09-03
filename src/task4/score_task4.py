"""Local V1 evaluator for Task 4 ODME/path-flow estimation."""
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

from task1.baseline_task1_historical_mean import HERE
from task4.build_task4_odme_artifacts import load_operator


REQUIRED = {"panel", "departure_time", "path_id", "origin_zone", "destination_zone", "path_flow"}


def read_submission(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Task 4 submission not found: {path}")
    d = pd.read_csv(path)
    missing = sorted(REQUIRED - set(d.columns))
    if missing:
        raise ValueError(f"Task 4 submission missing columns: {missing}")
    d = d.copy()
    for c in ("panel", "departure_time", "path_id", "origin_zone", "destination_zone"):
        d[c] = d[c].astype(str)
    d["path_flow"] = pd.to_numeric(d.path_flow, errors="coerce")
    return d


def score_panel(panel: str, release: Path, reference_root: Path, submission: pd.DataFrame) -> dict:
    network = release / "corridors" / panel / "network"
    path_ids, link_ids, A, paths, base = load_operator(network)
    ref_path = reference_root / f"{panel}_public_reference.csv"
    count_path = reference_root / f"{panel}_public_link_counts.csv"
    if not ref_path.exists() or not count_path.exists():
        raise FileNotFoundError(f"missing public ODME reference/count artifact for {panel}")
    ref = pd.read_csv(ref_path)
    count_frame = pd.read_csv(count_path)
    count_frame["link_id"] = count_frame.link_id.astype(str)
    link_index = {link: i for i, link in enumerate(link_ids)}
    scored_links = [link for link in count_frame.link_id if link in link_index]
    scored_rows = [link_index[link] for link in scored_links]
    A_score = A[scored_rows, :]
    counts = count_frame.set_index("link_id").reindex(scored_links).fillna(0.0)["count"].to_numpy(dtype=float)
    ref = ref.set_index("path_id").reindex(path_ids)
    sub = submission[submission.panel == panel].copy()
    duplicate = int(sub.duplicated(["path_id"]).sum())
    missing = int(ref.index.difference(sub.path_id).size)
    merged = ref[["origin_zone", "destination_zone", "path_flow"]].copy()
    merged["path_id"] = path_ids
    sub_idx = sub.set_index("path_id") if not sub.empty else pd.DataFrame()
    if not sub.empty:
        merged["pred_flow"] = sub_idx.reindex(path_ids)["path_flow"].to_numpy()
    else:
        merged["pred_flow"] = np.nan
    invalid = int((~np.isfinite(pd.to_numeric(merged.pred_flow, errors="coerce")) | (pd.to_numeric(merged.pred_flow, errors="coerce") < 0)).sum())
    # Enforce the declared metadata contract: submitted origin/destination zones
    # must match the released path definition (not merely be present). Otherwise
    # a row with the right path_id and flow but fabricated zones scored 1.0.
    zone_mismatch = 0
    if not sub.empty:
        so = sub_idx.reindex(path_ids)["origin_zone"].astype(str)
        sdz = sub_idx.reindex(path_ids)["destination_zone"].astype(str)
        ro = merged.origin_zone.astype(str).to_numpy()
        rd = merged.destination_zone.astype(str).to_numpy()
        present = sub_idx.reindex(path_ids)["path_flow"].notna().to_numpy()
        zone_mismatch = int(((so.to_numpy() != ro) | (sdz.to_numpy() != rd))[present].sum())
    if duplicate or missing or invalid or zone_mismatch:
        return {"level": "panel", "panel": panel, "family_id": None, "n_paths": len(path_ids), "missing_paths": missing, "duplicate_rows": duplicate, "invalid_rows": invalid, "zone_mismatch": zone_mismatch, "S_od": 0.0, "S_link": 0.0, "S_dev": 0.0, "S_attr": 0.0, "S_ODME": 0.0}
    fref = pd.to_numeric(merged.path_flow, errors="coerce").to_numpy(dtype=float)
    fhat = pd.to_numeric(merged.pred_flow, errors="coerce").to_numpy(dtype=float)
    loaded = A_score @ fhat
    denom_od = max(float(fref.sum()), 1e-9)
    s_od = max(0.0, 1.0 - float(np.sum(np.abs(fhat - fref))) / denom_od)
    denom_link = max(float(np.sum(counts)), 1e-9)
    s_link = max(0.0, 1.0 - float(np.sum(np.abs(loaded - counts))) / denom_link)
    # Deviation score: compare the submitted departure/path-flow deviation
    # from the released weak prior with the organizer reference deviation.
    prior = base.set_index("path_id").reindex(path_ids).base_flow.fillna(0.0).to_numpy(dtype=float)
    d_hat = float(np.abs(fhat - prior).sum())
    d_ref = float(np.abs(fref - prior).sum())
    if d_ref <= 1e-9:
        s_dev = 1.0 if d_hat <= 1e-9 else 0.0
    else:
        s_dev = float(np.exp(-abs(d_hat / d_ref - 1.0)))
    # Attraction score: normalized destination-zone flow distribution. This is
    # the released-data implementation of the organizer attraction reference.
    zones = paths.set_index("path_id").reindex(path_ids).destination_zone.astype(str).to_numpy()
    def attraction(flow):
        z = pd.DataFrame({"zone": zones, "flow": flow}).groupby("zone").flow.sum()
        return z / max(float(z.sum()), 1e-9)
    a_ref = attraction(fref); a_hat = attraction(fhat)
    all_zones = sorted(set(a_ref.index) | set(a_hat.index))
    s_attr = max(0.0, 1.0 - 0.5 * float(np.abs(a_hat.reindex(all_zones, fill_value=0.0) - a_ref.reindex(all_zones, fill_value=0.0)).sum()))
    s_odme = 0.45 * s_od + 0.25 * s_link + 0.15 * s_dev + 0.15 * s_attr
    return {"level": "panel", "panel": panel, "family_id": None, "n_paths": len(path_ids), "missing_paths": 0, "duplicate_rows": 0, "invalid_rows": 0, "zone_mismatch": 0, "S_od": s_od, "S_link": s_link, "S_dev": s_dev, "S_attr": s_attr, "S_ODME": s_odme}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", type=Path, required=True)
    ap.add_argument("--release-root", type=Path, default=HERE / "data_public" / "kaggle_release")
    ap.add_argument("--reference-root", type=Path, default=HERE / "reports" / "task4_odme")
    ap.add_argument("--panel", action="append")
    ap.add_argument("--output", type=Path, default=HERE / "reports" / "task4_eval_validation.csv")
    args = ap.parse_args()
    submission = read_submission(args.submission.resolve())
    manifest = json.loads((HERE / "config" / "corridors.json").read_text(encoding="utf-8"))
    panels = [p["corridor_id"] for p in manifest["panels"]]
    families = {p["corridor_id"]: p["family_id"] for p in manifest["panels"]}
    if args.panel:
        panels = [p for p in panels if p in set(args.panel)]
    rows = []
    for panel in panels:
        print(f"[Task4 evaluator] {panel}", flush=True)
        rows.append(score_panel(panel, args.release_root.resolve(), args.reference_root.resolve(), submission))
    panel_df = pd.DataFrame(rows)
    panel_df["family_id"] = panel_df.panel.map(families)
    family_rows = []
    for family, g in panel_df.groupby("family_id", sort=True):
        family_rows.append({"level": "family", "panel": None, "family_id": family, "n_paths": int(g.n_paths.sum()), "missing_paths": int(g.missing_paths.sum()), "duplicate_rows": int(g.duplicate_rows.sum()), "invalid_rows": int(g.invalid_rows.sum()), "S_od": np.nan, "S_link": np.nan, "S_dev": np.nan, "S_attr": np.nan, "S_ODME": float(g.S_ODME.mean())})
    family_df = pd.DataFrame(family_rows)
    overall = {"level": "overall", "panel": None, "family_id": "ALL", "n_paths": int(family_df.n_paths.sum()), "missing_paths": int(family_df.missing_paths.sum()), "duplicate_rows": int(family_df.duplicate_rows.sum()), "invalid_rows": int(family_df.invalid_rows.sum()), "S_od": np.nan, "S_link": np.nan, "S_dev": np.nan, "S_attr": np.nan, "S_ODME": float(family_df.S_ODME.mean())}
    result = pd.concat([panel_df, family_df, pd.DataFrame([overall])], ignore_index=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f"Wrote {args.output}")
    print(f"Overall S_ODME = {float(overall['S_ODME']):.6f}")


if __name__ == "__main__":
    main()
