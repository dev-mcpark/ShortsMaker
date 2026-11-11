import os
import json
import asyncio
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings

AUTH_TIMEOUT_SECONDS = 300

class YouTubeAuthRequired(RuntimeError):
    """Upload never started because its account could not be authenticated."""


def validate_authorization_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'accounts.google.com'
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('Google 로그인 주소를 확인할 수 없습니다.')
    return url


@contextmanager
def _authentication_lock(token: Path):
    lock = token.with_name(token.name + '.auth.lock.sqlite3')
    if token.is_symlink() or lock.is_symlink():
        raise ValueError('인증 파일의 연결 경로를 확인하세요.')
    lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(descriptor)
    db = sqlite3.connect(lock, timeout=0, isolation_level=None)
    try:
        try:
            db.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError as error:
            if error.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
            raise YouTubeAuthRequired('YOUTUBE_AUTH_BUSY: 다른 인증 작업이 끝난 뒤 확인하세요.') from None
        yield
    finally:
        db.close()


def _save_token(token: Path, content: str):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=token.parent, prefix='.token_', delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        if token.is_symlink():
            raise ValueError('인증 파일의 연결 경로가 바뀌었습니다.')
        os.replace(temporary, token)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class YouTubeUploader:
    def __init__(self):
        self.logger = get_logger(__name__)
        self.scopes = ["https://www.googleapis.com/auth/youtube.upload"]
        self.api_service_name = "youtube"
        self.api_version = "v3"
        self.client_secrets_file = str(settings.client_secrets_path)
        self.token_file = str(settings.token_file_path)

    def get_authenticated_service(self, *, interactive: bool = True, on_authorization_url=None):
        with _authentication_lock(Path(self.token_file)):
            return self._authenticate(interactive=interactive, on_authorization_url=on_authorization_url)

    def _authenticate(self, *, interactive: bool, on_authorization_url):
        creds = None
        # token.json 파일에 저장된 인증 정보가 있는지 확인 (보안: JSON 형식 사용)
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r', encoding='utf-8') as token:
                    token_data = json.load(token)
                    if not isinstance(token_data, dict):
                        raise ValueError('invalid token structure')
                    creds = Credentials.from_authorized_user_info(token_data, self.scopes)
            except (json.JSONDecodeError, ValueError):
                self.logger.warning('저장된 토큰 형식을 확인할 수 없어 재인증이 필요합니다.')
                creds = None

        # 인증 정보가 없거나 유효하지 않으면 로그인 시도
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    self.logger.warning('저장된 토큰 갱신에 실패했습니다. 인증 정보를 확인하세요.')
                    creds = None

            if not creds or not creds.valid:
                if not interactive:
                    raise RuntimeError("YOUTUBE_AUTH_REQUIRED: YouTube 업로드 계정을 다시 연결하세요.")
                if not os.path.exists(self.client_secrets_file):
                    raise FileNotFoundError(f"{self.client_secrets_file} 파일이 없습니다. Google Console에서 다운로드해주세요.")

                flow = InstalledAppFlow.from_client_secrets_file(
                    self.client_secrets_file, self.scopes)
                original_url = flow.authorization_url
                def authorization_url(**kwargs):
                    url, state = original_url(**kwargs)
                    validate_authorization_url(url)
                    if on_authorization_url:
                        on_authorization_url(url)
                    return url, state
                flow.authorization_url = authorization_url
                options = {'port': 0, 'timeout_seconds': AUTH_TIMEOUT_SECONDS}
                if on_authorization_url:
                    options['authorization_prompt_message'] = None
                creds = flow.run_local_server(**options)

            if not creds or not creds.valid:
                raise YouTubeAuthRequired('YOUTUBE_AUTH_REQUIRED: 유효한 인증을 받지 못했습니다.')
            _save_token(Path(self.token_file), creds.to_json())

        return build(self.api_service_name, self.api_version, credentials=creds)

    async def upload(self, video_path: str, metadata: dict):
        """Run the blocking Google client without freezing the UI loop."""
        return await asyncio.to_thread(self._upload_sync, video_path, metadata)

    @staticmethod
    def build_upload_body(metadata: dict) -> dict:
        """Prepare the exact private request fields for submission and local audit."""
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be a dictionary")
        title = metadata.get("title", "AI Generated Shorts")
        description = metadata.get("description", "Created by ShortsMaker")
        tags = metadata.get("tags", ["shorts", "ai"])
        synthetic_media = metadata.get("contains_synthetic_media", True)
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise ValueError("tags must be a list of strings")
        if not isinstance(synthetic_media, bool):
            raise ValueError("contains_synthetic_media must be a boolean")
        return {
            "snippet": {"title": title, "description": description,
                        "tags": list(tags), "categoryId": "22", "defaultLanguage": "ko"},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": synthetic_media},
        }

    def _upload_sync(self, video_path: str, metadata: dict):
        self.logger.info(f"Starting upload to YouTube: {video_path}")
        try:
            body = self.build_upload_body(metadata)
            try:
                youtube = self.get_authenticated_service()
            except Exception as error:
                raise YouTubeAuthRequired("YOUTUBE_AUTH_REQUIRED: YouTube 업로드 계정을 다시 연결하세요.") from error

            media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media
            )
            
            self.logger.info("Uploading file...")
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    self.logger.info(f"Uploaded {int(status.progress() * 100)}%")

            self.logger.info(f"Upload Successful! Video ID: {response.get('id')}")
            self.logger.info(f"Video URL: https://youtube.com/shorts/{response.get('id')}")
            return response.get('id')

        except YouTubeAuthRequired:
            raise
        except HttpError as e:
            self.logger.error(f"An HTTP error occurred: {e.resp.status} - {e.content}")
        except Exception as e:
            self.logger.error(f"An error occurred during upload: {e}")
        return None


def auth_command(arguments):
    if arguments == ['--auth-only']:
        YouTubeUploader().get_authenticated_service()
        print('YouTube upload authorization ready.')
        return 0
    if arguments not in (['--auth-only', '--json-progress'], ['--auth-check', '--json-progress']):
        raise ValueError('Usage: python -m shorts_maker.uploader.youtube_uploader --auth-only')
    def emit_url(url):
        print(json.dumps({'event': 'authorization_url', 'url': url}), flush=True)
    try:
        YouTubeUploader().get_authenticated_service(interactive=arguments[0] == '--auth-only', on_authorization_url=emit_url)
    except Exception as error:
        code = ('busy' if isinstance(error, YouTubeAuthRequired) and str(error).startswith('YOUTUBE_AUTH_BUSY')
                else 'client_missing' if isinstance(error, FileNotFoundError) else 'auth_required')
        print(json.dumps({'event': 'error', 'code': code}), flush=True)
        return 1
    print(json.dumps({'event': 'ready'}), flush=True)
    return 0


if __name__ == '__main__':
    import sys
    raise SystemExit(auth_command(sys.argv[1:]))
