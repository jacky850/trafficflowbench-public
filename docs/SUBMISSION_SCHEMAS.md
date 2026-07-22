# Submission schemas

The canonical machine-readable schema is:

```text
data_public/kaggle_release/submission_templates/submission_schemas.json
```

The CSV files in the same directory are templates and examples. They do not contain
private test labels. Exact row coverage is determined by the public split or the
private Kaggle submission request.

## Template status and complete validation templates

The original `sample_submission_state.csv` and `sample_submission_physics.csv`
files are intentionally small schema examples. They are not complete scoring
inputs. The builder below creates complete, label-free public-validation row
universes:

```powershell
python -B src\build_public_validation_templates.py `
  --release-root <local-organizer-release>
```

It writes the following additional files under
`data_public/kaggle_release/submission_templates/`:

```text
sample_submission_state_public_validation.csv
sample_submission_queue_public_validation.csv
sample_submission_physics_public_validation.csv
sample_submission_path_flow_public_validation.csv
sample_submission_all_tasks_public_validation.csv
public_validation_template_manifest.json
```

These files enumerate every public-validation target row for Tasks 1-2, the
complete eligible physical field for Task 3, and the released public ODME
period for Task 4. They contain only placeholder
predictions and are suitable for local QA and for preparing the Kaggle
interface. They are **not** the final hidden-test sample submission;
the final files must be regenerated from the organizer-only private-test key
package after that package exists. The manifest records the exact row counts.

The combined file is a task-tagged long table. It is made by vertical
concatenation of the four task files, not by joining state, queue, physics, and
ODME rows on timestamp. Its globally unique `submission_id` identifies the
task-specific key. The four task-specific files remain the easiest format for
local scoring and debugging.

To merge participant-produced task files locally:

```powershell
python -B src\merge_submissions.py `
  --state state_submission.csv `
  --queue queue_submission.csv `
  --physics physics_submission.csv `
  --odme path_flow_submission.csv `
  --output submission.csv
```

The state and physics templates are **schema examples only** (a few rows per
panel and regime); scoring a template as-is produces zero because required
rows are missing. The queue and path-flow templates fully enumerate their row
universes. The Task 1 required row set (eligible masked cells) is defined in
[`MASK_SPEC.md`](MASK_SPEC.md).

## Task 1 — state reconstruction

File: `sample_submission_state.csv`

```text
panel,timestamp,station_id,link_id,mask_regime,speed_kmh,flow_vph
```

Key:

```text
(panel, timestamp, station_id, link_id, mask_regime)
```

`speed_kmh` and `flow_vph` are the only scored channels. Occupancy is not scored;
density is derived by the evaluator and is not required in the submission.

## Task 2 — queue propagation

File: `sample_submission_queue.csv`

```text
window_id,timestamp,link_id,queue_pred
```

`queue_pred` must be binary 0/1. Rows cover future link-time cells from the public
queue window index. The released template enumerates the windows of **both**
public splits for convenience; a scored submission covers the windows of one
split (the evaluator scores per `--split`, and the private evaluator requests
its own window set). Extra windows from the other split are ignored. Missing
rows are treated as `queue_pred = 0`. The queue label definition
(`speed_kmh <= v_cut`, with `v_cut = 0.6 * free_speed_kmh` fallback) is in
`SCORING_SPEC.md` section 4. The scored panels are:

```text
D7_I10_E, D7_I10_W, D7_I210_E, D7_I210_W,
D7_I405_N, D7_I405_S, D12_I5_N, D12_I5_S
```

`D12_I405_N` and `D12_I405_S` are excluded from Queue only because validation quality
is insufficient. They remain in the other tasks.

## Task 3 — physics consistency

File: `sample_submission_physics.csv`

```text
panel,timestamp,link_id,mask_regime,speed_kmh,flow_vph,density_vpkm,
inflow_vph,outflow_vph,on_ramp_flow_vph,off_ramp_flow_vph,
on_ramp_valid,off_ramp_valid,accumulation_N
```

Key:

```text
(panel, timestamp, link_id, mask_regime)
```

The evaluator checks the submitted state and dynamic flow fields against the released
network topology. Density is checked through q=k*v but is not an independent accuracy
target. The locked score is `S_physics = (1/3) S_FD + (2/3) S_LWR`. Mode A uses
ramp-anchored conservation, Mode B uses valid ramp cells and excludes transitions
with missing ramp flow, and Mode C uses mainline-only conservation.

The complete public-validation physics template contains every eligible
link/time cell for each R1/R2/R3 regime. It is larger than the Task 1 target
template because Task 3 evaluates the reconstructed complete physical field,
not only the cells masked in Task 1.

## Task 4 — ODME/path flow

File: `sample_submission_path_flow.csv`

```text
panel,departure_time,path_id,origin_zone,destination_zone,path_flow
```

`path_flow` must be finite and nonnegative. IDs and legal connectivity must come from
the released per-panel network assets. The official private evaluator compares the
submitted path flows with hidden path-flow truth and hidden link counts.

`departure_time` is a **period token**, not an ISO timestamp: the public
release defines the single period `PUBLIC-TRAIN-PM` (the mean 15:00-19:00
weekday demand of the public split). The private evaluator announces its own
period tokens with the hidden scenario. The ISO-8601 rule below applies to the
`timestamp` columns of Tasks 1-3 only.

## General submission rules

- Use UTC ISO-8601 timestamps exactly as released.
- Do not rename panel, link, station, path, or zone IDs.
- Do not add density as a third Task 1 target.
- Do not delete ramp records from local processing or network assets.
- Do not submit private labels or hidden-test answers.
`on_ramp_valid` and `off_ramp_valid` are binary availability indicators. They
must be 1 for a valid released ramp observation, and 0 when the attached ramp
flow is unavailable. For a link with no ramp of that type, the corresponding
flag is structurally 1 and the flow is 0. In Mode A/B, transitions with an
attached ramp flag of 0 are excluded from the LWR score; they are never treated
as measured zero flow.
