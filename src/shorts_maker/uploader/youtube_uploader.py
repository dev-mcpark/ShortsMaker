import os
import pickle
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError

class YouTubeUploader:
    def __init__(self):
        self.scopes = ["https://www.googleapis.com/auth/youtube.upload"]
        self.api_service_name = "youtube"
        self.api_version = "v3"
        self.client_secrets_file = "client_secrets.json"
        self.token_file = "token.pickle"

    def get_authenticated_service(self):
        creds = None
        # token.pickle 파일에 저장된 인증 정보가 있는지 확인
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)
        
        # 인증 정보가 없거나 유효하지 않으면 로그인 시도
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.client_secrets_file):
                    raise FileNotFoundError(f"{self.client_secrets_file} 파일이 없습니다. Google Console에서 다운로드해주세요.")
                
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.client_secrets_file, self.scopes)
                creds = flow.run_local_server(port=0)
            
            # 인증 정보를 다음 실행을 위해 저장
            with open(self.token_file, 'wb') as token:
                pickle.dump(creds, token)

        return build(self.api_service_name, self.api_version, credentials=creds)

    async def upload(self, video_path: str, metadata: dict):
        print(f"Starting upload to YouTube: {video_path}")
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
            
            print("Uploading file...")
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"Uploaded {int(status.progress() * 100)}%")
            
            print(f"Upload Successful! Video ID: {response.get('id')}")
            print(f"Video URL: https://youtube.com/shorts/{response.get('id')}")
            return response.get('id')

        except HttpError as e:
            print(f"An HTTP error occurred: {e.resp.status} - {e.content}")
        except Exception as e:
            print(f"An error occurred during upload: {e}")
        return None