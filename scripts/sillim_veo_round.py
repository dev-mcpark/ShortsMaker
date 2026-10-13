"""Run one scene of the approved 2026-10-13 Sillim Veo Lite round.

Each scene is single-use. Inspect a raw clip and write its SHA-256 to
``scene_N.accepted`` before requesting the next scene. Keep the paid switch off
except for the exact invocation that submits a new scene.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.services.visual_cost import estimated_scene_cost
from shorts_maker.utils.config import PROJECT_ROOT, settings


MODEL = "veo-3.1-lite-generate-001"
ROUND_CAP_USD = 1.50
# All five authorized requests were submitted on 2026-10-13. Keep the shot
# brief for audit/reproduction; a later round needs its own authorization.
ROUND_CLOSED = True
OUT = PROJECT_ROOT / "outputs" / "evaluation" / "sillim_veo_round_20261013"
FIRST_FRAME = PROJECT_ROOT / "assets" / "sillim_veo_opening_seed_v1.png"

SHOTS = {
    1: (8, "The single bus rolls smoothly toward the open bay during the first 1.6 seconds as the camera tracks gently left to right, then settles. Keep the depot and all blank surfaces unchanged; no new objects or markings."),
    2: (8, "One continuous shot of a visibly fictional miniature city block in cream and dark teal, with a plain unmarked bus depot bay. A small rain cloud approaches in the distance as the camera slowly pushes forward. Calm daylight. No flooding, damage, people, signs, maps, labels, logos, letters, numerals, or identifiable real streets. Leave the lower third clear for captions."),
    3: (6, "One continuous shot of a visibly fictional miniature bus depot massing, cream and dark teal. The camera moves gently downward beside plain, unmarked building surfaces. Keep the structure abstract with no visible floor diagram or technically exact cross-section. No people, signs, labels, logos, letters, numerals, maps, or visible water. Leave space for an explanatory diagram and captions added in editing."),
    4: (8, "One continuous abstract miniature illustration: a modest blue stream of rainwater flows gently into a plain concealed storage volume beneath an unmarked cream-and-dark-teal city block. One slow lateral camera track. This is a conceptual explanation, not disaster footage or a depiction of an actual facility. No damage, people, signs, labels, logos, letters, numerals, maps, or measured levels. Leave the lower third clear for captions."),
    5: (8, "One continuous shot of a visibly fictional cream-and-dark-teal miniature depot. One unmarked bus departs calmly while a simple blank blue volume remains beneath opaque ground. The camera pulls back gently. Keep the underground area abstract and free of exact structural details. No people, signs, labels, logos, letters, numerals, maps, route marks, or measured water levels. Leave the lower third clear for captions."),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight(scene_number: int) -> tuple[Path, Path, int, str, float]:
    if ROUND_CLOSED:
        raise RuntimeError("This approved Veo round is closed; no further calls are authorized")
    if scene_number not in SHOTS:
        raise ValueError("scene must be 1–5")
    duration, prompt = SHOTS[scene_number]
    cost = estimated_scene_cost("video", MODEL, duration)
    if not settings.paid_production_enabled:
        raise RuntimeError("Paid production is disabled")
    if not settings.gcp_project_id or not settings.service_account_path.is_file():
        raise RuntimeError("Google project or service account is unavailable")
    if settings.gcp_location != "us-central1":
        raise RuntimeError("This round requires us-central1")
    if scene_number == 1 and not FIRST_FRAME.is_file():
        raise FileNotFoundError(FIRST_FRAME)
    OUT.mkdir(parents=True, exist_ok=True)
    record = OUT / f"scene_{scene_number}.json"
    clip = OUT / f"scene_{scene_number}.mp4"
    if record.exists() or clip.exists():
        raise RuntimeError("Scene already attempted; do not repeat an approved one-shot request")
    for prior in range(1, scene_number):
        prior_clip = OUT / f"scene_{prior}.mp4"
        accepted = OUT / f"scene_{prior}.accepted"
        if not prior_clip.is_file() or not accepted.is_file() or accepted.read_text().strip() != sha256(prior_clip):
            raise RuntimeError(f"Scene {prior} has not been accepted against its raw clip hash")
    existing = [OUT / f"scene_{number}.json" for number in SHOTS
                if (OUT / f"scene_{number}.json").is_file()]
    spent_estimate = sum(json.loads(path.read_text())["estimated_output_usd"] for path in existing)
    if spent_estimate + cost > ROUND_CAP_USD + 1e-9:
        raise RuntimeError("Approved round estimate would be exceeded")
    return record, clip, duration, prompt, cost


def run(scene_number: int) -> None:
    record_path, clip, duration, prompt, cost = preflight(scene_number)
    record = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "scene_number": scene_number,
        "model": MODEL,
        "duration_seconds": duration,
        "estimated_output_usd": cost,
        "round_cap_usd": ROUND_CAP_USD,
        "max_attempts": 1,
        "prompt": prompt,
        "first_frame_sha256": sha256(FIRST_FRAME) if scene_number == 1 else None,
        "status": "pending_or_submitted",
    }
    with record_path.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    try:
        generator = VideoGenerator(mode="video", max_veo_attempts=1)
        if generator.client is None:
            raise RuntimeError("Google video client is unavailable")
        generator._retry_veo_call(
            MODEL, prompt, str(clip), prompt,
            max_attempts=1,
            duration_seconds=duration,
            scene_number=scene_number,
            first_frame_path=str(FIRST_FRAME) if scene_number == 1 else None,
            request_budget_usd=round(cost + 0.06, 2),
        )
        record["status"] = "saved_unreviewed"
        record["clip_sha256"] = sha256(clip)
    except Exception as exc:
        record["status"] = "failed_or_unknown"
        record["error_type"] = type(exc).__name__
        record["error_message"] = str(exc)[:500]
        raise
    finally:
        record["finished_utc"] = datetime.now(timezone.utc).isoformat()
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"scene": scene_number, "status": record["status"], "clip": str(clip), "estimated_output_usd": cost}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=int, choices=SHOTS)
    args = parser.parse_args()
    run(args.scene)


if __name__ == "__main__":
    main()
