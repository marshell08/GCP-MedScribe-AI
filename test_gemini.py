import os
from google import genai
from dotenv import load_dotenv

# Ensure we wipe any system-level keys that conflict
if "GOOGLE_API_KEY" in os.environ:
    del os.environ["GOOGLE_API_KEY"]

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

print(f"Using Key: {api_key[:5]}... Length: {len(api_key)}")

# Test assuming it might actually be an OAuth token formatted as an API key:
from google.oauth2.credentials import Credentials
import vertexai
from vertexai.generative_models import GenerativeModel

print("Testing Vertex AI Initialization with this key as a token...")
try:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION")
    # If it is an OAuth token, we can build credentials:
    creds = Credentials(token=api_key)
    vertexai.init(project=project, location=location, credentials=creds)
    model = GenerativeModel("gemini-2.5-flash")
    resp = model.generate_content("hello")
    print("Vertex AI Success:", resp.text)
except Exception as e:
    print("Vertex AI Failed:", e)

