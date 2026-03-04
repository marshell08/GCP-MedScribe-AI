import asyncio
from google.cloud import speech_v2
import os

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/home/marshell/antigravity/gedemo-08-62f02692104f.json"
client = speech_v2.SpeechClient()

diarization_config = speech_v2.SpeakerDiarizationConfig(
    min_speaker_count=2,
    max_speaker_count=2,
)
features = speech_v2.RecognitionFeatures(
    diarization_config=diarization_config,
)
config = speech_v2.RecognitionConfig(
    explicit_decoding_config=speech_v2.ExplicitDecodingConfig(
        encoding=speech_v2.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        audio_channel_count=1,
    ),
    model="long", # also test "telephony" or "chirp"
    language_codes=["en-US"],
    features=features,
)

streaming_config = speech_v2.StreamingRecognitionConfig(config=config)
recognizer_str = "projects/gedemo-08/locations/global/recognizers/_"

def get_requests():
    yield speech_v2.StreamingRecognizeRequest(
        recognizer=recognizer_str,
        streaming_config=streaming_config
    )
    yield speech_v2.StreamingRecognizeRequest(audio=b'\x00' * 16000)

try:
    responses = client.streaming_recognize(requests=get_requests())
    for response in responses:
        print(response)
except Exception as e:
    print(f"Error: {e}")
