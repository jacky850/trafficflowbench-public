"""Aggregate the four task scores into the single leaderboard score.

This is the reference implementation of the weighting. It is not something you
can run end to end on the public package: Task 2 labels and the Task 3 boundary
flows are withheld, so those two reports cannot be produced locally and count as
zero here. A local total is therefore always lower than a leaderboard total, and
the two are not comparable.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from task1.baseline_task1_historical_mean import HERE


WEIGHTS = {"state": 0.35, "queue": 0.30, "physics": 0.15, "odme": 0.20}


def read_overall(path: Path, column: str) -> float:
    if not path.exists():
        print(f"WARNING: task report not found, task scored as 0.0: {path}")
        return 0.0
    try:
        d = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        print(f"WARNING: task report is empty, task scored as 0.0: {path}")
        return 0.0
    rows = d[d.level == "overall"]
    if rows.empty:
        print(f"WARNING: task report has no 'overall' row, task scored as 0.0: {path}")
        return 0.0
    value = pd.to_numeric(rows.iloc[0][column], errors="coerce")
    if pd.isna(value):
        print(f"WARNING: task report column '{column}' is not numeric, task scored as 0.0: {path}")
        return 0.0
    return float(value)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task1", type=Path, default=HERE / "reports" / "task1_enhanced_eval_validation.csv")
    ap.add_argument("--task2", type=Path, default=HERE / "reports" / "task2_persistence_eval_validation.csv")
    ap.add_argument("--task3", type=Path, default=HERE / "reports" / "task3_baseline_eval_validation.csv")
    ap.add_argument("--task4", type=Path, default=HERE / "reports" / "task4_eval_validation.csv")
    ap.add_argument("--output", type=Path, default=HERE / "reports" / "overall_baseline_score.csv")
    args = ap.parse_args()
    scores = {
        "state": read_overall(args.task1, "S_state"),
        "queue": read_overall(args.task2, "IoU_ST"),
        "physics": read_overall(args.task3, "S_physics"),
        "odme": read_overall(args.task4, "S_ODME"),
    }
    contribution = {task: WEIGHTS[task] * score for task, score in scores.items()}
    total = sum(contribution.values())
    rows = [
        {"level": "task", "task": task, "weight": WEIGHTS[task], "score": scores[task], "weighted_contribution": contribution[task]}
        for task in ("state", "queue", "physics", "odme")
    ]
    rows.append({"level": "overall", "task": "ALL", "weight": 1.0, "score": total, "weighted_contribution": total})
    result = pd.DataFrame(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(result.to_string(index=False))
    missing = [task for task, score in scores.items() if score == 0.0]
    if missing:
        print(f"WARNING: task(s) scored 0.0 (missing, empty, or genuinely zero): {missing}")
    print(f"Overall score = {total:.6f} ({100 * total:.2f}/100)")
    if {"queue", "physics"} & set(missing):
        print(
            "NOTE: queue and physics cannot be scored on the public package, so a local "
            "total is not comparable to the leaderboard. See docs/DATA.md."
        )


if __name__ == "__main__":
    main()
