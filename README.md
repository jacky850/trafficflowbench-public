# TrafficFlowBench Public Participant Repository

TrafficFlowBench is a four-task freeway-traffic benchmark for the 2026 IEEE
Big Data Cup. Participants reconstruct a coherent traffic system from the
public Kaggle data: monthly traffic states, short-term queues, physical flow
consistency, and dynamic OD/path flows.

This repository contains participant-facing code, schemas, configuration, and
documentation only. The public data package and the official submission
template are distributed through the Kaggle Competition Data page.

## Tasks

| Task | Setting | Participant output |
|---|---|---|
| Task 1 | Offline monthly masked reconstruction | Speed and flow for R1/R2/R3 masked cells |
| Task 2 | Online 60-minute history to 30-minute forecast | Binary queue predictions |
| Task 3 | Offline physical consistency | State, conservation, and ramp-flow fields |
| Task 4 | Offline dynamic ODME | Non-negative path flows |

All four task outputs are submitted as one unified CSV. The `task` column
identifies the task for each row. Use the official `sample_submission.csv`
provided on Kaggle as the definitive key and column template.

## Public data and split

The Kaggle release contains five corridor families and ten directional panels:
D7_I10, D7_I210, D7_I405, D12_I5, and D12_I405. Public training covers
2025-06-01 through 2026-02-28, and public validation covers
2026-03-01 through 2026-03-31. The PeMS-unavailable dates 2025-11-28 and
2025-11-29 are documented in `config/source_unavailable_dates.csv` and are not
treated as measured observations.

Speed, flow, and occupancy are detector channels. Density is derived from flow
and speed and is not separately scored in Task 1. On-ramp and off-ramp records
are retained for the physical-consistency and ODME tasks.

## Repository layout

```text
config/       Public corridor and Task 3 mode configuration
docs/         Competition, scoring, schema, quality, and run documentation
src/task1/    Task 1 baselines and public-validation scorer
src/task2/    Task 2 queue baseline and public-validation scorer
src/task3/    Task 3 physics baseline and public-validation scorer
src/task4/    Task 4 ODME baseline and public-validation scorer
src/          Unified submission, overall scoring, and contract helpers
```

No raw PeMS archives, private test labels, organizer solutions, hidden queue
targets, private evaluator code, or private CTM scenarios are included here.

## Quick start

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Download the public release from Kaggle and set its local path in PowerShell:

```powershell
$release = "C:\path\to\kaggle_release"
```

The detailed baseline and scoring commands are in
[`docs/RUN_LOCAL.md`](docs/RUN_LOCAL.md). Task-specific schemas and scoring
definitions are in [`docs/SUBMISSION_SCHEMAS.md`](docs/SUBMISSION_SCHEMAS.md)
and [`docs/SCORING_SPEC.md`](docs/SCORING_SPEC.md).

## Scoring summary

The single leaderboard score is:

```text
S_total = 0.35*S_state + 0.30*S_queue
        + 0.15*S_physics + 0.20*S_ODME
```

There is no expert-only score, no reproducibility component, and no hard
physics gate in Version 1. A missing or invalid task receives a default score
of zero for that task; other valid task outputs are scored normally.

Public-validation scores are self-diagnostics. The official Kaggle leaderboard
uses the hidden evaluation labels configured by the competition organizers.

## License and attribution

Use of the competition data is subject to the Kaggle Competition Rules and the
source-data terms stated on the Kaggle Data page. OpenStreetMap-derived network
materials must retain the attribution `© OpenStreetMap contributors` where
applicable.
