# Baselines

One runnable baseline per task, in `src/`. They exist to give you a starting
point and a number to beat, not to be strong.

## Task 1: the historical mean

`src/task1/baseline_task1_historical_mean.py` learns one weekday by
time-of-day profile of speed and flow per link from `train`, and predicts that
profile at every blanked cell. The builder emits exactly the required row set:

```bash
python src/task1/build_task1_baseline_submission.py \
  --release-root $REL --split train --output state_submission.csv
```

It uses nothing from the day it is reconstructing. Not the neighbouring links at
that moment, not the same link an hour earlier, not the shape of the queue that
is visibly forming around the gap. Every one of those is available to you, and
using any of them is the first thing that beats this.

`baseline_task1_structural_kf.py` is optional teaching code that runs a
structural Kalman filter per link.

## Task 2: persistence

`src/task2/build_task2_persistence_submission.py` reads the queue state at the
forecast origin and repeats it through all six future cells. It uses only the
released 60-minute history and never touches a future label.

```bash
python src/task2/build_task2_persistence_submission.py \
  --release-root $REL --split validation --output queue_submission.csv
```

## Task 3: nothing to build

Task 3 is scored on your Task 1 file, so its baseline is whatever your Task 1
baseline produces. `src/task3/build_task3_baseline_submission.py` remains for
the legacy self-contained physics frame and is not a submission route.

## Task 4: regularised ODME

`src/task4/build_task4_odme_artifacts.py` solves the non-negative,
prior-regularised path-flow problem against the released link counts:

```text
minimize  ||A f - c||^2 + lambda * ||f - b||^2   subject to f >= 0
```

with `A` the released path-link incidence, `c` the released counts, `b` the
released weak prior, and `lambda = 0.05`.

## What the reference baselines score

Each baseline above, scored against a perfect submission and averaged over the
ten corridors on the validation split.

| | Naive baseline | Perfect answer |
|---|---:|---:|
| `S_state` | 0.6903 | 1.0000 |
| `S_queue` | 0.2518 | 1.0000 |
| `S_physics` | 0.3467 | 0.9544 |
| `S_ODME` | 0.5904 | 1.0000 |
| **`S_total`** | **0.4872** | **0.9932** |

Two things to read from this table. The gap between the columns is the room a
method has to work in, and it is wide in every task. And `S_physics` does not
reach 1.0 even for an exact answer: the conservation residual is checked against
observations that carry measurement noise, so about 0.95 is the practical
ceiling. That ceiling is identical for everyone.
