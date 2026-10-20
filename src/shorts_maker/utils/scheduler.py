"""
ScheduleManager - 자동 비디오 프로덕션 스케줄링 관리 모듈

정기적인 비디오 생성 작업을 스케줄링하고 실행합니다.
"""
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.source_manager import SourceManager


_PROVIDER_LIMIT = re.compile(r"(?<!\d)429(?!\d)|RESOURCE_EXHAUSTED", re.IGNORECASE)
_VEO_RESULT_UNVERIFIED = "VEO_RESULT_UNVERIFIED"
_GOOGLE_BUDGET_EXCEEDED = "GOOGLE_BUDGET_EXCEEDED"
_VISUAL_COST_CAP_EXCEEDED = "VISUAL_COST_CAP_EXCEEDED"
_BGM_SELECTION_REQUIRED = "BGM_SELECTION_REQUIRED"
_ARTICLE_ANALYSIS_UNVERIFIED = "ARTICLE_ANALYSIS_UNVERIFIED"
_TOPIC_SCORING_UNVERIFIED = "TOPIC_SCORING_UNVERIFIED"
_PLANNING_UNVERIFIED = "PLANNING_UNVERIFIED"


class ScheduleManager:
    """
    스케줄 관리 클래스

    JSON 파일 기반으로 스케줄을 저장하고 관리합니다.
    APScheduler는 선택적으로 통합됩니다.
    """

    def __init__(self, filename: str = "schedules.json"):
        """
        ScheduleManager 초기화

        Args:
            filename: 스케줄 저장 파일 경로
        """
        self.logger = get_logger(__name__)
        self.filename = Path(filename)
        self._scheduler = None
        self._scheduler_running = False

    def _ensure_scheduler(self):
        """APScheduler 인스턴스 생성 (지연 초기화)"""
        if self._scheduler is None:
            try:
                from apscheduler.schedulers.asyncio import AsyncIOScheduler
                self._scheduler = AsyncIOScheduler()
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
            if schedule.get('enabled', True):
                self._register_job(schedule)

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
            frequency: 반복 주기 ('Daily', 'Weekly (Mon)', 'Weekly (Fri)', 등)
            topic: RSS 검색 토픽 (선택)
            direct_url: 직접 URL (선택)
            auto_upload: YouTube 자동 업로드 여부
            mode: 생성 모드 ('hybrid', 'image' 또는 'video')
            enabled: 활성화 여부

        Returns:
            생성된 스케줄 딕셔너리
        """
        self._validate_schedule(name, time, frequency, mode, direct_url)
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
            'created_at': datetime.now().isoformat(),
            'last_run': None,
            'run_count': 0
        }

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
                self._validate_schedule(updated['name'], updated['time'], updated['frequency'],
                                        updated['mode'], updated.get('direct_url'))
                schedule = updated
                schedules[i] = schedule
                self.save_schedules(schedules)

                # 스케줄러 작업 갱신
                if self._scheduler_running:
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
        if frequency != 'Daily' and frequency not in {f'Weekly ({day})' for day in days}:
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
                new_state = not schedule.get('enabled', True)
                return self.update_schedule(schedule_id, {'enabled': new_state}) is not None and new_state

        return None

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

            # 주기 설정
            trigger_kwargs = {'hour': hour, 'minute': minute}

            if frequency == 'Daily':
                pass  # 매일 실행
            elif 'Weekly' in frequency:
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
                'cron',
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

    async def _execute_pipeline(self, schedule: Dict[str, Any]):
        """스케줄된 파이프라인 실행"""
        from shorts_maker.services.production_service import ProductionService
        from shorts_maker.utils.bgm_manager import BGMManager
        from shorts_maker.utils.config import settings

        schedule = self.get_schedule(schedule['id'])
        if schedule is None or not schedule.get('enabled', True):
            return
        self.logger.info(f"=== Executing scheduled pipeline: {schedule['name']} ===")

        try:
            # A fixed article URL is one story; use topic discovery for a repeating source.
            if (schedule.get('direct_url')
                    and (schedule.get('last_rendered_url') == schedule['direct_url']
                         or (not schedule.get('last_rendered_url')
                             and schedule.get('last_result') == 'success'))):
                self.update_schedule(schedule['id'], {
                    'last_run': datetime.now().isoformat(),
                    'run_count': schedule.get('run_count', 0) + 1,
                    'last_result': 'duplicate_url',
                    'last_rendered_url': schedule['direct_url'],
                    'enabled': False,
                })
                return
            if not settings.paid_production_enabled:
                self.update_schedule(schedule['id'], {
                    'last_run': datetime.now().isoformat(),
                    'run_count': schedule.get('run_count', 0) + 1,
                    'last_result': 'paid_production_disabled',
                    'enabled': False,
                })
                self.logger.warning("Scheduled pipeline paused: paid production disabled")
                return
            if not BGMManager().has_documented_track():
                self.update_schedule(schedule['id'], {
                    'last_run': datetime.now().isoformat(),
                    'run_count': schedule.get('run_count', 0) + 1,
                    'last_result': 'music_missing',
                    'enabled': False,
                })
                self.logger.warning("Scheduled pipeline paused: documented BGM missing")
                return

            service = ProductionService(mode=schedule.get('mode', 'image'))

            result = await service.full_pipeline(
                topic=schedule.get('topic'),
                direct_url=schedule.get('direct_url'),
                auto_upload=schedule.get('auto_upload', False)
            )

            billing_disabled = "BILLING_DISABLED" in (result.error or "")
            music_missing = "사용 권한이 기록된 BGM이 없습니다" in (result.error or "")
            provider_limited = not result.success and bool(_PROVIDER_LIMIT.search(result.error or ""))
            veo_unverified = not result.success and _VEO_RESULT_UNVERIFIED in (result.error or "")
            google_budget_exceeded = not result.success and _GOOGLE_BUDGET_EXCEEDED in (result.error or "")
            visual_cost_cap_exceeded = not result.success and _VISUAL_COST_CAP_EXCEEDED in (result.error or "")
            music_selection_required = not result.success and _BGM_SELECTION_REQUIRED in (result.error or "")
            analysis_unverified = not result.success and _ARTICLE_ANALYSIS_UNVERIFIED in (result.error or "")
            scoring_unverified = not result.success and _TOPIC_SCORING_UNVERIFIED in (result.error or "")
            planning_unverified = not result.success and _PLANNING_UNVERIFIED in (result.error or "")
            rendered_failed = not result.success and bool(result.video_path)
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
            elif visual_cost_cap_exceeded:
                last_result = 'visual_cost_cap_exceeded'
            elif music_selection_required:
                last_result = 'music_selection_required'
            elif analysis_unverified:
                last_result = 'analysis_failed'
            elif scoring_unverified:
                last_result = 'scoring_failed'
            elif planning_unverified:
                last_result = 'planning_failed'
            elif rendered_failed:
                last_result = 'rendered_failed'
            updates = {
                'last_run': datetime.now().isoformat(),
                'run_count': schedule.get('run_count', 0) + 1,
                'last_result': last_result,
            }
            if (billing_disabled or music_missing or provider_limited or veo_unverified
                    or google_budget_exceeded or visual_cost_cap_exceeded
                    or music_selection_required or analysis_unverified or scoring_unverified
                    or planning_unverified or rendered_failed):
                updates['enabled'] = False
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
                'last_result': f'error: {str(e)}'
            }
            if _PROVIDER_LIMIT.search(str(e)):
                updates.update(enabled=False, last_result='provider_limit',
                               run_count=schedule.get('run_count', 0) + 1)
            elif _VEO_RESULT_UNVERIFIED in str(e):
                updates.update(enabled=False, last_result='veo_result_unverified',
                               run_count=schedule.get('run_count', 0) + 1)
            elif _GOOGLE_BUDGET_EXCEEDED in str(e):
                updates.update(enabled=False, last_result='google_budget_exceeded',
                               run_count=schedule.get('run_count', 0) + 1)
            elif _VISUAL_COST_CAP_EXCEEDED in str(e):
                updates.update(enabled=False, last_result='visual_cost_cap_exceeded',
                               run_count=schedule.get('run_count', 0) + 1)
            elif _BGM_SELECTION_REQUIRED in str(e):
                updates.update(enabled=False, last_result='music_selection_required',
                               run_count=schedule.get('run_count', 0) + 1)
            elif _ARTICLE_ANALYSIS_UNVERIFIED in str(e):
                updates.update(enabled=False, last_result='analysis_failed',
                               run_count=schedule.get('run_count', 0) + 1)
            elif _TOPIC_SCORING_UNVERIFIED in str(e):
                updates.update(enabled=False, last_result='scoring_failed',
                               run_count=schedule.get('run_count', 0) + 1)
            elif _PLANNING_UNVERIFIED in str(e):
                updates.update(enabled=False, last_result='planning_failed',
                               run_count=schedule.get('run_count', 0) + 1)
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
