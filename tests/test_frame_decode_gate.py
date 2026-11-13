"""Header-readable but undecodable first frames stop before review or spend."""
import hashlib
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from types import SimpleNamespace

from PIL import Image
from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.services.visual_review import inspect_frame, approve_first_frame, review_path
from shorts_maker.utils.config import settings
from shorts_maker.utils.media_validation import inspect_frame_bytes
from test_gui_creation_flows import script


def jpeg_bytes():
    output=BytesIO();Image.new('RGB',(540,960),'navy').save(output,format='JPEG')
    return output.getvalue()


class FrameDecodeGateTests(TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.frame=self.root/'broken.jpg';self.frame.write_bytes(jpeg_bytes()[:-100])
        p=patch.object(settings,'output_dir',self.root);p.start();self.addCleanup(p.stop)

    def test_header_readable_truncated_jpeg_cannot_be_previewed_or_approved(self):
        with Image.open(self.frame) as image:image.verify()
        with self.assertRaises(ValueError):inspect_frame(str(self.frame))
        story=script()
        with self.assertRaises(ValueError):
            approve_first_frame(story,story.scenes[0],str(self.frame),['bus'],['extra bus'],
                                'fixture',hashlib.sha256(self.frame.read_bytes()).hexdigest())
        self.assertFalse(review_path(story,story.scenes[0]).exists())

    def test_sdk_boundary_rejects_same_captured_bad_bytes_before_reservation(self):
        generator=object.__new__(VideoGenerator)
        generator._check_visual_cap=Mock();generator.client=Mock();generator.logger=Mock()
        generator.client.models.generate_videos.side_effect=RuntimeError('provider boundary reached')
        with patch('shorts_maker.generator.video_generator.require_paid_production_enabled'), \
                patch('shorts_maker.generator.video_generator.reserve_google_output') as reserve:
            reserve.return_value='fixture-request'
            with self.assertRaises(ValueError):
                generator._retry_veo_call('veo-3.1-lite-generate-001','one bus',str(self.root/'result.mp4'),'fallback',
                    max_attempts=1,request_budget_usd=.24,first_frame_path=str(self.frame),
                    expected_first_frame_sha256=hashlib.sha256(self.frame.read_bytes()).hexdigest())
        reserve.assert_not_called()
        generator.client.models.generate_videos.assert_not_called()

    def test_png_checksum_failure_is_a_friendly_validation_error(self):
        output=BytesIO();Image.new('RGB',(540,960),'navy').save(output,format='PNG')
        data=bytearray(output.getvalue())
        chunk=data.index(b'IDAT');length=int.from_bytes(data[chunk-4:chunk],'big')
        data[chunk+4+length] ^= 1
        with self.assertRaisesRegex(ValueError,'손상되지 않은'):
            inspect_frame_bytes(bytes(data))

    def test_png_and_jpeg_submit_exact_validated_bytes_mime_and_hash(self):
        for fmt,mime in [('PNG','image/png'),('JPEG','image/jpeg')]:
            with self.subTest(fmt=fmt):
                output=BytesIO();Image.new('RGB',(540,960),'navy').save(output,format=fmt)
                content=output.getvalue();self.frame.write_bytes(content)
                generator=object.__new__(VideoGenerator)
                generator._check_visual_cap=Mock();generator.client=Mock();generator.logger=Mock()
                video=Mock();video.save.side_effect=lambda p:Path(p).write_bytes(b'mocked returned video')
                generator.client.models.generate_videos.return_value=SimpleNamespace(done=True,
                    result=SimpleNamespace(generated_videos=[SimpleNamespace(video=video)]))
                def captured(data):
                    result=inspect_frame_bytes(data)
                    self.frame.write_bytes(b'changed after byte capture')
                    return result
                with patch('shorts_maker.generator.video_generator.require_paid_production_enabled'), \
                        patch('shorts_maker.generator.video_generator.reserve_google_output',return_value='fixture') as reserve, \
                        patch('shorts_maker.generator.video_generator.mark_google_result'), \
                        patch('shorts_maker.generator.video_generator.inspect_frame_bytes',side_effect=captured):
                    generator._retry_veo_call('veo-3.1-lite-generate-001','one bus',str(self.root/'result.mp4'),'fallback',
                        max_attempts=1,request_budget_usd=.24,first_frame_path=str(self.frame),
                        expected_first_frame_sha256=hashlib.sha256(content).hexdigest())
                request=generator.client.models.generate_videos.call_args.kwargs
                self.assertEqual(request['image'].image_bytes,content)
                self.assertEqual(request['image'].mime_type,mime)
                self.assertEqual(request['config']['number_of_videos'],1)
                self.assertFalse(request['config']['generate_audio'])
                reserve.assert_called_once()
