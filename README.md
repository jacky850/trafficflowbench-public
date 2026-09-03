# TrafficFlowBench

A four-task freeway-traffic benchmark for the 2026 IEEE Big Data Cup.

Ten directional freeway corridors, nine months of five-minute detector records,
and four questions asked of the same road. The benchmark asks you to
**reconstruct and explain a traffic system**, not to minimise one prediction
error — the four tasks are scored together, and the ones that pay best are the
ones a physically coherent method solves at the same time.

- **Data**: the Kaggle competition Data page
- **Code, schemas, baselines, scoring rules**: this repository
- **Start here**: [`docs/RUN_LOCAL.md`](docs/RUN_LOCAL.md)

---

## Why these four tasks

Every task is a problem a traffic-management centre actually has. They were
chosen because they need each other.

**Detectors fail, constantly.** On a real freeway a large share of every
five-minute record is missing, degraded, or imputed by the agency before anyone
sees it. Nothing downstream — no control strategy, no travel-time estimate, no
incident detection — works until the gaps are filled. **Task 1 is that: fill in
the missing cells.**

**Knowing what is happening now is not the same as knowing what happens next.**
A queue that has just started spreads upstream faster than intuition suggests,
and the decision to meter a ramp or post a warning has to be made before the
queue arrives. **Task 2 is that: from one hour of history, say which links are
queued over the next thirty minutes.**

**A reconstruction can fit every observation and still be impossible.** Fill in
missing cells with a smooth statistical model and you get plausible-looking
numbers that quietly violate conservation of vehicles — cars appear and vanish
between detectors. That is the failure mode that makes an estimate useless for
control, and RMSE cannot see it. **Task 3 is that: does your Task 1 answer obey
traffic-flow physics?** It is scored on the file you already submitted, so it
cannot be gamed independently — the only way to raise it is to reconstruct
better.

**Detectors count vehicles; they do not say where anyone is going.** Planning,
pricing and rerouting need origin-destination demand, which is never measured
directly and has to be inferred from link counts. The inverse problem is
underdetermined, so it needs a prior and it needs the counts to be right.
**Task 4 is that: recover path flows from counts.**

Put together: **fill the gaps, respect the physics, predict what comes next, and
explain where the traffic came from.** That is the loop a traffic centre runs,
and no single one of those steps is worth much alone.

## How the tasks connect

```text
                  masked observations
                          │
                          ▼
        ┌────────  Task 1: reconstruct  ───────┐
        │                 │                    │
        │                 ▼                    ▼
        │        Task 3: is it physical?   Task 4: where did it come from?
        │        (scored on the very          (counts → path flows)
        │         same file, no submission)
        ▼
  Task 2: what happens in the next 30 minutes
   (60 min of history, independent windows)
```

Tasks 1 and 3 are **the same submission judged twice** — once for accuracy,
once for physical coherence. Task 4 consumes counts and network structure. Task
2 stands on its own: it is scored on separate short windows, not on the month.

**A suggested order.** This is advice, not a rule — solve them however you like.

1. **Task 1 first**, because Task 3 comes free with it and together they are
   half the total score. Get a reconstruction working end to end before tuning.
2. **Then Task 3**, by changing Task 1. Look at where conservation breaks:
   usually a smoother that produces beautiful speeds and inconsistent flows.
   A method built around the flow balance tends to lift both scores at once.
3. **Then Task 4**, which is a self-contained inverse problem and where a
   classical, well-regularised solver goes a long way.
4. **Task 2 last**, because it shares the least with the others. It is worth
   0.30 and the naive baseline scores 0.25, so it is where the largest
   proportional gain sits.

## Scoring

```text
S_total = 0.35*S_state + 0.30*S_queue + 0.15*S_physics + 0.20*S_ODME
```

Every component is on [0, 1], 1 is perfect. Corridors are averaged equally, and
a missing task output scores 0 rather than being skipped. The full rule is in
[`docs/SCORING_SPEC.md`](docs/SCORING_SPEC.md).

---

## Task 1 — Reconstruct the missing state

**What is tested.** Whether you can recover speed and flow at cells the release
has removed, using everything else: the rest of the corridor at that moment, the
same link at other times, and the corridor's own history.

**What you get.** `mainline_states_masked/`, where the target cells are blanked
to null, plus ramp flows and the full network. The removal rate is one of three
regimes — R1 removes 20% of eligible cells, R2 30%, R3 50% — and each calendar
day is published under exactly one of them.

**What you submit.** One speed and one flow for every blanked eligible cell:

```text
panel,timestamp,station_id,link_id,mask_regime,speed_kmh,flow_vph
```

