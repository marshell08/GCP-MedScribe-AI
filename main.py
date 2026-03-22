"""Medical Scribe API leveraging ADK and the Multimodal Live API."""

import asyncio
import logging
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from google.genai import types, Client
from dotenv import load_dotenv
from google.cloud import speech_v2
from google.oauth2 import service_account

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

# Google Cloud STT V2 Credentials setup
adc_path = "/home/marshell/antigravity/gedemo-08-62f02692104f.json"
stt_credentials = None
if os.path.exists(adc_path):
    stt_credentials = service_account.Credentials.from_service_account_file(adc_path)
    logger.info("Loaded Google Cloud credentials from %s", adc_path)

app = FastAPI(title="MedScribe AI")

# Mount static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")



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
    
    # Map frontend values to STT V2 model strings
    # 'chirp_3' -> 'chirp-3', 'chirp_2' -> 'chirp-2'
    model_map = {
        "chirp_3": "chirp_3",
        "chirp_2": "chirp_2"
    }
    target_model = model_map.get(stt_model, "chirp_3")
    logger.info(f"Configuring STT model to use: {target_model}")

    return speech_v2.RecognitionConfig(
        explicit_decoding_config=explicit_decoding,
        model=target_model,
        language_codes=["en-US"],
        features=features,
    )

@app.get("/")
async def root():
    """Serve the clinical dashboard."""
    return FileResponse(static_dir / "index.html")

import queue
import threading

