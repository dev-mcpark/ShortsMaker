"""Read exact-scene manual work and approved native sources without spending."""

import hashlib
from pathlib import Path

from shorts_maker.services.asset_library import AssetLibrary
from shorts_maker.services.raw_review import raw_review_status
from shorts_maker.utils.config import settings
from shorts_maker.utils.media_validation import is_playable_video
from shorts_maker.utils.veo_prompt_exporter import MAX_MANUAL_CLIP_BYTES, VeoPromptExporter


class ExistingSceneClips:
    def __init__(self, script, scene_number, service, current_workspace):
        self.script, self.service = script, service
        self.current_workspace = current_workspace
        self.index = next((i for i, scene in enumerate(script.scenes) if type(scene_number) is int and scene.scene_number == scene_number), None)
        if self.index is None:
            raise ValueError('현재 대본의 장면 번호를 선택하세요.')
        self.scene = script.scenes[self.index]
        self.exporter = VeoPromptExporter()
        self.library = AssetLibrary(roots={'clips': settings.clips_dir})

    def _key(self, path):
        return 'clips/' + Path(path).absolute().relative_to(settings.clips_dir.absolute()).as_posix()

    def _native(self):
        path, frame_hash = self.service.review_clip_path(self.script, self.index)
        if not path or raw_review_status(self.script, self.scene, path, frame_hash) != 'approved':
            raise ValueError('현재 대본·장면의 승인된 Veo 원본이 없습니다.')
        return path

    def candidates(self):
        result = {}
        for workspace, label in self.exporter.list_workspaces(self.script).items():
            if workspace == self.current_workspace:
                continue
            try:
                path = self.exporter.get_clip_path(workspace, self.scene.scene_number)
                if path.is_file():
                    key = self._key(path)
                    self.library.path(key)
                    result[key] = {'label': f'보유 영상 · {label} · 장면 {self.scene.scene_number}', 'workspace': workspace}
            except (OSError, ValueError):
                continue
        try:
            key = self._key(self._native())
            self.library.path(key)
            result[key] = {'label': f'승인된 Veo 원본 · 장면 {self.scene.scene_number}', 'workspace': None}
        except (OSError, ValueError):
            pass  # Missing/unverified/rejected native work is not a reusable candidate.
        return result

    def _path(self, key, candidate):
        if candidate['workspace'] is not None:
            self.exporter.validate_workspace(self.script, candidate['workspace'])
            expected = self.exporter.get_clip_path(candidate['workspace'], self.scene.scene_number)
        else:
            expected = self._native()
        if self._key(expected) != key:
            raise ValueError('선택한 재료와 현재 장면 기록이 다릅니다.')
        path = self.library.preview(key)
        if path.stat().st_size > MAX_MANUAL_CLIP_BYTES:
            raise ValueError('장면 클립은 500 MB 이하로 선택하세요.')
        return path

    def preview(self, key, candidate):
        path = self._path(key, candidate)
        identity = self.library._identity(path)
        if not is_playable_video(path):
            raise ValueError('선택한 영상을 재생할 수 없습니다. 다른 재료를 선택하세요.')
        return str(path), identity

    def read(self, key, candidate, identity):
        path = self._path(key, candidate)
        if self.library._identity(path) != identity:
            raise ValueError('미리보기 이후 파일이 변경됐습니다. 다시 선택하세요.')
        with path.open('rb') as file:
            content = file.read(MAX_MANUAL_CLIP_BYTES + 1)
        if (len(content) > MAX_MANUAL_CLIP_BYTES or hashlib.sha256(content).hexdigest() != identity['sha256']
                or self.library._identity(self._path(key, candidate)) != identity):
            raise ValueError('읽는 동안 재료 또는 판정이 변경됐습니다. 다시 선택하세요.')
        return content
