"""Read exact-scene manual work and approved native sources without spending."""

import hashlib
import subprocess
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from moviepy.config import FFMPEG_BINARY
from PIL import Image, ImageOps

from shorts_maker.services.asset_library import AssetLibrary
from shorts_maker.services.raw_review import raw_review_status
from shorts_maker.services.visual_review import verified_first_frame
from shorts_maker.utils.config import settings
from shorts_maker.utils.media_validation import MAX_FRAME_BYTES, is_playable_video
from shorts_maker.utils.veo_prompt_exporter import MAX_MANUAL_CLIP_BYTES, VeoPromptExporter

APPROVED_FIRST_FRAME = 'approved-first-frame'


def _render_still(content: bytes) -> bytes:
    """Encode just the previewed image, without audio or generated motion."""
    frame = BytesIO()
    with Image.open(BytesIO(content)) as image:
        resized = ImageOps.pad(image.convert('RGBA'), (720, 1280), color='black')
        background = Image.new('RGBA', resized.size, 'black')
        Image.alpha_composite(background, resized).convert('RGB').save(frame, format='PNG')
    with TemporaryDirectory(prefix='shortsmaker-still-') as folder:
        output = Path(folder) / 'still.mp4'
        try:
            subprocess.run(
                [FFMPEG_BINARY, '-hide_banner', '-loglevel', 'error',
                 '-f', 'image2pipe', '-framerate', '24', '-c:v', 'png', '-i', 'pipe:0',
                 '-vf', 'tpad=stop_mode=clone:stop_duration=2', '-t', '2', '-an',
                 '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(output)],
                input=frame.getvalue(), capture_output=True, timeout=30, check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError('첫 프레임을 정지 영상으로 변환하지 못했습니다. 기존 장면 파일은 그대로입니다.') from error
        return output.read_bytes()


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

    def _approved_frame(self):
        path, digest = verified_first_frame(self.script, self.scene)
        return {'path': path, 'sha256': digest}

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
        try:
            self._approved_frame()
        except (OSError, ValueError):
            pass
        else:
            result[APPROVED_FIRST_FRAME] = {'label': '승인한 첫 프레임 · 정지 영상으로 사용', 'workspace': None}
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
        if key == APPROVED_FIRST_FRAME:
            identity = self._approved_frame()
            return identity['path'], identity
        path = self._path(key, candidate)
        identity = self.library._identity(path)
        if not is_playable_video(path):
            raise ValueError('선택한 영상을 재생할 수 없습니다. 다른 재료를 선택하세요.')
        return str(path), identity

    def read(self, key, candidate, identity):
        if key == APPROVED_FIRST_FRAME:
            frame = self._approved_frame()
            if frame != identity:
                raise ValueError('미리보기 이후 승인한 첫 프레임이 변경됐습니다. 다시 선택하세요.')
            with Path(frame['path']).open('rb') as file:
                content = file.read(MAX_FRAME_BYTES + 1)
            if len(content) > MAX_FRAME_BYTES or hashlib.sha256(content).hexdigest() != frame['sha256']:
                raise ValueError('읽는 동안 첫 프레임이 변경됐습니다. 다시 선택하세요.')
            clip = _render_still(content)
            if self._approved_frame() != frame:
                raise ValueError('변환하는 동안 첫 프레임 또는 승인이 변경됐습니다. 다시 선택하세요.')
            return clip
        path = self._path(key, candidate)
        if self.library._identity(path) != identity:
            raise ValueError('미리보기 이후 파일이 변경됐습니다. 다시 선택하세요.')
        with path.open('rb') as file:
            content = file.read(MAX_MANUAL_CLIP_BYTES + 1)
        if (len(content) > MAX_MANUAL_CLIP_BYTES or hashlib.sha256(content).hexdigest() != identity['sha256']
                or self.library._identity(self._path(key, candidate)) != identity):
            raise ValueError('읽는 동안 재료 또는 판정이 변경됐습니다. 다시 선택하세요.')
        return content