@app.websocket("/ws/scribe/{session_id}")
async def scribe_websocket(websocket: WebSocket, session_id: str):
    user_id = "default_user"
    await websocket.accept()
    logger.info("WEBSOCKET CONNECTED: session_id=%s", session_id)

    # Extract dynamic models from query parameters
    query_params = websocket.query_params
    stt_model = query_params.get("stt_model", "chirp_3")
    llm_model = query_params.get("llm_model", "gemini-2.5-flash")
    logger.info(f"Session {session_id} - STT Model: {stt_model}, LLM Model: {llm_model}")


    
    # Use persistent transcript to support reconnections
    if session_id not in session_transcripts:
        session_transcripts[session_id] = []
    session_transcript = session_transcripts[session_id]

    audio_queue = queue.Queue()
    loop = asyncio.get_running_loop()

    def run_stt_thread():
        """Connects to Google Cloud STT V2 and streams audio from audio_queue."""
        import traceback
        from google.cloud import speech_v2
        logger.info(f"Starting STT V2 thread for session {session_id}")
        
        try:
            if not stt_credentials:
                logger.error("STT Credentials not loaded. Cannot run STT.")
                return

            # Dynamic location configuration
            if stt_model == "chirp_2":
                target_location = "us-central1"
                target_endpoint = "us-central1-speech.googleapis.com"
                target_model_name = "chirp_2"
            else:
                target_location = "us"
                target_endpoint = "us-speech.googleapis.com"
                target_model_name = "chirp_3"

            sync_client = speech_v2.SpeechClient(
                credentials=stt_credentials,
                client_options={"api_endpoint": target_endpoint}
            )
            
            recognizer_suffix = target_model_name.replace("_", "")
            recognizer_id = f"medscribe-{recognizer_suffix}"
            recognizer_str = f"projects/{os.getenv('GOOGLE_CLOUD_PROJECT')}/locations/{target_location}/recognizers/{recognizer_id}"
            
            try:
                logger.info(f"Creating recognizer {recognizer_id} for model {target_model_name} in {target_location}...")
                request = speech_v2.CreateRecognizerRequest(
                    parent=f"projects/{os.getenv('GOOGLE_CLOUD_PROJECT')}/locations/{target_location}",
                    recognizer_id=recognizer_id,
                    recognizer=speech_v2.Recognizer(
                        default_recognition_config=speech_v2.RecognitionConfig(
                            language_codes=["en-US"],
                            model=target_model_name
                        )
                    )
                )
                operation = sync_client.create_recognizer(request=request)
                operation.result() # Wait for completion
                logger.info(f"Created recognizer {recognizer_id}")
            except Exception as e:
                if "AlreadyExists" in str(e) or "already exists" in str(e).lower():
                    logger.info(f"Recognizer {recognizer_id} already exists.")
                else:
                    logger.error(f"Failed to create recognizer: {e}")

            config = get_speech_config(stt_model)
            streaming_features = speech_v2.StreamingRecognitionFeatures(interim_results=True)
            streaming_config = speech_v2.StreamingRecognitionConfig(
                config=config,
                streaming_features=streaming_features
            )

            stop_flag = [False] # Use a list for mutability in nested scope
            
            def request_generator():
                # Yield config first
                yield speech_v2.StreamingRecognizeRequest(
                    recognizer=recognizer_str,
                    streaming_config=streaming_config
                )
                while True:
                    try:
                        chunk = audio_queue.get(timeout=0.1)
                        if chunk is None:  # Sentinel to stop
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

                                # Push transcript back to WebSocket
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
                        logger.info(f"STT Stream timed out (Aborted), reconnecting... Error: {e}")
                        import time
                        time.sleep(1)
                        continue
                    else:
                        logger.error(f"STT Inner Error: {e}")
                        raise e

        except Exception as e:
            logger.error(f"STT Thread Error in {session_id}: {e}")
            traceback.print_exc()

    stt_thread = threading.Thread(target=run_stt_thread, daemon=True)
    stt_thread.start()

    async def upstream_task():
        """Receive audio bytes from browser and stream to both STT V2 and Gemini."""
        try:
            while True:
                message = await websocket.receive()
                if "bytes" in message:
                    audio_bytes = message["bytes"]
                    # logger.info(f"Received {len(audio_bytes)} audio bytes")
                    # 1. Stream to STT V2 for UI Display
                    audio_queue.put(audio_bytes)
                    

                elif "text" in message:
                    try:
                        message_data = json.loads(message["text"])
                        if message_data.get("action") == "end_session":
                            logger.info("End session requested. Triggering SOAP summary.")
                            
                            if not session_transcript:
                                await websocket.send_json({"type": "text", "content": "No transcript available to summarize."})
                                continue

                            # Clear overriding GOOGLE_API_KEY to force GEMINI_API_KEY usage
                            import os
                            os.environ.pop("GOOGLE_API_KEY", None)
                            
                            is_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI") == "True"
                            if is_vertex:
                                client = Client(
                                    vertexai=True,
                                    project=os.getenv("GOOGLE_CLOUD_PROJECT"),
                                    location=os.getenv("GOOGLE_CLOUD_LOCATION")
                                )
                            else:
                                client = Client(
                                    api_key=os.getenv("GEMINI_API_KEY")
                                )
                            
                            logger.info(f"Transcript lines: {len(session_transcript)}")
                            full_text = "\n".join(session_transcript)
                            logger.info(f"Full text length to summarize: {len(full_text)}")
                            prompt = (
                                f"Here is a medical consultation transcript:\n\n{full_text}\n\n"
                                "Please provide the following outputs:\n"
                                "1. **Speaker Diarization**: Reconstruct the dialogue attributing lines correctly to 'Doctor' and 'Patient' based on context.\n\n"
                                "2. **SOAP Summary**: A professional, structured SOAP summary (Subjective, Objective, Assessment, Plan)."
                            )
                            
                            try:
                                logger.info(f"Calling generate_content with model {llm_model}...")
                                summary_response = await asyncio.to_thread(
                                    lambda: client.models.generate_content(
                                        model=llm_model, # Dynamic selection
                                        contents=prompt
                                    )
                                )
                                logger.info("generate_content response received.")
                                
                                if summary_response and summary_response.text:
                                    logger.info("SOAP Summary generated successfully.")
                                    await websocket.send_json({
                                        "type": "text",
                                        "content": summary_response.text
                                    })
                                else:
                                    await websocket.send_json({"type": "text", "content": "Summary generation returned no text."})
                            except Exception as e:
                                logger.error(f"GenerateContent failed: {e}")
                                await websocket.send_json({"type": "text", "content": f"Summary Error: {str(e)}"})
                    except json.JSONDecodeError:
                        pass
        except WebSocketDisconnect:
            logger.info("Upstream: Browser disconnected")
        finally:
             audio_queue.put(None) # Stop STT thread

    try:
        # Run upstream task until session ends
        await upstream_task()
    except Exception as e:
        logger.error("Session Error: %s", e)
    finally:
        logger.info("Session %s closed", session_id)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
