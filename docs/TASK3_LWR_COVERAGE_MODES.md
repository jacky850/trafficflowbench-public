# Task 3 — LWR coverage modes

Conservation can only be checked where the terms of the conservation equation
exist. A link with an on-ramp whose flow is unavailable has no measurable
`r_on`, and scoring that transition as if the ramp carried zero vehicles would
punish a correct submission for a missing detector.

Each corridor is therefore assigned one of three coverage modes, which decides
which transitions enter `S_LWR`:

| Mode | What is scored |
|---|---|
| **A** | Ramp-anchored conservation on every valid transition |
| **B** | Valid ramp transitions, plus mainline-only conservation on segments with no ramp; transitions with an attached but invalid ramp are omitted |
| **C** | Mainline-only segments with no ramp attachment |

Assignment is by ramp-observation coverage:

```text
Mode A: coverage >= 0.75 and valid cells >= 100,000
Mode B: coverage >= 0.25 and valid cells >= 100,000
Mode C: coverage <  0.25  or valid cells <  100,000
```

## The table is frozen and public

The assignment is **not** re-derived at scoring time. It lives in
[`../config/task3_lwr_modes.json`](../config/task3_lwr_modes.json), which the
evaluator reads by default, and it is identical for every participant and every
run. It is published so you can see exactly which transitions your corridor is
judged on before you submit.

```bash
python -c "import json;print(json.load(open('config/task3_lwr_modes.json'))['panels'])"
```

Ramp validity requires `is_score_eligible`, `pct_observed >= 75`, and a finite
flow value. An invalid ramp cell is unavailable evidence, never a measured zero.
For a link with no ramp of a given type the corresponding flag is structurally
valid and the flow is zero.
