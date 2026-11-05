"""Offline, private production scorecard."""

import argparse
import csv
import json
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path


PUBLIC_FIELD = "public_release_confirmed"
ENGAGED_FIELD = "engaged_views_7d"
FIELDS = (
    "report_path", "video_path", "script_key", "production_mode", "quality_passed",
    "estimated_visual_output_cost_usd", "accepted", "billed_cost_usd", "views_7d",
    "average_view_duration_seconds_7d", "revenue_usd_7d", "review_note",
    ENGAGED_FIELD, PUBLIC_FIELD,
)


def _reports(outputs_dir: Path) -> dict[str, dict]:
    reports = {}
    for path in outputs_dir.rglob("*.production.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or not data.get("script_key"):
            raise ValueError(f"알 수 없는 제작 기록 형식: {path}")
        reports[str(path.resolve())] = data
    return reports


def init_reviews(outputs_dir: Path, review_file: Path) -> int:
    """Add missing rendered videos without overwriting editorial work."""
    reports = _reports(outputs_dir)
    review_file.parent.mkdir(parents=True, exist_ok=True)
    exists = review_file.exists()
    known = set()
    columns = list(FIELDS)
    if exists:
        with review_file.open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            columns = reader.fieldnames or []
            if not (set(FIELDS) - {PUBLIC_FIELD, ENGAGED_FIELD}).issubset(columns):
                raise ValueError("검토 CSV의 열이 누락되었습니다.")
            rows = list(reader)
            known = {str(Path(row["report_path"]).resolve()) for row in rows}
        missing = [field for field in (PUBLIC_FIELD, ENGAGED_FIELD) if field not in columns]
        if missing:
            columns.extend(missing)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="",
                                                 dir=review_file.parent, delete=False) as file:
                    temporary = Path(file.name)
                    writer = csv.DictWriter(file, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(rows)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, review_file)
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
    with review_file.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        if not exists:
            writer.writeheader()
        for path in sorted(reports.keys() - known):
            report = reports[path]
            writer.writerow({"report_path": path, **{
                field: report.get(field) for field in FIELDS
                if field in {"video_path", "script_key", "production_mode", "quality_passed",
                             "estimated_visual_output_cost_usd"}
            }})
    return len(reports.keys() - known)


def _number(row: dict, field: str):
    value = (row.get(field) or "").strip()
    if not value:
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field}는 0 이상의 유한한 숫자여야 합니다.")
    return number


def _retention(row: dict) -> tuple:
    views = _number(row, "views_7d")
    engaged = _number(row, ENGAGED_FIELD)
    duration = _number(row, "average_view_duration_seconds_7d")
    if engaged is not None and (not engaged.is_integer() or (views is not None and engaged > views)):
        raise ValueError("유효 조회수는 전체 조회수 이하의 정수여야 합니다.")
    return views, engaged, duration


