"""One Jamsu scene-4 Veo image-to-video attempt; dry-run unless --execute is given."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.services.google_budget import budget_status, check_google_budget
from shorts_maker.services.visual_cost import estimated_scene_cost
from shorts_maker.utils.config import PROJECT_ROOT, settings


MODEL = "veo-3.1-lite-generate-001"
DURATION = 8
REQUEST_CAP_USD = 0.24
FRAME = PROJECT_ROOT / "assets" / "jamsu_scene4_seed_v1.png"
FRAME_SHA256 = "b6d82866dfc53e3f86b26767ac6d0f1dc0ce35590e648d3a97a5edbc9a76939b"
SCRIPT = PROJECT_ROOT / "docs" / "jamsu_bridge_narration_candidate.json"
REVIEW = PROJECT_ROOT / "docs" / "jamsu_scene4_visual_review.json"
SOURCE_URL = "https://mediahub.seoul.go.kr/archives/2019683"
OUT = PROJECT_ROOT / "outputs" / "evaluation" / "jamsu_scene4_native_20261031"
PROMPT = (
    "Use the supplied image as the first frame of one continuous silent portrait shot of a "
    "fictional architectural scale model for an unbuilt bridge revision. Slowly truck the camera "
    "from left to right along the single widened pedestrian deck, with clear parallax through "
    "the railings. Keep the model figures, supports, floor panels, and calm water otherwise still. "
    "The side viewing bays and both blue transparent floor panels remain flush with the walkable "
    "deck as the camera brings them into closer view. Preserve the starting image's one-level "
    "layout and panel positions. Soft daylight and open lower third for editor captions. "
    "No elevated pink path, construction, lifting, removal, flood, ship, new structure, duplicate "
    "panel, water-filled hole, writing, logo, or audio."
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def visual_review_status() -> str:
    script = json.loads(SCRIPT.read_text(encoding="utf-8"))
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    scene = next((item for item in script["scenes"] if item["scene_number"] == 4), None)
    if script["source_url"] != SOURCE_URL:
        raise ValueError("Visual review is stale: primary source changed")
    expected = {
        "scene_number": 4,
        "source_urls": [script["source_url"], *script.get("supporting_source_urls", [])],
        "script_text": scene["script_text"] if scene else None,
        "frame_sha256": sha256(FRAME),
        "motion_prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
    }
    if any(review.get(key) != value for key, value in expected.items()):
        raise ValueError("Visual review is stale: source, narration, frame, or motion changed")
    if any(not isinstance(review.get(key), list) or not review[key]
           or any(not isinstance(item, str) or not item.strip() for item in review[key])
           for key in ("must_show", "must_avoid")):
        raise ValueError("Visual review needs concrete acceptance and rejection criteria")
    decision = review.get("decision")
    if decision not in {"pending", "approved", "rejected"}:
        raise ValueError("Visual review decision is invalid")
    note = review.get("reviewer_note")
    if decision == "approved" and (not isinstance(note, str) or not note.strip()):
        raise ValueError("Approved visual review needs a reviewer note")
    return decision


def preflight() -> float:
    if (OUT / "request.json").exists() or (OUT / "scene_4.mp4").exists():
        raise RuntimeError("This Jamsu one-shot attempt has already been used")
    if sha256(FRAME) != FRAME_SHA256:
        raise ValueError("The reviewed first frame has changed")
    visual_review_status()
    if FRAME.stat().st_size > 20_000_000:
        raise ValueError("First frame exceeds the 20 MB limit")
    with Image.open(FRAME) as image:
        if image.format not in {"PNG", "JPEG"} or abs(image.width / image.height - 9 / 16) > 0.02:
            raise ValueError("First frame must be a portrait 9:16 PNG or JPEG")
        image.verify()
    cost = estimated_scene_cost("video", MODEL, DURATION)
    if cost > REQUEST_CAP_USD or cost > settings.max_visual_cost_usd:
        raise ValueError("Veo output estimate exceeds the request or visual cap")
    if not budget_status().get("enabled"):
        raise RuntimeError("The Google monthly budget guard must be active")
    check_google_budget(cost)
    return cost


def run() -> None:
    if visual_review_status() != "approved":
        raise RuntimeError("The scene-4 first frame and motion need an editorial verdict before paid submission")
    cost = preflight()
    if not settings.paid_production_enabled:
        raise RuntimeError("Paid production is disabled")
    if not settings.gcp_project_id or not settings.service_account_path.is_file():
        raise RuntimeError("Google project or service account is unavailable")
    if settings.gcp_location != "us-central1":
        raise RuntimeError("This pilot requires us-central1")
    generator = VideoGenerator(mode="video", max_veo_attempts=1)
    if generator.client is None:
        raise RuntimeError("Google video client is unavailable")

    OUT.mkdir(parents=True, exist_ok=True)
    request_path = OUT / "request.json"
    clip = OUT / "scene_4.mp4"
    record = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "scene_number": 4, "model": MODEL, "duration_seconds": DURATION,
        "estimated_output_usd": cost, "request_cap_usd": REQUEST_CAP_USD,
        "max_attempts": 1, "first_frame_sha256": FRAME_SHA256,
        "visual_review_sha256": sha256(REVIEW),
        "source_url": SOURCE_URL, "prompt": PROMPT, "status": "pending_or_submitted",
    }
    with request_path.open("x", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
    try:
        generator._retry_veo_call(
            MODEL, PROMPT, str(clip), PROMPT,
            max_attempts=1, duration_seconds=DURATION, scene_number=4,
            first_frame_path=str(FRAME), request_budget_usd=REQUEST_CAP_USD,
            source_url=SOURCE_URL, expected_first_frame_sha256=FRAME_SHA256,
        )
        record.update(status="saved_unreviewed", clip_sha256=sha256(clip))
    except Exception as error:
        record.update(status="provider_limited" if "RESOURCE_EXHAUSTED" in str(error)
                      else "failed_or_unknown", error_type=type(error).__name__,
                      error_message=str(error)[:500])
        raise
    finally:
        record["finished_utc"] = datetime.now(timezone.utc).isoformat()
        request_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": record["status"], "clip": str(clip),
                      "estimated_output_usd": cost}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="submit the single budgeted request")
    args = parser.parse_args()
    if args.execute:
        run()
    else:
        print(json.dumps({"status": "ready" if visual_review_status() == "approved" else "awaiting_frame_approval", "model": MODEL,
                          "estimated_output_usd": preflight(), "request_cap_usd": REQUEST_CAP_USD}))


if __name__ == "__main__":
    main()
