"""
ScheduleManager - 자동 비디오 프로덕션 스케줄링 관리 모듈

정기적인 비디오 생성 작업을 스케줄링하고 실행합니다.
"""
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta

from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.source_manager import SourceManager


_INTERVAL_WEEKS = {"Every 2 Weeks": 2, "Every 4 Weeks": 4}


_PROVIDER_LIMIT = re.compile(r"(?<!\d)429(?!\d)|RESOURCE_EXHAUSTED", re.IGNORECASE)
_VEO_RESULT_UNVERIFIED = "VEO_RESULT_UNVERIFIED"
_GOOGLE_BUDGET_EXCEEDED = "GOOGLE_BUDGET_EXCEEDED"
_OPENAI_BUDGET_EXCEEDED = "OPENAI_BUDGET_EXCEEDED"
_OPENAI_MODEL_RETIRED = "OPENAI_MODEL_RETIRED"
_VISUAL_COST_CAP_EXCEEDED = "VISUAL_COST_CAP_EXCEEDED"
_BGM_SELECTION_REQUIRED = "BGM_SELECTION_REQUIRED"
_ARTICLE_ANALYSIS_UNVERIFIED = "ARTICLE_ANALYSIS_UNVERIFIED"
_TOPIC_SCORING_UNVERIFIED = "TOPIC_SCORING_UNVERIFIED"
_PLANNING_UNVERIFIED = "PLANNING_UNVERIFIED"
_RUN_FIELDS = (
    'last_run', 'run_count', 'last_result', 'last_script', 'last_planned_url',
    'last_rendered_url', 'last_video_path', 'last_video_sha256', 'last_youtube_id', 'accepted_at',
    'queued_at', 'last_episode_id',
    'scheduled_for', 'late_by_seconds', 'skipped_slots',
)


