import os
import json
import asyncio
import queue
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from google.cloud import speech_v2
from google.oauth2 import service_account
from dotenv import load_dotenv
import requests
import asyncio
load_dotenv()

app = FastAPI()

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

from fastapi.responses import RedirectResponse
import time

@app.get("/")
async def root():
    # Append a timestamp to break the browser cache
    return RedirectResponse(url=f"/static/index.html?v={int(time.time())}")

GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION")

# Force discovery of locally generated ADC for isolated venvs
adc_path = "/home/marshell/antigravity/gedemo-08-62f02692104f.json"
stt_credentials = None
if os.path.exists(adc_path):
    stt_credentials = service_account.Credentials.from_service_account_file(adc_path)

# Required by GCP STT streaming
speech_client = speech_v2.SpeechAsyncClient(credentials=stt_credentials)

def get_speech_config():
    features = speech_v2.RecognitionFeatures(
        enable_automatic_punctuation=True,
    )
    explicit_decoding = speech_v2.ExplicitDecodingConfig(
        encoding=speech_v2.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        audio_channel_count=1,
    )
    return speech_v2.RecognitionConfig(
        explicit_decoding_config=explicit_decoding,
        model="medical_conversation",
        language_codes=["en-US"],
        features=features,
    )

@app.websocket("/ws/scribe")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    audio_queue = queue.Queue()
    session_transcript = []
    
    # We must run STT in a separate background thread because Google Cloud's 
    # Python async generator implementation blocks the main event loop 
    # while waiting for the audio stream to conclude.
    def run_stt_thread(loop, wsock, user_queue, transcript_list):
        import time
        from google.cloud import speech
        
        import traceback
        try:
            # Initialize SpeechClient without explicit quota_project_id to prevent 403 IAM denied
            sync_client = speech_v2.SpeechClient(credentials=stt_credentials)
            config = get_speech_config()
            streaming_features = speech_v2.StreamingRecognitionFeatures(
                interim_results=True
            )
            streaming_config = speech_v2.StreamingRecognitionConfig(
                config=config,
                streaming_features=streaming_features
            )
            
            # v2 explicitly requires a routing recognizer, medical defaults to global
            recognizer_str = f"projects/{GOOGLE_CLOUD_PROJECT}/locations/global/recognizers/_"

        except Exception as e:
            print(f"STT Setup Error: {e}")
            traceback.print_exc()
            return

        def request_generator():
            # v2 Streaming API requires the configuration to be the very first yielded request,
            # followed by the audio blocks in subsequent requests.
            yield speech_v2.StreamingRecognizeRequest(
                recognizer=recognizer_str,
                streaming_config=streaming_config
            )
            while True:
                try:
                    # Use a very short timeout so the GIL is frequently released
                    chunk = user_queue.get(timeout=0.05)
                    if chunk is None:
                        # Client sent disconnect signal
                        print("STT thread received disconnect signal chunk (None)")
                        break
                    print(f"STT generator yielding chunk of length {len(chunk)}")
                    yield speech_v2.StreamingRecognizeRequest(audio=chunk)
                except queue.Empty:
                    # Explicitly yield the GIL so the main FastAPI thread can receive the WebSocket packets!
                    time.sleep(0.01)
                    continue
        
        try:
            print("Starting Sync STT thread (v2)...")
            responses = sync_client.streaming_recognize(
                requests=request_generator()
            )
            sentence_count_since_insight = 0
            
            for response in responses:
                print(f"STT Response received. results length: {len(response.results)}")
                if not response.results:
                    continue
                result = response.results[0]
                if not result.alternatives:
                    continue
                
                alt = result.alternatives[0]
                text = alt.transcript
                print(f"Transcript: {text}, is_final: {result.is_final}")
                
                if result.is_final:
                    transcript_list.append(text)
                    asyncio.run_coroutine_threadsafe(
                        wsock.send_json({
                            "type": "transcript",
                            "text": text,
                            "is_final": True
                        }), loop
                    )
                else:
                    asyncio.run_coroutine_threadsafe(
                        wsock.send_json({
                            "type": "transcript",
                            "text": text,
                            "is_final": False
                        }), loop
                    )
            print("STT thread loop completed.")
        except Exception as e:
            print(f"STT Error in thread: {e}")

    loop = asyncio.get_event_loop()
    import threading
    stt_thread = threading.Thread(target=run_stt_thread, args=(loop, websocket, audio_queue, session_transcript))
    stt_thread.daemon = True
    stt_thread.start()

    try:
        while True:
            # Uvicorn receive format for WebSockets
            message = await websocket.receive()
            
            if message["type"] == "websocket.disconnect":
                print("WebSocket disconnect message received")
                audio_queue.put(None)
                break
                
            if "bytes" in message and message["bytes"]:
                chunk_len = len(message["bytes"])
                print(f"Received audio chunk of {chunk_len} bytes")
                audio_queue.put(message["bytes"])
            elif "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                    if data.get("action") == "end_session":
                        print("Ending session triggered by client")
                        audio_queue.put(None)
                        
                        full_transcript = " ".join(session_transcript)
                        print(f"Final Transcript Length: {len(full_transcript)}")
                        
                        prompt = f"""
You are an expert medical scribe. I am providing you with an un-diarized transcript of a clinical encounter.
Perform the following two tasks and return the results as a JSON object:
1. "diarized_transcript": Split the text into a logical conversation, labeling the speakers as "Doctor:" and "Patient:". Use linebreaks block formatting.
2. "soap_note": Generate a professional SOAP (Subjective, Objective, Assessment, Plan) note based on the encounter. Use markdown.
If the dialogue is incomplete, formulate the SOAP as best as possible.

Raw Transcript:
{full_transcript}
"""                     
                        try:
                            # Use Vertex AI REST API to support API key authentication
                            api_key = os.getenv("GEMINI_API_KEY")
                            project = os.getenv("GOOGLE_CLOUD_PROJECT")
                            location = os.getenv("GOOGLE_CLOUD_LOCATION")
                            
                            url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models/gemini-2.5-flash:generateContent"
                            headers = {
                                "x-goog-api-key": api_key,
                                "Content-Type": "application/json"
                            }
                            payload = {
                                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                                "generationConfig": {
                                    "responseMimeType": "application/json",
                                    "responseSchema": {
                                        "type": "OBJECT",
                                        "properties": {
                                            "diarized_transcript": {"type": "STRING"},
                                            "soap_note": {"type": "STRING"}
                                        }
                                    }
                                }
                            }
                            
                            def fetch_gemini():
                                return requests.post(url, headers=headers, json=payload, timeout=30)
                                
                            resp = await asyncio.to_thread(fetch_gemini)
                            
                            if resp.status_code == 200:
                                result_json = resp.json()
                                text_response = result_json["candidates"][0]["content"]["parts"][0]["text"]
                                parsed_payload = json.loads(text_response)
                                await websocket.send_json({
                                    "type": "final_processed",
                                    "diarized_transcript": parsed_payload.get("diarized_transcript", ""),
                                    "soap_note": parsed_payload.get("soap_note", "")
                                })
                            else:
                                print(f"GenAI HTTP Error {resp.status_code}: {resp.text}")
                                await websocket.send_json({"action": "client_error", "message": f"GenAI API Error: {resp.status_code}"})
                                
                        except Exception as ai_err:
                            print(f"GenAI Parsing Error: {ai_err}")
                            await websocket.send_json({"action": "client_error", "message": f"GenAI Gen Failed: {ai_err}"}) 
                    elif data.get("action") == "client_error":
                        print(f"\n[FRONTEND JS CRASH]: {data.get('message')}\n")
                except json.JSONDecodeError:
                    print(f"Failed to decode text message: {message['text']}")
            else:
                print(f"Unhandled websocket message format: {message}")
    except WebSocketDisconnect:
        print("WebSocket disconnected via exception")
        audio_queue.put(None)
    finally:
        # We don't need to cancel a task anymore since it is a daemon thread
        # just cleanly terminate the queue.
        audio_queue.put(None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
