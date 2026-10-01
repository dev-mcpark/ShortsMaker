"""The scorecard only compares complete, paired production evidence."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from shorts_maker.services.scorecard import FIELDS, init_reviews, summarize


class ScorecardTests(unittest.TestCase):
    def test_paired_cost_and_seven_day_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory) / "outputs"
            outputs.mkdir()
            reviews = outputs / "reviews.csv"
            paths = {}
            for key in ("robot", "stars"):
                for mode in ("image", "hybrid"):
                    path = outputs / f"{key}_{mode}.production.json"
                    path.write_text(json.dumps({
                        "schema_version": 1, "script_key": key,
                        "production_mode": mode, "quality_passed": True,
                        "youtube_id": f"{key}-{mode}",
                    }), encoding="utf-8")
                    paths[(key, mode)] = str(path.resolve())

            self.assertEqual(init_reviews(outputs, reviews), 4)
            with reviews.open(encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
            for row in rows:
                key, mode = next(pair for pair, path in paths.items() if path == row["report_path"])
                row["accepted"] = "no" if (key, mode) == ("stars", "hybrid") else "yes"
                row["billed_cost_usd"] = str({
                    ("robot", "image"): 0.2, ("robot", "hybrid"): 0.7,
                    ("stars", "image"): 0.3, ("stars", "hybrid"): 0.6,
                }[(key, mode)])
                if key == "robot":
                    row["views_7d"] = "100" if mode == "image" else "120"
                    row["average_view_duration_seconds_7d"] = "20" if mode == "image" else "22"
                    row["revenue_usd_7d"] = "0.01" if mode == "image" else "0.02"
            with reviews.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

            self.assertEqual(init_reviews(outputs, reviews), 0)
            (outputs / "extra_image.production.json").write_text(json.dumps({
                "schema_version": 1, "script_key": "extra",
                "production_mode": "image", "quality_passed": True,
            }), encoding="utf-8")
            self.assertEqual(init_reviews(outputs, reviews), 1)
            summary = summarize(outputs, reviews)
            self.assertEqual(summary["rendered_reports"], 5)
            self.assertEqual(summary["paired_scripts"], 2)
            self.assertEqual(summary["complete_cost_pairs"], 2)
            self.assertEqual(summary["modes"]["image"]["accepted_rate"], 1)
            self.assertEqual(summary["modes"]["image"]["billed_cost_per_accepted_usd"], 0.25)
            self.assertEqual(summary["modes"]["hybrid"]["accepted_rate"], 0.5)
            self.assertEqual(summary["modes"]["hybrid"]["billed_cost_per_accepted_usd"], 1.3)
            self.assertEqual(summary["complete_7d_outcome_pairs"], 1)
            self.assertEqual(summary["complete_7d_revenue_pairs"], 1)
            self.assertEqual(summary["outcomes_7d"]["hybrid"]["average_view_duration_seconds"], 22)

    def test_retention_can_be_compared_before_monetization(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory)
            for mode in ("image", "hybrid"):
                (outputs / f"{mode}.production.json").write_text(json.dumps({
                    "schema_version": 1, "script_key": "topic", "production_mode": mode,
                    "quality_passed": True, "youtube_id": mode,
                }), encoding="utf-8")
            reviews = outputs / "reviews.csv"
            init_reviews(outputs, reviews)
            with reviews.open(encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
            for row in rows:
                row.update(accepted="yes", billed_cost_usd="0.1", views_7d="100",
                           average_view_duration_seconds_7d="20")
            with reviews.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

            summary = summarize(outputs, reviews)
            self.assertEqual(summary["complete_7d_outcome_pairs"], 1)
            self.assertEqual(summary["complete_7d_revenue_pairs"], 0)
            self.assertIsNone(summary["outcomes_7d"]["image"]["revenue_usd"])


if __name__ == "__main__":
    unittest.main()
