"""Single place that talks to the LLM (Gemini via Google AI Studio)."""
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "google")
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.1-flash-lite")
MIN_INTERVAL = 4.5  # seconds between calls -> stays under 15 requests/min (free tier)

_client = None
_last_call = 0.0


def _get_client():
    global _client
    if _client is None:
        key = os.getenv("API_KEY")
        if not key:
            raise RuntimeError("API_KEY is missing. Copy .env.example to .env and add your key.")
        # timeout (ms): a hanging connection fails after 60 s and call_llm retries, instead of freezing the run
        _client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60000))
    return _client


def _mime(path):
    return "image/png" if path.lower().endswith(".png") else "image/jpeg"


def call_llm(prompt, image_path=None, as_json=False, retries=5):
    """Send prompt (+ optional bill image) to the model and return the text reply."""
    global _last_call
    parts = []
    if image_path:
        with open(image_path, "rb") as f:
            parts.append(types.Part.from_bytes(data=f.read(), mime_type=_mime(image_path)))
    parts.append(prompt)
    cfg = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json" if as_json else "text/plain",
    )
    last_err = None
    for attempt in range(1, retries + 1):
        wait = MIN_INTERVAL - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        try:
            resp = _get_client().models.generate_content(model=MODEL_NAME, contents=parts, config=cfg)
            if resp.text:
                return resp.text
            last_err = "empty response"
        except Exception as e:  # rate limit, network, etc.
            last_err = str(e)[:120]
        print(f"  retry {attempt}/{retries}: {last_err}")
        time.sleep(5 * attempt)
    raise RuntimeError(f"LLM call failed: {last_err}")