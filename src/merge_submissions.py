"""Build the single upload file from one file per task.

The leaderboard reads six columns keyed by the organizer's ``submission_id``:

    submission_id,task,speed_kmh,flow_vph,queue_pred,path_flow

Working in that shape is awkward, so most people keep one file per task in its
natural key. This script joins those files onto ``submission_key.csv`` and
writes the upload file, in template order, with a value in every cell.

Task 3 has no file. It is scored on the Task 1 state rows.

    python src/merge_submissions.py \
      --state state_submission.csv \
      --queue queue_submission.csv \
      --odme  path_flow_submission.csv \
      --key   submission_key.csv \
      --output submission.csv

The key file is large, so it is streamed rather than held in memory.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

CHUNK = 1_000_000
OUT_COLUMNS = ["submission_id", "task", "speed_kmh", "flow_vph", "queue_pred", "path_flow"]
# The natural key of each per-task file, and the values it supplies.
KEYS = {"state": ["panel", "timestamp", "station_id", "link_id", "mask_regime"],
        "queue": ["window_id", "timestamp", "link_id"],
        "odme": ["panel", "departure_time", "path_id"]}
VALUES = {"state": ["speed_kmh", "flow_vph"], "queue": ["queue_pred"], "odme": ["path_flow"]}


def load(path: Path, task: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{task} submission not found: {path}")
    frame = pd.read_csv(path)
    missing = sorted(set(KEYS[task] + VALUES[task]) - set(frame.columns))
    if missing:
        raise ValueError(f"{path} is missing columns: {missing}")
    frame = frame[KEYS[task] + VALUES[task]].copy()
    for column in KEYS[task]:
        frame[column] = (pd.to_datetime(frame[column], utc=True) if column == "timestamp"
                         else frame[column].astype(str))
    for column in VALUES[task]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    duplicated = int(frame.duplicated(KEYS[task]).sum())
    if duplicated:
        raise ValueError(f"{path} has {duplicated} duplicate rows over {KEYS[task]}")
    return frame.set_index(KEYS[task])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", type=Path, required=True)
    ap.add_argument("--queue", type=Path, required=True)
    ap.add_argument("--odme", type=Path, required=True)
    ap.add_argument("--key", type=Path, required=True,
                    help="submission_key.csv, from the same folder as sample_submission.csv")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    tasks = {"state": load(args.state.resolve(), "state"),
             "queue": load(args.queue.resolve(), "queue"),
             "odme": load(args.odme.resolve(), "odme")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    written, gaps, first = 0, {t: 0 for t in tasks}, True
    for chunk in pd.read_csv(args.key.resolve(), chunksize=CHUNK, dtype=str):
        chunk["timestamp"] = pd.to_datetime(chunk.timestamp, utc=True, errors="coerce")
        out = pd.DataFrame({"submission_id": chunk.submission_id.astype("int64"),
                            "task": chunk.task.astype(str)})
        for column in ("speed_kmh", "flow_vph", "queue_pred", "path_flow"):
            out[column] = 0.0
        for task, table in tasks.items():
            rows = out.task == task
            if not rows.any():
                continue
            wanted = pd.MultiIndex.from_frame(chunk.loc[rows, KEYS[task]])
            found = table.reindex(wanted)
            for column in VALUES[task]:
                values = found[column].to_numpy()
                gaps[task] += int(pd.isna(values).sum())
                out.loc[rows, column] = pd.Series(values).fillna(0.0).to_numpy()
        out[OUT_COLUMNS].to_csv(args.output.resolve(), mode="w" if first else "a",
                                header=first, index=False)
        first = False
        written += len(out)
        print(f"  {written:,} rows", end="\r", flush=True)

    print(f"Wrote {written:,} rows to {args.output.resolve()}")
    for task, n in gaps.items():
        if n:
            print(f"WARNING: {n:,} {task} values had no match and were written as 0. "
                  f"Check the {KEYS[task]} in your {task} file.")
    if not any(gaps.values()):
        print("Every scored cell was filled from your files.")


if __name__ == "__main__":
    main()
