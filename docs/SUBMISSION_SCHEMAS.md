# Submission schemas

You submit **three** files. Task 3 is scored on your Task 1 file and has no
submission of its own.

Every file may be scored on its own, or the three may be merged into a single
task-tagged table with `src/merge_submissions.py`.

## Task 1: state reconstruction

`sample_submission_state.csv`

```text
panel,timestamp,station_id,link_id,mask_regime,speed_kmh,flow_vph
```

Key: `(panel, timestamp, station_id, link_id, mask_regime)`.

Required rows are exactly the eligible masked cells of the split being scored,
for each of R1, R2 and R3. A missing row is scored as a zero prediction and
still counts in the RMSE denominator, so a partial submission is valid but
self-penalising. `speed_kmh` and `flow_vph` are the only scored channels. Do not
add density.

Note that `station_id` is in the key but not in the mask hash: when several
stations share a link they are masked together, and each is scored separately.

## Task 2: queue forecasting

`sample_submission_queue.csv`

```text
window_id,timestamp,link_id,queue_pred
```

`queue_pred` must be 0 or 1. Rows cover the future link-time cells of the
released window index. A missing row is treated as `queue_pred = 0`. The
template enumerates the windows of more than one split for convenience. The
evaluator scores the split you pass with `--split` and ignores the rest.

## Task 4: OD and path flow

`sample_submission_path_flow.csv`

```text
panel,departure_time,path_id,origin_zone,destination_zone,path_flow
```

`path_flow` must be finite and non-negative. IDs must come from the released
per-corridor network assets. Do not rename or invent them.

`departure_time` is a **period token, not a timestamp**. The public release
defines one period per split. The private evaluation announces its own with the
hidden scenario.

## Merging

```bash
python src/merge_submissions.py \
  --state   state_submission.csv \
  --queue   queue_submission.csv \
  --odme    path_flow_submission.csv \
  --key     submission_key.csv \
  --output  submission.csv
```

`submission_key.csv` ships beside `sample_submission.csv` and maps every
`submission_id` to the cell it names. The merge joins your three files onto it
by their natural keys and writes the six columns the leaderboard reads, in
template order, with a value in every cell. Kaggle rejects a file containing a
blank. The three per-task files remain the easiest format for local scoring and
debugging.

## General rules

- Use the UTC ISO-8601 timestamps exactly as released, byte for byte.
- Do not rename panel, link, station, path or zone IDs.
- Do not delete ramp records from the network assets you read.
- Do not submit values copied from an organizer-only file.
