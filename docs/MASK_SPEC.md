# Task 1 masks

## What a target is

The release ships the masks **already applied**. In
`corridors/<PANEL>/<split>/mainline_states_masked/` the speed and flow of every
target cell have been blanked to null.

**Read the targets from the template, not from the nulls.** A blank is not the
same thing as a target, for two reasons. A cell blank because a detector was
down carries `is_score_eligible == False`. And around every scored Task 2 window
the observations are removed for the thirty-minute horizon and the hour that
follows it, in all four measured channels, on eligible cells that Task 1 does
not ask about: the horizon is what Task 2 has to predict, so it cannot also ship
as an observation. Selecting on `is_score_eligible == True and speed_kmh is
null` therefore returns more rows than the release scores.

Each split publishes the complete required row set:

```text
task1/<PANEL>/<split>/sample_submission_state.csv
```

Fill in its `speed_kmh` and `flow_vph` columns and you have a valid submission
with exactly the right coverage.

## Regimes

Three masking rates are scored, and `S_state` is their unweighted mean:

| Regime | Share of eligible cells removed |
|---|---:|
| R1 | 0.20 |
| R2 | 0.30 |
| R3 | 0.50 |

**One calendar day is published under exactly one regime.** The masked layer is
partitioned that way:

```text
mainline_states_masked/mask_regime=R1/synthetic_mainline_2031_03_01.parquet
mainline_states_masked/mask_regime=R2/synthetic_mainline_2031_03_02.parquet
...
```

A day therefore appears once, in one view. It is not published three times at
three different rates. Three views of the same day would let you intersect them
and read most of the answer straight off the release.

The practical consequence: a regime is a property of the day, not a knob you can
turn. R3 days are harder because half of every eligible cell is gone, and they
are the days that dominate the row count.

**The three regimes do not get equal numbers of days.** The assignment is drawn
per day, so on a 31-day split one regime may land on fourteen days and another on
four. On `D7_I405_N` validation, R3 covers only four. `S_state` still averages
the three regimes **equally**, so on some corridors one third of your state score
rests on a handful of days and will be noisier than the rest. That is the same
for every participant.

You can also reproduce the mask yourself rather than read it off the files. Hash
`panel|regime|date|timestamp|link_id` with blake2b, read the digest as a
big-endian 64-bit integer, divide by 2^64, and compare against the regime's rate.
Use the timestamp and date text exactly as stored. `stable_mask()` in
`src/task1/baseline_task1_historical_mean.py` is the reference implementation.

It reproduces the **mask**, which is not the same as the set of blanks you can
see in the files. Two things separate them, in opposite directions: the mask is
drawn over eligible cells only, and cells inside a Task 2 window history are
excluded from it because that history republishes them, while the blanks also
cover the Task 2 horizon and its buffer, which are not Task 1 targets. The
template is the only exact statement of what Task 1 asks for.

## Coverage and penalties

For each corridor and regime, the required rows are exactly the eligible masked
cells of the split being scored, keyed by

```text
(panel, timestamp, station_id, link_id, mask_regime)
```

A missing row is scored as a zero prediction and still counts in the RMSE
denominator, so a partial submission is valid but self-penalising.

`station_id` is part of the key but not part of the masking. Masking happens at
the `(day, timestamp, link)` level, so several stations on one link are always
blanked together, and each is then scored separately.

## Timestamps

Use the timestamp text exactly as it appears in the released files
(`YYYY-MM-DDTHH:MM:SSZ`). Parsing to a datetime and re-serialising it with a
different timezone suffix or precision produces keys that will not join.