class ScheduleManager:
    """
    스케줄 관리 클래스

    JSON 파일 기반으로 스케줄을 저장하고 관리합니다.
    APScheduler는 선택적으로 통합됩니다.
    """

    def __init__(self, filename: str = "schedules.json", *, queue_only: bool = False):
        """
        ScheduleManager 초기화

        Args:
            filename: 스케줄 저장 파일 경로
        """
        self.logger = get_logger(__name__)
        self.filename = Path(filename)
        self.queue_only = queue_only
        self._scheduler = None
        self._scheduler_running = False
        self._production_lock = asyncio.Lock()

    def _ensure_scheduler(self):
        """APScheduler 인스턴스 생성 (지연 초기화)"""
        if self._scheduler is None:
            try:
                from apscheduler.schedulers.asyncio import AsyncIOScheduler
                self._scheduler = AsyncIOScheduler(timezone='Asia/Seoul') if self.queue_only else AsyncIOScheduler()
                self.logger.info("APScheduler initialized")
            except ImportError:
                self.logger.warning("APScheduler not installed. Scheduling features disabled.")
                return None
        return self._scheduler

    def start_scheduler(self):
        """스케줄러 시작"""
        scheduler = self._ensure_scheduler()
        if scheduler is None:
            raise RuntimeError("APScheduler를 사용할 수 없습니다.")
        if not self._scheduler_running:
            scheduler.start()
            self._scheduler_running = True
            self.logger.info("Scheduler started")

            # 저장된 스케줄 로드 및 등록
            try:
                self._load_and_register_jobs()
            except Exception:
                self.stop_scheduler()
                raise

    def stop_scheduler(self):
        """스케줄러 중지"""
        if self._scheduler and self._scheduler_running:
            scheduler = self._scheduler
            self._scheduler = None
            self._scheduler_running = False
            scheduler.shutdown(wait=False)
            self.logger.info("Scheduler stopped")

    def _load_and_register_jobs(self):
        """저장된 스케줄을 로드하여 작업 등록"""
        schedules = self.load_schedules()
        for schedule in schedules:
            if schedule.get('enabled', True) and (not self.queue_only or schedule.get('review_operator') == 'agent'):
                self._register_job(schedule)

    def sync_jobs(self):
        """Reload external review changes without replacing an unchanged clock trigger."""
        if not self._scheduler_running:
            return
        desired = {s['id']: s for s in self.load_schedules() if s.get('enabled', True)
                   and (not self.queue_only or s.get('review_operator') == 'agent')}
        jobs = {job.id: job for job in self._scheduler.get_jobs()}
        for job_id in jobs.keys() - desired.keys():
            self._unregister_job(job_id)
        for job_id, schedule in desired.items():
            previous = jobs[job_id].args[0] if job_id in jobs else {}
            if not previous or any(previous.get(key) != schedule.get(key) for key in (
                'time', 'frequency', 'interval_anchor_at', 'first_run_at', 'review_operator',
            )):
                self._register_job(schedule)

    @staticmethod
    def _interval_start(schedule):
        if schedule.get('first_run_at'):
            return datetime.fromisoformat(schedule['first_run_at'])
        created = datetime.fromisoformat(schedule.get('interval_anchor_at') or schedule['created_at'])
        hour, minute = map(int, schedule['time'].split(':'))
        first = created.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return first + timedelta(days=1) if first <= created else first

    @classmethod
    def _due_slot(cls, schedule):
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo('Asia/Seoul')).replace(tzinfo=None)
        first = cls._interval_start(schedule)
        if now < first:
            return None
        interval = timedelta(weeks=_INTERVAL_WEEKS[schedule["frequency"]])
        slot = first + ((now - first) // interval) * interval
        previous = schedule.get('scheduled_for')
        if previous and slot <= datetime.fromisoformat(previous):
            return None
        missed_start = datetime.fromisoformat(previous) + interval if previous else first
        count = max(0, (slot - missed_start) // interval)
        return {'scheduled_for': slot.isoformat(), 'late_by_seconds': round((now - slot).total_seconds(), 3),
                'skipped_slots': [(missed_start + i * interval).isoformat() for i in range(count)]}

    async def queue_overdue(self):
        """Recover at most the latest due slot, recording skipped slots without paying or replaying them."""
        for schedule in self.load_schedules():
            if (schedule.get('enabled') and schedule.get('review_operator') == 'agent'
                    and self._due_slot(schedule)):
                await self._execute_pipeline(schedule)

    def load_schedules(self) -> List[Dict[str, Any]]:
        """
        저장된 스케줄 목록 로드

        Returns:
            스케줄 딕셔너리 리스트
        """
        if not self.filename.exists():
            return []
        try:
            schedules = json.loads(self.filename.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError) as e:
            raise ValueError(f"일정 파일을 읽을 수 없습니다: {self.filename}") from e
        if not isinstance(schedules, list) or any(not isinstance(item, dict) for item in schedules):
            raise ValueError(f"일정 파일 형식이 잘못되었습니다: {self.filename}")
        for schedule in schedules:
            history = schedule.get('run_history', [])
            if not isinstance(history, list) or any(not isinstance(run, dict) for run in history):
                raise ValueError(f"일정 실행 이력 형식이 잘못되었습니다: {self.filename}")
        return schedules

    def save_schedules(self, schedules: List[Dict[str, Any]]):
        """
        스케줄 목록 저장

        Args:
            schedules: 저장할 스케줄 리스트
        """
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=self.filename.parent,
                prefix=f'.{self.filename.name}.', delete=False,
            ) as file:
                temp_path = Path(file.name)
                json.dump(schedules, file, indent=2, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, self.filename)
            self.logger.info(f"Saved {len(schedules)} schedules")
        except OSError as e:
            self.logger.error(f"Failed to save schedules: {e}")
            raise
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    def create_schedule(
        self,
        name: str,
        time: str,
        frequency: str = "Daily",
        topic: Optional[str] = None,
        direct_url: Optional[str] = None,
        auto_upload: bool = False,
        mode: str = "hybrid",
        enabled: bool = True
    ) -> Dict[str, Any]:
        """
        새 스케줄 생성

        Args:
            name: 스케줄 이름
            time: 실행 시간 (HH:MM 형식)
            frequency: 반복 주기 ('Daily', 'Weekly (Mon)', 'Every 4 Weeks' 등)
            topic: 등록된 RSS 분야 (선택, None이면 전체)
            direct_url: 직접 URL (선택)
            auto_upload: YouTube 자동 업로드 여부
            mode: 생성 모드 ('hybrid', 'image' 또는 'video')
            enabled: 활성화 여부

        Returns:
            생성된 스케줄 딕셔너리
        """
        self._validate_schedule(name, time, frequency, mode, direct_url)
        created_at = datetime.now().isoformat()
        schedule = {
            'id': str(uuid.uuid4()),
            'name': name,
            'time': time,
            'frequency': frequency,
            'topic': topic,
            'direct_url': direct_url,
            'auto_upload': auto_upload,
            'mode': mode,
            'enabled': enabled,
            'created_at': created_at,
            'last_run': None,
            'run_count': 0
        }
        if frequency in _INTERVAL_WEEKS and enabled:
            schedule['interval_anchor_at'] = created_at

        # 저장
        schedules = self.load_schedules()
        schedules.append(schedule)
        self.save_schedules(schedules)

        # 스케줄러에 등록
        if self._scheduler_running and enabled:
            try:
                self._register_job(schedule)
            except Exception:
                self.update_schedule(schedule['id'], {'enabled': False,
                                                      'last_result': 'registration_failed'})
                raise

        self.logger.info(f"Created schedule: {name} at {time}")
        return schedule

    def update_schedule(self, schedule_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        스케줄 업데이트

        Args:
            schedule_id: 업데이트할 스케줄 ID
            updates: 업데이트할 필드 딕셔너리

        Returns:
            업데이트된 스케줄 또는 None
        """
        schedules = self.load_schedules()
        for i, schedule in enumerate(schedules):
            if schedule['id'] == schedule_id:
                updated = {**schedule, **updates}
                if updates.get('run_count', 0) > schedule.get('run_count', 0):
                    if schedule.get('last_run'):
                        previous_run = {key: schedule[key] for key in _RUN_FIELDS if key in schedule}
                        updated['run_history'] = [*schedule.get('run_history', []), previous_run]
                    # A new attempt must not inherit another episode's script or review copy.
                    for key in _RUN_FIELDS:
                        if key not in updates:
                            updated.pop(key, None)
                self._validate_schedule(updated['name'], updated['time'], updated['frequency'],
                                        updated['mode'], updated.get('direct_url'))
                if updated.get('review_operator') == 'agent' and updated['frequency'] not in _INTERVAL_WEEKS:
                    raise ValueError('에이전트 운영 일정은 2주 또는 4주 주기를 사용하세요.')
                if updated.get('first_run_at'):
                    first = datetime.fromisoformat(updated['first_run_at'])
                    if updated['frequency'] not in _INTERVAL_WEEKS or first.tzinfo is not None:
                        raise ValueError('첫 회차 시작은 2주 또는 4주 일정의 로컬 날짜·시간이어야 합니다.')
                if (updated['frequency'] in _INTERVAL_WEEKS and updated.get('enabled')
                        and (schedule['frequency'] not in _INTERVAL_WEEKS
                             or not updated.get('interval_anchor_at'))):
                    updated['interval_anchor_at'] = datetime.now().isoformat()
                reschedule = any(schedule.get(key) != updated.get(key)
                                 for key in ('enabled', 'time', 'frequency', 'first_run_at', 'review_operator'))
                schedule = updated
                schedules[i] = schedule
                self.save_schedules(schedules)

                # 스케줄러 작업 갱신
                if self._scheduler_running and reschedule:
                    self._unregister_job(schedule_id)
                    if schedule.get('enabled', True):
                        try:
                            self._register_job(schedule)
                        except Exception:
                            self.update_schedule(schedule_id, {'enabled': False,
                                                               'last_result': 'registration_failed'})
                            raise

                self.logger.info(f"Updated schedule: {schedule_id}")
                return schedule

        self.logger.warning(f"Schedule not found: {schedule_id}")
        return None

    @staticmethod
    def _validate_schedule(name: str, time: str, frequency: str, mode: str,
                           direct_url: Optional[str] = None):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("일정 이름이 필요합니다.")
        if not isinstance(time, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', time):
            raise ValueError("시간은 HH:MM 형식이어야 합니다.")
        days = {'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'}
        if frequency != 'Daily' and frequency not in _INTERVAL_WEEKS and frequency not in {f'Weekly ({day})' for day in days}:
            raise ValueError("지원하지 않는 반복 주기입니다.")
        if mode not in {'hybrid', 'image', 'video'}:
            raise ValueError("지원하지 않는 생성 모드입니다.")
        if direct_url is not None and not SourceManager.is_allowed_url(direct_url):
            raise ValueError("공개된 http 또는 https 기사 URL이 필요합니다.")

    def delete_schedule(self, schedule_id: str) -> bool:
        """
        스케줄 삭제

        Args:
            schedule_id: 삭제할 스케줄 ID

        Returns:
            삭제 성공 여부
        """
        schedules = self.load_schedules()
        original_count = len(schedules)
        for schedule in schedules:
            if (schedule['id'] == schedule_id and schedule.get('last_result') in {
                    'operator_pending', 'run_in_progress', 'script_review_pending'}):
                raise ValueError('미해결 제작 회차는 삭제할 수 없습니다. 결과·검토를 먼저 정리하세요.')
        schedules = [s for s in schedules if s['id'] != schedule_id]

        if len(schedules) < original_count:
            self.save_schedules(schedules)
            self._unregister_job(schedule_id)
            self.logger.info(f"Deleted schedule: {schedule_id}")
            return True

        self.logger.warning(f"Schedule not found for deletion: {schedule_id}")
        return False

    def toggle_schedule(self, schedule_id: str) -> Optional[bool]:
        """
        스케줄 활성화/비활성화 토글

        Args:
            schedule_id: 토글할 스케줄 ID

        Returns:
            새로운 활성화 상태 또는 None
        """
        schedules = self.load_schedules()
        for schedule in schedules:
            if schedule['id'] == schedule_id:
                if (schedule.get('review_operator') == 'agent' and not schedule.get('enabled')
                        and schedule.get('last_result') in {'operator_pending', 'run_in_progress'}):
                    raise ValueError('제작 인계·실행 결과를 먼저 확인하세요. 새 회차로 건너뛸 수 없습니다.')
                if not schedule.get('enabled', True) and schedule.get('last_result') == 'script_review_pending':
                    raise ValueError("검토 대기 각본은 바로 재개할 수 없습니다. 다음 소재를 찾으려면 각본을 제외하세요.")
                new_state = not schedule.get('enabled', True)
                return self.update_schedule(schedule_id, {'enabled': new_state}) is not None and new_state

        return None

    def reject_pending_script(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Leave a reviewed-out script in history and resume only RSS discovery."""
        schedule = self.get_schedule(schedule_id)
        if schedule is None:
            return None
        if schedule.get('last_result') != 'script_review_pending' or schedule.get('enabled'):
            raise ValueError("제외할 검토 대기 각본이 없습니다.")
        if schedule.get('last_youtube_id'):
            raise ValueError("비공개 완성본이 연결된 회차는 각본 제외로 재개할 수 없습니다. 완성본을 검토하세요.")
        return self.update_schedule(schedule_id, {
            'last_result': 'script_rejected',
            'enabled': not bool(schedule.get('direct_url')),
        })

    def accept_pending_video(self, schedule_id: str, video_path: str) -> Dict[str, Any]:
        """Resume RSS discovery only after a reviewed private upload is bound to its saved source."""
        schedule, video, video_sha256, video_id = self._verified_pending_video(schedule_id, video_path)
        updated = self.update_schedule(schedule_id, {
            'last_result': 'private_review_accepted',
            'last_video_path': str(video),
            'last_video_sha256': video_sha256,
            'last_youtube_id': video_id,
            'accepted_at': datetime.now().isoformat(),
            'enabled': not bool(schedule.get('direct_url')),
        })
        if updated is None:
            raise ValueError('일정이 사라져 완료 기록을 저장하지 못했습니다.')
        return updated

    def pending_video_info(self, schedule_id: str, video_path: str) -> Dict[str, str]:
        """Preview an exact verified attachment without adopting it or changing the schedule."""
        _, video, video_hash, video_id = self._verified_pending_video(schedule_id, video_path)
        return {'video_path': str(video), 'video_sha256': video_hash, 'youtube_id': video_id}

    def record_private_review_copy(self, schedule_id: str, video_path: str) -> Dict[str, Any]:
        """Attach a matching upload without claiming owner acceptance or re-enabling the next slot."""
        _, video, video_hash, video_id = self._verified_pending_video(schedule_id, video_path)
        updated = self.update_schedule(schedule_id, {
            'last_video_path': str(video), 'last_video_sha256': video_hash, 'last_youtube_id': video_id,
        })
        if updated is None:
            raise ValueError('일정이 사라져 업로드 기록을 연결하지 못했습니다.')
        return updated

    def _verified_pending_video(self, schedule_id: str, video_path: str) -> tuple:
        from shorts_maker.services.production_service import script_sha256
        from shorts_maker.utils.config import settings

        schedule = self.get_schedule(schedule_id)
        if (schedule is None or schedule.get('last_result') != 'script_review_pending'
                or schedule.get('enabled')):
            raise ValueError("검토 대기 중인 각본 일정이 없습니다.")
        if schedule.get('last_episode_id'):
            from shorts_maker.services.operating_budget import episode_path
            if episode_path(schedule['last_episode_id']).with_suffix('.operation.pending.json').exists():
                raise ValueError('회차 실행 결과를 먼저 대조하세요. 미확인 실행 중에는 영상을 연결·채택할 수 없습니다.')
        if not isinstance(video_path, str) or not video_path:
            raise ValueError("완성 영상 경로가 필요합니다.")
        try:
            video = Path(video_path).resolve()
            if (video.suffix.lower() != '.mp4' or not video.is_file()
                    or not video.is_relative_to(settings.output_dir.resolve())):
                raise ValueError("출력 폴더의 완성 MP4를 선택하세요.")
            report_path = video.with_suffix('.production.json').resolve()
            if not report_path.is_relative_to(settings.output_dir.resolve()):
                raise ValueError('출력 폴더의 제작 기록이 필요합니다.')
            report = json.loads(report_path.read_text(encoding='utf-8'))
            with video.open('rb') as stream:
                video_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            raise ValueError("영상과 제작 기록을 확인할 수 없습니다.") from error
        if video.with_suffix('.upload-pending.json').exists():
            raise ValueError('업로드 결과를 먼저 대조하세요.')
        if (not isinstance(report, dict) or not isinstance(report.get('video_path'), str)
                or Path(report['video_path']).resolve() != video
                or not isinstance(schedule.get('last_script'), dict)
                or report.get('source_url') != schedule['last_script'].get('source_url')
                or report.get('script_sha256') != script_sha256(schedule['last_script'])
                or report.get('quality_passed') is not True
                or report.get('video_sha256') != video_sha256):
            raise ValueError("저장된 각본·출처·품질·영상 해시가 제작 기록과 일치하지 않습니다.")
        video_id = report.get('youtube_id')
        upload = report.get('youtube_upload_request')
        if (not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{6,64}', video_id)
                or not isinstance(upload, dict) or not isinstance(upload.get('status'), dict)
                or upload['status'].get('privacyStatus') != 'private'
                or not isinstance(report.get('uploaded_at_utc'), str)
                or not report['uploaded_at_utc']):
            raise ValueError("확인된 YouTube 비공개 업로드 기록이 필요합니다.")
        if schedule.get('last_youtube_id') and (
                schedule.get('last_video_path') != str(video)
                or schedule.get('last_video_sha256') != video_sha256
                or schedule['last_youtube_id'] != video_id):
            raise ValueError("이미 연결된 비공개 검토본의 경로·영상 해시·YouTube ID와 일치해야 합니다.")
        return schedule, video, video_sha256, video_id

    def get_execution_history(self) -> List[Dict[str, Any]]:
        """Return retained attempts and the current review state, newest first."""
        history = []
        for schedule in self.load_schedules():
            runs = list(schedule.get('run_history', []))
            if schedule.get('last_run'):
                runs.append({key: schedule[key] for key in _RUN_FIELDS if key in schedule})
            history.extend({**run, 'schedule_id': schedule['id'], 'name': schedule['name']}
                           for run in runs)
        return sorted(history, key=lambda run: run.get('last_run', ''), reverse=True)

    def get_schedule(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """
        특정 스케줄 조회

        Args:
            schedule_id: 조회할 스케줄 ID

        Returns:
            스케줄 딕셔너리 또는 None
        """
        schedules = self.load_schedules()
        for schedule in schedules:
            if schedule['id'] == schedule_id:
                return schedule
        return None

    def _register_job(self, schedule: Dict[str, Any]):
        """APScheduler에 작업 등록"""
        if not self._scheduler:
            return

        try:
            hour, minute = map(int, schedule['time'].split(':'))
            frequency = schedule.get('frequency', 'Daily')

            if frequency in _INTERVAL_WEEKS:
                first_run = self._interval_start(schedule)
                trigger, trigger_kwargs = 'interval', {'weeks': _INTERVAL_WEEKS[frequency], 'start_date': first_run}
            else:
                trigger, trigger_kwargs = 'cron', {'hour': hour, 'minute': minute}
            if frequency.startswith('Weekly'):
                # Weekly (Mon), Weekly (Fri) 등에서 요일 추출
                day_map = {
                    'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3,
                    'Fri': 4, 'Sat': 5, 'Sun': 6
                }
                for day_name, day_num in day_map.items():
                    if day_name in frequency:
                        trigger_kwargs['day_of_week'] = day_num
                        break

            self._scheduler.add_job(
                self._execute_pipeline,
                trigger,
                id=schedule['id'],
                args=[schedule],
                replace_existing=True,
                **trigger_kwargs
            )

            self.logger.info(f"Registered job: {schedule['name']} at {schedule['time']}")

        except Exception as e:
            self.logger.error(f"Failed to register job {schedule['id']}: {e}")
            raise

    def _unregister_job(self, schedule_id: str):
        """APScheduler에서 작업 제거"""
        if not self._scheduler:
            return

        try:
            self._scheduler.remove_job(schedule_id)
            self.logger.info(f"Unregistered job: {schedule_id}")
        except Exception as e:
            self.logger.debug(f"Job {schedule_id} not found for removal: {e}")

    async def _execute_pipeline(self, schedule: Dict[str, Any], *, operator: bool = False):
        """스케줄된 파이프라인 실행"""
        # The saved schedule must be re-read after both in-process and cross-process waiting.
        async with self._production_lock:
            lock_path = self.filename.with_name(f"{self.filename.name}.lock.sqlite3")
            connection = sqlite3.connect(lock_path, timeout=0, isolation_level=None)
            locked = False
            try:
                while not locked:
                    try:
                        connection.execute("BEGIN EXCLUSIVE")
                        locked = True
                    except sqlite3.OperationalError as error:
                        if error.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                            raise
                        await asyncio.sleep(0.1)
                await self._execute_pipeline_serial(schedule, operator=operator)
            finally:
                connection.close()

    async def _execute_pipeline_serial(self, schedule: Dict[str, Any], *, operator: bool = False):
        from shorts_maker.services.production_service import ProductionService
        from shorts_maker.services.google_budget import budget_status as google_budget_status
        from shorts_maker.services.openai_budget import budget_status as openai_budget_status
        from shorts_maker.utils.bgm_manager import BGMManager
        from shorts_maker.utils.config import settings

        schedule = self.get_schedule(schedule['id'])
        if schedule is None:
            return
        if operator:
            if (schedule.get('enabled') or schedule.get('review_operator') != 'agent'
                    or schedule.get('last_result') != 'operator_pending'
                    or not schedule.get('last_episode_id')
                    or os.getenv('SHORTSMAKER_EPISODE_ID') != schedule['last_episode_id']):
                raise ValueError('저장된 에이전트 회차와 제작 대기가 일치하지 않습니다.')
            if settings.paid_production_enabled:
                from shorts_maker.uploader.youtube_uploader import YouTubeAuthRequired, YouTubeUploader
                try:
                    await asyncio.to_thread(YouTubeUploader().get_authenticated_service, interactive=False)
                except Exception:
                    raise YouTubeAuthRequired(
                        'YOUTUBE_AUTH_REQUIRED: 유료 기획 전에 YouTube 업로드 계정을 다시 연결하세요. '
                        '기존 auth-only 절차 후 같은 회차를 재개할 수 있습니다.'
                    ) from None
        else:
            if not schedule.get('enabled', True):
                return
            if schedule.get('review_operator') == 'agent':
                slot = self._due_slot(schedule)
                if slot is None:
                    return
                now = datetime.now().isoformat()
                self.update_schedule(schedule['id'], {
                    'last_run': now, 'queued_at': now, 'run_count': schedule.get('run_count', 0) + 1,
                    'last_result': 'operator_pending', 'enabled': False, **slot,
                })
                return
            if self.queue_only:
                return
        if schedule.get('last_result') == 'script_review_pending':
            self.update_schedule(schedule['id'], {'enabled': False})
            return
        self.logger.info(f"=== Executing scheduled pipeline: {schedule['name']} ===")
        run_count = schedule.get('run_count', 0) + (0 if operator else 1)

        try:
            # A fixed article URL is one story; use topic discovery for a repeating source.
            article_url = schedule.get('direct_url')
            prior_article_run = article_url and any(
                other.get('id') != schedule['id']
                and (other.get('last_rendered_url') == article_url
                     or other.get('last_planned_url') == article_url
                     or (other.get('direct_url') == article_url
                         and not other.get('last_rendered_url')
                         and other.get('last_result') == 'success'))
                for other in self.load_schedules()
            )
            if (article_url and (prior_article_run
                    or schedule.get('last_rendered_url') == article_url
                    or schedule.get('last_planned_url') == article_url
                    or (not schedule.get('last_rendered_url')
                        and schedule.get('last_result') == 'success'))):
                self.update_schedule(schedule['id'], {
                    'last_run': datetime.now().isoformat(),
                    'run_count': run_count,
                    'last_result': 'duplicate_url',
                    'last_planned_url': article_url,
                    'enabled': False,
                })
                return
            if not settings.paid_production_enabled:
                self.update_schedule(schedule['id'], {
                    'last_run': datetime.now().isoformat(),
                    'run_count': run_count,
                    'last_result': 'paid_production_disabled',
                    'enabled': False,
                })
                self.logger.warning("Scheduled pipeline paused: paid production disabled")
                return
            for status, remaining, reason in (
                (google_budget_status, 'remaining_krw', 'google_budget_exceeded'),
                (openai_budget_status, 'remaining_usd', 'openai_budget_exceeded'),
            ):
                try:
                    snapshot = status()
                    if snapshot.get('enabled') and snapshot.get(remaining, 0) > 0:
                        continue
                except (RuntimeError, ValueError, OSError):
                    pass
                self.update_schedule(schedule['id'], {
                    'last_run': datetime.now().isoformat(),
                    'run_count': run_count,
                    'last_result': reason,
                    'enabled': False,
                })
                self.logger.warning("Scheduled pipeline paused: %s", reason)
                return
            if not BGMManager().has_documented_track():
                self.update_schedule(schedule['id'], {
                    'last_run': datetime.now().isoformat(),
                    'run_count': run_count,
                    'last_result': 'music_missing',
                    'enabled': False,
                })
                self.logger.warning("Scheduled pipeline paused: documented BGM missing")
                return

            service = ProductionService(mode=schedule.get('mode', 'image'))

            # Persist the pause before the first paid call; a killed process cannot save a final result.
            self.update_schedule(schedule['id'], {
                'last_run': datetime.now().isoformat(),
                'run_count': run_count,
                'last_result': 'run_in_progress',
                'enabled': False,
            })

            result = await service.full_pipeline(
                topic=schedule.get('topic'),
                direct_url=schedule.get('direct_url'),
                auto_upload=schedule.get('auto_upload', False)
            )

            if getattr(result, 'review_pending', False):
                self.update_schedule(schedule['id'], {
                    'last_run': datetime.now().isoformat(),
                    'run_count': run_count,
                    'last_result': 'script_review_pending',
                    'last_planned_url': schedule.get('direct_url') or result.script.source_url,
                    'last_script': result.script.model_dump(),
                    'enabled': False,
                })
                self.logger.info("Scheduled script awaits visual review: %s", result.script.title)
                return

            billing_disabled = "BILLING_DISABLED" in (result.error or "")
            music_missing = "사용 권한이 기록된 BGM이 없습니다" in (result.error or "")
            provider_limited = not result.success and bool(_PROVIDER_LIMIT.search(result.error or ""))
            veo_unverified = not result.success and _VEO_RESULT_UNVERIFIED in (result.error or "")
            google_budget_exceeded = not result.success and _GOOGLE_BUDGET_EXCEEDED in (result.error or "")
            openai_budget_exceeded = not result.success and _OPENAI_BUDGET_EXCEEDED in (result.error or "")
            visual_cost_cap_exceeded = not result.success and _VISUAL_COST_CAP_EXCEEDED in (result.error or "")
            music_selection_required = not result.success and _BGM_SELECTION_REQUIRED in (result.error or "")
            analysis_unverified = not result.success and _ARTICLE_ANALYSIS_UNVERIFIED in (result.error or "")
            scoring_unverified = not result.success and _TOPIC_SCORING_UNVERIFIED in (result.error or "")
            planning_unverified = not result.success and _PLANNING_UNVERIFIED in (result.error or "")
            # This exact collector error occurs before the paid topic-scoring request.
            source_unavailable = (not schedule.get('direct_url') and not result.success
                                  and not result.video_path
                                  and (result.error or "").startswith(
                                      "PLANNING_UNVERIFIED: RSS_SOURCE_UNVERIFIED:"))
            rendered_failed = not result.success and bool(result.video_path)
            # Other failures pause before another scheduled paid round.
            # 공급자 제한 뒤의 다음 일정이 계획·내레이션 비용을 다시 쓰지 않도록 멈춘다.
            last_result = 'success' if result.success else 'failed'
            if billing_disabled:
                last_result = 'billing_disabled'
            elif music_missing:
                last_result = 'music_missing'
            elif provider_limited:
                last_result = 'provider_limit'
            elif veo_unverified:
                last_result = 'veo_result_unverified'
            elif google_budget_exceeded:
                last_result = 'google_budget_exceeded'
            elif openai_budget_exceeded:
                last_result = 'openai_budget_exceeded'
            elif _OPENAI_MODEL_RETIRED in (result.error or ''):
                last_result = 'model_migration_required'
            elif visual_cost_cap_exceeded:
                last_result = 'visual_cost_cap_exceeded'
            elif music_selection_required:
                last_result = 'music_selection_required'
            elif analysis_unverified:
                last_result = 'analysis_failed'
            elif scoring_unverified:
                last_result = 'scoring_failed'
            elif source_unavailable:
                last_result = 'source_unavailable'
            elif planning_unverified:
                last_result = 'planning_failed'
            elif rendered_failed:
                last_result = 'rendered_failed'
            updates = {
                'last_run': datetime.now().isoformat(),
                'run_count': run_count,
                'last_result': last_result,
                'enabled': source_unavailable or (
                    not result.success and result.error == "스크립트 생성 실패" and not result.video_path),
            }
            if result.video_path:
                updates['last_video_path'] = str(result.video_path)
                updates['last_youtube_id'] = (getattr(result, 'youtube_id', None)
                                              if result.success and schedule.get('auto_upload') else None)
            if schedule.get('direct_url') and (result.success or result.video_path):
                updates['last_rendered_url'] = schedule['direct_url']
                updates['enabled'] = False
            self.update_schedule(schedule['id'], updates)

            if result.success:
                self.logger.info(f"Scheduled pipeline completed: {result.video_path}")
            else:
                self.logger.error(f"Scheduled pipeline failed: {result.error}; video_path={result.video_path}")

        except Exception as e:
            self.logger.error(f"Scheduled pipeline error: {e}")
            updates = {
                'last_run': datetime.now().isoformat(),
                'run_count': run_count,
                'last_result': 'error_paused',
                'enabled': False,
            }
            if _PROVIDER_LIMIT.search(str(e)):
                updates['last_result'] = 'provider_limit'
            elif _VEO_RESULT_UNVERIFIED in str(e):
                updates['last_result'] = 'veo_result_unverified'
            elif _GOOGLE_BUDGET_EXCEEDED in str(e):
                updates['last_result'] = 'google_budget_exceeded'
            elif _OPENAI_BUDGET_EXCEEDED in str(e):
                updates['last_result'] = 'openai_budget_exceeded'
            elif _OPENAI_MODEL_RETIRED in str(e):
                updates['last_result'] = 'model_migration_required'
            elif _VISUAL_COST_CAP_EXCEEDED in str(e):
                updates['last_result'] = 'visual_cost_cap_exceeded'
            elif _BGM_SELECTION_REQUIRED in str(e):
                updates['last_result'] = 'music_selection_required'
            elif _ARTICLE_ANALYSIS_UNVERIFIED in str(e):
                updates['last_result'] = 'analysis_failed'
            elif _TOPIC_SCORING_UNVERIFIED in str(e):
                updates['last_result'] = 'scoring_failed'
            elif _PLANNING_UNVERIFIED in str(e):
                updates['last_result'] = 'planning_failed'
            self.update_schedule(schedule['id'], updates)

    def get_next_run_times(self) -> List[Dict[str, Any]]:
        """
        다음 실행 시간 목록 조회

        Returns:
            스케줄 ID와 다음 실행 시간 리스트
        """
        if not self._scheduler:
            return []

        result = []
        for job in self._scheduler.get_jobs():
            result.append({
                'id': job.id,
                'next_run': job.next_run_time.isoformat() if job.next_run_time else None
            })
        return result
