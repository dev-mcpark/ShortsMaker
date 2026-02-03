"""
CharacterOverlay - 캐릭터 오버레이 합성 유틸리티

뉴스 스타일 영상에서 캐릭터(앵커/리포터)를 배경 영상 위에
일관되게 합성하기 위한 유틸리티입니다.

핵심 전략:
- AI가 캐릭터를 생성하지 않고, 사전 준비된 캐릭터 영상/이미지를 합성
- 이를 통해 100% 캐릭터 일관성 보장
- Safety 필터 우회 가능

지원하는 캐릭터 영상 형식:
1. 그린스크린(크로마키) 영상 - 녹색 배경 자동 제거
2. 투명 배경 영상 (WebM with alpha, MOV with ProRes 4444)
3. 일반 영상 - 배경 제거 없이 그대로 합성
"""
import os
import numpy as np
from typing import Optional, Tuple, Literal
from pathlib import Path
from PIL import Image, ImageDraw
from moviepy import (
    VideoFileClip,
    ImageClip,
    CompositeVideoClip,
    concatenate_videoclips,
    vfx
)
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings


class CharacterOverlay:
    """
    캐릭터 오버레이 합성 클래스

    배경 영상/이미지 위에 캐릭터를 일관되게 합성합니다.
    """

    # 프리셋 위치 설정
    POSITION_PRESETS = {
        "bottom_right": (0.75, 0.75),  # 오른쪽 하단 (기본)
        "bottom_left": (0.05, 0.75),
        "top_right": (0.75, 0.05),
        "top_left": (0.05, 0.05),
        "center_bottom": (0.35, 0.70),
    }

    def __init__(
        self,
        character_source: Optional[str] = None,
        position: str = "bottom_right",
        size_ratio: float = 0.25,  # 화면 대비 캐릭터 크기 비율
        corner_radius: int = 0,  # 0 = 둥근 모서리 없음 (자연스러운 합성)
        border_width: int = 0,  # 0 = 테두리 없음 (자연스러운 합성)
        border_color: Tuple[int, int, int] = (255, 255, 255),
        chroma_key_enabled: bool = True,
        chroma_key_color: str = "green",  # "green", "blue", or hex color
        chroma_key_threshold: float = 0.3,  # 크로마키 민감도 (0.0~1.0)
    ):
        """
        CharacterOverlay 초기화

        Args:
            character_source: 캐릭터 이미지/영상 경로
            position: 위치 프리셋 이름 또는 (x_ratio, y_ratio) 튜플
            size_ratio: 화면 대비 캐릭터 크기 비율 (0.0~1.0)
            corner_radius: 둥근 모서리 반지름
            border_width: 테두리 두께
            border_color: 테두리 색상 (RGB)
            chroma_key_enabled: 크로마키 배경 제거 활성화
            chroma_key_color: 크로마키 색상 ("green", "blue", 또는 hex)
            chroma_key_threshold: 크로마키 민감도 (0.0~1.0)
        """
        self.logger = get_logger(__name__)
        self.chroma_key_threshold = chroma_key_threshold

        # 기본 캐릭터 소스 설정
        if character_source is None:
            self.character_source = str(settings.character_image_path)
        else:
            self.character_source = character_source

        # 위치 설정
        if isinstance(position, str):
            self.position = self.POSITION_PRESETS.get(position, (0.75, 0.75))
        else:
            self.position = position

        self.logger.info(f"CharacterOverlay initialized: {character_source}, position={self.position}")

    def create_rounded_mask(self, size: Tuple[int, int]) -> Image.Image:
        """둥근 모서리 마스크 생성"""
        mask = Image.new('L', size, 0)
        draw = ImageDraw.Draw(mask)

        # 둥근 사각형 그리기
        draw.rounded_rectangle(
            [(0, 0), (size[0]-1, size[1]-1)],
            radius=self.corner_radius,
            fill=255
        )
        return mask

    def create_rounded_mask_array(self, size: Tuple[int, int]) -> np.ndarray:
        """둥근 모서리 마스크를 numpy 배열로 생성 (영상용)"""
        mask = self.create_rounded_mask(size)
        return np.array(mask) / 255.0  # 0~1 범위로 정규화

    def apply_chroma_key(self, frame: np.ndarray) -> np.ndarray:
        """
        프레임에서 크로마키 색상을 제거하여 알파 채널 생성

        Args:
            frame: RGB 또는 RGBA 프레임 (numpy array)

        Returns:
            RGBA 프레임 (크로마키 영역이 투명하게 처리됨)
        """
        if not self.chroma_key_enabled:
            # 크로마키 비활성화 시 그대로 반환 (알파 채널 추가)
            if frame.shape[2] == 3:
                alpha = np.ones((frame.shape[0], frame.shape[1], 1), dtype=np.uint8) * 255
                return np.concatenate([frame, alpha], axis=2)
            return frame

        # 크로마키 기준 색상 설정
        if self.chroma_key_color == "green":
            key_color = np.array([0, 255, 0])
        elif self.chroma_key_color == "blue":
            key_color = np.array([0, 0, 255])
        else:
            # Hex 색상 파싱
            try:
                hex_color = self.chroma_key_color.lstrip('#')
                key_color = np.array([int(hex_color[i:i+2], 16) for i in (0, 2, 4)])
            except:
                key_color = np.array([0, 255, 0])  # 기본값: 녹색

        # RGB만 사용
        rgb = frame[:, :, :3].astype(np.float32)

        # 크로마키 색상과의 거리 계산 (정규화된 유클리드 거리)
        diff = np.sqrt(np.sum((rgb - key_color) ** 2, axis=2)) / 441.67  # max distance = sqrt(255^2 * 3)

        # 임계값 기반 알파 마스크 생성
        threshold = self.chroma_key_threshold
        alpha = np.clip((diff - threshold * 0.5) / (threshold * 0.5), 0, 1)
        alpha = (alpha * 255).astype(np.uint8)

        # RGBA 이미지 생성
        if frame.shape[2] == 4:
            # 기존 알파와 결합
            alpha = np.minimum(alpha, frame[:, :, 3])

        rgba = np.concatenate([frame[:, :, :3], alpha[:, :, np.newaxis]], axis=2)
        return rgba

    def apply_mask_to_frame(self, frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """
        프레임에 마스크 적용 (둥근 모서리 등)

        Args:
            frame: RGBA 프레임
            mask: 0~1 범위의 마스크

        Returns:
            마스크가 적용된 RGBA 프레임
        """
        if frame.shape[2] == 3:
            # RGB → RGBA 변환
            alpha = np.ones((frame.shape[0], frame.shape[1], 1), dtype=np.uint8) * 255
            frame = np.concatenate([frame, alpha], axis=2)

        # 마스크 크기 조정
        if mask.shape[:2] != frame.shape[:2]:
            from PIL import Image
            mask_img = Image.fromarray((mask * 255).astype(np.uint8))
            mask_img = mask_img.resize((frame.shape[1], frame.shape[0]), Image.Resampling.LANCZOS)
            mask = np.array(mask_img) / 255.0

        # 알파 채널에 마스크 적용
        frame[:, :, 3] = (frame[:, :, 3].astype(np.float32) * mask).astype(np.uint8)
        return frame

    def create_border_frame(self, size: Tuple[int, int]) -> Image.Image:
        """테두리 프레임 이미지 생성"""
        # 투명 배경 + 테두리
        frame = Image.new('RGBA', size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(frame)

        # 테두리 그리기
        for i in range(self.border_width):
            draw.rounded_rectangle(
                [(i, i), (size[0]-1-i, size[1]-1-i)],
                radius=self.corner_radius,
                outline=(*self.border_color, 255)
            )
        return frame

    def prepare_character_image(
        self,
        target_size: Tuple[int, int]
    ) -> Optional[Image.Image]:
        """
        캐릭터 이미지 준비 (크기 조정 + 마스크 적용)

        Args:
            target_size: (width, height) 목표 크기

        Returns:
            준비된 캐릭터 이미지 (RGBA)
        """
        if not os.path.exists(self.character_source):
            self.logger.warning(f"Character source not found: {self.character_source}")
            return None

        try:
            # 이미지 로드
            char_img = Image.open(self.character_source).convert('RGBA')

            # 크기 조정 (비율 유지)
            char_img.thumbnail(target_size, Image.Resampling.LANCZOS)

            # 정확한 크기로 중앙 배치
            result = Image.new('RGBA', target_size, (0, 0, 0, 0))
            offset_x = (target_size[0] - char_img.width) // 2
            offset_y = (target_size[1] - char_img.height) // 2
            result.paste(char_img, (offset_x, offset_y), char_img)

            # 마스크 적용
            mask = self.create_rounded_mask(target_size)
            result.putalpha(mask)

            # 테두리 추가
            border = self.create_border_frame(target_size)
            result = Image.alpha_composite(result, border)

            return result

        except Exception as e:
            self.logger.error(f"Failed to prepare character image: {e}")
            return None

    def composite_on_image(
        self,
        background_path: str,
        output_path: str
    ) -> str:
        """
        배경 이미지에 캐릭터 합성

        Args:
            background_path: 배경 이미지 경로
            output_path: 출력 이미지 경로

        Returns:
            출력 파일 경로
        """
        self.logger.info(f"Compositing character on image: {background_path}")

        try:
            # 배경 로드
            bg = Image.open(background_path).convert('RGBA')
            bg_width, bg_height = bg.size

            # 캐릭터 크기 계산
            char_width = int(bg_width * self.size_ratio)
            char_height = int(bg_height * self.size_ratio)

            # 캐릭터 이미지 준비
            char_img = self.prepare_character_image((char_width, char_height))

            if char_img is None:
                self.logger.warning("No character image, saving background only")
                bg.save(output_path)
                return output_path

            # 위치 계산
            pos_x = int(bg_width * self.position[0])
            pos_y = int(bg_height * self.position[1])

            # 합성
            bg.paste(char_img, (pos_x, pos_y), char_img)
            bg.save(output_path)

            self.logger.info(f"Character composited: {output_path}")
            return output_path

        except Exception as e:
            self.logger.error(f"Image compositing failed: {e}")
            return background_path

    def composite_on_video(
        self,
        background_video_path: str,
        output_path: str,
        character_video_path: Optional[str] = None
    ) -> str:
        """
        배경 영상에 캐릭터 합성

        캐릭터 영상이 제공된 경우:
        1. 크로마키(그린스크린) 배경 제거
        2. 둥근 모서리 마스크 적용
        3. 테두리 프레임 추가
        4. 배경 영상과 합성

        Args:
            background_video_path: 배경 영상 경로
            output_path: 출력 영상 경로
            character_video_path: 캐릭터 영상 경로 (없으면 이미지 사용)

        Returns:
            출력 파일 경로
        """
        self.logger.info(f"Compositing character on video: {background_video_path}")
        if character_video_path:
            self.logger.info(f"  Using character video: {character_video_path}")

        bg_clip = None
        char_clip = None
        border_clip = None
        final_clip = None

        try:
            # 배경 영상 로드
            bg_clip = VideoFileClip(background_video_path)
            duration = bg_clip.duration
            bg_width, bg_height = bg_clip.size

            # 캐릭터 크기 계산
            char_width = int(bg_width * self.size_ratio)
            char_height = int(bg_height * self.size_ratio)

            # 위치 계산
            pos_x = int(bg_width * self.position[0])
            pos_y = int(bg_height * self.position[1])

            # 둥근 모서리 마스크 생성 (corner_radius > 0일 때만)
            rounded_mask = None
            if self.corner_radius > 0:
                rounded_mask = self.create_rounded_mask_array((char_width, char_height))

            # 캐릭터 클립 준비
            if character_video_path and os.path.exists(character_video_path):
                # 캐릭터 영상 사용
                self.logger.info(f"  Loading character video clip: {character_video_path}")
                char_clip = VideoFileClip(character_video_path)

                # 크기 조정
                char_clip = char_clip.resized((char_width, char_height))

                # 영상 길이 맞추기 (루프)
                if char_clip.duration < duration:
                    loops_needed = int(duration / char_clip.duration) + 1
                    self.logger.info(f"  Looping character video {loops_needed} times")
                    char_clip = concatenate_videoclips([char_clip] * loops_needed)
                char_clip = char_clip.subclipped(0, duration)

                # 크로마키 처리 함수 (transform은 get_frame, t 두 인자를 전달)
                def process_frame(get_frame, t):
                    frame = get_frame(t)
                    # 1. 크로마키 적용 (배경 제거) - 항상 적용
                    rgba_frame = self.apply_chroma_key(frame)
                    # 2. 둥근 모서리 마스크 적용 (corner_radius > 0일 때만)
                    if rounded_mask is not None:
                        rgba_frame = self.apply_mask_to_frame(rgba_frame, rounded_mask)
                    return rgba_frame

                # 프레임별 처리 적용
                char_clip = char_clip.transform(process_frame)
                self.logger.info(f"  Applied chroma key (natural compositing, no border/corner)")

            else:
                # 캐릭터 이미지 사용 (정지 이미지)
                char_img = self.prepare_character_image((char_width, char_height))

                if char_img is None:
                    self.logger.warning("No character source, saving background only")
                    bg_clip.write_videofile(output_path, codec="libx264", audio=False, logger=None)
                    return output_path

                # PIL Image -> numpy array for MoviePy
                char_array = np.array(char_img)
                char_clip = ImageClip(char_array, duration=duration)

            # 캐릭터 위치 설정
            char_clip = char_clip.with_position((pos_x, pos_y))

            # 테두리 사용 여부 확인 (border_width가 0보다 크면 테두리 추가)
            if self.border_width > 0:
                # 테두리 프레임 생성 (ImageClip으로)
                border_img = self.create_border_frame((char_width, char_height))
                border_array = np.array(border_img)
                border_clip = ImageClip(border_array, duration=duration)
                border_clip = border_clip.with_position((pos_x, pos_y))
                # 합성 (배경 → 캐릭터 → 테두리)
                final_clip = CompositeVideoClip([bg_clip, char_clip, border_clip])
                self.logger.info(f"  Added border frame (width={self.border_width})")
            else:
                # 테두리 없이 합성 (배경 → 캐릭터만)
                final_clip = CompositeVideoClip([bg_clip, char_clip])
                self.logger.info(f"  No border frame (natural compositing)")
            self.logger.info(f"  Rendering final composite video...")

            final_clip.write_videofile(
                output_path,
                codec="libx264",
                audio=False,
                fps=bg_clip.fps or 24,
                logger=None
            )

            self.logger.info(f"✅ Character composited on video: {output_path}")
            return output_path

        except Exception as e:
            self.logger.error(f"Video compositing failed: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return background_video_path

        finally:
            # 리소스 정리
            if bg_clip:
                bg_clip.close()
            if char_clip:
                char_clip.close()
            if border_clip:
                border_clip.close()
            if final_clip:
                final_clip.close()

    def process_scene_clip(
        self,
        clip_path: str,
        scene_number: int,
        is_video: bool = True
    ) -> str:
        """
        단일 씬 클립에 캐릭터 합성

        Args:
            clip_path: 입력 클립 경로
            scene_number: 씬 번호
            is_video: True면 영상, False면 이미지

        Returns:
            합성된 클립 경로
        """
        # 출력 경로 생성
        ext = ".mp4" if is_video else ".png"
        output_path = clip_path.replace(ext, f"_with_char{ext}")

        if is_video:
            return self.composite_on_video(clip_path, output_path)
        else:
            return self.composite_on_image(clip_path, output_path)


class CharacterOverlayConfig:
    """캐릭터 오버레이 설정"""

    def __init__(self):
        self.enabled: bool = False
        # 캐릭터 이미지: 설정에 정의된 경로에 파일이 있으면 사용, 없으면 None
        self.character_image: Optional[str] = (
            str(settings.character_image_path)
            if settings.character_image_path.exists()
            else None
        )
        # 캐릭터 영상: 설정에 정의된 경로에 파일이 있으면 사용, 없으면 None
        self.character_video: Optional[str] = (
            str(settings.character_video_path)
            if settings.character_video_path.exists()
            else None
        )
        self.position: str = "bottom_right"
        self.size_ratio: float = 0.25
        self.corner_radius: int = 0  # 0 = 둥근 모서리 없음 (자연스러운 합성)
        self.border_width: int = 0  # 0 = 테두리 없음 (자연스러운 합성)
        self.border_color: Tuple[int, int, int] = (255, 255, 255)

        # 크로마키 설정
        self.chroma_key_enabled: bool = True
        self.chroma_key_color: str = "green"  # "green", "blue", or hex color
        self.chroma_key_threshold: float = 0.3

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "character_image": self.character_image,
            "character_video": self.character_video,
            "position": self.position,
            "size_ratio": self.size_ratio,
            "corner_radius": self.corner_radius,
            "border_width": self.border_width,
            "border_color": self.border_color,
            "chroma_key_enabled": self.chroma_key_enabled,
            "chroma_key_color": self.chroma_key_color,
            "chroma_key_threshold": self.chroma_key_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CharacterOverlayConfig":
        config = cls()
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config

    def create_overlay(self) -> CharacterOverlay:
        """설정으로 CharacterOverlay 인스턴스 생성"""
        return CharacterOverlay(
            character_source=self.character_image,
            position=self.position,
            size_ratio=self.size_ratio,
            corner_radius=self.corner_radius,
            border_width=self.border_width,
            border_color=self.border_color,
            chroma_key_enabled=self.chroma_key_enabled,
            chroma_key_color=self.chroma_key_color,
            chroma_key_threshold=self.chroma_key_threshold,
        )
