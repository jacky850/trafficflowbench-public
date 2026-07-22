# Data Quality and Coverage EDA

This report is generated from raw PeMS 5-minute records after selecting TrafficFlowBench stations. It describes data quality; it is not a leaderboard result.

- `pct_observed` is retained exactly as reported by PeMS. The legacy audit flag `is_imputed = 1` means `pct_observed < 100` (some lane observations were imputed); it does not mean the entire cell is unusable.
- Task 1 accuracy eligibility is `pct_observed >= 75` plus non-null speed and flow. For Task 3/4 ramp-flow use, the required value is flow. The figure below shows the observation-quality share `pct_observed >= 75` before channel-specific value checks.
- Ramp observations are retained for conservation and ODME. A month with inadequate ramp quality is not suitable as the primary ODME/physics evaluation window.
- PeMS did not publish daily station files for **2025-11-28** or **2025-11-29**. November 2025 therefore contains 2025-11-01 through 2025-11-27 and 2025-11-30 only; these two unavailable dates are excluded from every task index and are never imputed by the organizers.

## Monthly source-quality matrix

![Monthly source quality](assets/monthly-source-quality.svg)

Each column is a calendar month and each row is a directional corridor panel. The upper matrix is the share of selected **mainline** cells with `pct_observed >= 75`; the lower matrix is the corresponding **ramp** share. The number in each cell is the percentage. November's two documented unavailable dates are excluded from the task index without a separate chart marker. A `-` means no selected records were available.

Use this one figure to compare measured coverage in both panels. The quality threshold and final train/dev allocation remain organizer decisions and will be recorded in the release manifest.

## Data split

![Data split](assets/data-split.svg)

The corridor-uniform split uses public training data from 2025-06 through 2026-02 and public validation data in 2026-03. The official test is the Kaggle private evaluation set. April through June 2026 are excluded from the public split because D12 I-405 observation quality is insufficient in that period.

