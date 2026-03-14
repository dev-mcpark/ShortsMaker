import os
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings

class YouTubeUploader:
    def __init__(self):
        self.logger = get_logger(__name__)
        self.scopes = ["https://www.googleapis.com/auth/youtube.upload"]
        self.api_service_name = "youtube"
        self.api_version = "v3"
        self.client_secrets_file = str(settings.client_secrets_path)
        self.token_file = str(settings.token_file_path)

    def get_authenticated_service(self):
        creds = None
        # token.json 파일에 저장된 인증 정보가 있는지 확인 (보안: JSON 형식 사용)
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r', encoding='utf-8') as token:
                    token_data = json.load(token)
                    creds = Credentials.from_authorized_user_info(token_data, self.scopes)
            except (json.JSONDecodeError, ValueError) as e:
                self.logger.warning(f"토큰 파일 손상됨, 재인증 필요: {e}")
                creds = None

        # 인증 정보가 없거나 유효하지 않으면 로그인 시도
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    self.logger.warning(f"토큰 갱신 실패, 재인증 진행: {e}")
                    os.remove(self.token_file)
                    creds = None

            if creds is None:
                if not os.path.exists(self.client_secrets_file):
                    raise FileNotFoundError(f"{self.client_secrets_file} 파일이 없습니다. Google Console에서 다운로드해주세요.")

                flow = InstalledAppFlow.from_client_secrets_file(
                    self.client_secrets_file, self.scopes)
                creds = flow.run_local_server(port=0)

            # 인증 정보를 JSON 형식으로 안전하게 저장
            with open(self.token_file, 'w', encoding='utf-8') as token:
                token.write(creds.to_json())

        return build(self.api_service_name, self.api_version, credentials=creds)

    async def upload(self, video_path: str, metadata: dict):
        self.logger.info(f"Starting upload to YouTube: {video_path}")
        try:
            youtube = self.get_authenticated_service()
            
            body = {
                "snippet": {
                    "title": metadata.get("title", "AI Generated Shorts"),
                    "description": metadata.get("description", "Created by ShortsMaker"),
                    "tags": metadata.get("tags", ["shorts", "ai"]),
                    "categoryId": "22" # People & Blogs
                },
                "status": {
                    "privacyStatus": "private", # 처음에는 안전하게 비공개로 업로드
                    "selfDeclaredMadeForKids": False
                }
            }

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

        except HttpError as e:
            self.logger.error(f"An HTTP error occurred: {e.resp.status} - {e.content}")
        except Exception as e:
            self.logger.error(f"An error occurred during upload: {e}")
        return None