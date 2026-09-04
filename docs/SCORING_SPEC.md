# Scoring specification

The normative scoring contract for Release 1.0. The README explains what each
score means. This page is the exact rule.

## Aggregation

Each directional corridor is scored on its own. Directions are averaged equally
within a family, families are averaged equally, and the four task scores are
combined with fixed weights:

```text
S_total = 0.35*S_state + 0.30*S_queue + 0.15*S_physics + 0.20*S_ODME
```

A missing task output scores 0, not a skipped average. A corridor with no
scoreable cell scores 0, not 1.

## Eligibility

```text
is_imputed        = pct_observed < 100
is_score_eligible = pct_observed >= 75 and the required values are non-null
```

Only `is_score_eligible` cells are scored. `speed_kmh` and `flow_vph` are the
only scored channels. Occupancy is not scored, and density is derived by the
evaluator.

## Task 1: state reconstruction

For each masking regime `r` in `{R1, R2, R3}`:

```text
S_speed(r) = max(0, 1 - RMSE_speed(r) / 25)
S_flow(r)  = max(0, 1 - RMSE_flow_per_lane(r) / 600)
S_state(r) = 0.54*S_speed(r) + 0.46*S_flow(r)
S_state    = mean over r
```

`RMSE_flow_per_lane` divides both the submitted and the true flow by the
station's lane count, from `fd_parameters.csv`, before the residual. Against
total link flow the 600 scale was roughly five times stricter than the 25 km/h
speed scale and made corridors incomparable on lane count alone. One
fixed-quality model scored `S_flow` from 0.0086 to 0.3255 across the ten
corridors. Per lane that spread in `S_state` falls from 0.158 to 0.020.

Mask rates are `R1 = 0.20`, `R2 = 0.30`, `R3 = 0.50`. The submission key is
`(panel, timestamp, station_id, link_id, mask_regime)`. The mask itself is
defined in [`MASK_SPEC.md`](MASK_SPEC.md).

## Task 2: queue forecasting

You see 60 minutes of history through the forecast origin `T` and predict a
binary queue indicator for `T+5 … T+30`. Per window:

```text
IoU = |Qpred AND Qtrue| / |Qpred OR Qtrue|
```

A window that genuinely has no queue and for which none was predicted scores 1.
The two conditions, `queue_onset` and `queue_ongoing`, carry equal weight. Each
contributes 5 windows per corridor and split.

`queue_onset` windows have no queue visible in the history and a queue in the
horizon. `queue_ongoing` windows already show a queue at the origin. Both
require a queue somewhere in the horizon, so an empty-empty window cannot be
drawn as a free mark. Origins within a `(panel, split, condition)` group are at
least 360 minutes apart. The condition label is derived only from the history
you can see.

The ground truth is taken from the underlying state rather than the noisy
observation, so measurement error cannot flip the indicator back and forth at
the threshold. The threshold is `speed <= v_cut`, `v_cut = 0.60 * free_speed`.

`D12_I405_N` and `D12_I405_S` are excluded from Task 2 only. They remain in the
other three tasks.

## Task 3: physical consistency

**Task 3 has no submission of its own.** It is scored on the speeds and flows
you submitted for Task 1. The evaluator derives the physics frame itself:

```text
k = q/v                 density is an identity, not an estimate
N = k*L                 accumulation follows from density and link length
inflow, outflow         organizer-derived from the released topology
r_on, r_off             the released ramp observations
```

This removes every free parameter that could be tuned against the physics score
independently of the state. Before anchoring, a submission could set `k = q/v_f` and score `S_FD` 0.9999
instead of an honest 0.8833. Or it could project the boundary flows onto the
conservation equation and score `S_LWR` 1.0 whatever state it had submitted. The only way to move `S_physics` is now to submit a
better Task 1 answer.

The fundamental-diagram term is evaluated per lane:

```text
q_lane = q_total/lanes,  k_lane = k_total/lanes,  capacity_lane = capacity/lanes
```

Conservation is evaluated in total-flow units over five-minute transitions:

```text
N(t+dt) - N(t) = dt*(q_in + r_on - q_out - r_off)
S_LWR = max(0, 1 - sum|residual| / sum|rhs|)
```

```text
S_physics = (1/3)*S_FD + (2/3)*S_LWR
```

The two terms do different jobs, and the weights reflect that. `S_FD` is a
validity check: it separates the physically possible from the impossible, not the
good from the better.

Because the ratio normalizes by submitted flow, a cell claiming an empty road is
both trivially valid and invisible to it, so blanking a submission used to raise
`S_FD`. A panel and regime whose submitted cells are more than a fifth below
50 vph now scores `S_FD` 0. Nothing in the released data comes close to that
floor, so an honest answer is unaffected.

`S_LWR` carries the discrimination. It falls monotonically with injected error
and sends a congestion-erasing submission to zero. Which
transitions are scored depends on the corridor's coverage mode, published in
[`TASK3_LWR_COVERAGE_MODES.md`](TASK3_LWR_COVERAGE_MODES.md).

`S_qkv` appears in the evaluator output as a diagnostic only. Derived density
makes `q = k*v` an identity.

## Task 4: OD and path-flow estimation

Let `f*` be the reference path flow, `fhat` the submission, `A` the released
path-link incidence, `c` the link counts, and `b` the released weak prior:

```text
S_od   = max(0, 1 - sum|fhat - f*| / max(sum f*, eps))
S_link = max(0, 1 - sum|A*fhat - c| / max(sum c, eps))
S_dev  = exp(-|Dhat/Dstar - 1|),  Dhat = sum|fhat-b|,  Dstar = sum|f*-b|
S_attr = max(0, 1 - 0.5*L1(a_hat, a_star))
```

`a` is the normalised destination-attraction distribution.

```text
S_ODME = 0.45*S_od + 0.25*S_link + 0.15*S_dev + 0.15*S_attr
```

Invalid IDs, mismatched zones, duplicate or missing paths, negative flows, or
non-finite values invalidate the affected corridor.

## What is never released

Hidden truth, private-split labels, private complete counts, `queue_true`
labels for evaluation, organizer boundary flows, and private evaluator
configuration. The public package carries observations, network assets,
templates, and the baselines in `src/`.
