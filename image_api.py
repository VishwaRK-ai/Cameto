import asyncio
import io
import json
import logging
import os
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import requests

try:
    import google.generativeai as genai
except ImportError:
    genai = None

# Load environment variables without modifying existing files
load_dotenv(override=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("gemini-multimodal-detector")

# Exact prompt for Heuristic Synthetic Signal Analysis and Screenshot OCR
GEMINI_DEEPFAKE_OCR_PROMPT = (
    "Analyze this image for two critical dimensions:\n"
    "1. HEURISTIC SYNTHETIC SIGNAL ANALYSIS: Check for AI-generated artifacts, synthetic elements, or deepfake characteristics. "
    "Provide a score from 0.0 to 100.0 representing the heuristic synthetic signal probability that this image is AI-generated.\n"
    "2. OPTICAL CHARACTER RECOGNITION (OCR): Transcribe any readable text, headlines, banners, watermarks, UI text, or WhatsApp/social media messaging visible in the image.\n\n"
    "Return your analysis strictly as a JSON object with two keys:\n"
    "- 'deepfake_score': float between 0.0 and 100.0 (representing the heuristic synthetic signal score)\n"
    "- 'extracted_text': string containing all transcribed text, or empty string if no readable text is present.\n"
    "Do not include any markdown formatting or extra commentary."
)

# Exact prompt for Audio Heuristic Synthetic Signal & Voice Note Auditing
GEMINI_AUDIO_DEEPFAKE_PROMPT = (
    "Analyze this audio file for heuristic synthetic signal indicators, AI voice cloning artifacts, or synthetic speech anomalies. "
    "Also transcribe the audio.\n\n"
    "Return strictly JSON: "
    '{"deepfake_score": float, "transcription": str, "status": "success"}. '
    "deepfake_score must be a float between 0.0 and 100.0 representing the heuristic synthetic signal score that this voice is AI-cloned or synthetic. "
    "transcription must contain the transcribed speech from the audio. Do not include markdown formatting."
)

# ---------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------
app = FastAPI(
    title="Gemini Multimodal Heuristic Synthetic Signal & Audio Analysis Service",
    description="Analyzes viral images and audio voice notes using Google Gemini 3.8 Flash SDK for heuristic synthetic signal detection, OCR, and transcription.",
    version="3.1.0",
)

# Enable CORS for frontend integration (Next.js localhost:3000, n8n, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5678",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------
class ImageDetectRequest(BaseModel):
    image_url: str = Field(
        ...,
        description="Publicly accessible HTTP/HTTPS URL of the image to analyze."
    )


class ImageDetectResponse(BaseModel):
    deepfake_score: Optional[float] = Field(
        default=None,
        description="Heuristic synthetic signal probability that the image is AI-generated (0.0 to 100.0) or null if unavailable."
    )
    extracted_text: Optional[str] = Field(
        default="",
        description="Text extracted from the screenshot or image via OCR."
    )
    status: str = Field(
        default="success",
        description="Status of detection ('success' or 'unavailable')."
    )


class AudioDetectResponse(BaseModel):
    deepfake_score: Optional[float] = Field(
        default=None,
        description="Heuristic synthetic signal probability that the audio voice is synthetic or cloned (0.0 to 100.0) or null if unavailable."
    )
    transcription: Optional[str] = Field(
        default="",
        description="Transcription of the speech in the audio."
    )
    status: str = Field(
        default="success",
        description="Status of detection ('success' or 'unavailable')."
    )


# ---------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------
def clean_json_response(raw_text: str) -> Dict[str, Any]:
    """
    Cleans and parses JSON output from Gemini, handling potential markdown code fences.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback regex search for JSON object containing deepfake_score
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        # Fallback regex search for float value
        score_match = re.search(r'"?deepfake_score"?\s*:\s*([0-9]+(?:\.[0-9]+)?)', text)
        if score_match:
            return {"deepfake_score": float(score_match.group(1))}
        raise ValueError(f"Could not parse valid JSON from text: {text}")


def download_image(url: str, timeout_seconds: float = 12.0) -> tuple[bytes, str]:
    """
    Downloads image from URL into memory. Returns (image_bytes, mime_type).
    """
    parsed = urlparse(url.strip())
    if not parsed.scheme or parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme: {url}")
    if not parsed.netloc:
        raise ValueError(f"Invalid URL domain: {url}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GeminiFactCheckBot/1.0"
    }
    response = requests.get(url, headers=headers, timeout=timeout_seconds)
    response.raise_for_status()

    content = response.content
    if not content:
        raise ValueError("Downloaded image content is empty.")

    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if not content_type or "image" not in content_type:
        # Infer MIME type from URL extension or default to image/jpeg
        if url.lower().endswith(".png"):
            content_type = "image/png"
        elif url.lower().endswith(".webp"):
            content_type = "image/webp"
        else:
            content_type = "image/jpeg"

    return content, content_type


def analyze_image_with_gemini(image_bytes: bytes, mime_type: str) -> tuple[float, str]:
    """
    Sends image bytes and prompt to gemini-3.8-flash via google-generativeai SDK.
    Returns (deepfake_score, extracted_text).
    """
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip().strip('"\'')
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured in environment.")

    if not genai:
        raise RuntimeError("google-generativeai package is not installed.")

    genai.configure(api_key=api_key)

    # Explicitly use gemini-3.8-flash model
    model = genai.GenerativeModel(
        model_name="gemini-3.8-flash",
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.1,
        }
    )

    image_part = {
        "mime_type": mime_type,
        "data": image_bytes,
    }

    # Pass image bytes and prompt to Gemini
    response = model.generate_content([image_part, GEMINI_DEEPFAKE_OCR_PROMPT])

    if not response or not response.text:
        raise ValueError("Empty response received from Gemini API.")

    parsed = clean_json_response(response.text)
    score_raw = parsed.get("deepfake_score", 0.0)
    score_float = float(score_raw)

    # If model returned a decimal ratio (0.0 - 1.0), scale to 0 - 100
    if 0.0 < score_float <= 1.0:
        score_float = score_float * 100.0

    final_score = max(0.0, min(100.0, round(score_float, 2)))
    extracted_text = str(parsed.get("extracted_text", "")).strip()

    return final_score, extracted_text


def analyze_audio_with_gemini(audio_bytes: bytes, mime_type: str) -> tuple[float, str]:
    """
    Sends audio bytes and prompt to gemini-3.8-flash via google-generativeai SDK.
    Returns (deepfake_score, transcription).
    """
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip().strip('"\'')
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured in environment.")

    if not genai:
        raise RuntimeError("google-generativeai package is not installed.")

    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        model_name="gemini-3.8-flash",
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.1,
        }
    )

    audio_part = {
        "mime_type": mime_type,
        "data": audio_bytes,
    }

    response = model.generate_content([audio_part, GEMINI_AUDIO_DEEPFAKE_PROMPT])

    if not response or not response.text:
        raise ValueError("Empty response received from Gemini Audio API.")

    parsed = clean_json_response(response.text)
    score_raw = parsed.get("deepfake_score", 0.0)
    score_float = float(score_raw)

    if 0.0 < score_float <= 1.0:
        score_float = score_float * 100.0

    final_score = max(0.0, min(100.0, round(score_float, 2)))
    transcription = str(parsed.get("transcription", "")).strip()

    return final_score, transcription


# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------
@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint confirming Gemini configuration."""
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip().strip('"\'')
    return {
        "status": "healthy",
        "service": "gemini-deepfake-detector",
        "model": "gemini-3.8-flash",
        "gemini_configured": bool(api_key and api_key != "your_gemini_api_key_here"),
        "sdk_installed": genai is not None,
    }


@app.post(
    "/api/detect-image",
    response_model=ImageDetectResponse,
    tags=["Detection"],
    summary="Detect heuristic synthetic signal in image using Gemini 3.8 Flash"
)
async def detect_image(payload: ImageDetectRequest) -> ImageDetectResponse:
    """
    Downloads the image from image_url and calls Gemini 3.8 Flash for heuristic synthetic signal analysis.
    If the API fails, times out, or the model is not found, returns {"deepfake_score": null, "status": "unavailable"}.
    """
    try:
        # Step 1: Download image bytes into memory (run in thread to not block event loop)
        image_bytes, mime_type = await asyncio.to_thread(download_image, payload.image_url)

        # Step 2: Call Gemini API with timeout protection
        score, extracted_text = await asyncio.wait_for(
            asyncio.to_thread(analyze_image_with_gemini, image_bytes, mime_type),
            timeout=25.0
        )

        return ImageDetectResponse(deepfake_score=score, extracted_text=extracted_text, status="success")

    except asyncio.TimeoutError:
        logger.error(f"Gemini API or download timed out for URL: {payload.image_url}")
        return ImageDetectResponse(deepfake_score=None, extracted_text="", status="unavailable")

    except Exception as e:
        logger.warning(
            f"Error analyzing image URL '{payload.image_url}': {e}. Returning status='unavailable', deepfake_score=None"
        )
        return ImageDetectResponse(deepfake_score=None, extracted_text="", status="unavailable")


@app.post(
    "/api/detect-audio",
    response_model=AudioDetectResponse,
    tags=["Detection"],
    summary="Detect heuristic synthetic signal in voice notes & transcribe speech using Gemini 3.8 Flash"
)
async def detect_audio(
    file: Optional[UploadFile] = File(None),
    request: Request = None,
) -> AudioDetectResponse:
    """
    Accepts an audio file upload (multipart/form-data) such as .mp3, .wav, or .ogg.
    Calls Gemini 3.8 Flash to detect heuristic synthetic signals / voice cloning and generate a transcription.
    Returns {"deepfake_score": float, "transcription": str, "status": "success"} or unavailable.
    """
    try:
        audio_bytes = b""
        mime_type = "audio/mp3"
        filename = ""

        if file is not None:
            audio_bytes = await file.read()
            filename = (file.filename or "").lower()
            if file.content_type and "audio" in file.content_type.lower():
                mime_type = file.content_type.lower()
        elif request is not None:
            audio_bytes = await request.body()
            req_ct = request.headers.get("content-type", "").lower()
            if "audio" in req_ct:
                mime_type = req_ct.split(";")[0].strip()

        if not audio_bytes:
            raise ValueError("No audio content received in request.")

        # Normalize MIME types for Gemini compatibility
        if filename.endswith(".wav") or "wav" in mime_type:
            mime_type = "audio/wav"
        elif filename.endswith(".ogg") or "ogg" in mime_type:
            mime_type = "audio/ogg"
        elif filename.endswith(".m4a") or "m4a" in mime_type or "mp4" in mime_type:
            mime_type = "audio/m4a"
        elif filename.endswith(".aac") or "aac" in mime_type:
            mime_type = "audio/aac"
        else:
            mime_type = "audio/mp3"

        score, transcription = await asyncio.wait_for(
            asyncio.to_thread(analyze_audio_with_gemini, audio_bytes, mime_type),
            timeout=35.0
        )

        return AudioDetectResponse(deepfake_score=score, transcription=transcription, status="success")

    except asyncio.TimeoutError:
        logger.error("Gemini Audio analysis timed out.")
        return AudioDetectResponse(deepfake_score=None, transcription="", status="unavailable")

    except Exception as e:
        logger.warning(f"Error analyzing audio: {e}. Returning status='unavailable', deepfake_score=None")
        return AudioDetectResponse(deepfake_score=None, transcription="", status="unavailable")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("IMAGE_API_PORT", 8001))
    uvicorn.run("image_api:app", host="0.0.0.0", port=port, reload=True)
