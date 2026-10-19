"""One bounded Sillim scene-2 stream Veo attempt; dry-run unless --execute is given."""

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
DURATION = 4
REQUEST_CAP_USD = 0.15
FRAME = PROJECT_ROOT / "assets" / "sillim_scene2_stream_seed_v2.png"
FRAME_SHA256 = "d5b1642a735d86768a8a3624e7be374b505665d803582601a40dae493bbf4b6a"
OUT = PROJECT_ROOT / "outputs" / "evaluation" / "sillim_scene2_stream_native_20261020"
PROMPT = (
    "One locked, silent shot of the supplied independent generic stream miniature. "
    "Rain grows visibly denser beneath the dark cloud, making more ripples across "
    "the contained stream; water stays below the banks. Preserve its standalone "
    "plinth and neutral cream background. No bus, depot, roads, real-location "
    "likeness, overflow, damage, writing, signs, logos, people, or measured outcome."
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight() -> float:
    if (OUT / "request.json").exists() or (OUT / "scene_2_stream.mp4").exists():
        raise RuntimeError("This one-shot approval has already been used")
    if sha256(FRAME) != FRAME_SHA256:
        raise ValueError("The approved first frame has changed")
    if FRAME.stat().st_size > 20_000_000:
        raise ValueError("First frame exceeds the 20 MB limit")
    with Image.open(FRAME) as image:
        if image.format not in {"PNG", "JPEG"} or abs(image.width / image.height - 9 / 16) > 0.02:
            raise ValueError("First frame must be a portrait 9:16 PNG or JPEG")
        image.verify()
    cost = estimated_scene_cost("video", MODEL, DURATION)
    if cost > REQUEST_CAP_USD or cost > settings.max_visual_cost_usd:
        raise ValueError("Veo output estimate exceeds the approved request or visual cap")
    if not budget_status().get("enabled"):
        raise RuntimeError("The Google monthly budget guard must be active")
    check_google_budget(cost)
    return cost


def run() -> None:
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
    clip = OUT / "scene_2_stream.mp4"
    record = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "scene_number": 2, "shot": "stream", "model": MODEL, "duration_seconds": DURATION,
        "estimated_output_usd": cost, "request_cap_usd": REQUEST_CAP_USD,
        "max_attempts": 1, "first_frame_sha256": FRAME_SHA256,
        "prompt": PROMPT, "status": "pending_or_submitted",
    }
    with request_path.open("x", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
    try:
        generator._retry_veo_call(
            MODEL, PROMPT, str(clip), PROMPT,
            max_attempts=1, duration_seconds=DURATION, scene_number=2,
            first_frame_path=str(FRAME), request_budget_usd=REQUEST_CAP_USD,
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
    parser.add_argument("--execute", action="store_true", help="submit the one approved paid request")
    args = parser.parse_args()
    if args.execute:
        run()
    else:
        print(json.dumps({"status": "ready", "model": MODEL,
                          "estimated_output_usd": preflight(), "request_cap_usd": REQUEST_CAP_USD}))


if __name__ == "__main__":
    main()
