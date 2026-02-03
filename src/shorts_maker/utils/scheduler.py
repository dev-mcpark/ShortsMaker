"""
ScheduleManager - 자동 비디오 프로덕션 스케줄링 관리 모듈

정기적인 비디오 생성 작업을 스케줄링하고 실행합니다.
"""
import json
import uuid
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

from shorts_maker.utils.logger import get_logger


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
        if scheduler and not self._scheduler_running:
            scheduler.start()
            self._scheduler_running = True
            self.logger.info("Scheduler started")

            # 저장된 스케줄 로드 및 등록
            self._load_and_register_jobs()

    def stop_scheduler(self):
        """스케줄러 중지"""
        if self._scheduler and self._scheduler_running:
            self._scheduler.shutdown(wait=False)
            self._scheduler_running = False
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
        try:
            if self.filename.exists():
                content = self.filename.read_text(encoding='utf-8')
                return json.loads(content)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"Failed to load schedules: {e}")
        return []

    def save_schedules(self, schedules: List[Dict[str, Any]]):
        """
        스케줄 목록 저장

        Args:
            schedules: 저장할 스케줄 리스트
        """
        try:
            self.filename.write_text(
                json.dumps(schedules, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
            self.logger.info(f"Saved {len(schedules)} schedules")
        except IOError as e:
            self.logger.error(f"Failed to save schedules: {e}")

    def create_schedule(
        self,
        name: str,
        time: str,
        frequency: str = "Daily",
        topic: Optional[str] = None,
        direct_url: Optional[str] = None,
        auto_upload: bool = False,
        mode: str = "image",
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
            mode: 생성 모드 ('image' 또는 'video')
            enabled: 활성화 여부

        Returns:
            생성된 스케줄 딕셔너리
        """
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
        if self._scheduler_running:
            self._register_job(schedule)

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
                # 업데이트 적용
                schedule.update(updates)
                schedules[i] = schedule
                self.save_schedules(schedules)

                # 스케줄러 작업 갱신
                if self._scheduler_running:
                    self._unregister_job(schedule_id)
                    if schedule.get('enabled', True):
                        self._register_job(schedule)

                self.logger.info(f"Updated schedule: {schedule_id}")
                return schedule

        self.logger.warning(f"Schedule not found: {schedule_id}")
        return None

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

        self.logger.info(f"=== Executing scheduled pipeline: {schedule['name']} ===")

        try:
            service = ProductionService(mode=schedule.get('mode', 'image'))

            result = await service.full_pipeline(
                topic=schedule.get('topic'),
                direct_url=schedule.get('direct_url'),
                auto_upload=schedule.get('auto_upload', False)
            )

            # 실행 기록 업데이트
            self.update_schedule(schedule['id'], {
                'last_run': datetime.now().isoformat(),
                'run_count': schedule.get('run_count', 0) + 1,
                'last_result': 'success' if result.success else 'failed'
            })

            if result.success:
                self.logger.info(f"Scheduled pipeline completed: {result.video_path}")
            else:
                self.logger.error(f"Scheduled pipeline failed: {result.error}")

        except Exception as e:
            self.logger.error(f"Scheduled pipeline error: {e}")
            self.update_schedule(schedule['id'], {
                'last_run': datetime.now().isoformat(),
                'last_result': f'error: {str(e)}'
            })

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
