# Source module map

The executable implementation is grouped by task. The small root-level
modules are compatibility entry points so the documented commands remain
stable.

## Task packages

- `src/task1/` — state baselines, Task 1 submission builder, and evaluator.
- `src/task2/` — queue persistence baseline, queue utilities, and evaluator.
- `src/task3/` — physics submission builder and mode-aware evaluator.
- `src/task4/` — ODME baseline builder and evaluator.
- `src/release/` — contract validation and overall-score aggregation.
- `src/build_public_validation_templates.py` — generates complete,
  label-free public-validation templates for all four tasks and the combined
  task-tagged QA file.
- `src/merge_submissions.py` — validates four participant files and merges
  them into one Kaggle-style long-table submission.

The released network, ramp, path, and queue-window assets are data-package
inputs. Organizer-only PeMS downloaders, network construction, hidden-answer
generation, and private-test generation are intentionally not shipped.
