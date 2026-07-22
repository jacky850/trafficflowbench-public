# TrafficFlowBench Scoring Specification

This is the technical scoring contract for Release 1.0. Public-validation
reports are self-diagnostics only; official ranking uses hidden Kaggle private-evaluation truth.

## Averaging

Each directional panel is scored first. Directions are averaged equally within
each of the five families, and family scores are averaged equally. Missing task
outputs receive the configured default score of zero.

## Quality eligibility

```text
is_imputed        = pct_observed < 100
is_score_eligible = pct_observed >= 75 and required values are non-null
```

Task 1 scores speed and flow only. Density is derived. Ramp flow is retained for
Task 3 and Task 4. Invalid ramp cells are unavailable evidence, never measured
zero flow.

## Task 1

For `r` in `{R1,R2,R3}`:

```text
S_speed(r) = max(0, 1 - RMSE_speed(r)/25)
S_flow(r)  = max(0, 1 - RMSE_flow(r)/600)
S_state(r) = 0.54*S_speed(r) + 0.46*S_flow(r)
S_state    = mean_r S_state(r)
```

The mask rates are R1=0.20, R2=0.30, and R3=0.50. The submission key is
`(panel,timestamp,station_id,link_id,mask_regime)`.

## Task 2

Participants observe 60 minutes through forecast origin `T` and predict binary
queue status at `T+5,...,T+30`. For each window:

```text
IoU_ST = |Qhat intersection Qtruth| / |Qhat union Qtruth|
```

Empty-empty scores 1. Normal and disruption windows receive equal weight.
D12_I405_N/S are excluded from Queue only because of public validation quality.

The released public window index separates origins within each
`(panel, split, condition)` group by at least 360 minutes. The participant-visible
`condition` is determined only from the 60-minute history available at the forecast
origin; an organizer-only future-queue eligibility filter is used only when sampling
windows and is not exposed as target information.

## Task 3

FD is evaluated in per-lane units:

```text
q_lane = q_total/lanes
k_lane = k_total/lanes
capacity_lane = capacity_total/lanes
```

LWR conservation is evaluated in total-flow units:

```text
N(t+dt)-N(t) = dt*(q_in+r_on-q_out-r_off)
```

The official revised physics score is:

```text
S_physics = (1/3)*S_FD + (2/3)*S_LWR
```

Ramp validity requires `is_score_eligible`, `pct_observed >= 75`, and finite
flow. Mode A uses ramp-anchored LWR on valid transitions. Mode B uses valid
ramp transitions, omits attached-ramp transitions with invalid cells, and uses
mainline-only LWR on no-ramp segments. Mode C scores only mainline segments
with no ramp attachment. Modes are fixed by the public audit table in
`TASK3_LWR_COVERAGE_MODES.md`.

`S_qkv` is diagnostic only because derived density makes `q=k*v` an identity.

## Task 4

Let `f*` be the organizer reference path flow, `fhat` the submission, `A` the
released path-link incidence, and `c` the measured/private link counts:

```text
S_od = max(0, 1 - sum(abs(fhat-f*)) / max(sum(f*), eps))
S_link = max(0, 1 - sum(abs(A*fhat-c)) / max(sum(c), eps))
```

Let `b` be the released weak path-flow prior:

```text
Dhat = sum(abs(fhat-b))
Dstar = sum(abs(f*-b))
S_dev = exp(-abs(Dhat/Dstar - 1))
```

`S_attr` is the normalized destination-attraction distribution L1 score:

```text
S_attr = max(0, 1 - 0.5*L1(a_hat,a_star))
```

The final ODME score is:

```text
S_ODME = 0.45*S_od + 0.25*S_link + 0.15*S_dev + 0.15*S_attr
```

Invalid IDs, mismatched zones, duplicate paths, missing paths, negative flows,
or non-finite values make the affected panel invalid.

## Overall score

```text
S_total = 0.35*S_state + 0.30*S_queue
        + 0.15*S_physics + 0.20*S_ODME
```

## Leakage boundary

The public package may contain public train/validation observations and
participant baseline code. It must not contain hidden truth, private test
scenarios, private complete counts, `queue_true` labels intended for private
evaluation, or private evaluator code.
