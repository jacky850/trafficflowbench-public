# Running locally

```bash
git clone https://github.com/jacky850/trafficflowbench-public.git
cd trafficflowbench-public
pip install -r requirements.txt
```

Download the data package from the Kaggle Data page and unpack it anywhere:
https://www.kaggle.com/competitions/2026-ieee-big-data-traffic-flow-bench/data

Unpacking gives you a `kaggle_public/` directory. That directory, not its
parent, is what every script means by `--release-root`. The examples below use
`$REL`.

```bash
REL=/path/to/kaggle_public
```

Add `--panel D12_I5_N` to any command while you iterate. A single corridor runs
in minutes, all ten do not.

## Task 1, and Task 3 with it

`train` is the only split whose answers are released, so it is the split to
develop against.

```bash
python src/task1/build_task1_baseline_submission.py \
  --release-root $REL --split train --output state_submission.csv

python src/task1/score_task1.py \
  --submission state_submission.csv --release-root $REL --split train

```

On `D12_I5_N` the shipped baseline scores `S_state` 0.6252 on train.

Task 3 needs no file of its own. It is scored on this same submission. But it
cannot be scored locally, for the reason below.

When you are ready, build the same submission for the split being scored:

```bash
python src/task1/build_task1_baseline_submission.py \
  --release-root $REL --split validation --output state_submission.csv
```

## Task 3 cannot be scored locally

`score_task3.py` runs, but the number it prints on the public package is not a
score. Conservation is checked against organizer boundary flows, which are never
published. Inflow and outflow per link are the flow field itself, which is the
Task 1 answer. Without
them the evaluator falls back to applying the topology to your own submitted
flows. That is not accurate enough at this resolution. The conservation signal is
about 0.75% of the accumulated vehicle total, and a topology-derived flux misses
the true one by about 0.22%. So `S_LWR` floors at zero for everyone.

Measured on `D12_I5_N` validation: **a perfect answer scores 0.3301 locally and
the naive baseline scores 0.3299.** With the organizer flows the same two
submissions score **0.9598 and 0.3242**. So the local run tells you nothing
about your Task 3 quality. Read the evaluator for the rule, and let the
leaderboard produce the number.

What does move `S_physics` is the Task 1 answer, and `score_task1.py` does
discriminate. Reconstructing in a way that conserves vehicles between
neighbouring links is the lever.

## Task 2

```bash
python src/task2/build_task2_persistence_submission.py \
  --release-root $REL --split validation --output queue_submission.csv
```

Queue labels are withheld for **every** split, including train, so
`score_task2.py` cannot be run on the public package either. It is included
because the leaderboard runs it, and reading it is the precise definition of the
score.

## Task 4

```bash
python src/task4/build_task4_odme_artifacts.py \
  --release-root $REL --split validation --output-root task4_odme

python src/task4/score_task4.py \
  --submission task4_odme/baseline_submission.csv \
  --release-root $REL --split validation
```

This reports `S_link` only: your path flows loaded onto the network against the
published link counts. That is a quarter of Task 4 and the one part computable
from released data. `S_od`, `S_dev` and `S_attr` compare against organizer path
flows you do not have, so they are scored on the leaderboard alone.

Do not score yourself against the reference the builder writes. It is a solve
over `base_od.csv` and the released counts, both of which ship in the package,
so reproducing it scores a perfect `S_od` locally and tells you nothing.

## The file you upload

```bash
python src/merge_submissions.py \
  --state state_submission.csv \
  --queue queue_submission.csv \
  --odme  task4_odme/baseline_submission.csv \
  --key   $REL/submission_key.csv \
  --output submission.csv
```

Three files in, one upload file out, in the six columns the leaderboard reads
and in template order. Task 3 contributes no rows: it is scored on the Task 1
rows already in the file.
