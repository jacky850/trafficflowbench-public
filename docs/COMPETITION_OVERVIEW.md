# TrafficFlowBench Competition Architecture — Release 1.0

This document is the long-form orientation for organizers, mentors, and participants.
It explains what each task means, what information is public, what the organizer uses
as reference truth, how task scores are combined, and how to reproduce the public
baseline results.

## 1. Design goal

The benchmark asks whether a method can move through four connected traffic-analysis
problems without requiring the organizer to pretend that every traffic quantity is a
direct detector measurement:

```text
released traffic observations
        |
        v
Task 1: reconstruct masked speed/flow state
        |
        v
Task 3: test physical consistency of that reconstructed state

released recent history ---> Task 2: forecast queue propagation

mainline + on-ramp + off-ramp counts ---> Task 4: estimate OD/path flows
```

Task 1 and Task 4 are primarily offline tasks over the public monthly split. Task 2
is online and short horizon. Task 3 is a downstream physical consistency task. In
Release 1.0, Task 3 does not impose a minimum Task 1 score gate, but it does require a
usable Task 1 state file.

## 2. What is public and what is hidden

### Public Kaggle release

The public data package contains:

- train and validation mainline state partitions;
- train and validation ramp state partitions;
- nodes, links, detector-to-link maps, and ramp topology/volume maps;
- zones, legal paths, path-link incidence, and ODME metadata;
- deterministic Task 1 mask conventions and submission templates;
- Task 2 window index and released train/validation queue targets;
- machine-readable release manifests and schemas.

### Kaggle private evaluation

The private evaluator contains:

- hidden counterfactual traffic scenarios;
- hidden Task 1 target cells for the private scenario;
- hidden queue references;
- hidden path-flow reference `f*` and hidden link counts `c`;
- the official private evaluator implementation.

The private test is not simply a month that participants can download from PeMS. The
organizer uses calibrated synthetic/counterfactual scenarios so that knowing the
source family does not reveal the hidden answer.

## 3. Time split and quality policy

The same split is used for all five corridor families:

```text
public_train      2025-06-01 through 2026-02-28
public_validation 2026-03-01 through 2026-03-31
private_test      Kaggle hidden private-evaluation scenarios
excluded          2026-04-01 through 2026-06-30
```

The excluded period is not a convenient test set. It is omitted because D12 I-405
has insufficient observation quality for a common public benchmark allocation.

PeMS has no station files for 2025-11-28 and 2025-11-29. These dates are documented in
`config/source_unavailable_dates.csv` and are absent from every task index. They are
not organizer imputations and do not create a separate November score category.

For each source cell:

```text
is_imputed        = pct_observed < 100
is_score_eligible = pct_observed >= 75 and required values are non-null
```

The `is_imputed` flag is intentionally strict and preserves the PeMS audit meaning.
The 75% threshold is the score-eligibility threshold. Task 1 scores speed and flow;
occupancy and density are retained as context/diagnostics but not scored.

Density is derived. A participant does not need to submit density for Task 1. For
physics checks, the evaluator derives:

```text
k_hat = q_hat / max(v_hat, 1)
```

Ramp data are retained because removing ramp flow would break conservation information
and weaken ODME/path-flow estimation.

## 4. Task 1: masked state reconstruction

### Participant input

For a public split, the participant receives the released state tables and the
deterministic mask regime. Unmasked eligible cells are available as context. Masked
mainline speed and flow values are the prediction targets.

### Participant output

```text
panel,timestamp,station_id,link_id,mask_regime,speed_kmh,flow_vph
```

The key includes `station_id`; link-time alone is not sufficient when several
detectors share a link.

### Organizer reference

The organizer retains the complete released source values and applies the same frozen
mask. Only eligible masked cells are scored. Public validation uses the released
validation values. The private evaluation uses hidden counterfactual labels.

### Score

For each regime `r`:

```text
S_speed(r) = max(0, 1 - RMSE_speed(r)/25)
S_flow(r)  = max(0, 1 - RMSE_flow(r)/600)
S_state(r) = 0.54*S_speed(r) + 0.46*S_flow(r)
```

Then:

```text
S_state = mean(S_state(R1), S_state(R2), S_state(R3))
```

R3 is harder than R1, but each regime has equal macro weight. This prevents a model
from receiving an artificially high score by performing well only at the easiest mask.

## 5. Task 2: queue propagation

### Participant input

At forecast origin `T`, the participant receives 60 minutes of recent history:

```text
T-60, T-55, ..., T-5, T
```

The forecast covers:

```text
T+5, T+10, T+15, T+20, T+25, T+30
```

This is a propagation forecast. It does not ask the participant to explain why an
incident happened or to write a reasoning narrative.

### Recurrent and disruption windows

The organizer samples normal and disruption-detected windows. The condition label is
provided in the window index for organizer-side balancing. Participants do not need
to submit a recurrent/non-recurrent label. The benchmark tests whether a method can
continue a queue pattern and its spatial/temporal propagation from recent observations.

### Why D12 I-405 is excluded from Queue

The D12 I-405 public validation period does not have enough eligible observations for
a reliable queue reference. Including it would make the score depend on missing or
imputed quality rather than model performance. We therefore exclude `D12_I405_N` and
`D12_I405_S` from Queue only. They remain in State, Physics, and ODME so that the
network package is not fragmented.

### Score

For every window, compare submitted and reference queue masks over `(link_id,
5-minute time cell)`:

```text
IoU_ST = |Qhat intersection Q*| / |Qhat union Q*|
```

