"""The scorecard keeps paired and editorial evidence separate."""

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
                    row["public_release_confirmed"] = "yes"
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
            (outputs / "editorial_cut.production.json").write_text(json.dumps({
                "schema_version": 1, "script_key": "robot", "production_mode": "image",
                "paired_comparison_eligible": False, "quality_passed": True,
            }), encoding="utf-8")
            self.assertEqual(init_reviews(outputs, reviews), 1)
            summary = summarize(outputs, reviews)
            self.assertEqual(summary["rendered_reports"], 6)
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
                           average_view_duration_seconds_7d="20",
                           public_release_confirmed="yes")
            with reviews.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

            summary = summarize(outputs, reviews)
            self.assertEqual(summary["complete_7d_outcome_pairs"], 1)
            self.assertEqual(summary["complete_7d_revenue_pairs"], 0)
            self.assertIsNone(summary["outcomes_7d"]["image"]["revenue_usd"])

    def test_editorial_costs_include_rejected_cuts_without_polluting_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory)
            reviews = outputs / "reviews.csv"
            for name in ("accepted", "rejected", "pending"):
                (outputs / f"{name}.production.json").write_text(json.dumps({
                    "schema_version": 1, "script_key": "same-story",
                    "production_mode": "video", "paired_comparison_eligible": False,
                    "quality_passed": True,
                }), encoding="utf-8")
            init_reviews(outputs, reviews)
            with reviews.open(encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
            for row in rows:
                if "accepted.production" in row["report_path"]:
                    row.update(accepted="yes", billed_cost_usd="0.04")
                elif "rejected.production" in row["report_path"]:
                    row.update(accepted="no", billed_cost_usd="0.02")
            with reviews.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

            summary = summarize(outputs, reviews)
            self.assertEqual(summary["paired_scripts"], 0)
            self.assertEqual(summary["editorial_cuts"], {
                "rendered": 3, "complete_cost_reviews": 2, "accepted": 1,
                "accepted_rate": 0.5, "billed_cost_usd": 0.06,
                "billed_cost_per_accepted_usd": 0.06,
            })
            self.assertIsNone(summary["editorial_outcomes_7d"])

    def test_editorial_outcomes_include_published_accepted_cuts_before_bill(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory)
            reviews = outputs / "reviews.csv"
            for name, uploaded in (("billed", True), ("unbilled", True),
                                   ("private_review", False), ("uploaded_private", True),
                                   ("rejected", True)):
                (outputs / f"{name}.production.json").write_text(json.dumps({
                    "schema_version": 1, "script_key": name,
                    "production_mode": "video", "paired_comparison_eligible": False,
                    "quality_passed": True,
                    "youtube_id": name if uploaded else None,
                }), encoding="utf-8")
            init_reviews(outputs, reviews)
            with reviews.open(encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
            for row in rows:
                name = Path(row["report_path"]).name.split(".")[0]
                row.update(accepted="no" if name == "rejected" else "yes",
                           views_7d="100", average_view_duration_seconds_7d="20")
                if name in {"billed", "unbilled"}:
                    row["public_release_confirmed"] = "yes"
                if name == "billed":
                    row.update(billed_cost_usd="0.2", revenue_usd_7d="0.01")
                if name == "unbilled":
                    row["average_view_duration_seconds_7d"] = "30"
            with reviews.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

            summary = summarize(outputs, reviews)
            self.assertEqual(summary["editorial_cuts"]["complete_cost_reviews"], 1)
            self.assertEqual(summary["editorial_outcomes_7d"], {
                "complete_videos": 2, "views": 200,
                "average_view_duration_seconds": 25.0,
                "complete_revenue_videos": 1, "revenue_usd": None,
            })

    def test_unpaired_automatic_runs_are_counted_as_editorial_cuts(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory)
            reviews = outputs / "reviews.csv"
            for name, key, mode in (
                ("pair_image", "pair", "image"),
                ("pair_hybrid", "pair", "hybrid"),
                ("solo_hybrid", "solo", "hybrid"),
                ("solo_video", "video", "video"),
                ("pending_image", "pending", "image"),
            ):
                (outputs / f"{name}.production.json").write_text(json.dumps({
                    "schema_version": 1, "script_key": key, "production_mode": mode,
                    "quality_passed": True, "paired_comparison_eligible": True,
                    "youtube_id": name if name == "solo_hybrid" else None,
                }), encoding="utf-8")
            init_reviews(outputs, reviews)
            with reviews.open(encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
            for row in rows:
                name = Path(row["report_path"]).name.split(".")[0]
                if name == "solo_hybrid":
                    row.update(accepted="yes", billed_cost_usd="0.5",
                               public_release_confirmed="yes", views_7d="100",
                               average_view_duration_seconds_7d="20")
                elif name == "solo_video":
                    row.update(accepted="no", billed_cost_usd="0.3")
            with reviews.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

            summary = summarize(outputs, reviews)
            self.assertEqual(summary["paired_scripts"], 1)
            self.assertEqual(summary["editorial_cuts"], {
                "rendered": 3, "complete_cost_reviews": 2, "accepted": 1,
                "accepted_rate": 0.5, "billed_cost_usd": 0.8,
                "billed_cost_per_accepted_usd": 0.8,
            })
            self.assertEqual(summary["editorial_outcomes_7d"]["complete_videos"], 1)

    def test_source_story_cost_counts_revisions_and_comparison_once(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory)
            reviews = outputs / "reviews.csv"
            for name, source, script, mode in (
                ("first", "https://example.com/a", "a-v1", "image"),
                ("comparison", "https://example.com/a", "a-v1", "hybrid"),
                ("revised", "https://example.com/a", "a-v2", "video"),
                ("other", "https://example.com/b", "b", "video"),
                ("legacy", None, "legacy", "video"),
            ):
                (outputs / f"{name}.production.json").write_text(json.dumps({
                    "schema_version": 1, "script_key": script, "source_url": source,
                    "production_mode": mode, "quality_passed": True,
                }), encoding="utf-8")
            init_reviews(outputs, reviews)
            with reviews.open(encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
            for row in rows:
                name = Path(row["report_path"]).name.split(".")[0]
                row["accepted"] = "yes" if name == "revised" else "no"
                row["billed_cost_usd"] = "0.1"
            with reviews.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

            summary = summarize(outputs, reviews)["source_stories"]
            self.assertEqual(summary, {
                "tracked": 2, "unattributed_cuts": 1, "complete_cost_stories": 2,
                "accepted": 1, "accepted_rate": 0.5, "billed_cost_usd": 0.4,
                "billed_cost_per_accepted_usd": 0.4,
            })

            rows[0]["billed_cost_usd"] = ""
            with reviews.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            self.assertEqual(summarize(outputs, reviews)["source_stories"]["complete_cost_stories"], 1)

    def test_owner_acceptance_survives_missing_bill_without_changing_cost_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory)
            reviews = outputs / 'reviews.csv'
            for name in ('accepted', 'rejected', 'pending'):
                (outputs / f'{name}.production.json').write_text(json.dumps({
                    'schema_version': 1, 'script_key': name, 'production_mode': 'video',
                    'quality_passed': True, 'youtube_id': name,
                }))
            init_reviews(outputs, reviews)
            with reviews.open(newline='') as file:
                rows = list(csv.DictReader(file))
            for row in rows:
                name = Path(row['report_path']).name.split('.')[0]
                if name == 'accepted':
                    row['accepted'] = 'yes'
                elif name == 'rejected':
                    row.update(accepted='no', billed_cost_usd='.1')

            def summary():
                with reviews.open('w', newline='') as file:
                    writer = csv.DictWriter(file, fieldnames=FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)
                return summarize(outputs, reviews)

            result = summary()
            self.assertEqual(result['editorial_reviews'], {
                'reviewed': 2, 'accepted': 1, 'pending': 1, 'accepted_pending_cost': 1,
            })
            self.assertEqual(result['editorial_cuts']['complete_cost_reviews'], 1)
            self.assertIsNone(result['editorial_cuts']['billed_cost_per_accepted_usd'])
            self.assertIsNone(result['editorial_outcomes_7d'])
            next(row for row in rows if row['accepted'] == 'yes')['billed_cost_usd'] = '.2'
            result = summary()
            self.assertEqual(result['editorial_reviews']['accepted'], 1)
            self.assertEqual(result['editorial_reviews']['accepted_pending_cost'], 0)
            self.assertAlmostEqual(result['editorial_cuts']['billed_cost_per_accepted_usd'], .3)

    def test_init_adds_public_release_column_without_losing_existing_reviews(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory)
            for name in ("existing", "new"):
                (outputs / f"{name}.production.json").write_text(json.dumps({
                    "schema_version": 1, "script_key": name, "production_mode": "video",
                    "quality_passed": True,
                }), encoding="utf-8")
            reviews = outputs / "reviews.csv"
            with reviews.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=[*FIELDS[:-1], "custom_note"])
                writer.writeheader()
                writer.writerow({"report_path": str((outputs / "existing.production.json").resolve()),
                                 "accepted": "no", "billed_cost_usd": "0.12",
                                 "review_note": "keep", "custom_note": "also keep"})

            self.assertEqual(init_reviews(outputs, reviews), 1)
            with reviews.open(encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 2)
            self.assertIn("public_release_confirmed", rows[0])
            self.assertEqual(rows[0]["billed_cost_usd"], "0.12")
            self.assertEqual(rows[0]["review_note"], "keep")
            self.assertEqual(rows[0]["custom_note"], "also keep")
            self.assertEqual(rows[1]["custom_note"], "")
            self.assertEqual(init_reviews(outputs, reviews), 0)

            rows[0]["public_release_confirmed"] = "maybe"
            with reviews.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=[*FIELDS[:-1], "custom_note",
                                                           "public_release_confirmed"])
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "public_release_confirmed"):
                summarize(outputs, reviews)


if __name__ == "__main__":
    unittest.main()
