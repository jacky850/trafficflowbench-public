# Run the public benchmark locally

This guide assumes that the public Kaggle release has already been downloaded
and that its local path is stored in `$release`. Raw PeMS downloads, network
construction, hidden answers, and private-test generation are organizer-only
and are not part of this repository.

## 1. Install and validate

```powershell
python -m pip install -r requirements.txt
python -m compileall -q src
python -B src\validate_competition_contract.py
```

The root-level `src\score_task*.py`, `src\build_task*.py`, and
`src\score_overall.py` files are stable compatibility entry points. The actual
implementations are grouped under `src/task1/` through `src/task4/`.

## 2. Task 1 — state baseline and score

```powershell
python -B src\build_task1_baseline_submission.py `
  --release-root $release `
  --output reports\task1_enhanced_state_submission.csv

python -B src\score_task1.py `
  --submission reports\task1_enhanced_state_submission.csv `
  --release-root $release `
  --output reports\task1_enhanced_eval_validation.csv
```

The builder covers all ten panels and R1/R2/R3. The evaluator scores only
eligible masked speed and flow cells.

## 3. Task 2 — queue baseline and score

```powershell
python -B src\build_task2_persistence_submission.py `
  --release-root $release `
  --split validation `
  --output reports\task2_persistence_validation.csv

python -B src\score_task2.py `
  --release-root $release `
  --truth-file $organizer_truth `
  --submission reports\task2_persistence_validation.csv `
  --split validation `
  --output reports\task2_persistence_eval_validation.csv
```

The released queue window index is used as-is; participants do not regenerate
the organizer's window selection. `$organizer_truth` is an organizer-local path
to validation truth and is intentionally not part of the public Kaggle package.

## 4. Task 3 — physics baseline and score

Task 3 consumes the completed Task 1 state submission.

```powershell
python -B src\build_task3_baseline_submission.py `
  --state-submission reports\task1_enhanced_state_submission.csv `
  --release-root $release `
  --output reports\task3_physics_baseline_submission.csv

python -B src\score_task3.py `
  --state-submission reports\task1_enhanced_state_submission.csv `
  --physics-submission reports\task3_physics_baseline_submission.csv `
  --release-root $release `
  --output reports\task3_eval_validation.csv
```

The physics submission includes speed, flow, derived density, mainline boundary
flows, ramp flows, validity flags, and accumulation for all three regimes.

## 5. Task 4 — ODME baseline and score

```powershell
python -B src\build_task4_odme_artifacts.py `
  --release-root $release `
  --output-root reports\task4_odme

python -B src\score_task4.py `
  --release-root $release `
  --submission reports\task4_odme\baseline_submission.csv `
  --reference-root reports\task4_odme `
  --output reports\task4_eval_validation.csv
```

The local reference is for self-diagnostics only. The official private test uses
hidden counterfactual truth from the Kaggle private evaluation set.

## 6. Overall score

```powershell
python -B src\score_overall.py `
  --task1 reports\task1_enhanced_eval_validation.csv `
  --task2 reports\task2_persistence_eval_validation.csv `
  --task3 reports\task3_eval_validation.csv `
  --task4 reports\task4_eval_validation.csv `
  --output reports\overall_baseline_score.csv
```

Reports and generated submissions remain under the ignored `reports/` directory.
