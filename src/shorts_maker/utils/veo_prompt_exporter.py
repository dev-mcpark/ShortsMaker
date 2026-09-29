"""
VEO 프롬프트 내보내기 유틸리티.

수동 생성 모드에서 씬별 VEO 프롬프트를 추출하고,
업로드된 클립 파일을 관리합니다.
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger

logger = get_logger(__name__)


class VeoPromptExporter:
    """VEO 프롬프트 추출 및 수동 클립 파일 관리 클래스"""

    def get_script_id(self, script: ShortsScript) -> str:
        """스크립트 ID 생성: 타임스탬프_제목(안전문자만)"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[^\w\uAC00-\uD7A3]', '_', script.title)[:30]
        return f"{timestamp}_{safe_title}"

    def get_clips_dir(self, script_id: str) -> Path:
        """해당 스크립트의 클립 저장 디렉토리 반환 및 생성"""
        clips_dir = settings.clips_dir / script_id
        clips_dir.mkdir(parents=True, exist_ok=True)
        return clips_dir

    def get_clip_path(self, script_id: str, scene_number: int) -> Path:
        """씬 번호에 해당하는 클립 파일 경로 반환"""
        return self.get_clips_dir(script_id) / f"scene_{scene_number:02d}.mp4"

    def get_prompt_for_scene(self, scene: VideoScene) -> str:
        """씬의 VEO 프롬프트 조합: visual_description + motion_instruction"""
        parts = [scene.visual_description]
        if scene.motion_instruction:
            parts.append(scene.motion_instruction)
        return " ".join(parts)

    def get_scenes_status(
        self, script: ShortsScript, script_id: str
    ) -> List[Dict]:
        """
        각 씬의 클립 파일 존재 여부 확인.

        Returns:
            [{"scene_number": 1, "clip_path": "...", "exists": True, "prompt": "..."}, ...]
        """
        result = []
        for scene in script.scenes:
            clip_path = self.get_clip_path(script_id, scene.scene_number)
            result.append({
                "scene_number": scene.scene_number,
                "clip_path": str(clip_path),
                "exists": clip_path.exists(),
                "prompt": self.get_prompt_for_scene(scene),
                "visual_description": scene.visual_description,
                "motion_instruction": scene.motion_instruction,
                "script_text": scene.script_text,
                "duration_seconds": scene.duration_seconds,
            })
        return result

    def all_clips_ready(self, script: ShortsScript, script_id: str) -> bool:
        """모든 씬의 클립 파일이 존재하는지 확인"""
        return all(
            self.get_clip_path(script_id, scene.scene_number).exists()
            for scene in script.scenes
        )

    def save_uploaded_clip(
        self, file_content: bytes, script_id: str, scene_number: int
    ) -> Path:
        """
        업로드된 파일 내용을 지정 경로에 저장.

        Returns:
            저장된 파일의 Path
        """
        clip_path = self.get_clip_path(script_id, scene_number)
        clip_path.write_bytes(file_content)
        logger.info(f"✅ 씬 {scene_number} 클립 저장: {clip_path}")
        return clip_path

    def export_json(self, script: ShortsScript, script_id: str) -> str:
        """전체 프롬프트를 JSON 문자열로 반환 (클립보드/파일 저장용)"""
        clips_dir = self.get_clips_dir(script_id)
        data = {
            "script_id": script_id,
            "title": script.title,
            "generated_at": datetime.now().isoformat(),
            "total_scenes": len(script.scenes),
            "instructions": (
                "아래 각 씬의 veo_prompt를 VEO(또는 다른 영상 생성 서비스)에 입력하여 "
                "영상을 생성하세요. 생성된 영상은 save_as에 명시된 파일명으로 "
                "output_directory 폴더에 저장해주세요."
            ),
            "output_directory": str(clips_dir),
            "scenes": [
                {
                    "scene_number": scene.scene_number,
                    "save_as": f"scene_{scene.scene_number:02d}.mp4",
                    "clip_path": str(self.get_clip_path(script_id, scene.scene_number)),
                    "duration_seconds": scene.duration_seconds,
                    "script_text": scene.script_text,
                    "veo_prompt": self.get_prompt_for_scene(scene),
                    "visual_description": scene.visual_description,
                    "motion_instruction": scene.motion_instruction,
                    "aspect_ratio": "9:16",
                    "style_notes": (
                        "Professional broadcast quality, 4K, no people, "
                        "no presenter, background scene only"
                    ),
                }
                for scene in script.scenes
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    def get_ready_clip_paths(
        self, script: ShortsScript, script_id: str
    ) -> Optional[Dict[int, str]]:
        """
        모든 씬이 준비된 경우 {scene_number: clip_path} dict 반환.
        미완성이면 None 반환.
        """
        if not self.all_clips_ready(script, script_id):
            return None
        return {
            scene.scene_number: str(self.get_clip_path(script_id, scene.scene_number))
            for scene in script.scenes
        }
