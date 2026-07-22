# Public baselines

The repository exposes one runnable baseline family per task. Baseline output
CSV files are local QA artifacts and are not committed to GitHub.

## Task 1 — enhanced masked-state baseline

`src/task1/baseline_task1_enhanced.py` combines a public-train weekday/time-of-
day profile with same-day temporal and spatial interpolation. The builder
`src/task1/build_task1_baseline_submission.py` applies the frozen R1/R2/R3
masks and writes speed and flow predictions for all ten panels.

The historical-mean implementation remains available as a simpler comparison:
`src/task1/baseline_task1_historical_mean.py`. The structural Kalman variant is
optional teaching code: `src/task1/baseline_task1_structural_kf.py`.

## Task 2 — persistence queue baseline

`src/task2/build_task2_persistence_submission.py` copies the queue status at
the forecast origin through the six future five-minute cells. It uses the
released queue-window index and does not use future queue labels.

## Task 3 — ramp-aware physics baseline

`src/task3/build_task3_baseline_submission.py` reconstructs the complete state
from the Task 1 submission and emits the required physics fields, including
derived density, boundary flows, ramp flows, validity flags, and accumulation.
`src/task3/score_task3.py` applies the fixed per-lane FD and total-flow LWR
scoring rule with the panel's published coverage mode.

## Task 4 — regularized ODME baseline

`src/task4/build_task4_odme_artifacts.py` solves the nonnegative,
prior-regularized path-flow problem from released train counts. The evaluator
`src/task4/score_task4.py` reports path-flow, loaded-link, prior-deviation, and
destination-attraction components.

## What is not shipped

Raw PeMS downloaders, public-release builders, hidden-answer generators,
topology construction utilities, old gate/ranking experiments, and research
demos are kept in the organizer's private working copy. They are deliberately
absent from the public Release 1.0 branch.