An empty prediction and empty reference receive IoU 1. Normal and disruption windows
are averaged equally:

```text
S_queue = 0.5*mean(IoU_ST_normal)
        + 0.5*mean(IoU_ST_disruption)
```

The eight scored panels are the two directions of D7 I-10, D7 I-210, D7 I-405, and
D12 I-5. Each scored family and direction is equally weighted.

Within each `(panel, split, condition)` group, public forecast origins are at
least 360 minutes apart. The participant-visible condition is determined from
the 60-minute history at the origin; future queue status is used only by the
organizer when selecting evaluable windows.

## 6. Task 3: physical consistency

Task 3 uses the participant's Task 1 state. For each mask regime, the evaluator fills
unmasked cells with organizer observations and masked cells with Task 1 predictions.
Multiple stations on one link are aggregated by mean speed/flow.

The participant supplies:

```text
panel,timestamp,link_id,mask_regime,
speed_kmh,flow_vph,density_vpkm,
inflow_vph,outflow_vph,on_ramp_flow_vph,off_ramp_flow_vph,
on_ramp_valid,off_ramp_valid,accumulation_N
```

`speed_kmh`, `flow_vph`, and `density_vpkm` describe the reconstructed link
state. Density is derived (`density = flow / speed` with the evaluator's
zero-speed convention) and is not an additional scored channel. The two ramp
flow fields are usable only when their corresponding validity flag is `1`.
The flags are part of the submission contract; the evaluator fixes the
coverage mode for each corridor and does not let a participant choose it.

The evaluator uses a coverage-aware physical mode. Mode A uses ramp-anchored
conservation when released ramp observations meet the quality threshold; Mode B
uses available ramp anchors while masking low-quality ramp cells; Mode C falls
back to mainline-only conservation when ramp coverage is insufficient. The
assignment is fixed by the release manifest.

The scored components are:

1. **Fundamental-diagram score (`S_FD`):** on sensored links, the submitted
   per-lane state is checked against the calibrated speed-flow-density relation.
2. **LWR conservation score (`S_LWR`):** total-flow conservation is checked
   over adjacent five-minute cells, using the fixed mode and valid ramp anchors.

```text
S_physics = (1/3)*S_FD + (2/3)*S_LWR
```

The q-k-v identity is retained as a diagnostic (`S_qkv`) and is not an extra
weighted term, so speed, flow, and derived density are not triple-counted.

There is no minimum Task 1 performance gate. A low-quality state can naturally lower
Task 3 through its FD and conservation scores. A missing/incomplete Task 1 state
file makes the affected Task 3 score zero.

## 7. Task 4: ODME/path flow

The released network contains legal directed paths, origin/destination zones, link
incidence, mainline detector anchors, and ramp counts. The public OD prior is a weak,
organizer-defined prior and is not claimed to be directly observed individual OD.

The private scenario supplies hidden `f*`, `c`, and fixed `A`. For submitted `fhat`:

```text
S_od   = max(0, 1 - L1(fhat,f*) / max(sum(f*), epsilon))
S_link = max(0, 1 - L1(A*fhat,c) / max(sum(c), epsilon))
Let Dhat = sum(|fhat-b|), D* = sum(|f*-b|):
S_dev  = exp(-|Dhat/D* - 1|)   (with the documented zero-denominator convention)
S_attr = max(0, 1 - 0.5*L1(ahat,a))
S_ODME = 0.45*S_od + 0.25*S_link + 0.15*S_dev + 0.15*S_attr
```

For public diagnostics, `c` only contains links with released detector counts. An
unobserved connector is not treated as a measured count of zero; this avoids the old
failure mode in which the dense path incidence was incorrectly compared with a sparse
detector-only validation vector.

## 8. Gates, missing tasks, and ranking

Release 1.0 intentionally does not use a minimum-performance gate between tasks.
Schema and key validation still exist. Missing task files receive zero for that task.
Task 3 requires Task 1 because it is defined downstream of the reconstructed state.

The one leaderboard uses:

```text
S_total = 0.35*S_state + 0.30*S_queue
        + 0.15*S_physics + 0.20*S_ODME
```

The Physics weight is 15 percentage points of the final score. A physics score of zero
does not erase the other tasks, but it forfeits the entire Physics contribution.

## 9. Public repository and data package

The repository contains code and documentation. The Kaggle public release contains
the data package. At minimum, participants should obtain:

```text
data_public/kaggle_release/
├── release_manifest.json
├── d7_odme_manifest.json
├── d12_odme_manifest.json
├── config/
├── submission_templates/
├── task2/
└── corridors/<10 panels>/
    ├── network/
    ├── train/mainline_states/
    ├── train/ramp_states/
    ├── validation/mainline_states/
    └── validation/ramp_states/
```

No public upload should contain raw source archives, private test labels, hidden
counterfactual files, or the private evaluator.

## 10. Reproducibility workflow

From the repository root:

```powershell
python -B src\validate_competition_contract.py
python -m compileall -q src
```

Then run the four baseline/evaluator pairs documented in `README.md` and
`docs/RUN_LOCAL.md`. The final command is:

```powershell
python -B src\score_overall.py
```

The current public-validation baseline output is:

```text
S_state   = 0.591069
S_queue   = 0.543117
S_physics = 0.243610
S_ODME    = 0.839270
S_total   = 0.574205  (57.42 / 100)
```

These are reproducibility diagnostics from the current regenerated public queue
window package; they are not hidden private-test results. A participant may
submit only a subset of tasks, but any omitted task receives its configured
default score of zero on the single leaderboard.