The required rows are enumerated for you in
`task1/<PANEL>/<split>/sample_submission_state.csv`. A missing row scores as a
zero prediction and still counts in the denominator.

**How it is scored.** Per regime, then averaged over the three:

```text
S_speed = max(0, 1 - RMSE_speed / 25)                # km/h
S_flow  = max(0, 1 - RMSE_flow_per_lane / 600)       # veh/h/lane
S_state = 0.54*S_speed + 0.46*S_flow
```

Flow RMSE is taken **per lane**. Against total link flow the same error scored
very differently on a three-lane and a six-lane corridor, which made corridors
incomparable on lane count alone.

**Baseline.** A weekday × time-of-day profile plus local interpolation:

```bash
python src/task1/build_task1_baseline_submission.py \
  --release-root $REL --split train --output state_submission.csv
python src/task1/score_task1.py \
  --submission state_submission.csv --release-root $REL --split train
```

---

## Task 2 — Predict the queue

**What is tested.** Short-horizon propagation: not whether you can see the queue
that is already there, but whether you can tell where it goes next, and where a
new one is about to form.

**What you get.** Independent windows. Each gives you 60 minutes of observations
up to a forecast origin `T`, and asks about `T+5 … T+30` — six five-minute steps
over every link. Windows come in two conditions, five of each per corridor and
split:

- `queue_onset` — nothing queued in the history, a queue in the horizon;
- `queue_ongoing` — a queue is already visible at `T`.

Both guarantee a queue somewhere in the horizon, so no window can be won by
predicting "no queue everywhere" and collecting a free mark.

**What you submit.** A binary indicator per link and future timestamp:

```text
window_id,timestamp,link_id,queue_pred
```

**How it is scored.** Space-time intersection-over-union per window, averaged
with equal weight across windows and conditions:

```text
IoU = |predicted AND true| / |predicted OR true|
```

A link is queued when its speed is at or below `0.60 × free_speed`. The label is
taken from the underlying state rather than the noisy observation, so
measurement error cannot flip it back and forth at the threshold.

`D12_I405_N` and `D12_I405_S` are excluded from Task 2 only; they remain in the
other three tasks.

**Baseline.** Persistence — repeat the queue state at `T` through all six steps:

```bash
python src/task2/build_task2_persistence_submission.py \
  --release-root $REL --split validation --output queue_submission.csv
```

It scores 0.2518. Queue labels are withheld for every split, so this is one task
you cannot self-score; `src/task2/score_task2.py` is published so you can read
exactly how the leaderboard will judge you.

---

## Task 3 — Is your reconstruction physical?

**What is tested.** Whether the numbers you submitted for Task 1 could describe
real traffic. Two things a real freeway always satisfies:

- **The fundamental diagram.** Speed, flow and density on a link are not
  independent. Given density, flow is bounded, and beyond a critical density
  flow falls rather than rises.
- **Conservation.** Vehicles do not appear or vanish. Over five minutes, the
  change in the number of vehicles on a link equals what came in, from upstream
  and from the on-ramp, minus what left.

```text
N(t+dt) - N(t) = dt * (q_in + r_on - q_out - r_off)
```

**What you submit.** *Nothing.* Task 3 is scored on your Task 1 file. The
evaluator derives the rest itself — density as `q/v`, accumulation as `k·L`,
boundary flows from the released topology, ramp flows from the released ramp
observations.

This is deliberate. When Task 3 accepted its own submission, a participant could
declare `k = q/v_f` and score 0.9999 on the diagram term instead of an honest
0.8833, or project boundary flows straight onto the conservation equation and
score a perfect 1.0 whatever state they had submitted. Anchoring the score to
the Task 1 answer closes both routes by construction.

**How it is scored.**

```text
S_physics = (1/3)*S_FD + (2/3)*S_LWR
```

`S_LWR` carries the discrimination: it falls monotonically as error is injected
and goes to zero for a submission that erases congestion, while `S_FD` moves by
less than 0.03 across the same range. Which transitions are scored depends on
your corridor's ramp-observation coverage — the table is frozen and published in
[`docs/TASK3_LWR_COVERAGE_MODES.md`](docs/TASK3_LWR_COVERAGE_MODES.md).

```bash
python src/task3/score_task3.py \
  --state-submission state_submission.csv --release-root $REL --split train
```

Note that the naive baseline scores about 0.35 here against roughly 0.96 for an
exact answer. That gap is the largest in the benchmark, and it is the clearest
signal that fitting cells one at a time is not enough.

---

## Task 4 — Recover the demand

**What is tested.** The classical inverse problem of traffic estimation: link
counts are observed, path flows are not, and there are far more paths than
independent measurements. A useful answer has to reproduce the counts *and* stay
close to what is plausible.

