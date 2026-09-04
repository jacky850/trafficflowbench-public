"""Local Task 4 check: how well your path flows reproduce the observed counts.

This does not compute S_ODME. The leaderboard scores Task 4 against the
withheld path flows through four parts,

    S_ODME = 0.45*S_od + 0.25*S_link + 0.15*S_dev + 0.15*S_attr

and three of them need the truth. Only S_link compares against something the
release publishes: load your path flows onto the network and compare the result
with the observed link counts. That is the classic ODME objective, so it is
worth optimizing on its own, but it is a quarter of the Task 4 score and a good
S_link does not guarantee a good S_ODME.

Do not score yourself against the reference this repository used to build. That
reference is a regularized solve over base_od.csv and the released counts, both
of which ship in the public package, so reproducing it scores a perfect S_od
locally and tells you nothing about the leaderboard.
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

from task1.baseline_task1_historical_mean import HERE
from task4.build_task4_odme_artifacts import load_operator, released_counts, released_prior

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


def score_panel(panel: str, release: Path, split: str, submission: pd.DataFrame) -> dict:
    """S_link only: A @ f against the released counts, on the counted links."""
    path_ids, link_ids, A, paths, base = load_operator(release / "corridors" / panel / "network")
    count_frame = released_counts(release, panel, split)
    if count_frame is None:
        raise FileNotFoundError(
            f"{panel}: no released link counts for the {split} split. Expected "
            f"{release / 'task4' / panel / split / 'synthetic_link_counts.csv'}.")
    count_frame["link_id"] = count_frame.link_id.astype(str)
    link_index = {link: i for i, link in enumerate(link_ids)}
    scored_links = [link for link in count_frame.link_id if link in link_index]
    A_score = A[[link_index[link] for link in scored_links], :]
    counts = (count_frame.set_index("link_id").reindex(scored_links)["count"]
              .fillna(0.0).to_numpy(dtype=float))

    # A path appears once per split, so keep only the split being scored.
    prior = released_prior(release, panel, split)
    sub = submission[submission.panel == panel]
    if prior is not None and len(prior) and "departure_time" in prior.columns:
        sub = sub[sub.departure_time == str(prior.departure_time.iloc[0])]
    duplicate = int(sub.duplicated(["path_id"]).sum())
    missing = int(pd.Index(path_ids).difference(sub.path_id).size)
    f = sub.set_index("path_id").reindex(path_ids)["path_flow"].to_numpy(dtype=float) \
        if len(sub) else np.full(len(path_ids), np.nan)
    invalid = int((~np.isfinite(f) | (f < 0)).sum())
    row = {"level": "panel", "panel": panel, "family_id": None, "n_paths": len(path_ids),
           "n_counted_links": len(scored_links), "missing_paths": missing,
           "duplicate_rows": duplicate, "invalid_rows": invalid}
    if duplicate or missing or invalid:
        return {**row, "S_link": 0.0}
    loaded = A_score @ f
    denom = max(float(np.sum(counts)), 1e-9)
    return {**row, "S_link": max(0.0, 1.0 - float(np.sum(np.abs(loaded - counts))) / denom)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--submission", type=Path, required=True)
    ap.add_argument("--release-root", type=Path, default=HERE / "data_public" / "kaggle_release")
    ap.add_argument("--split", choices=["train", "validation", "private"], default="validation")
    ap.add_argument("--panel", action="append")
    ap.add_argument("--output", type=Path, default=HERE / "reports" / "task4_link_fit.csv")
    args = ap.parse_args()
    submission = read_submission(args.submission.resolve())
    manifest = json.loads((HERE / "config" / "corridors.json").read_text(encoding="utf-8"))
    panels = [p["corridor_id"] for p in manifest["panels"]]
    families = {p["corridor_id"]: p["family_id"] for p in manifest["panels"]}
    if args.panel:
        panels = [p for p in panels if p in set(args.panel)]
    rows = []
    for panel in panels:
        print(f"[Task4 link fit] {panel}", flush=True)
        rows.append(score_panel(panel, args.release_root.resolve(), args.split, submission))
    panel_df = pd.DataFrame(rows)
    panel_df["family_id"] = panel_df.panel.map(families)
    # Corridor families, equally weighted, the way the leaderboard aggregates.
    family_df = pd.DataFrame([
        {"level": "family", "panel": None, "family_id": family,
         "n_paths": int(g.n_paths.sum()), "n_counted_links": int(g.n_counted_links.sum()),
         "missing_paths": int(g.missing_paths.sum()), "duplicate_rows": int(g.duplicate_rows.sum()),
         "invalid_rows": int(g.invalid_rows.sum()), "S_link": float(g.S_link.mean())}
        for family, g in panel_df.groupby("family_id", sort=True)])
    overall = float(family_df.S_link.mean())
    result = pd.concat([panel_df, family_df, pd.DataFrame([
        {"level": "overall", "panel": None, "family_id": "ALL",
         "n_paths": int(family_df.n_paths.sum()),
         "n_counted_links": int(family_df.n_counted_links.sum()),
         "missing_paths": int(family_df.missing_paths.sum()),
         "duplicate_rows": int(family_df.duplicate_rows.sum()),
         "invalid_rows": int(family_df.invalid_rows.sum()), "S_link": overall}])],
        ignore_index=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f"Wrote {args.output}")
    print(f"Overall S_link = {overall:.6f}")
    print("S_link is 25% of Task 4. S_od, S_dev and S_attr need the withheld "
          "path flows and are scored only on the leaderboard.")


if __name__ == "__main__":
    main()
