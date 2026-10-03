import os
import asyncio
import subprocess
import time
import glob
from contextlib import suppress
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
from moviepy import VideoFileClip, TextClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip, ImageClip, CompositeAudioClip
from moviepy.config import FFMPEG_BINARY
import moviepy.video.fx as vfx
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut
from openai import APIConnectionError, AsyncOpenAI, InternalServerError
from PIL import Image, ImageDraw, ImageFont
from shorts_maker.utils.bgm_manager import BGMManager
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings
from shorts_maker.utils.paid_gate import require_paid_production_enabled

# [CRITICAL FIX] Manually set ImageMagick path for macOS Homebrew install
if os.path.exists("/opt/homebrew/bin/magick"):
    os.environ["IMAGEMAGICK_BINARY"] = "/opt/homebrew/bin/magick"


class VideoEditor:
    def __init__(
        self,
        tts_voice: str = "alloy",
        bgm_volume: float = 0.2,
        subtitle_color: str = "#F6F8FA",
        subtitle_size: int = 54,
        subtitle_y_position: int = 1300,
        bgm_mood: Optional[str] = None,
        bgm_track: Optional[str] = None,
        subtitle_style: str = "soft",
    ):
        """
        VideoEditor 초기화

        Args:
            tts_voice: TTS 음성 선택 ('alloy', 'nova', 'onyx', 'shimmer', 'echo')
            bgm_volume: BGM 볼륨 (0.0 ~ 1.0)
            subtitle_color: 자막 색상 (hex color)
            subtitle_size: 자막 폰트 크기 (40-80)
            subtitle_y_position: 자막 Y 위치 (1000-1600)
            subtitle_style: soft 기본 자막 또는 card 로컬 비교용 자막
        """
        self.logger = get_logger(__name__)
        self.bgm_manager = BGMManager()

        self.client = None  # Local edits with prepared narration need no API key.
        self._temp_files: List[str] = []  # 임시 파일 추적

        # User-configurable options
        self.tts_voice = tts_voice
        self.bgm_volume = bgm_volume
        self.bgm_mood = bgm_mood
        self.bgm_track = bgm_track
        self.selected_bgm_path: Optional[str] = None
        self.subtitle_color = subtitle_color
        self.subtitle_size = subtitle_size
        self.subtitle_y_position = subtitle_y_position
        if subtitle_style not in {"soft", "card"}:
            raise ValueError("subtitle_style은 soft 또는 card여야 합니다.")
        self.subtitle_style = subtitle_style

        self.voice_map = {
            'suspense': 'onyx',
            'sci-fi': 'onyx',
            'mysterious': 'onyx',
            'corporate': 'alloy',
            'luxury': 'alloy',
            'cinematic': 'alloy',
            'emotional': 'nova',
            'calm': 'nova',
            'energetic': 'shimmer',
            'upbeat': 'shimmer'
        }

    def _get_voice_for_mood(self, mood: str) -> str:
        # If user explicitly set a voice, use it; otherwise fall back to mood mapping
        if self.tts_voice and self.tts_voice != "auto":
            return self.tts_voice
        return self.voice_map.get(mood.lower(), 'alloy')

    def preflight_music(self, script) -> Optional[str]:
        """Resolve documented music before narration or visual API calls."""
        if getattr(self, "bgm_volume", 0) <= 0:
            self.selected_bgm_path = None
            return None
        track = getattr(self, "bgm_track", None)
        mood = (getattr(script, "mood", "cinematic") if self.bgm_mood in (None, "", "auto")
                else self.bgm_mood)
        self.selected_bgm_path = (self.bgm_manager.get_track_path(track) if track
                                  else self.bgm_manager.get_bgm_path(mood))
        if not self.selected_bgm_path:
            raise ValueError(
                f"'{track or mood}'의 사용 권한이 기록된 BGM이 없습니다. "
                "bgm/*.mp3.license.json을 확인하거나 BGM 음량을 0으로 설정하세요."
            )
        return self.selected_bgm_path

    def _track_temp_file(self, path: str):
        """임시 파일 추적에 추가"""
        if path and path not in self._temp_files:
            self._temp_files.append(path)

    def cleanup_temp_files(self, keep_output: bool = True):
        """
        임시 파일 정리

        Args:
            keep_output: True면 최종 출력 파일은 유지
        """
        cleaned = 0
        for path in self._temp_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
                    cleaned += 1
            except OSError as e:
                self.logger.warning(f"임시 파일 삭제 실패: {path} - {e}")

        self._temp_files.clear()
        self.logger.info(f"🧹 임시 파일 {cleaned}개 정리 완료")

    def _cleanup_clips(self, clips: List):
        """MoviePy 클립 리소스 정리"""
        for clip in clips:
            try:
                if hasattr(clip, 'close'):
                    clip.close()
            except Exception:
                pass

    def cleanup_old_temp_files(self, max_age_hours: int = 24):
        """오래된 임시 파일 정리 (24시간 이상)"""
        temp_dir = str(settings.temp_dir)
        if not os.path.exists(temp_dir):
            return

        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        cleaned = 0

        for pattern in ["*.mp3", "*.png", "*.mp4"]:
            for filepath in glob.glob(os.path.join(temp_dir, pattern)):
                try:
                    file_age = current_time - os.path.getmtime(filepath)
                    if file_age > max_age_seconds:
                        os.remove(filepath)
                        cleaned += 1
                except OSError:
                    pass

        if cleaned > 0:
            self.logger.info(f"🧹 오래된 임시 파일 {cleaned}개 정리")

    async def prepare_narration(self, script) -> List[str]:
        """Generate narration once, before the costly visual generation step."""
        self.preflight_music(script)
        audio_paths = []
        voice = self._get_voice_for_mood(getattr(script, 'mood', 'cinematic'))
        try:
            for index, scene in enumerate(script.scenes):
                path = await self._generate_tts(scene.script_text, index, voice)
                audio_paths.append(path)
            self.validate_narration(audio_paths)
            return audio_paths
        except Exception:
            self.cleanup_temp_files()
            raise

    @staticmethod
    def validate_narration(audio_paths: List[str]) -> None:
        total_duration = 0.0
        for path in audio_paths:
            audio = AudioFileClip(path)
            try:
                total_duration += audio.duration + 0.5
            finally:
                audio.close()
        if total_duration > settings.max_shorts_duration:
            raise ValueError(
                f"내레이션이 {total_duration:.1f}초로 너무 깁니다. "
                f"{settings.max_shorts_duration:.1f}초 이하가 되도록 스크립트를 줄여주세요."
            )

    async def compose_video(
        self,
        media_paths: List[str],
        script,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        audio_paths: Optional[List[str]] = None,
    ) -> str:
        if len(media_paths) != len(script.scenes):
            raise ValueError("씬 수와 클립 수가 일치하지 않습니다.")
        if audio_paths is not None and len(audio_paths) != len(script.scenes):
            raise ValueError("씬 수와 내레이션 수가 일치하지 않습니다.")
        bgm_path = self.preflight_music(script)
        # 시작 시 오래된 임시 파일 정리
        self.cleanup_old_temp_files()

        processed_clips = []
        final_video = None
        try:
            voice_name = self._get_voice_for_mood(getattr(script, 'mood', 'cinematic'))

            for i, (path, scene) in enumerate(zip(media_paths, script.scenes)):
                self.logger.info(f"Editing scene {scene.scene_number}...")
                if progress_callback:
                    progress_callback(5 + 65 * i / len(script.scenes), f"씬 {i + 1}/{len(script.scenes)} TTS 생성 중...")

                # 1. TTS
                audio_path = audio_paths[i] if audio_paths is not None else await self._generate_tts(scene.script_text, i, voice_name)
                if is_cancelled and is_cancelled():
                    raise RuntimeError("사용자에 의해 취소됨")
                audio = AudioFileClip(audio_path)
                duration = audio.duration + 0.5
            
                # 2. Visual Clip (Adaptive to file type)
                clip = self._create_visual_clip(path, duration)
                clip = clip.with_audio(audio)
            
                # [FIX] Character is now integrated into the video via Veo.
                # No need for manual overlay anymore.
                layers = [clip]

                # 3. Subtitle (Flattened structure)
                subtitle_clips = self._create_subtitle_clips(scene.script_text, duration)
                if subtitle_clips:
                    layers.extend(subtitle_clips)

                # [FIX] Explicit duration for composite clip
                final_scene_clip = CompositeVideoClip(
                    layers, size=(settings.video_width, settings.video_height),
                ).with_duration(duration)
            
                processed_clips.append(final_scene_clip)
                if progress_callback:
                    progress_callback(5 + 65 * (i + 1) / len(script.scenes), f"씬 {i + 1}/{len(script.scenes)} 편집 완료")

            if not processed_clips:
                self.logger.warning("No clips to compose.")
                return ""

            self.logger.info("Concatenating all clips...")
            final_video = concatenate_videoclips(processed_clips, method="compose")
        
            # [CRITICAL] Enforce 59s Limit for Shorts
            # If video is longer than 59s, speed it up to fit exactly into 58.5s (safety margin)
            MAX_SHORTS_DURATION = settings.max_shorts_duration
            if final_video.duration > MAX_SHORTS_DURATION:
                self.logger.warning(f"⚠️ Video duration ({final_video.duration}s) exceeds Shorts limit.")
                self.logger.info("⚡ Speeding up video to fit 58.5s...")
            
                # Calculate speed factor (e.g., 65s / 58.5s = 1.11x speed)
                target_duration = settings.target_duration
                speed_factor = final_video.duration / target_duration
            
                # Apply speed effect to both video and audio
                final_video = final_video.with_effects([vfx.MultiplySpeed(speed_factor)])
        
            # 4. BGM
            if progress_callback:
                progress_callback(75, "BGM 합성 중...")
            if bgm_path:
                bgm = AudioFileClip(bgm_path)
                if bgm.duration < final_video.duration:
                    from moviepy.audio.fx import AudioLoop
                    bgm = bgm.with_effects([AudioLoop(duration=final_video.duration)])
                else:
                    bgm = bgm.subclipped(0, final_video.duration)
                fade = min(0.8, final_video.duration / 4)
                bgm = bgm.with_volume_scaled(self.bgm_volume).with_effects(
                    [AudioFadeIn(min(0.2, fade)), AudioFadeOut(fade)]
                )
                final_video = final_video.with_audio(CompositeAudioClip([final_video.audio, bgm]))

            settings.output_dir.mkdir(parents=True, exist_ok=True)
            output_filename = str(settings.output_dir / f"final_shorts_{time.time_ns()}.mp4")
            if is_cancelled and is_cancelled():
                raise RuntimeError("사용자에 의해 취소됨")
            if progress_callback:
                progress_callback(85, "최종 렌더링 중...")
            await asyncio.to_thread(
                final_video.write_videofile,
                output_filename,
                fps=24,
                codec="libx264",
                audio_codec="aac",
            )
            await asyncio.to_thread(self._normalize_output_audio, output_filename)
            return output_filename
        finally:
            self._cleanup_clips(processed_clips)
            if final_video is not None:
                with suppress(Exception):
                    final_video.close()
            self.cleanup_temp_files()

    @staticmethod
    def _normalize_output_audio(path: str) -> None:
        output = Path(path)
        normalized = output.with_name(f"{output.stem}.normalized.mp4")
        try:
            result = subprocess.run([
                FFMPEG_BINARY, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(output), "-map", "0:v:0", "-map", "0:a:0",
                "-c:v", "copy", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a", "aac", "-b:a", "192k", "-shortest", str(normalized),
            ], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f"오디오 음량 보정 실패: {result.stderr.strip()[-500:]}")
            os.replace(normalized, output)
        finally:
            normalized.unlink(missing_ok=True)

    def _create_visual_clip(self, path, duration):
        clip = None
        try:
            extension = os.path.splitext(path)[1].lower()
            # IMAGE MODE
            if extension in {'.png', '.jpg', '.jpeg'}:
                clip = ImageClip(path).with_duration(duration)
                clip = clip.resized(height=1920)
                if clip.w < 1080: clip = clip.resized(width=1080)
                if clip.w > 1080: clip = clip.cropped(x_center=clip.w / 2, width=1080)
                if clip.h > 1920: clip = clip.cropped(y_center=clip.h / 2, height=1920)
                clip = clip.with_position('center')
                return clip

            # VIDEO MODE
            elif extension in {'.mp4', '.mov', '.webm'}:
                clip = VideoFileClip(path)

                # Loop if too short (MoviePy v2 fix)
                if clip.duration < duration:
                    clip = clip.with_effects([vfx.Loop(duration=duration)])
                else:
                    clip = clip.with_duration(duration)

                # Resize/Crop to 9:16
                clip = clip.resized(height=1920)
                if clip.w < 1080:
                    clip = clip.resized(width=1080)
                if clip.w > 1080:
                    clip = clip.cropped(x1=clip.w/2 - 540, width=1080)
                if clip.h > 1920:
                    clip = clip.cropped(y_center=clip.h / 2, height=1920)

                return clip.with_position('center')

            raise ValueError(f"지원하지 않는 미디어 형식: {extension or path}")

        except Exception as e:
            self.logger.error(f"Visual clip creation error: {e}")
            # 리소스 정리: 오류 발생 시 clip 닫기
            if clip is not None:
                try:
                    clip.close()
                except Exception:
                    pass
            raise

    @staticmethod
    def _wrap_subtitle(text: str, font_name: str, font_size: int, max_width: int = 860) -> str:
        """Keep Korean words and their punctuation together within the caption width."""
        font = ImageFont.truetype(font_name, font_size)
        lines = []
        for paragraph in text.splitlines():
            paragraph_lines = []
            line = ""
            for word in paragraph.split():
                candidate = f"{line} {word}" if line else word
                if line and font.getlength(candidate) > max_width:
                    paragraph_lines.append(line)
                    line = word
                else:
                    line = candidate
            paragraph_lines.append(line)
            # ponytail: move at most two words; inspect complex wraps in playback.
            if len(paragraph_lines) > 1:
                previous = paragraph_lines[-2].split()
                last = paragraph_lines[-1]
                moved = 0
                while (len(previous) >= 3 and moved < 2
                       and font.getlength(last) < font.getlength(" ".join(previous))
                       * (0.6 if moved == 0 else 0.4)):
                    balanced = f"{previous[-1]} {last}"
                    if font.getlength(balanced) > max_width:
                        break
                    last = balanced
                    previous.pop()
                    moved += 1
                paragraph_lines[-2] = " ".join(previous)
                paragraph_lines[-1] = last
            lines.extend(paragraph_lines)
        return "\n".join(lines)

    @staticmethod
    def _caption_segments(text: str, duration: float) -> List[tuple[str, float, float]]:
        """Keep one short phrase on screen at a time."""
        if duration <= 0:
            return []
        chunks = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}" if current else word
            if current and len(candidate) > 26:
                chunks.append(current)
                current = word
            else:
                current = candidate
            if current.endswith((".", ",", "?", "!", "。", "？", "！")):
                chunks.append(current)
                current = ""
        if current:
            chunks.append(current)
        if not chunks:
            return []

        index = 1
        while index < len(chunks):
            if (len(chunks[index].split()) == 1 and len(chunks[index]) <= 7
                    and not chunks[index - 1].endswith((".", ",", "?", "!", "。", "？", "！"))):
                head, separator, tail = chunks[index - 1].rpartition(" ")
                if separator and " " in head:
                    chunks[index - 1] = head
                    chunks[index] = f"{tail} {chunks[index]}"
                else:
                    chunks[index - 1] += f" {chunks.pop(index)}"
                    continue
            index += 1

        # ponytail: character-weighted timing is a draft; use word timestamps for final sync.
        spoken_duration = max(duration - 0.5, duration * 0.8)
        weights = [len(chunk.replace(" ", "")) for chunk in chunks]
        total = sum(weights)
        elapsed = 0
        segments = []
        for index, (chunk, weight) in enumerate(zip(chunks, weights)):
            start = spoken_duration * elapsed / total
            elapsed += weight
            end = duration if index == len(chunks) - 1 else spoken_duration * elapsed / total
            segments.append((chunk, start, end - start))
        return segments

    def _create_subtitle_clips(self, text, duration) -> List:
        """Returns a list of clips for clean subtitle rendering using user-configurable settings."""
        def place(clip, start, length):
            margin = 80
            if clip.h > settings.video_height - 2 * margin:
                raise ValueError("자막이 화면 높이를 초과합니다. 문장을 줄여주세요.")
            y = min(max(margin, self.subtitle_y_position), settings.video_height - clip.h - margin)
            return clip.with_position(('center', y)).with_start(start).with_duration(length)

        segments = self._caption_segments(text, duration)
        if not segments:
            return []

        def render(font_name, font_size, color, stroke_width):
            clips = []
            try:
                for phrase, start, length in segments:
                    card = getattr(self, "subtitle_style", "soft") == "card"
                    clip = TextClip(
                        text=self._wrap_subtitle(
                            phrase, font_name, font_size, 820 if card else 860,
                        ),
                        font_size=font_size,
                        color=color,
                        font=font_name,
                        method='caption',
                        size=(844 if card else 900, None),
                        text_align='left' if card else 'center',
                        horizontal_align='left' if card else 'center',
                        stroke_color='#102536',
                        stroke_width=stroke_width,
                    )
                    if card:
                        height = clip.h + 44
                        panel = Image.new("RGBA", (940, height), (0, 0, 0, 0))
                        draw = ImageDraw.Draw(panel)
                        draw.rounded_rectangle(
                            (0, 0, 939, height - 1), radius=24,
                            fill=(10, 29, 43, 204), outline=(128, 214, 201, 95), width=2,
                        )
                        draw.rounded_rectangle(
                            (20, 20, 26, height - 21), radius=3,
                            fill=(128, 214, 201, 230),
                        )
                        clip = CompositeVideoClip(
                            [ImageClip(np.asarray(panel)), clip.with_position((48, 22))],
                            size=(940, height),
                        )
                    clips.append(place(clip, start, length))
                return clips
            except Exception:
                self._cleanup_clips(clips)
                raise

        try:
            return render('/System/Library/Fonts/AppleSDGothicNeo.ttc', self.subtitle_size, self.subtitle_color, 2)
        except Exception as e:
            self.logger.error(f"❌ Subtitle error: {e}")
            try:
                return render('Arial', 50, 'white', 1)
            except Exception as fallback_error:
                self.logger.error(f"자막 폴백도 실패: {fallback_error}")
                raise

    async def _generate_tts(self, text: str, scene_idx: int, voice: str) -> str:
        require_paid_production_enabled()
        if self.client is None:
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required to generate narration.")
            self.client = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0)
        settings.temp_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(settings.temp_dir / f"audio_{scene_idx}_{time.time_ns()}.mp3")
        self._track_temp_file(output_path)
        self.logger.info(f"Generating OpenAI TTS ({voice}) for scene {scene_idx}...")

        for attempt in range(2):
            try:
                response = await self.client.audio.speech.create(
                    model="tts-1",
                    voice=voice,
                    input=text
                )
                await asyncio.to_thread(response.stream_to_file, output_path)
                return output_path
            except (APIConnectionError, InternalServerError) as error:
                if attempt:
                    raise
                self.logger.warning("OpenAI TTS transient failure; retrying once: %s", error)
                await asyncio.sleep(2)
