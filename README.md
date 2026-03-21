# MedScribe AI

MedScribe AI is a real-time proof-of-concept application that captures medical conversations via a browser microphone, streams the audio to Google Cloud Speech-to-Text (STT) V2 for live transcription, and post-processes the dialogue using Vertex AI (Gemini 2.5 Flash) to generate a Speaker-Diarized transcript and a formatted Clinical SOAP Note.

## Architecture Overview

The codebase uses a Two-Step Architecture to bypass STT V2 streaming limitations:
1. **Real-Time Transcription:** The frontend uses the `AudioContext` to continuously stream `LINEAR16` 16000Hz PCM audio over WebSockets to a FastAPI backend. The audio is routed to the Google Cloud STT V2 `medical_conversation` model to deliver ultra-fast, un-diarized live text to the UI.
2. **Post-Session Diarization & Insights:** Upon ending the session, the monolithic transcript is sent via REST API to Vertex AI using Gemini 2.5 Flash, which intelligently re-structures the dialogue by Speaker (Doctor/Patient) and synthesizes a professional SOAP (Subjective, Objective, Assessment, Plan) Markdown note.

---

## Prerequisites

To run this application, you must have:
- **Python 3.10+**
- **A Google Cloud Project** with the following APIs enabled:
  - Cloud Speech-to-Text V2 API
  - Vertex AI API (for Gemini)
- **A Google Cloud Service Account JSON Key** (with permissions to use STT in your project).
- **A Vertex AI API Key** (Generated from the Google Cloud Platform Console -> APIs & Services -> Credentials).

---

## Environment Setup

1. **Clone the repository and enter the directory:**
   ```bash
   git clone <your-repo-url>
   cd PointClickCare
   ```

2. **Create a virtual environment and install dependencies:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure the Environment Variables:**
   Create a `.env` file in the root directory and add the following keys. Ensure you replace the placeholders with your actual Google Cloud Project ID and Location (e.g., `us-central1`).

   ```env
   # Your Vertex AI API Key (must be tied to a GCP Project, NOT consumer AI Studio)
   GEMINI_API_KEY=your_vertex_ai_api_key

   # Your Google Cloud Project configuration
   GOOGLE_CLOUD_PROJECT=your_gcp_project_id
   GOOGLE_CLOUD_LOCATION=your_gcp_region
   ```

4. **Attach the Google Cloud Service Account (ADC):**
   The Google Cloud STT V2 Client requires a local Service Account JSON file to authenticate the live audio stream. 
   
   Place your downloaded Service Account JSON file somewhere on your machine.
   Update the exact absolute path to your Service Account file in `main.py` on line `29`:
   ```python
   # main.py
   adc_path = "/path/to/your/service-account-key.json"
   ```

---

## Running the Application

1. **Start the FastAPI Backend Server:**
   Ensure your virtual environment is activated, then run:
   ```bash
   python main.py
   ```
   *The server will start locally on port 8080.*

2. **Open the Medical Dashboard:**
   Open your browser and navigate to:
   ```text
   http://localhost:8080/static/index.html
   ```

3. **Usage Flow:**
   - Click **"Start Session"** and allow Microphone Permissions.
   - Speak some conversational medical dialogue. You will see the raw text stream in real-time.
   - Click **"End Session"**. Wait 2-5 seconds for Gemini to process the text.
   - The UI will dynamically replace the raw transcript with the Diarized version, and the Right Panel will populate with the structured clinical SOAP summary!

---

## Troubleshooting

- **`400 The medical_conversation model must have automatic punctuation enabled.`**: Ensure your `stt_config` in `main.py` has `enable_automatic_punctuation=True`.
- **`401 UNAUTHENTICATED: API keys are not supported by this API.`**: Ensure the `GEMINI_API_KEY` in your `.env` is specifically generated from the **Google Cloud Console**, not the generic Google AI Studio portal. The backend explicitly routes the HTTP REST call to `aiplatform.googleapis.com` (Vertex AI).
- **Silence on the UI / No Text**: Check your browser Console Logs (F12). If the WebSocket is connecting and the Microphone is capturing, ensure your Service Account JSON pathway inside `main.py` is correct. The backend STT generator will silently fail if it cannot locate the ADC token.
# GCP-MedScribe-AI
