# ShortsMaker 🎬

AI-powered YouTube Shorts automation pipeline using Veo3 (Video) or Imagen 3 (Image).
Automatically plans, generates, edits, and uploads YouTube Shorts based on trending topics.

## ✨ Features
- **Auto-Planning:** Fetches trending news via RSS and uses GPT-4o-mini to write scripts.
- **AI Generation:** Creates visuals using Google **Veo 2** (Video Mode) or **Imagen 3** (Image Mode).
- **Auto-Editing:** Composes video, TTS voiceover, subtitles, and BGM using `moviepy`.
- **Orchestration:** Fully managed by **Prefect** for retries, scheduling, and monitoring.
- **YouTube Upload:** Automatically uploads the final video as a private Short.

## 🛠️ Setup

### 1. Prerequisites
- Python 3.12+
- `uv` (recommended) or `pip`
- Google Cloud Project with Vertex AI enabled
- OpenAI API Key

### 2. Installation
```bash
# Clone the repository
git clone <repository_url>
cd ShortsMaker

# Install dependencies
uv sync  # or: pip install -r requirements.txt
```

### 3. Environment Config
Create a `.env` file in the root directory:
```ini
OPENAI_API_KEY=sk-...
GCP_PROJECT_ID=your-project-id
GCP_LOCATION=us-central1
GENERATION_MODE=image  # or 'video'
```

---

## 🔑 Authentication Setup (Critical)

This project requires **two distinct Google credentials** to function properly. Place both files in the project root directory.

### 1. Vertex AI (Image/Video Generation) -> `service_account.json`
Required for generating content using Google's Veo or Imagen models.

1. Go to **Google Cloud Console** > **IAM & Admin** > **Service Accounts**.
2. Create a new Service Account.
3. Grant the **"Vertex AI User"** role to this account.
4. Create and download the JSON key.
5. Rename the downloaded file to **`service_account.json`** and place it in the project root.

### 2. YouTube Data API (Upload) -> `client_secrets.json`
Required for uploading the final video to YouTube on your behalf.

1. Go to **Google Cloud Console** > **APIs & Services** > **Credentials**.
2. Click **Create Credentials** > **OAuth client ID**.
3. Select application type: **Desktop App**.
4. Download the JSON file.
5. Rename the downloaded file to **`client_secrets.json`** and place it in the project root.
6. *Note: On the first run, a browser window will open asking you to log in to your YouTube account.*

---

## 🚀 Usage

### 1. Run the ShortsMaker Studio
Start the local desktop app:
```bash
python src/shorts_maker/gui.py
```
This will launch a web interface at `http://localhost:8080`.

### 2. Workflow
1.  **Planning Tab:**
    *   Choose "Auto-Discovery" or enter a URL.
    *   Click "Generate Script".
    *   **Edit the JSON script** directly in the editor.
    *   Click "Confirm & Save".

2.  **Generation Tab:**
    *   Click "Start Production".
    *   Watch the live logs as the AI generates visuals and voiceovers.
    *   The final video will appear in the Preview player.

3.  **Publishing Tab:**
    *   Review/Edit metadata.
    *   Click "Upload to YouTube".

## 🛠️ Configuration
*   **API Keys:** Configure in the sidebar or via `.env`.
*   **Mode:** Toggle between 'Video' (Veo) and 'Image' (Imagen) modes in the sidebar.

---

## 🧑‍💻 Development Workflow

The system is designed to **automatically reflect code changes**.

1. **Edit Code:** Modify `script_planner.py` or `video_editor.py` in your IDE.
2. **Save:** Just save the file.
3. **Run:** Click **Run** in the Prefect Dashboard. The Worker will load the latest code immediately.

> **Note:** You only need to re-deploy (`python src/shorts_maker/main.py`) if you change the **Flow name**, **Schedule**, or **Parameters**. For logic changes, no action is needed.

## 📁 Project Structure
- `src/shorts_maker/planner`: Script writing logic (GPT-4o).
- `src/shorts_maker/generator`: Image/Video generation (Vertex AI).
- `src/shorts_maker/editor`: Video editing & composition (MoviePy).
- `src/shorts_maker/uploader`: YouTube API integration.
- `flows/`: Prefect orchestration logic.
