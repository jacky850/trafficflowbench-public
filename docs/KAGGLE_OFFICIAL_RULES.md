# TrafficFlowBench — Official Competition Rules (Release 1.0)

## Competition purpose

TrafficFlowBench evaluates data-driven and physics-aware methods for freeway
traffic reconstruction, short-horizon queue propagation, physics consistency,
and path-flow ODME. Release 1.0 has four tasks, one common formula for all
teams, and one final leaderboard. There is no reasoning-text score and no
expert score.

## Public/private architecture

- **GitHub** contains code, schemas, documentation, baselines, and local QA tools.
- **Kaggle** contains the public train/validation package, network/ramp/path
  assets, templates, and manifests.
- **Kaggle private evaluation** uses hidden evaluation labels and organizer-controlled scenarios.

Public-validation scores are self-diagnostics and are not ranked. Official
ranking uses the Kaggle private evaluation set. Private labels, hidden scenarios,
complete hidden link counts, and evaluator code are never released.

## Data and quality policy

The public package contains five corridor families and ten directional panels.
The source channels are speed, flow, and occupancy. Density is derived from
flow and speed; it is not a fourth measurement channel. On-ramp and off-ramp
records are retained because they are required for conservation and ODME.

For every cell:

```text
is_imputed       = (pct_observed < 100)
is_score_eligible = (pct_observed >= 75) and required values are non-null
```

The 75% threshold determines scoring eligibility. Missing ramp observations
are unavailable evidence, not measured zero flow. The documented PeMS-unavailable
dates 2025-11-28 and 2025-11-29 are absent from task indices.

## Task 1 — offline masked state reconstruction

Participants reconstruct masked eligible mainline speed and flow cells under
three deterministic regimes:

```text
R1 = 20% mask
R2 = 30% mask
R3 = 50% mask
```

For each regime:

```text
S_speed = max(0, 1 - RMSE_speed / 25)
S_flow  = max(0, 1 - RMSE_flow / 600)
S_state(r) = 0.54*S_speed + 0.46*S_flow
```

```text
S_state = mean(S_state(R1), S_state(R2), S_state(R3))
```

Only speed and flow are scored. Occupancy and density are not accuracy targets.

## Task 2 — online queue propagation

At forecast origin `T`, participants receive the previous 60 minutes and
predict binary queue status for `T+5` through `T+30` minutes. This is queue
propagation, not incident detection.

For each window:

```text
IoU_ST = |Qhat intersection Qtruth| / |Qhat union Qtruth|
```

An empty-empty pair scores 1. Normal and disruption windows receive equal
weight. `queue_pred` must be binary 0/1.

The public window index spaces forecast origins by at least 360 minutes within
each panel/split/condition group. The condition is assigned from the observed
60-minute history at the origin; future queue labels are not used to expose a
participant-visible condition.

Queue scoring excludes D12_I405_N and D12_I405_S because their public
validation quality is insufficient. They remain in Tasks 1, 3, and 4.

## Task 3 — physics consistency

Task 3 uses the reconstructed Task 1 state and the released network topology.
FD checks use per-lane units:

```text
q_lane = q_total / lanes
k_lane = k_total / lanes
```

LWR conservation uses total-flow units and vehicle accumulation:

```text
N(t+dt)-N(t) = dt*(q_in + r_on - q_out - r_off)
```

The official physics score is:

```text
S_physics = (1/3)*S_FD + (2/3)*S_LWR
```

The fixed corridor modes are defined by public ramp quality:

- **Mode A:** coverage >= 0.75 and at least 100,000 valid ramp cells. Uses
  ramp-anchored LWR on valid ramp transitions.
- **Mode B:** coverage >= 0.25 and at least 100,000 valid ramp cells. Uses
  valid ramp transitions; a transition with an attached but invalid ramp cell
  is omitted, never filled with zero. No-ramp segments use mainline-only LWR.
- **Mode C:** coverage < 0.25 or fewer than 100,000 valid cells. Official LWR
  uses only mainline segments with no ramp attachment.

The mode is fixed per panel and identical for all teams. Density is a physical
consistency field, not an independent accuracy score. The detailed panel table
is in `docs/TASK3_LWR_COVERAGE_MODES.md`.

## Task 4 — ODME/path-flow estimation

Participants submit nonnegative path flows using the released path set, zone
metadata, and path-link incidence. The public diagnostic uses released measured
mainline/ramp counts; unobserved connector links are not treated as measured
zeros. The private test replaces these with hidden counterfactual truth.

The score is:

```text
S_ODME = 0.45*S_od + 0.25*S_link + 0.15*S_dev + 0.15*S_attr
```

`S_od` compares submitted path flows with the organizer reference, `S_link`
compares loaded path flows with measured link counts, `S_dev` evaluates the
appropriate deviation from the released weak prior, and `S_attr` compares the
normalized destination-attraction distribution. Invalid path IDs, zones,
duplicates, negative flows, or missing paths receive zero for the affected panel.

## Final score

The single leaderboard score is:

```text
S_total = 0.35*S_state + 0.30*S_queue
        + 0.15*S_physics + 0.20*S_ODME
```

Directions are averaged equally within each family, and the five family scores
are averaged equally. A missing task receives its configured default score of 0.

## Baselines and reproducibility

The repository provides historical/structural Task 1 baselines, queue
persistence, a topology-aware ramp-anchored Task 3 baseline, and a
prior-regularized Task 4 ODME baseline. Baseline scores are public-validation
self-diagnostics, not leaderboard standings.

## Conduct and attribution

Lawful external data and pretrained models are allowed and must be disclosed.
Recovering private labels or querying a source to reconstruct hidden scenarios
is prohibited. PeMS and network-data attribution must be preserved in all
redistributions. Team size, dates, submission limits, prizes, and license are
set on the competition platform before launch.
