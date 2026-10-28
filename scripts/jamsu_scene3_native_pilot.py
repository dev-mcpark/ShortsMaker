"""One Jamsu scene-3 Veo image-to-video attempt; dry-run unless --execute is given."""

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
FRAME = PROJECT_ROOT / "assets" / "jamsu_scene3_seed_v3.png"
FRAME_SHA256 = "67478a1f29d9d31d0b41f6baaf6a7b4a08fe05d2420aed5d8be041a7e5b42379"
FRAME_APPROVED = False
SOURCE_URL = "https://mediahub.seoul.go.kr/archives/2019683"
OUT = PROJECT_ROOT / "outputs" / "evaluation" / "jamsu_scene3_native_20261028"
PROMPT = (
    "One continuous silent vertical shot of the supplied fictional architectural scale model. "
    "The low gray pedestrian bridge, its tiny model figures, and calm blue water remain fully "
    "visible, fixed, and intact. Above it, the empty pink elevated walkway with railings and "
    "two slender supports is a removable 2024 proposal layer. In one slow clean movement, "
    "only that entire pink proposal layer lifts straight upward and out of the exhibit model, "
    "leaving the lower bridge unchanged and unmarked. "
    "Locked camera, stable geometry, soft studio daylight, generous blank lower third for later "
    "editor captions. This illustrates a design revision, not physical demolition or real footage. "
    "No writing, numbers, logos, new figures, vehicles, new structures, rising water, flood, collapse, "
    "or damage."
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight() -> float:
    if (OUT / "request.json").exists() or (OUT / "scene_3.mp4").exists():
        raise RuntimeError("This Jamsu one-shot attempt has already been used")
    if sha256(FRAME) != FRAME_SHA256:
        raise ValueError("The reviewed first frame has changed")
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
    if not FRAME_APPROVED:
        raise RuntimeError("The revised first frame needs an editorial verdict before paid submission")
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
    clip = OUT / "scene_3.mp4"
    record = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "scene_number": 3, "model": MODEL, "duration_seconds": DURATION,
        "estimated_output_usd": cost, "request_cap_usd": REQUEST_CAP_USD,
        "max_attempts": 1, "first_frame_sha256": FRAME_SHA256,
        "source_url": SOURCE_URL, "prompt": PROMPT, "status": "pending_or_submitted",
    }
    with request_path.open("x", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
    try:
        generator._retry_veo_call(
            MODEL, PROMPT, str(clip), PROMPT,
            max_attempts=1, duration_seconds=DURATION, scene_number=3,
            first_frame_path=str(FRAME), request_budget_usd=REQUEST_CAP_USD,
            source_url=SOURCE_URL,
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
        print(json.dumps({"status": "ready" if FRAME_APPROVED else "awaiting_frame_approval", "model": MODEL,
                          "estimated_output_usd": preflight(), "request_cap_usd": REQUEST_CAP_USD}))


if __name__ == "__main__":
    main()
