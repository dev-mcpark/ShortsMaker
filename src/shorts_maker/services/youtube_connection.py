"""Cancellable auth-only subprocess; OAuth credentials stay in the existing uploader."""

import asyncio
import json
import sys
from datetime import datetime

from shorts_maker.uploader.youtube_uploader import AUTH_TIMEOUT_SECONDS, validate_authorization_url
from shorts_maker.utils.config import PROJECT_ROOT


class YouTubeConnection:
    def __init__(self):
        self.running = False
        self.message = '저장된 업로드 인증은 버튼을 눌러 확인하세요.'
        self.authorization_url = ''
        self.checked_at = ''
        self._cancel = None

    def cancel(self):
        if self._cancel:
            self._cancel.set()

    async def run(self, *, interactive: bool):
        if self.running:
            raise ValueError('진행 중인 인증 작업이 끝난 뒤 확인하세요.')
        self.running = True
        self.authorization_url = self.checked_at = ''
        self.message = 'Google 로그인 대기 중 · 기본 브라우저를 확인하세요.' if interactive else '저장된 인증을 확인하고 있습니다.'
        self._cancel = asyncio.Event()
        process, reader, cancelled = None, None, None
        ready, error_code, stop_message = False, '', ''
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'shorts_maker.uploader.youtube_uploader',
                '--auth-only' if interactive else '--auth-check', '--json-progress',
                cwd=PROJECT_ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)

            async def read_result():
                nonlocal ready, error_code
                async for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get('event') == 'authorization_url':
                        self.authorization_url = validate_authorization_url(event['url'])
                    elif event.get('event') == 'ready':
                        ready = True
                    elif event.get('event') == 'error':
                        error_code = event.get('code')
                return await process.wait()

            reader = asyncio.create_task(read_result())
            cancelled = asyncio.create_task(self._cancel.wait())
            done, _ = await asyncio.wait((reader, cancelled), timeout=AUTH_TIMEOUT_SECONDS, return_when=asyncio.FIRST_COMPLETED)
            if reader not in done:
                stop_message = ('인증 대기 시간이 끝났습니다. 로그인·승인과 저장된 인증 상태를 확인하세요.' if not done
                                else '인증 대기를 취소했습니다. 저장된 인증 상태는 확인 버튼으로 다시 점검하세요.')
                self.message = '인증 대기를 종료하고 있습니다.'
                return
            code = await reader
            if code == 0 and ready:
                self.checked_at = datetime.now().astimezone().strftime('%m-%d %H:%M:%S %Z')
                self.message = '저장 인증 준비 완료 · 실제 업로드 시 권한을 다시 확인합니다.'
            elif error_code == 'busy':
                self.message = '다른 인증 작업이 진행 중입니다. 끝난 뒤 확인하세요.'
            elif error_code == 'client_missing':
                self.message = 'OAuth 클라이언트 파일이 없습니다. 사용 안내의 YouTube 연결 설정을 확인하세요.'
            else:
                self.message = '인증을 완료하지 못했습니다. Google 로그인·승인과 OAuth 설정을 확인한 뒤 직접 다시 연결하세요.'
        except asyncio.CancelledError:
            self.message = '인증 대기가 중단됐습니다. 저장된 인증 상태를 다시 확인하세요.'
            raise
        except (OSError, ValueError, KeyError, TypeError):
            self.message = '인증 결과를 확인할 수 없습니다. OAuth 설정과 저장된 인증을 확인하세요.'
        finally:
            if process and process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
            for task in (reader, cancelled):
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(*(task for task in (reader, cancelled) if task), return_exceptions=True)
            self.running = False
            if stop_message:
                self.message = stop_message
            self.authorization_url = ''
            self._cancel = None
