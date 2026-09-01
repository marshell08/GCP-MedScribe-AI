"""Medical Scribe API leveraging Speech-to-Text V2 and Gemini Transcribe 3.5 Live."""

import asyncio
import logging
import json
import os
import sys
import queue
import threading
import base64
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

import google.auth
import google.auth.transport.requests
from google import genai
from google.genai import types
from google.cloud import speech_v2
from google.oauth2 import service_account
import httpx
import requests

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("scribe_app")

APP_NAME = "medical-scribe-live"

# Global dictionary to persist transcripts across WebSocket reconnections
session_transcripts = {}

# Credentials and project configuration
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "gedemo-08")
DEFAULT_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
adc_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/home/marshell/antigravity/gedemo-08-62f02692104f.json")

app = FastAPI(title="MedScribe AI")

# Mount static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def get_genai_client(location: str = "global") -> genai.Client:
    """Create a Google GenAI Client configured for Vertex AI."""
    try:
        return genai.Client(vertexai=True, project=PROJECT_ID, location=location)
    except Exception as e:
        logger.warning(f"Error initializing GenAI Client with location {location}: {e}")
        return genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")


def get_stt_credentials():
    """Load STT credentials from ADC path if valid, otherwise fallback to default."""
    if adc_path and os.path.exists(adc_path):
        try:
            return service_account.Credentials.from_service_account_file(adc_path)
        except Exception as e:
            logger.warning(f"Could not load credentials from {adc_path}: {e}")
    return None


def get_speech_config(stt_model: str):
    """Generate Google Cloud STT V2 RecognitionConfig."""
    features = speech_v2.RecognitionFeatures(
        enable_automatic_punctuation=True,
    )
    explicit_decoding = speech_v2.ExplicitDecodingConfig(
        encoding=speech_v2.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        audio_channel_count=1,
    )
    
    target_model = "chirp_2" if stt_model == "chirp_2" else "chirp_3"
    logger.info(f"Configuring STT V2 model to use: {target_model}")

    return speech_v2.RecognitionConfig(
        explicit_decoding_config=explicit_decoding,
        model=target_model,
        language_codes=["en-US"],
        features=features,
    )


async def generate_soap_summary(llm_model: str, full_text: str, soap_only: bool = False) -> str:
    """Generate Diarized transcript and structured SOAP summary using Gemini."""
    if soap_only:
        prompt = (
            f"Here is a medical consultation transcript:\n\n{full_text}\n\n"
            "Synthesize a professional, structured clinical SOAP note:\n"
            "- **Subjective**: Chief complaint, history of present illness (HPI), symptoms, duration, and patient remarks.\n"
            "- **Objective**: Physical examination findings, vitals, and clinical observations.\n"
            "- **Assessment**: Primary clinical diagnosis and differential diagnoses.\n"
            "- **Plan**: Treatment plan, medications/prescriptions, diagnostic orders, lifestyle recommendations, and follow-up timeline."
        )
    else:
        prompt = (
            f"Here is a medical consultation transcript:\n\n{full_text}\n\n"
            "Please provide the following outputs:\n"
            "1. **Speaker Diarization**: Reconstruct the dialogue attributing lines correctly to 'Doctor' and 'Patient' based on context. "
            "CRITICAL: You MUST place each speaker's turn on a completely new line. Do NOT combine multiple speakers into a single paragraph. "
            "Format each turn strictly as:\n"
            "**Doctor:** [text]\n\n**Patient:** [text]\n\n"
            "2. **SOAP Summary**: A professional, structured SOAP summary (Subjective, Objective, Assessment, Plan)."
        )

    location = DEFAULT_LOCATION
    target_loc = "global" if any(v in llm_model for v in ["3.5", "3.6", "3.7"]) else location

    # 1. Try Google GenAI SDK with requested model
    try:
        client = get_genai_client(location=target_loc)
        logger.info(f"Calling GenAI generate_content with model {llm_model} in {target_loc}...")
        response = await client.aio.models.generate_content(
            model=llm_model,
            contents=prompt
        )
        if response and response.text and len(response.text.strip()) > 0:
            logger.info(f"Summary generated successfully via GenAI SDK with {llm_model}.")
            return response.text
    except Exception as e:
        logger.warning(f"GenAI SDK call for {llm_model} encountered issue: {e}")

    # 2. Fallback models if primary model is unavailable
    fallback_models = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-pro"]
    for fb_model in fallback_models:
        if fb_model == llm_model:
            continue
        try:
            fb_loc = "global" if any(v in fb_model for v in ["3.5", "3.6", "3.7"]) else location
            client = get_genai_client(location=fb_loc)
            logger.info(f"Attempting fallback SOAP generation with model {fb_model} in {fb_loc}...")
            response = await client.aio.models.generate_content(
                model=fb_model,
                contents=prompt
            )
            if response and response.text and len(response.text.strip()) > 0:
                logger.info(f"Fallback summary generated successfully with {fb_model}.")
                return response.text
        except Exception as fb_err:
            logger.warning(f"Fallback {fb_model} failed: {fb_err}")

    # 3. Direct REST API Fallback
    api_key = os.getenv("GEMINI_API_KEY")
    rest_model = "gemini-2.5-flash" if "transcribe" in llm_model else llm_model
    url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{location}/publishers/google/models/{rest_model}:generateContent"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-goog-api-key"] = api_key
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}

    logger.info(f"Calling Vertex AI REST fallback for model {rest_model}...")
    response = await asyncio.to_thread(requests.post, url, headers=headers, json=payload)
    if response.status_code == 200:
        resp_json = response.json()
        if "candidates" in resp_json and resp_json["candidates"]:
            cand = resp_json["candidates"][0]
            if "content" in cand and "parts" in cand["content"]:
                return cand["content"]["parts"][0]["text"]
    
    raise RuntimeError(f"Vertex API REST error {response.status_code}: {response.text}")


