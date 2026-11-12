"""
VEO 프롬프트 내보내기 유틸리티.

수동 생성 모드에서 씬별 VEO 프롬프트를 추출하고,
업로드된 클립 파일을 관리합니다.
"""
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.media_validation import is_playable_video

logger = get_logger(__name__)
MAX_MANUAL_CLIP_BYTES = 500_000_000


class VeoPromptExporter:
    """VEO 프롬프트 추출 및 수동 클립 파일 관리 클래스"""

    def get_script_id(self, script: ShortsScript) -> str:
        """스크립트 ID 생성: 타임스탬프_제목(안전문자만)"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[^\w\uAC00-\uD7A3]', '_', script.title)[:30]
        return f"{timestamp}_{safe_title}_{uuid.uuid4().hex[:8]}"

    def get_clips_dir(self, script_id: str) -> Path:
        """해당 스크립트의 클립 저장 디렉토리 반환 및 생성"""
        clips_dir = self._clips_dir(script_id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        return clips_dir

    def _clips_dir(self, script_id: str) -> Path:
        if not re.fullmatch(r"[\w-]{1,80}", script_id):
            raise ValueError("유효하지 않은 스크립트 ID입니다.")
        clips_dir = settings.clips_dir / script_id
        if not clips_dir.resolve().is_relative_to(settings.clips_dir.resolve()):
            raise ValueError('클립 작업 폴더가 출력 경계를 벗어났습니다.')
        return clips_dir

    def create_workspace(self, script: ShortsScript) -> str:
        script_id = self.get_script_id(script)
        directory = self.get_clips_dir(script_id)
        (directory / 'workspace.json').write_text(json.dumps({
            'schema_version': 1, 'script_id': script_id,
            'script': script.model_dump(mode='json'),
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        return script_id

    def validate_workspace(self, script: ShortsScript, script_id: str) -> None:
        path = self._clips_dir(script_id) / 'workspace.json'
        if not path.resolve().is_relative_to(settings.clips_dir.resolve()):
            raise ValueError('작업 기록이 출력 경계를 벗어났습니다.')
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(record, dict) or type(record.get('schema_version')) is not int
                    or record['schema_version'] != 1 or record.get('script_id') != script_id
                    or record.get('script') != script.model_dump(mode='json')):
                raise ValueError('현재 대본과 일치하는 작업 기록이 필요합니다.')
        except (OSError, ValueError) as error:
            raise ValueError('보유 영상 작업을 복원할 수 없습니다. 현재 대본과 작업 기록을 확인하세요.') from error
        for scene in script.scenes:
            self.get_clip_path(script_id, scene.scene_number)

    def list_workspaces(self, script: ShortsScript) -> Dict[str, str]:
        workspaces = []
        for path in settings.clips_dir.glob('*/workspace.json'):
            try:
                script_id = path.parent.name
                self.validate_workspace(script, script_id)
                ready = sum(item['exists'] for item in self.get_scenes_status(script, script_id))
                if ready:
                    workspaces.append((path.parent.stat().st_mtime, script_id,
                                       f'{script_id} · 연결 {ready}/{len(script.scenes)}장면'))
            except (OSError, ValueError):
                continue
        return {script_id: label for _, script_id, label in sorted(workspaces, reverse=True)}

    def get_clip_path(self, script_id: str, scene_number: int) -> Path:
        """씬 번호에 해당하는 클립 파일 경로 반환"""
        path = self.get_clips_dir(script_id) / f"scene_{scene_number:02d}.mp4"
        if not path.resolve().is_relative_to(settings.clips_dir.resolve()):
            raise ValueError('장면 파일이 클립 출력 경계를 벗어났습니다.')
        return path

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
                "exists": clip_path.is_file(),
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
            self.get_clip_path(script_id, scene.scene_number).is_file()
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
        if len(file_content) > MAX_MANUAL_CLIP_BYTES:
            raise ValueError('장면 클립은 500 MB 이하로 선택하세요.')
        clip_path = self.get_clip_path(script_id, scene_number)
        temp_path = clip_path.with_name(f'.{clip_path.stem}.{uuid.uuid4().hex}.tmp.mp4')
        try:
            temp_path.write_bytes(file_content)
            if not is_playable_video(temp_path):
                raise ValueError('업로드한 파일을 영상으로 재생할 수 없습니다. 기존 장면 파일은 유지됩니다.')
            os.replace(temp_path, clip_path)
        finally:
            temp_path.unlink(missing_ok=True)
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
                        "Follow the scene's specified subjects, people, counts, setting and visual style. "
                        "Preserve recurring identities and use the selected model's supported resolution."
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
