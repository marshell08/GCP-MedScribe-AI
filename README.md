# MedScribe AI

MedScribe AI is a real-time application that captures medical conversations via a browser microphone, streams the audio to Google Cloud Speech-to-Text (STT) V2 for live transcription, and leverages Gemini models to generate Speaker-Diarized dialogue breakdowns and structured Clinical SOAP Notes at the end of the session.

## Key Features

- **Dynamic Model Selection**: Choose between **Chirp 3** (Advanced Multilingual) and **Chirp 2** for live transcription, and select from various **Gemini 2.5/3.1** options for post-session analytics.
- **Edge Voice Activity Detection (VAD)**: The frontend locally calculates sound energy to pause audio transmission during silence, avoiding flooding WebSocket pipes with background noise.
- **Stream Reconnection Loops**: The backend continuously monitors and recreates direct Speech pipes upon inactivity aborts, keeping the session uninterrupted during prolonged pauses.
- **Dynamic Region Routing**: Automatically switches API endpoints and project region anchors depending upon the chosen model's availability footprint (e.g., fallback routing Chirp 2 into `us-central1` zone meshes).
- **Consolidated Layout Layouts**: Redefined side-by-side splits with real-time text panels and responsive SOAP summaries at the core.

---

## Prerequisites

To run or deploy this application, you must have:
- **Python 3.10+**
- **A Google Cloud Project** with the following APIs enabled:
  - `speech.googleapis.com` (Speech-to-Text V2)
  - `aiplatform.googleapis.com` (Vertex AI API)
  - `cloudbuild.googleapis.com` (for Cloud Run deployments)
  - `artifactregistry.googleapis.com` (for Cloud Run deployments)

---

### 🔑 Required IAM Roles

Depending on your execution mode, ensure the active credentials holding your session hold the following bindings:

#### 💻 For Local Running (via Service Account JSON)
The local service account (referenced in `main.py`) requires:
- **`Speech Client`** (`roles/speech.client`) - To process live audio streams.

#### 🚀 For Cloud Run Deployments (via `deploy.sh`)
The account triggering the terminal commands requires:
- **`Cloud Build Editor`** (`roles/cloudbuild.builds.editor`)
- **`Storage Admin`** (`roles/storage.admin`) - To upload source triggers.
- **`Artifact Registry Writer`** (`roles/artifactregistry.writer`) - To push compiled triggers.
- **`Cloud Run Admin`** (`roles/run.admin`) - To allocate revision slots.
- **`Service Account User`** (`roles/iam.serviceAccountUser`) - To bind computation identities.

---

## Environment Setup

1. **Clone the repository and enter the directory:**
   ```bash
   git clone <your-repo-url>
   cd <repository-name>
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

## Cloud Run Deployment (Serverless)

You can deploy this application securely onto **Google Cloud Run** using the provided containerization wrapper and pipeline.

### 🚀 Automated Deployment
1.  **Grant Executability to your deploy script**:
    ```bash
    chmod +x deploy.sh
    ```
2.  **Execute the Pipeline**:
    ```bash
    ./deploy.sh
    ```
    This script automatically compiles your workspace into **Artifact Registry** using `gcloud builds` and allocates a managed revision slot securely.

### 🛡️ Post-Deployment Authentication Setup
Workloads in Cloud Run operate under the **Default Compute Engine Service Account**. To authorize audio stream processing, ensure that identity holds the Speech Admin API bindings:
```bash
gcloud projects add-iam-policy-binding [YOUR_PROJECT_ID] \
    --member="serviceAccount:[PROJECT_NUMBER]-compute@developer.gserviceaccount.com" \
    --role="roles/speech.admin"
```

### 🌐 Accessing Private/Protected Services
If your Organization Policy forbids making Cloud Run endpoints fully public (`allUsers`), fire an authentication proxy forwards on your workspace shell to visit safely without standard 403 Forbidden gates:
```bash
gcloud run services proxy medscribe-ai --region=us-central1 --port=8080
```
Then visit: 👉 `http://localhost:8080`

---

## Troubleshooting

- **`400 The medical_conversation model must have automatic punctuation enabled.`**: Ensure your `stt_config` in `main.py` has `enable_automatic_punctuation=True`.
- **`401 UNAUTHENTICATED: API keys are not supported by this API.`**: Ensure the `GEMINI_API_KEY` in your `.env` is specifically generated from the **Google Cloud Console**, not the generic Google AI Studio portal. The backend explicitly routes the HTTP REST call to `aiplatform.googleapis.com` (Vertex AI).
- **Silence on the UI / No Text**: Check your browser Console Logs (F12). If the WebSocket is connecting and the Microphone is capturing, ensure your Service Account JSON pathway inside `main.py` is correct. The backend STT generator will silently fail if it cannot locate the ADC token.