**What you get.** The path set, the path-link incidence matrix `A`, the released
link counts `c` for one demand period, and a weak path-flow prior `b`.

**What you submit.**

```text
panel,departure_time,path_id,origin_zone,destination_zone,path_flow
```

Flows must be finite and non-negative, and `departure_time` is a period token
rather than a timestamp — copy it from the template.

**How it is scored.** Four components: how close your path flows are to the
reference, whether they reproduce the counts when loaded onto the network, how
far you moved from the prior compared with how far the reference moved, and
whether your destination-attraction distribution is right.

```text
S_ODME = 0.45*S_od + 0.25*S_link + 0.15*S_dev + 0.15*S_attr
```

The `S_dev` term is what stops the two obvious degenerate answers: submitting
the prior unchanged, and fitting the counts exactly with a wild demand pattern.

**Baseline.** Non-negative least squares with prior regularisation:

```bash
python src/task4/build_task4_odme_artifacts.py \
  --release-root $REL --split validation --output-root task4_odme
```

---

## The data

Ten directional corridors — `D7_I10`, `D7_I210`, `D7_I405`, `D12_I5`,
`D12_I405`, each in both directions — at five-minute resolution, with mainline
detectors, ramp flows, link geometry, fundamental-diagram parameters, paths and
an OD prior.

| Split | Masked inputs | Answers released | What it is for |
|---|:--:|:--:|---|
| `train` | yes | **yes** | fitting, and scoring yourself |
| `validation` | yes | no | practice submissions |
| `private` | yes | no | the ranked evaluation |

Every cell carries `pct_observed`, and only cells with `pct_observed >= 75` and
non-null values are scored. About 76% qualify. **The rest are still released —
degraded data is part of the problem, not a defect in the package.** An
unavailable ramp reading is unavailable evidence, never a measured zero: treat
it as zero and Task 3 will cost you.

**The released records are synthetic.** They were generated by a calibrated
traffic-flow model whose parameters — free-flow speed, per-lane capacity, jam
density, demand by weekday and time of day, measurement-noise scale, detector
availability — were measured from real freeway detector data on the
corresponding corridors. No real record, shifted or resampled or copied, appears
in the release, and the released calendar deliberately matches no real period.

What that means for you: the data obeys real traffic physics and carries
realistic measurement error, but there is nothing to look it up in. There is no
external source to join against, and a method that works here is a method that
works on the road.

More in [`docs/DATA.md`](docs/DATA.md).

---

## Quick start

```bash
git clone https://github.com/jacky850/trafficflowbench-public.git
cd trafficflowbench-public
pip install -r requirements.txt

REL=/path/to/the/downloaded/data

python src/task1/build_task1_baseline_submission.py \
  --release-root $REL --split train --panel D12_I5_N --output state_submission.csv
python src/task1/score_task1.py \
  --submission state_submission.csv --release-root $REL --split train --panel D12_I5_N
python src/task3/score_task3.py \
  --state-submission state_submission.csv --release-root $REL --split train --panel D12_I5_N
```

One corridor runs in minutes; drop `--panel` for all ten. The full walkthrough,
including how to build the file you upload, is in
[`docs/RUN_LOCAL.md`](docs/RUN_LOCAL.md).

## What is here

```text
src/task1/   state baselines, submission builder, evaluator
src/task2/   persistence baseline, queue utilities, evaluator
src/task3/   the anchored physics evaluator
src/task4/   ODME baseline and evaluator
src/merge_submissions.py   three task files -> one upload
config/      the corridor list, the release contract, the Task 3 mode table
docs/        the scoring rule, schemas, masks, data layout, baselines
```

| Document | What it answers |
|---|---|
| [`RUN_LOCAL.md`](docs/RUN_LOCAL.md) | How do I run any of this? |
| [`DATA.md`](docs/DATA.md) | What is in the package, and which split has answers? |
| [`SCORING_SPEC.md`](docs/SCORING_SPEC.md) | Exactly how is each number computed? |
| [`SUBMISSION_SCHEMAS.md`](docs/SUBMISSION_SCHEMAS.md) | What columns, what keys, what coverage? |
| [`MASK_SPEC.md`](docs/MASK_SPEC.md) | Which cells am I being asked about? |
| [`BASELINES.md`](docs/BASELINES.md) | What do the baselines do, and what do they score? |
| [`TASK3_LWR_COVERAGE_MODES.md`](docs/TASK3_LWR_COVERAGE_MODES.md) | Which transitions is my corridor judged on? |

Official rules, deadlines and prizes are on the Kaggle competition page.