def summarize(outputs_dir: Path, review_file: Path) -> dict:
    reports = _reports(outputs_dir)
    reviews = {}
    with review_file.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if not (set(FIELDS) - {ENGAGED_FIELD}).issubset(reader.fieldnames or []):
            raise ValueError("검토 CSV의 열이 누락되었습니다.")
        for row in reader:
            path = str(Path(row["report_path"]).resolve())
            if path not in reports or path in reviews:
                raise ValueError(f"제작 기록이 없거나 중복된 검토 행: {path}")
            release = (row.get(PUBLIC_FIELD) or "").strip().lower()
            if release not in {"", "yes", "no"}:
                raise ValueError(f"{PUBLIC_FIELD}는 yes 또는 no여야 합니다: {path}")
            row[PUBLIC_FIELD] = release
            reviews[path] = row

    grouped = defaultdict(lambda: defaultdict(list))
    for path, report in reports.items():
        if (report.get("production_mode") in {"image", "hybrid"}
                and report.get("paired_comparison_eligible", True)):
            grouped[report["script_key"]][report["production_mode"]].append(path)

    totals = {mode: {"accepted": 0, "cost": 0.0} for mode in ("image", "hybrid")}
    outcomes = {mode: {"views": 0.0, "engaged_views": 0.0, "watch_seconds": 0.0, "revenue": 0.0}
                for mode in ("image", "hybrid")}
    paired = complete = outcome_pairs = revenue_pairs = 0
    paired_paths = set()
    for modes in grouped.values():
        if len(modes["image"]) != 1 or len(modes["hybrid"]) != 1:
            continue
        paired += 1
        paired_paths.update(modes[mode][0] for mode in totals)
        rows = {mode: reviews.get(modes[mode][0]) for mode in totals}
        if any(row is None or row["accepted"].strip().lower() not in {"yes", "no"}
               or _number(row, "billed_cost_usd") is None for row in rows.values()):
            continue
        accepted = {mode: rows[mode]["accepted"].strip().lower() == "yes" for mode in totals}
        for mode in totals:
            report = reports[modes[mode][0]]
            if accepted[mode] and not report.get("quality_passed"):
                raise ValueError("품질 검사를 통과하지 못한 영상을 채택할 수 없습니다.")
            totals[mode]["accepted"] += accepted[mode]
            totals[mode]["cost"] += _number(rows[mode], "billed_cost_usd")
        complete += 1

        if not all(accepted.values()):
            continue
        metrics = {}
        for mode in totals:
            row = rows[mode]
            metrics[mode] = (*_retention(row), _number(row, "revenue_usd_7d"))
        if any(not reports[modes[mode][0]].get("youtube_id")
               or rows[mode][PUBLIC_FIELD] != "yes" or
               any(value is None for value in metrics[mode][:3]) for mode in totals):
            continue
        outcome_pairs += 1
        for mode in totals:
            views, engaged, duration, _revenue = metrics[mode]
            outcomes[mode]["views"] += views
            outcomes[mode]["engaged_views"] += engaged
            outcomes[mode]["watch_seconds"] += engaged * duration
        if all(metrics[mode][3] is not None for mode in totals):
            revenue_pairs += 1
            for mode in totals:
                outcomes[mode]["revenue"] += metrics[mode][3]

    editorial_paths = [path for path in reports if path not in paired_paths]
    editorial_complete = editorial_accepted = 0
    editorial_reviewed = editorial_selected = 0
    editorial_cost = 0.0
    editorial_outcome_count = editorial_revenue_count = 0
    editorial_views = editorial_engaged = editorial_watch_seconds = editorial_revenue = 0.0
    for path in editorial_paths:
        row = reviews.get(path)
        if row is None or row["accepted"].strip().lower() not in {"yes", "no"}:
            continue
        accepted = row["accepted"].strip().lower() == "yes"
        if accepted and not reports[path].get("quality_passed"):
            raise ValueError("품질 검사를 통과하지 못한 영상을 채택할 수 없습니다.")
        editorial_reviewed += 1
        editorial_selected += accepted
        cost = _number(row, "billed_cost_usd")
        if cost is not None:
            editorial_complete += 1
            editorial_accepted += accepted
            editorial_cost += cost
        if (not accepted or not reports[path].get("youtube_id")
                or row[PUBLIC_FIELD] != "yes"):
            continue
        views, engaged, duration = _retention(row)
        if views is None or engaged is None or duration is None:
            continue
        editorial_outcome_count += 1
        editorial_views += views
        editorial_engaged += engaged
        editorial_watch_seconds += engaged * duration
        revenue = _number(row, "revenue_usd_7d")
        if revenue is not None:
            editorial_revenue_count += 1
            editorial_revenue += revenue

    source_groups = defaultdict(list)
    for path, report in reports.items():
        source_url = report.get("source_url")
        if isinstance(source_url, str) and source_url.strip():
            source_groups[source_url.strip()].append(path)
    source_complete = source_accepted = 0
    source_cost = 0.0
    for paths in source_groups.values():
        rows = [reviews.get(path) for path in paths]
        if any(row is None or row["accepted"].strip().lower() not in {"yes", "no"}
               or _number(row, "billed_cost_usd") is None for row in rows):
            continue
        source_complete += 1
        source_accepted += any(row["accepted"].strip().lower() == "yes" for row in rows)
        source_cost += sum(_number(row, "billed_cost_usd") for row in rows)

    return {
        "rendered_reports": len(reports),
        "paired_scripts": paired,
        "complete_cost_pairs": complete,
        "pending_cost_pairs": paired - complete,
        "modes": {
            mode: {
                "accepted": totals[mode]["accepted"],
                "accepted_rate": round(totals[mode]["accepted"] / complete, 4) if complete else None,
                "billed_cost_usd": round(totals[mode]["cost"], 4) if complete else None,
                "billed_cost_per_accepted_usd": round(
                    totals[mode]["cost"] / totals[mode]["accepted"], 4,
                ) if totals[mode]["accepted"] else None,
            } for mode in totals
        },
        "editorial_reviews": {
            "reviewed": editorial_reviewed,
            "accepted": editorial_selected,
            "pending": len(editorial_paths) - editorial_reviewed,
            "accepted_pending_cost": editorial_selected - editorial_accepted,
        },
        "editorial_cuts": {
            "rendered": len(editorial_paths),
            "complete_cost_reviews": editorial_complete,
            "accepted": editorial_accepted,
            "accepted_rate": round(editorial_accepted / editorial_complete, 4) if editorial_complete else None,
            "billed_cost_usd": round(editorial_cost, 4) if editorial_complete else None,
            "billed_cost_per_accepted_usd": round(
                editorial_cost / editorial_accepted, 4,
            ) if editorial_accepted else None,
        },
        "source_stories": {
            "tracked": len(source_groups),
            "unattributed_cuts": len(reports) - sum(map(len, source_groups.values())),
            "complete_cost_stories": source_complete,
            "accepted": source_accepted,
            "accepted_rate": round(source_accepted / source_complete, 4) if source_complete else None,
            "billed_cost_usd": round(source_cost, 4) if source_complete else None,
            "billed_cost_per_accepted_usd": round(source_cost / source_accepted, 4)
            if source_accepted else None,
        },
        "editorial_outcomes_7d": {
            "complete_videos": editorial_outcome_count,
            "views": int(editorial_views),
            "engaged_views": int(editorial_engaged),
            "average_view_duration_seconds": round(
                editorial_watch_seconds / editorial_engaged, 2,
            ) if editorial_engaged else None,
            "complete_revenue_videos": editorial_revenue_count,
            "revenue_usd": round(editorial_revenue, 4)
            if editorial_revenue_count == editorial_outcome_count else None,
        } if editorial_outcome_count else None,
        "complete_7d_outcome_pairs": outcome_pairs,
        "complete_7d_revenue_pairs": revenue_pairs,
        "outcomes_7d": {
            mode: {
                "views": int(outcomes[mode]["views"]),
                "engaged_views": int(outcomes[mode]["engaged_views"]),
                "average_view_duration_seconds": round(
                    outcomes[mode]["watch_seconds"] / outcomes[mode]["engaged_views"], 2,
                ) if outcomes[mode]["engaged_views"] else None,
                "revenue_usd": round(outcomes[mode]["revenue"], 4) if revenue_pairs else None,
            } for mode in totals
        } if outcome_pairs else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "summary"))
    parser.add_argument("--outputs", type=Path, default=Path("outputs"))
    parser.add_argument("--reviews", type=Path, default=Path("outputs/evaluation/reviews.csv"))
    args = parser.parse_args()
    if args.action == "init":
        print(f"Added {init_reviews(args.outputs, args.reviews)} rows to {args.reviews}")
    else:
        print(json.dumps(summarize(args.outputs, args.reviews), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
