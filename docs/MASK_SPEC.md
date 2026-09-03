# Task 1 masks

## What a target is

The release ships the masks **already applied**. In
`corridors/<PANEL>/<split>/mainline_states_masked/` the speed and flow of every
target cell have been blanked to null. A cell is a Task 1 target when

```text
is_score_eligible == True   and   speed_kmh and flow_vph are null
```

Cells that are null because a detector was down are not targets: those carry
`is_score_eligible == False`. The distinction is the eligibility flag, so read
it rather than testing for nulls alone.

You do not have to find the targets yourself. Each split publishes the complete
required row set:

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
three different rates — three views of the same day would let you intersect them
and read most of the answer straight off the release.

The practical consequence: a regime is a property of the day, not a knob you can
turn. R3 days are harder because half of every eligible cell is gone, and they
are the days that dominate the row count.

**The three regimes do not get equal numbers of days.** The assignment is drawn
per day, so on a 31-day split one regime may land on fourteen days and another on
four — on `D7_I405_N` validation, R3 covers only four. `S_state` still averages
the three regimes **equally**, so on some corridors one third of your state score
rests on a handful of days and will be noisier than the rest. That is the same
for every participant.

If you want to reproduce the mask yourself rather than read it off the files, it
is `blake2b(panel|regime|date|timestamp|link_id)` taken as a big-endian 64-bit
integer, divided by 2^64, compared against the regime's rate — using the
timestamp and date text exactly as stored. `stable_mask()` in
`src/task1/baseline_task1_historical_mean.py` is the reference implementation,
and it reproduces the published blanks exactly.

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
blanked together — and each is then scored separately.

## Timestamps

Use the timestamp text exactly as it appears in the released files
(`YYYY-MM-DDTHH:MM:SSZ`). Parsing to a datetime and re-serialising it with a
different timezone suffix or precision produces keys that will not join.