@app.get("/")
async def root():
    """Serve the clinical dashboard."""
    return FileResponse(static_dir / "index.html")


async def process_audio_upload(file_bytes: bytes, mime_type: str, model_name: str) -> dict:
    """Process recorded consultation audio with Gemini for Speaker Diarization and SOAP note."""
    
    # 1. Special handling for native Gemini 3.5 Transcribe Diarization
    if model_name == "gemini-3.5-transcribe-preview":
        try:
            logger.info("Running native Gemini 3.5 Transcribe Diarization via Vertex AI...")
            credentials, _ = google.auth.default()
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            token = credentials.token

            audio_b64 = base64.b64encode(file_bytes).decode("utf-8")
            url = "https://aiplatform.googleapis.com/v1/projects/gedemo-08/locations/global/publishers/google/models/gemini-3.5-transcribe-preview:generateContent"
            payload = {
                "contents": [
                    {"role": "user", "parts": [{"inlineData": {"mimeType": mime_type, "data": audio_b64}}]}
                ],
                "generationConfig": {
                    "audioTranscriptionConfig": {
                        "diarization": True,
                        "languageCodes": ["en-US"]
                    }
                }
            }
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            async with httpx.AsyncClient(timeout=90.0) as http_client:
                resp = await http_client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    resp_json = resp.json()
                    parts = resp_json.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    diarized_lines = []
                    for p in parts:
                        at = p.get("audioTranscription", {})
                        spk = at.get("speakerLabel", "")
                        text = at.get("text", p.get("text", "")).strip()
                        if text:
                            speaker_tag = "Doctor" if spk == "spk:0" else ("Patient" if spk == "spk:1" else ("Speaker " + spk.replace("spk:", "")))
                            diarized_lines.append(f"**{speaker_tag}:** {text}")
                    
                    native_transcript = "\n\n".join(diarized_lines)
                    
                    # Generate SOAP note using Gemini Flash from the native diarized transcript
                    soap_note = await generate_soap_summary(
                        llm_model="gemini-3.7-flash", 
                        full_text=native_transcript,
                        soap_only=True
                    )
                    
                    combined_output = (
                        f"### 1. Speaker Diarized Transcript (Native Gemini 3.5 Transcribe Diarization)\n\n"
                        f"{native_transcript}\n\n"
                        f"---\n\n"
                        f"{soap_note}"
                    )
                    
                    return {
                        "status": "success",
                        "model_used": "gemini-3.5-transcribe-preview (Native Diarization) + gemini-3.7-flash",
                        "content": combined_output
                    }
                else:
                    logger.warning(f"Native transcribe failed with {resp.status_code}: {resp.text}")
        except Exception as native_err:
            logger.warning(f"Native transcribe exception: {native_err}. Falling back to standard pipeline...")

    # 2. Multimodal LLM pipeline
    prompt = (
        "You are an expert AI clinical documentation assistant.\n"
        "Listen carefully to this recorded medical consultation and generate the following structured outputs:\n\n"
        "### 1. Speaker Diarized Transcript\n"
        "Transcribe the entire consultation verbatim, accurately attributing each speaker turn strictly to 'Doctor' or 'Patient' based on acoustic speaker turns and conversational context.\n"
        "Format each turn with clean paragraph breaks:\n"
        "**Doctor:** [Doctor statement]\n\n"
        "**Patient:** [Patient statement]\n\n"
        "### 2. Clinical SOAP Summary\n"
        "Synthesize a professional, structured clinical SOAP note:\n"
        "- **Subjective**: Chief complaint, history of present illness (HPI), symptoms, duration, and patient remarks.\n"
        "- **Objective**: Physical examination findings, vitals, and clinical observations.\n"
        "- **Assessment**: Primary clinical diagnosis and differential diagnoses.\n"
        "- **Plan**: Treatment plan, medications/prescriptions, diagnostic orders, lifestyle recommendations, and follow-up timeline."
    )

    target_model = model_name
    if target_model == "gemini-3.5-transcribe-preview":
        target_model = "gemini-3.7-flash"

    target_loc = "global" if any(v in target_model for v in ["3.5", "3.6", "3.7"]) else DEFAULT_LOCATION

    # Primary multimodal generation call
    try:
        client = get_genai_client(location=target_loc)
        logger.info(f"Processing audio upload ({len(file_bytes)} bytes, {mime_type}) using model {target_model} in {target_loc}...")
        response = await client.aio.models.generate_content(
            model=target_model,
            contents=[
                types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                prompt
            ]
        )
        if response and response.text and len(response.text.strip()) > 0:
            logger.info(f"Audio processing successful with {target_model}.")
            return {
                "status": "success",
                "model_used": target_model,
                "content": response.text
            }
    except Exception as e:
        logger.warning(f"Audio processing with {target_model} failed: {e}. Trying fallback...")

    # Fallbacks
    for fb_model in ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-2.5-flash"]:
        if fb_model == target_model:
            continue
        try:
            fb_loc = "global" if any(v in fb_model for v in ["3.5", "3.6", "3.7"]) else DEFAULT_LOCATION
            client = get_genai_client(location=fb_loc)
            logger.info(f"Attempting fallback audio processing with {fb_model} in {fb_loc}...")
            response = await client.aio.models.generate_content(
                model=fb_model,
                contents=[
                    types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                    prompt
                ]
            )
            if response and response.text and len(response.text.strip()) > 0:
                logger.info(f"Fallback audio processing successful with {fb_model}.")
                return {
                    "status": "success",
                    "model_used": fb_model,
                    "content": response.text
                }
        except Exception as fb_err:
            logger.warning(f"Fallback audio model {fb_model} failed: {fb_err}")

    raise HTTPException(status_code=500, detail="Failed to generate clinical documentation from uploaded audio.")


