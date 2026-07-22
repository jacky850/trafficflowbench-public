# Task 3 LWR Coverage Modes

This document defines the coverage-aware policy for the revised Task 3 LWR
diagnostic/evaluator. It prevents missing ramp observations from becoming a
penalty on a participant's mainline reconstruction.

The policy is fixed before leaderboard evaluation. It is based on the released
public-validation ramp quality audit, not on a participant's score.

## Ramp-cell validity

A ramp cell is valid only when all three conditions hold:

```text
is_score_eligible == true
pct_observed >= 75
flow_vph is finite and non-null
```

Coverage is computed over unique `(timestamp, ramp_link_id)` cells:

```text
ramp_coverage = valid ramp cells / all ramp cells
```

An invalid ramp cell is not a measured zero. It is unavailable evidence.

## LWR equations

For a mainline segment with reliable ramp observations:

```text
N(t+1) - N(t)
  = dt * (q_in(t) + r_on(t) - q_out(t) - r_off(t))
```

For a segment with no on-ramp or off-ramp attachment:

```text
N(t+1) - N(t)
  = dt * (q_in(t) - q_out(t))
```

The second equation is **not** used by replacing a missing ramp flow with zero
on a segment that actually has a ramp.

In the submission schema, `inflow_vph` and `outflow_vph` are the **mainline
boundary flows**. The attached-ramp terms are submitted separately as
`on_ramp_flow_vph` and `off_ramp_flow_vph`; the evaluator adds each valid ramp
term exactly once. A baseline must not add a ramp flow into both sets of
columns.

The evaluator also scores a transition only when every internal mainline
neighbour named by the released topology is present in the submission. External
connector IDs are boundary conditions and are not treated as missing evidence.
This avoids penalising a sensor-only submission for an unobserved latent link.

## Corridor modes

The thresholds are:

```text
Mode A: coverage >= 0.75 and valid cells >= 100,000
Mode B: coverage >= 0.25 and valid cells >= 100,000
Mode C: coverage < 0.25 or valid cells < 100,000
```

The validation audit for the current release is:

| Panel | Valid cells | Coverage | Mode |
|---|---:|---:|---|
| D7_I10_E | 265,583 | 0.256787 | B |
| D7_I10_W | 346,255 | 0.337698 | B |
| D7_I210_E | 262,143 | 0.300014 | B |
| D7_I210_W | 343,344 | 0.359895 | B |
| D7_I405_N | 62,388 | 0.067935 | C |
| D7_I405_S | 44,292 | 0.043962 | C |
| D12_I5_N | 760,175 | 0.761247 | A |
| D12_I5_S | 622,831 | 0.652854 | B |
| D12_I405_N | 220,108 | 0.457164 | B |
| D12_I405_S | 192,940 | 0.460420 | B |

The two D12 I405 panels remain in Tasks 1, 3, and 4. Their exclusion from
Queue is a separate decision.

## Mode A — complete ramp-anchored LWR

Mode A has enough reliable ramp data to use the ramp-anchored equation on
valid ramp cells. Segments without ramp attachments use the mainline-only
equation. Invalid ramp cells are still omitted rather than set to zero.

Current Mode A panel:

```text
D12_I5_N
```

## Mode B — hybrid LWR

Mode B retains the corridor but uses separate eligibility rules for each
segment-time transition:

1. A segment with a valid ramp observation uses `q_in + r_on - q_out - r_off`.
2. A segment with a ramp attachment but a missing/invalid ramp flow is omitted
   from the LWR residual for that transition.
3. A segment with no ramp attachment uses `q_in - q_out`.
4. Missing ramp flow is never replaced by zero for scoring.
5. `S_FD` and other mainline-state diagnostics continue to use their own
   eligible cells; ramp coverage does not reduce the Task 1 score.

This mode does not give a participant a low score because the organizer lacked
a ramp measurement. It reduces the number of LWR cells on which the organizer
has defensible evidence. The evaluator reports the number of scored LWR cells
and the coverage alongside the score.

Current Mode B panels:

```text
D7_I10_E, D7_I10_W,
D7_I210_E, D7_I210_W,
D12_I5_S,
D12_I405_N, D12_I405_S
```

## Mode C — mainline-only LWR

Mode C is used when ramp evidence is too sparse to support a stable
ramp-anchored component. The official LWR component uses only segments with no
on/off-ramp attachment and the mainline-only equation. Ramp-dependent cells are
retained for organizer diagnostics but are not used to penalize participants.

Current Mode C panels:

```text
D7_I405_N, D7_I405_S
```

## Scoring and reporting

The mode is a property of the released panel and is the same for every team.
The evaluator must report at least:

```text
panel
mode
ramp_coverage
valid_ramp_cells
lwr_scored_cells
S_LWR
S_FD
```

`S_qkv` is retained as a diagnostic identity check. Because density is derived
from submitted/reconstructed flow and speed, `q = k*v` is expected to be one
up to numerical tolerance and is not an independent leaderboard component.

This policy is the active Task 3 evaluator policy for the merged QA branch.
The mode table is organizer-fixed and is identical for every participant.

## Baseline interpretation

Two organizer baselines are reported separately:

1. **Raw baseline (`raw_state`)**: uses the reconstructed Task 1 state and a
   simple upstream-discharge estimate. It does not force the conservation
   equation to hold. Its LWR score is therefore a deliberately weak reference
   and measures how much physical inconsistency a simple baseline has.
2. **Projected reference (`projected`)**: applies a minimum-norm correction to
   the submitted inflow/outflow fields so that the discrete mainline
   conservation equation is satisfied. It is a physics-reference construction,
   not a hidden truth and not evidence that a predictive model learned the
   dynamics. It should not be the only baseline shown to participants.

The current ramp-anchored baseline uses valid released on/off-ramp counts in
the separate ramp columns. Missing ramp cells are excluded rather than filled
with zero. The projected reference remains a separate diagnostic construction;
it is not a hidden truth and not evidence that a predictive model learned the
dynamics.
