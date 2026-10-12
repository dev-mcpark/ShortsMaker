"""Conservative, per-output visual estimates used before paid generation.

Reviewed 2026-10-12 against Google's public Agent Platform pricing. Update these
rates when the provider changes its pricing. The image estimate uses the
published 1K output example and includes a small buffer.
"""

IMAGE_USD = {
    "gemini-3.1-flash-lite-image": 0.034,
}
VIDEO_USD_PER_SECOND = {
    "veo-3.1-lite-generate-001": 0.03,
    "veo-3.1-fast-generate-001": 0.08,
}


def scene_mode(production_mode: str, scene, index: int) -> str:
    """Use one moving hook in hybrid mode unless the script overrides it."""
    if production_mode == "hybrid":
        return getattr(scene, "visual_mode", None) or ("video" if index == 0 else "image")
    return production_mode


def estimated_scene_cost(mode: str, model_id: str, duration_seconds: int = 0) -> float:
    """Estimate one new 1K image or one silent 720p video output."""
    prices = IMAGE_USD if mode == "image" else VIDEO_USD_PER_SECOND if mode == "video" else None
    if prices is None or model_id not in prices:
        raise ValueError(f"비용을 알 수 없는 비주얼 모델입니다: {model_id}")
    return prices[model_id] * (duration_seconds if mode == "video" else 1)
