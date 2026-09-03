# Running locally

```bash
git clone https://github.com/jacky850/trafficflowbench-public.git
cd trafficflowbench-public
pip install -r requirements.txt
```

Download the data package from the Kaggle Data page and unpack it anywhere.
Every script takes `--release-root`; the examples below use `$REL`.

```bash
REL=/path/to/trafficflowbench-release
```

Add `--panel D12_I5_N` to any command while you iterate — a single corridor runs
in minutes, all ten do not.

## Task 1, and Task 3 with it

`train` is the only split whose answers are released, so it is the split to
develop against.

```bash
python src/task1/build_task1_baseline_submission.py \
  --release-root $REL --split train --output state_submission.csv

python src/task1/score_task1.py \
  --submission state_submission.csv --release-root $REL --split train

# Task 3 needs no file of its own - it is scored on the same submission
python src/task3/score_task3.py \
  --state-submission state_submission.csv --release-root $REL --split train
```

On one corridor the shipped baseline scores about `S_state` 0.91 and
`S_physics` 0.33 on train. Task 3 is the score to attack: it is low not because
the physics check is unfair but because a smooth statistical reconstruction does
not conserve vehicles.

When you are ready, build the same submission for the split being scored:

```bash
python src/task1/build_task1_baseline_submission.py \
  --release-root $REL --split validation --output state_submission.csv
```

## Task 2

```bash
python src/task2/build_task2_persistence_submission.py \
  --release-root $REL --split validation --output queue_submission.csv
```

Queue labels are withheld for **every** split, including train, so
`score_task2.py` cannot be run on the public package. It is included because the
leaderboard runs it, and reading it is the precise definition of the score.

## Task 4

```bash
python src/task4/build_task4_odme_artifacts.py \
  --release-root $REL --split validation --output-root task4_odme

python src/task4/score_task4.py \
  --submission task4_odme/baseline_submission.csv \
  --release-root $REL --reference-root task4_odme
```

The builder writes both a submission and a locally derived reference, so this
score is a check that your solver reproduces the released link counts — not an
estimate of the leaderboard, which compares against organizer path flows you do
not have.

## The file you upload

```bash
python src/merge_submissions.py \
  --state state_submission.csv \
  --queue queue_submission.csv \
  --odme  task4_odme/baseline_submission.csv \
  --output submission.csv
```

Three files in, one long table out. Task 3 contributes no rows: it is scored on
the Task 1 rows already in the file.