@app.post("/api/upload-audio")
async def upload_audio_endpoint(
    file: UploadFile = File(...),
    model: str = Form("gemini-3.7-flash")
):
    """Receive uploaded medical audio file and return Diarized Transcript & SOAP Note."""
    try:
        content = await file.read()
        if not content or len(content) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        # Resolve MIME type
        filename = (file.filename or "").lower()
        mime_type = file.content_type or "audio/wav"
        if filename.endswith(".mp3"):
            mime_type = "audio/mp3"
        elif filename.endswith(".m4a"):
            mime_type = "audio/mp4"
        elif filename.endswith(".ogg") or filename.endswith(".oga"):
            mime_type = "audio/ogg"
        elif filename.endswith(".flac"):
            mime_type = "audio/flac"
        elif filename.endswith(".webm"):
            mime_type = "audio/webm"
        elif filename.endswith(".wav"):
            mime_type = "audio/wav"

        result = await process_audio_upload(content, mime_type, model)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in upload_audio_endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/scribe/{session_id}")
async def scribe_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    logger.info("WEBSOCKET CONNECTED: session_id=%s", session_id)

    # Extract dynamic models from query parameters
    query_params = websocket.query_params
    stt_model = query_params.get("stt_model", "gemini-3.5-transcribe-live-preview")
    llm_model = query_params.get("llm_model", "gemini-3.5-transcribe-preview")
    logger.info(f"Session {session_id} - STT Model: {stt_model}, LLM Model: {llm_model}")

    # Persistent transcript to support reconnections
    if session_id not in session_transcripts:
        session_transcripts[session_id] = []
    session_transcript = session_transcripts[session_id]

    loop = asyncio.get_running_loop()
    is_gemini_live = ("gemini" in stt_model.lower() and "live" in stt_model.lower())

    # Queues for audio bytes
    stt_thread_queue = queue.Queue() if not is_gemini_live else None
    async_audio_queue = asyncio.Queue() if is_gemini_live else None

    # Handler for Gemini Transcribe 3.5 Live preview
    async def run_gemini_live_stream():
        logger.info(f"Starting Gemini Live stream task for session {session_id} with model {stt_model}")
        try:
            loc = "global" if "3.5" in stt_model else DEFAULT_LOCATION
            client = get_genai_client(location=loc)
            config = types.LiveConnectConfig(
                response_modalities=[types.Modality.TEXT],
                input_audio_transcription=types.AudioTranscriptionConfig()
            )

            async with client.aio.live.connect(model=stt_model, config=config) as live_session:
                logger.info(f"Gemini Live session connected for {session_id}")

                async def receive_gemini_messages():
                    try:
                        async for response in live_session.receive():
                            if response.server_content:
                                sc = response.server_content
                                if hasattr(sc, "input_transcription") and sc.input_transcription:
                                    it = sc.input_transcription
                                    text = it.text or ""
                                    is_final = bool(it.finished)
                                    if text:
                                        session_transcript.append(text)
                                        await websocket.send_json({
                                            "type": "transcription",
                                            "content": text,
                                            "is_final": is_final,
                                            "engine": "gemini"
                                        })
                                elif hasattr(sc, "model_turn") and sc.model_turn:
                                    for part in sc.model_turn.parts:
                                        if getattr(part, "text", None):
                                            session_transcript.append(part.text)
                                            await websocket.send_json({
                                                "type": "transcription",
                                                "content": part.text,
                                                "is_final": True,
                                                "engine": "gemini"
                                            })
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.error(f"Error receiving from Gemini Live: {e}")

                receive_task = asyncio.create_task(receive_gemini_messages())

                try:
                    while True:
                        chunk = await async_audio_queue.get()
                        if chunk is None:
                            break
                        await live_session.send_realtime_input(
                            audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                        )
                finally:
                    receive_task.cancel()
        except Exception as e:
            logger.error(f"Gemini Live error in session {session_id}: {e}")
            try:
                await websocket.send_json({
                    "type": "transcription",
                    "content": f"[Live Engine Notice: {str(e)}]",
                    "is_final": True
                })
            except Exception:
                pass

    # Handler for Speech-to-Text V2 (Chirp 3 / Chirp 2)
    def run_stt_v2_thread():
        import traceback
        logger.info(f"Starting STT V2 thread for session {session_id}")
        
        try:
            stt_credentials = get_stt_credentials()

            if stt_model == "chirp_2":
                target_location = "us-central1"
                target_endpoint = "us-central1-speech.googleapis.com"
                target_model_name = "chirp_2"
            else:
                target_location = "us"
                target_endpoint = "us-speech.googleapis.com"
                target_model_name = "chirp_3"

            client_opts = {"api_endpoint": target_endpoint}
            if stt_credentials:
                sync_client = speech_v2.SpeechClient(credentials=stt_credentials, client_options=client_opts)
            else:
                sync_client = speech_v2.SpeechClient(client_options=client_opts)
            
            recognizer_suffix = target_model_name.replace("_", "")
            recognizer_id = f"medscribe-{recognizer_suffix}"
            recognizer_str = f"projects/{PROJECT_ID}/locations/{target_location}/recognizers/{recognizer_id}"
            
            try:
                logger.info(f"Ensuring recognizer {recognizer_id} in {target_location}...")
                request = speech_v2.CreateRecognizerRequest(
                    parent=f"projects/{PROJECT_ID}/locations/{target_location}",
                    recognizer_id=recognizer_id,
                    recognizer=speech_v2.Recognizer(
                        default_recognition_config=speech_v2.RecognitionConfig(
                            language_codes=["en-US"],
                            model=target_model_name
                        )
                    )
                )
                operation = sync_client.create_recognizer(request=request)
                operation.result()
                logger.info(f"Created recognizer {recognizer_id}")
            except Exception as e:
                if "AlreadyExists" in str(e) or "already exists" in str(e).lower():
                    pass
                else:
                    logger.warning(f"Recognizer create notice: {e}")

            config = get_speech_config(stt_model)
            streaming_features = speech_v2.StreamingRecognitionFeatures(interim_results=True)
            streaming_config = speech_v2.StreamingRecognitionConfig(
                config=config,
                streaming_features=streaming_features
            )

            stop_flag = [False]
            
            def request_generator():
                yield speech_v2.StreamingRecognizeRequest(
                    recognizer=recognizer_str,
                    streaming_config=streaming_config
                )
                while True:
                    try:
                        chunk = stt_thread_queue.get(timeout=0.1)
                        if chunk is None:
                            stop_flag[0] = True
                            break
                        yield speech_v2.StreamingRecognizeRequest(audio=chunk)
                    except queue.Empty:
                        continue
                        
            while not stop_flag[0]:
                try:
                    responses = sync_client.streaming_recognize(requests=request_generator())
                    for response in responses:
                        for result in response.results:
                            if result.alternatives:
                                alt = result.alternatives[0]
                                text = alt.transcript
                                is_final = result.is_final
                                
                                if is_final:
                                    session_transcript.append(f"Speaker: {text}")

                                asyncio.run_coroutine_threadsafe(
                                    websocket.send_json({
                                        "type": "transcription",
                                        "content": text,
                                        "is_final": is_final
                                    }),
                                    loop
                                )
                except Exception as e:
                    if "Aborted" in str(e) or "Stream timed out" in str(e):
                        logger.info(f"STT stream paused/aborted, continuing... ({e})")
                        import time
                        time.sleep(1)
                        continue
                    else:
                        logger.error(f"STT Inner Error: {e}")
                        break

        except Exception as e:
            logger.error(f"STT Thread Error in {session_id}: {e}")
            traceback.print_exc()

    # Start appropriate background task
    gemini_live_task = None
    if is_gemini_live:
        gemini_live_task = asyncio.create_task(run_gemini_live_stream())
    else:
        stt_thread = threading.Thread(target=run_stt_v2_thread, daemon=True)
        stt_thread.start()

    async def upstream_task():
        """Receive audio bytes and control actions from the frontend."""
        try:
            while True:
                message = await websocket.receive()
                if "bytes" in message:
                    audio_bytes = message["bytes"]
                    if is_gemini_live and async_audio_queue:
                        await async_audio_queue.put(audio_bytes)
                    elif stt_thread_queue:
                        stt_thread_queue.put(audio_bytes)

                elif "text" in message:
                    try:
                        message_data = json.loads(message["text"])
                        if message_data.get("action") == "end_session":
                            logger.info("End session requested. Triggering SOAP summary.")
                            
                            if not session_transcript:
                                await websocket.send_json({
                                    "type": "text",
                                    "content": "No transcript available to summarize."
                                })
                                continue

                            full_text = "\n".join(session_transcript)
                            logger.info(f"Transcript lines: {len(session_transcript)}, chars: {len(full_text)}")
                            
                            try:
                                summary_text = await generate_soap_summary(llm_model, full_text)
                                await websocket.send_json({
                                    "type": "text",
                                    "content": summary_text
                                })
                                logger.info("SOAP summary delivered to client.")
                            except Exception as e:
                                logger.error(f"Failed to generate summary: {e}")
                                await websocket.send_json({
                                    "type": "text",
                                    "content": f"Summary Error: {str(e)}"
                                })
                    except json.JSONDecodeError:
                        pass
        except (WebSocketDisconnect, RuntimeError):
            logger.info(f"WebSocket disconnected for session {session_id}")
        finally:
            if is_gemini_live and async_audio_queue:
                await async_audio_queue.put(None)
            elif stt_thread_queue:
                stt_thread_queue.put(None)

    try:
        await upstream_task()
    except Exception as e:
        logger.error(f"Session Error in {session_id}: {e}")
    finally:
        if gemini_live_task and not gemini_live_task.done():
            gemini_live_task.cancel()
        logger.info("Session %s completed", session_id)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
