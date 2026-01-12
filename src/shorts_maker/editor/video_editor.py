import os
import asyncio
from typing import List
from moviepy import VideoFileClip, TextClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip, ImageClip, CompositeAudioClip
import moviepy.video.fx as vfx # Import effects module
from moviepy.video.fx import FadeIn
from gtts import gTTS
from openai import AsyncOpenAI
from shorts_maker.utils.bgm_manager import BGMManager

class VideoEditor:
    def __init__(self):
        self.bgm_manager = BGMManager()
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.voice_map = {
            'mysterious': 'onyx', 'dramatic': 'onyx', 'dark': 'onyx',
            'happy': 'nova', 'playful': 'nova', 'upbeat': 'nova',
            'cinematic': 'alloy'
        }

    def _get_voice_for_mood(self, mood: str) -> str:
        return self.voice_map.get(mood.lower(), 'alloy')

    async def compose_video(self, media_paths: List[str], script) -> str:
        processed_clips = []
        voice_name = self._get_voice_for_mood(getattr(script, 'mood', 'cinematic'))
        
        for i, (path, scene) in enumerate(zip(media_paths, script.scenes)):
            print(f"Editing scene {scene.scene_number}...")
            
            # 1. TTS
            audio_path = await self._generate_tts(scene.script_text, i, voice_name)
            await asyncio.sleep(2)
            audio = AudioFileClip(audio_path)
            duration = audio.duration + 0.5
            
            # 2. Visual Clip (Adaptive to file type)
            clip = self._create_visual_clip(path, duration)
            clip = clip.with_audio(audio)
            
            # 3. Subtitle
            subtitle_clip = self._create_subtitle_clip(scene.script_text, duration)
            final_scene_clip = CompositeVideoClip([clip, subtitle_clip])
            
            # Fade In
            if i > 0:
                final_scene_clip = final_scene_clip.with_effects([FadeIn(duration=0.5)])
            
            processed_clips.append(final_scene_clip)

        if not processed_clips:
            print("No clips to compose.")
            return ""

        print("Concatenating all clips...")
        final_video = concatenate_videoclips(processed_clips, method="compose")
        
        # 4. BGM
        try:
            mood = getattr(script, 'mood', 'cinematic')
            bgm_path = self.bgm_manager.get_bgm_path(mood)
            if bgm_path and os.path.exists(bgm_path):
                bgm = AudioFileClip(bgm_path)
                # Loop BGM if needed using new syntax
                if bgm.duration < final_video.duration:
                    # AudioFileClip might not support with_effects(Loop) same way?
                    # Actually audio looping in moviepy is mostly done via audio_loop from afx
                    from moviepy.audio.fx import AudioLoop
                    bgm = bgm.with_effects([AudioLoop(duration=final_video.duration)])
                else:
                    bgm = bgm.subclipped(0, final_video.duration)
                
                bgm = bgm.with_volume_scaled(0.15)
                final_video = final_video.with_audio(CompositeAudioClip([final_video.audio, bgm]))
        except Exception as e:
            print(f"Error adding BGM: {e}")

        output_filename = f"outputs/final_shorts_{int(asyncio.get_event_loop().time())}.mp4"
        final_video.write_videofile(output_filename, fps=24, codec="libx264", audio_codec="aac")
        return output_filename

    def _create_visual_clip(self, path, duration):
        try:
            # IMAGE MODE
            if path.endswith('.png') or path.endswith('.jpg'):
                clip = ImageClip(path).with_duration(duration)
                clip = clip.resized(height=1920)
                if clip.w < 1080: clip = clip.resized(width=1080)
                clip = clip.with_position('center')
                return clip
                
            # VIDEO MODE
            elif path.endswith('.mp4'):
                clip = VideoFileClip(path)
                # Loop if too short (MoviePy v2 fix)
                if clip.duration < duration:
                    # clip = clip.loop(duration=duration) # OLD
                    clip = clip.with_effects([vfx.Loop(duration=duration)]) # NEW
                else:
                    clip = clip.with_duration(duration)
                
                # Resize/Crop to 9:16
                clip = clip.resized(height=1920)
                if clip.w > 1080:
                    clip = clip.cropped(x1=clip.w/2 - 540, width=1080)
                
                return clip.with_position('center')
                
        except Exception as e:
            print(f"Visual clip creation error: {e}")
            from moviepy import ColorClip
            return ColorClip(size=(1080, 1920), color=(0,0,0), duration=duration)

    def _create_subtitle_clip(self, text, duration):
        try:
            txt_clip = TextClip(
                text=text,
                font_size=60, 
                color='white', 
                font='AppleGothic', 
                method='caption', 
                size=(850, None), 
                text_align='center',
                stroke_color='black',
                stroke_width=4
            ).with_duration(duration).with_position(('center', 1440))
            return txt_clip
        except Exception as e:
            print(f"Subtitle creation error: {e}")
            from moviepy import ColorClip
            return ColorClip(size=(10, 10), color=(0,0,0,0), duration=duration)

    async def _generate_tts(self, text: str, scene_idx: int, voice: str) -> str:
        output_path = f"temp/audio_{scene_idx}_{int(asyncio.get_event_loop().time())}.mp3"
        print(f"Generating OpenAI TTS ({voice}) for scene {scene_idx}...")
        
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                response = await self.client.audio.speech.create(
                    model="tts-1",
                    voice=voice,
                    input=text
                )
                response.stream_to_file(output_path)
                return output_path
            except Exception as e:
                print(f"⚠️ OpenAI TTS Attempt {attempt+1} Failed ({e}).")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    print("Switching to gTTS fallback...")
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self._run_gtts, text, output_path)
                    return output_path
        
        return output_path

    def _run_gtts(self, text, output_path):
        tts = gTTS(text=text, lang='ko', slow=False)
        tts.save(output_path)