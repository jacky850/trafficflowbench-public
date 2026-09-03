# Task 3 — LWR coverage modes

Conservation can only be checked where the terms of the conservation equation
exist. A link with an on-ramp whose flow is unavailable has no measurable
`r_on`, and scoring that transition as if the ramp carried zero vehicles would
punish a correct submission for a missing detector.

Each corridor is therefore assigned a coverage mode, which decides which
transitions enter `S_LWR`:

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

## All ten corridors are Mode A

Detector health in this release is uniform by design — every corridor carries
the same `pct_observed` distribution — so ramp coverage comes out the same
everywhere, at **0.7560**, and all ten corridors clear the Mode A threshold.
Nothing is scored under a weaker rule than anything else.

That figure sits about 0.006 above the A/B boundary, which is close. The table is
therefore **derived once from the published release and frozen**, rather than
re-measured at scoring time, so no corridor can drift across the line between
one evaluation and the next.

It lives in [`../config/task3_lwr_modes.json`](../config/task3_lwr_modes.json),
which the evaluator reads by default, and it is identical for every participant
and every run:

```bash
python -c "import json;print({k:v['mode'] for k,v in json.load(open('config/task3_lwr_modes.json'))['panels'].items()})"
```

Ramp validity requires `is_score_eligible`, `pct_observed >= 75`, and a finite
flow value. An invalid ramp cell is unavailable evidence, never a measured zero.
For a link with no ramp of a given type the corresponding flag is structurally
valid and the flow is zero.
