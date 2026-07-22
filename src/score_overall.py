"""Aggregate four task reports into the unified V1 score."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from task1.baseline_task1_historical_mean import HERE


WEIGHTS = {"state": 0.35, "queue": 0.30, "physics": 0.15, "odme": 0.20}


def read_overall(path: Path, column: str) -> float:
    if not path.exists():
        print(f"WARNING: report not found; {path.name} receives 0.0")
        return 0.0
    frame = pd.read_csv(path)
    rows = frame[frame.level == "overall"]
    if rows.empty:
        print(f"WARNING: no overall row; {path.name} receives 0.0")
        return 0.0
    value = pd.to_numeric(rows.iloc[0][column], errors="coerce")
    if pd.isna(value):
        print(f"WARNING: non-numeric score; {path.name} receives 0.0")
        return 0.0
    return float(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task1", type=Path, required=True)
    parser.add_argument("--task2", type=Path, required=True)
    parser.add_argument("--task3", type=Path, required=True)
    parser.add_argument("--task4", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    scores = {
        "state": read_overall(args.task1, "S_state"),
        "queue": read_overall(args.task2, "IoU_ST"),
        "physics": read_overall(args.task3, "S_physics"),
        "odme": read_overall(args.task4, "S_ODME"),
    }
    rows = []
    total = 0.0
    for task in ("state", "queue", "physics", "odme"):
        contribution = WEIGHTS[task] * scores[task]
        total += contribution
        rows.append({"level": "task", "task": task, "weight": WEIGHTS[task],
                     "score": scores[task], "weighted_contribution": contribution})
    rows.append({"level": "overall", "task": "ALL", "weight": 1.0,
                 "score": total, "weighted_contribution": total})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.output, index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"Overall score = {total:.6f} ({100 * total:.2f}/100)")


if __name__ == "__main__":
    main()
