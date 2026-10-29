"""Render one source-checked script in image and hybrid modes with identical narration."""

import argparse
import asyncio
import json
import math
from pathlib import Path

from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.planner.models import ShortsScript
from shorts_maker.services.production_service import ProductionService
from shorts_maker.services.raw_review import verified_raw_clip
from shorts_maker.services.visual_cost import estimated_scene_cost, scene_mode
from shorts_maker.utils.config import settings


def estimate_pair(script: ShortsScript) -> tuple[float, float]:
    image = len(script.scenes) * estimated_scene_cost("image", settings.image_model_id)
    hybrid = 0.0
    for index, scene in enumerate(script.scenes):
        mode = scene_mode("hybrid", scene, index)
        if mode == 'image':
            hybrid += estimated_scene_cost('image', settings.image_model_id)
    return image, hybrid


async def render_pair(script: ShortsScript, budget_usd: float) -> None:
    image_estimate, hybrid_estimate = estimate_pair(script)
    if not math.isfinite(budget_usd) or budget_usd < 0 or image_estimate + hybrid_estimate > budget_usd:
        raise ValueError(
            f"최악의 비주얼 추정 합계 ${image_estimate + hybrid_estimate:.3f}가 "
            f"비교 실험 상한 ${budget_usd:.3f}를 넘습니다."
        )
    if max(image_estimate, hybrid_estimate) > settings.max_visual_cost_usd:
        raise ValueError("영상별 비주얼 비용 상한을 넘습니다.")
    if not settings.paid_production_enabled:
        raise ValueError(ProductionService.PAID_WORK_DISABLED)
    hybrid_service = ProductionService(mode='hybrid', max_veo_attempts=1)
    for index, scene in enumerate(script.scenes):
        if scene_mode('hybrid', scene, index) == 'video':
            clip, frame_hash = hybrid_service.review_clip_path(script, index)
            if not clip:
                raise ValueError(f'RAW_CLIP_REVIEW_REQUIRED: 씬 {scene.scene_number}의 승인된 Veo 원본이 필요합니다.')
            verified_raw_clip(script, scene, clip, frame_hash)
    print(f"Pair new visual upper estimate: ${image_estimate + hybrid_estimate:.3f}", flush=True)

    narrator = VideoEditor(bgm_volume=0.0)
    audio_paths = await narrator.prepare_narration(script)
    try:
        for mode in ("image", "hybrid"):
            service = ProductionService(
                mode=mode, max_veo_attempts=1, editor_options={"bgm_volume": 0.0},
            )
            result = await service.produce_video(script, prepared_audio_paths=audio_paths)
            print(json.dumps({
                "mode": mode, "success": result.success,
                "video_path": result.video_path, "report_path": result.report_path,
                "estimated_visual_cost_usd": result.estimated_visual_cost_usd,
                "error": result.error,
            }, ensure_ascii=False), flush=True)
            if not result.success:
                raise RuntimeError(f"{mode} 제작 실패; 상세 원인은 위 결과를 확인하세요.")
    finally:
        narrator.cleanup_temp_files()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("--budget-usd", type=float, default=1.25)
    args = parser.parse_args()
    script = ShortsScript.model_validate_json(args.script.read_text(encoding="utf-8"))
    asyncio.run(render_pair(script, args.budget_usd))


if __name__ == "__main__":
    main()
