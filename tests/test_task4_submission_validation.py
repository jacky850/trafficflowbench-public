#!/usr/bin/env python3
"""Regression tests for Task 4 submission validation in score_panel.

Uses a two-path synthetic fixture (no competition data). Run from the
repository root:

    python tests/test_task4_submission_validation.py
"""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd


class Task4Validation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panel = "TEST_PANEL"
        network = self.root / "corridors" / self.panel / "network"
        task = self.root / "task4" / self.panel / "validation"
        network.mkdir(parents=True)
        task.mkdir(parents=True)
        # Two routes, each uniquely measured, and one unmeasured connector.
        pd.DataFrame({"path_id": ["p1", "p2"], "origin_zone": ["1", "1"],
                      "destination_zone": ["2", "3"]}).to_csv(network / "path_set.csv", index=False)
        pd.DataFrame({"path_id": ["p1", "p2", "p1", "p2"],
                      "link_id": ["a", "b", "connector", "connector"]}).to_csv(network / "path_link_incidence.csv", index=False)
        pd.DataFrame({"link_id": ["a", "b"], "count": [100., 50.]}).to_csv(task / "synthetic_link_counts.csv", index=False)
        self.valid = pd.DataFrame({"panel": [self.panel] * 2, "departure_time": ["TEST-VALIDATION"] * 2,
                                   "path_id": ["p1", "p2"], "origin_zone": ["1", "1"],
                                   "destination_zone": ["2", "3"], "path_flow": [100., 50.]})
        self.valid.to_csv(task / "synthetic_weak_prior.csv", index=False)

    def score(self, frame):
        # Exercise the real reader's ID coercion as well as score_panel.
        path = self.root / "submission.csv"
        frame.to_csv(path, index=False)
        return score_panel(self.panel, self.root, "validation", read_submission(path))

    def test_valid_is_unchanged(self):
        row = self.score(self.valid)
        self.assertAlmostEqual(row["S_link"], 1.)
        self.assertEqual(row["invalid_rows"], 0)
        self.assertEqual(row["n_counted_links"], 2)

    def test_numeric_zone_ids_compare_as_strings(self):
        frame = self.valid.copy()
        frame["origin_zone"] = frame.origin_zone.astype(int)
        frame["destination_zone"] = frame.destination_zone.astype(int)
        self.assertAlmostEqual(self.score(frame)["S_link"], 1.)

    def test_count_error_score_is_unchanged(self):
        frame = self.valid.copy()
        frame.loc[0, "path_flow"] = 70.
        self.assertAlmostEqual(self.score(frame)["S_link"], .8)

    def test_other_split_is_ignored(self):
        extra = self.valid.copy()
        extra["departure_time"] = "TEST-PRIVATE"
        frame = pd.concat([self.valid, extra], ignore_index=True)
        self.assertAlmostEqual(self.score(frame)["S_link"], 1.)

    def test_duplicate_path_scores_zero_without_exception(self):
        frame = pd.concat([self.valid, self.valid.iloc[:1]], ignore_index=True)
        row = self.score(frame)
        self.assertEqual(row["S_link"], 0.)
        self.assertEqual(row["duplicate_rows"], 1)

    def test_unknown_extra_path_scores_zero(self):
        extra = self.valid.iloc[:1].copy()
        extra["path_id"] = "unknown"
        row = self.score(pd.concat([self.valid, extra], ignore_index=True))
        self.assertEqual(row["S_link"], 0.)
        self.assertGreater(row["invalid_rows"], 0)

    def test_wrong_origin_scores_zero(self):
        frame = self.valid.copy()
        frame.loc[0, "origin_zone"] = "other_origin"
        row = self.score(frame)
        self.assertEqual(row["S_link"], 0.)
        self.assertGreater(row["invalid_rows"], 0)

    def test_wrong_destination_scores_zero(self):
        frame = self.valid.copy()
        frame.loc[0, "destination_zone"] = "other_destination"
        row = self.score(frame)
        self.assertEqual(row["S_link"], 0.)
        self.assertGreater(row["invalid_rows"], 0)

    def test_missing_path_scores_zero(self):
        row = self.score(self.valid.iloc[:1])
        self.assertEqual(row["S_link"], 0.)
        self.assertEqual(row["missing_paths"], 1)

    def test_negative_flow_scores_zero(self):
        frame = self.valid.copy()
        frame.loc[0, "path_flow"] = -1.
        self.assertEqual(self.score(frame)["S_link"], 0.)

    def test_nonfinite_flow_scores_zero(self):
        for value in [float("nan"), float("inf")]:
            with self.subTest(value=value):
                frame = self.valid.copy()
                frame.loc[0, "path_flow"] = value
                self.assertEqual(self.score(frame)["S_link"], 0.)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--starter-root", type=Path,
                    default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    sys.path.insert(0, str(args.starter_root.resolve() / "src"))
    from task4.score_task4 import read_submission, score_panel
    unittest.main(argv=[sys.argv[0]], verbosity=2)
