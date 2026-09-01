# MedScribe AI
**Powered by Google Cloud Agent Platform** &bull; **Author:** Marshell Rodrigues

MedScribe AI is a modern clinical documentation and speech transcription platform that transforms medical consultations into structured clinical notes. It supports two primary modes:
1. **Live Real-Time Scribe**: Low-latency bidirectional live microphone streaming with real-time text feedback.
2. **Batch Audio File Scribe**: Batch audio upload (`WAV`, `MP3`, `M4A`, `FLAC`, `OGG`, `WebM`) with speaker diarization and structured SOAP clinical note synthesis.

---

## 🚀 Live Demo on Cloud Run

- **URL**: [https://medscribe-ai-hwgvfcrogq-uc.a.run.app](https://medscribe-ai-hwgvfcrogq-uc.a.run.app)

---

## ✨ Key Features

- **Gemini Transcribe 3.5 Live Preview**: Real-time bidirectional streaming ASR via the Google GenAI Multimodal Live API (`gemini-3.5-transcribe-live-preview`), delivering instantaneous transcription chunks over WebSockets.
- **Dynamic STT Engine Selection**: Switch between **Gemini Transcribe 3.5 Live Preview**, **Chirp 3** (Speech-to-Text V2 Multilingual), and **Chirp 2** (Speech-to-Text V2 Streaming).
- **Batch Audio File Upload & Demo Player**: Drag-and-drop or select recorded audio files, listen via the built-in audio player, or test instantly with the one-click **⚡ Try Demo Audio** button.
- **Multimodal Speaker Diarization**: Leverages Gemini multimodal capabilities to identify and label conversational turns between `**Doctor:**` and `**Patient:**`.
- **Structured Clinical SOAP Notes**: Synthesizes comprehensive medical notes including:
  - **Subjective**: Chief complaint, history of present illness (HPI), review of systems (ROS).
  - **Objective**: Vital signs, physical examination findings, observations.
  - **Assessment**: Primary clinical impression and differential diagnosis.
  - **Plan**: Diagnostic testing, prescriptions, medications, therapies, patient education, and follow-up.
- **Next-Gen Gemini Reasoning Models**: Powered by **Gemini 3.7 Flash**, **Gemini 3.6 Flash**, **Gemini 3.5 Flash**, **Gemini 3.5 Flash-Lite**, **Gemini 2.5 Flash**, and **Gemini 2.5 Pro** routed through Vertex AI.
- **Edge Voice Activity Detection (VAD)**: Frontend audio processing dynamically pauses data transmission during silence, conserving bandwidth and token usage.
- **Modern Medical Dashboard**: Side-by-side split layout with animated audio waveform visualizer, real-time live captions, and rendered Markdown clinical documentation with one-click copy.

---

## 🏗️ Technical Architecture

### 1. 🎙️ Live Real-Time Scribe Pipeline
```
[Browser Mic (16kHz PCM)] ──(WebSocket)──> [FastAPI Backend]
                                               │
               ┌───────────────────────────────┴───────────────────────────────┐
               ▼                                                               ▼
  [Gemini Multimodal Live API]                                    [Speech-to-Text V2 API]
  (gemini-3.5-transcribe-live-preview)                           (Chirp 3 / Chirp 2)
               │                                                               │
               └───────────────────────────────┬───────────────────────────────┘
                                               ▼
                              [Real-Time Captions Streamed to UI]
                                               │
                                 (Live Session Completed)
                                               ▼
                                  [Gemini Reasoning Model]
                               (Gemini 3.7 / 3.6 / 3.5 Flash)
                                               ▼
                             [Diarized Transcript & SOAP Note]
```

### 2. 📁 Batch Audio Upload Pipeline
```
[Audio File (WAV/MP3/M4A/etc.)] ──(POST /api/upload-audio)──> [FastAPI Backend]
                                                                     │
                                                      [Vertex AI Gemini Multimodal]
                                                      (Gemini 3.7/3.6/3.5/2.5 Flash)
                                                                     │
                                                                     ▼
                                                     [Diarized Transcript & SOAP Note]
```

---

## 📋 Prerequisites

- **Python 3.10+**
- **Google Cloud Project** with the following APIs enabled:
  - `aiplatform.googleapis.com` (Vertex AI API)
  - `speech.googleapis.com` (Speech-to-Text V2)
  - `cloudbuild.googleapis.com` (for Cloud Run deployments)
  - `artifactregistry.googleapis.com` (for Container Registry)
  - `run.googleapis.com` (Cloud Run)

---

## 🔑 Required IAM Roles

Ensure the active Service Account (or Cloud Run service identity) has the following roles:
- **`Vertex AI User`** (`roles/aiplatform.user`) - For Gemini models and Multimodal Live API.
- **`Speech Client`** (`roles/speech.client`) or **`Speech Admin`** (`roles/speech.admin`) - For Speech-to-Text V2 Chirp models.

For Cloud Run deployment:
- **`Cloud Build Editor`** (`roles/cloudbuild.builds.editor`)
- **`Storage Admin`** (`roles/storage.admin`)
- **`Artifact Registry Writer`** (`roles/artifactregistry.writer`)
- **`Cloud Run Admin`** (`roles/run.admin`)
- **`Service Account User`** (`roles/iam.serviceAccountUser`)

---

## ⚙️ Environment Setup & Local Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/marshell08/GCP-MedScribe-AI.git
   cd GCP-MedScribe-AI
   ```

2. **Create a virtual environment and install dependencies:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables (Optional for local development):**
   Create a `.env` file in the root directory:
   ```env
   GOOGLE_CLOUD_PROJECT=your_project_id
   GOOGLE_CLOUD_LOCATION=us-central1
   GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service-account-key.json
   ```

4. **Run the Application:**
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8080 --reload
   ```
   Open your browser at: `http://localhost:8080`

---

## 🚀 Cloud Run Deployment

Deploy directly to Google Cloud Run using the automated deployment script:

```bash
chmod +x deploy.sh
./deploy.sh
```

The script will:
1. Package the application and build the container image using Google Cloud Build.
2. Push the image to Artifact Registry (`us-central1-docker.pkg.dev/$PROJECT_ID/medscribe-repo/medscribe-ai:latest`).
3. Deploy the container service to Google Cloud Run in `us-central1` with unauthenticated access.

---

## 🩺 Usage Guide

### Mode 1: Live Real-Time Scribe
1. Select the **Live Real-Time Scribe** tab.
2. Choose your **Real-Time Transcription Engine** (e.g., `Gemini Transcribe 3.5 Live Preview` or `Chirp 3`).
3. Select your desired **AI Model for SOAP Notes** (e.g., `Gemini 3.7 Flash`, `Gemini 3.6 Flash`).
4. Click **Start Live Session** and speak into your microphone.
5. Watch the real-time transcript stream on the left panel.
6. Click **End Session & Generate SOAP** to generate the speaker-diarized breakdown and clinical SOAP notes.

### Mode 2: Batch Audio File Scribe
1. Select the **Batch Audio Upload** tab.
2. Drag and drop any consultation audio file (`.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac`, `.webm`) or click **⚡ Try Demo Audio**.
3. Listen to the audio with the built-in player.
4. Select the **AI Processing Engine** (e.g., `Gemini Transcribe 3.5 Preview`, `Gemini 3.7 Flash`).
5. Click **Process Audio & Generate Clinical Notes**.
6. View the complete speaker-diarized dialogue and structured SOAP notes, and use the **Copy** button to export to your clipboard.

---

## 🛡️ License & Credits

- **Author**: Marshell Rodrigues
- **Platform**: Google Cloud Agent Platform & Vertex AI
