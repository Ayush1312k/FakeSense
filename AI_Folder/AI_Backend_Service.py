import base64
import json
import time
import requests
import os
import re
from typing import List, Dict, Any, Optional
from flask import Flask, request, jsonify
from flask_cors import CORS

# --- SECURE CREDENTIALS LOADING ---
# Load environment variables from .env file (keys are hidden and never hardcoded)
try:
    from dotenv import load_dotenv
    current_dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(current_dir, '.env'))
    load_dotenv(os.path.join(current_dir, '..', '.env'))
except ImportError:
    pass

def _load_env_fallback():
    search_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'),
        os.path.join(os.getcwd(), '.env')
    ]
    for path in search_paths:
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            k, v = line.split('=', 1)
                            k, v = k.strip(), v.strip()
                            if k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass

_load_env_fallback()

# Read key securely from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GEMINI_MODELS_POOL = ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.8-flash"]

app = Flask(__name__)
CORS(app)


# ==============================================================================
# GEMINI ENGINE FUNCTIONS
# ==============================================================================

def call_gemini_api(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calls the Google Gemini API with smart model pooling and automatic
    fallback if tool quotas (like Search) are temporarily rate-limited.
    """
    if not GEMINI_API_KEY:
        return {"status": "error", "message": "Gemini API key is not configured in .env"}

    working_payload = dict(payload)

    for model_name in GEMINI_MODELS_POOL:
        current_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        max_retries = 2
        initial_delay = 1

        for attempt in range(max_retries):
            try:
                headers = {'Content-Type': 'application/json'}
                response = requests.post(current_url, headers=headers, json=working_payload, timeout=25)
                
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError:
                        return {"status": "error", "message": "Invalid JSON response from Gemini."}
                        
                # If 429 quota hit and tools (Google Search) were attached, retry immediately without tools
                if response.status_code == 429 and "tools" in working_payload:
                    print(f"[Notice] Search tool quota reached on {model_name}. Retrying with direct neural reasoning...")
                    del working_payload["tools"]
                    retry_resp = requests.post(current_url, headers=headers, json=working_payload, timeout=25)
                    if retry_resp.status_code == 200:
                        return retry_resp.json()

                if response.status_code in (429, 500, 503):
                    if attempt < max_retries - 1:
                        time.sleep(initial_delay * (2 ** attempt))
                        continue
                        
                if response.status_code == 404:
                    break  # Try next model in pool

            except requests.exceptions.RequestException:
                if attempt < max_retries - 1:
                    time.sleep(initial_delay * (2 ** attempt))
                    continue
                break

    return {"status": "error", "message": "Failed to connect to Google Gemini service."}


def extract_gemini_classification(text: str) -> Dict[str, Any]:
    """Parses structured classification output."""
    is_real = True
    upper = text.upper()
    if "CLASSIFICATION: LIKELY FAKE" in upper or "CLASSIFICATION: UNVERIFIABLE" in upper or "VERDICT: FAKE" in upper:
        is_real = False
    elif "LIKELY FAKE (1)" in upper:
        is_real = False

    classification_tag = "CLASSIFICATION:"
    if classification_tag in text:
        parts = text.split(classification_tag, 1)
        analysis_text = parts[0].strip()
        label_text = parts[1].strip().split('\n')[0].strip()
    else:
        analysis_text = text.strip()
        label_text = "LIKELY AUTHENTIC (0)" if is_real else "LIKELY FAKE (1)"

    analysis_text = re.sub(r'\*\*', '', analysis_text)
    return {
        "is_real": is_real,
        "analysis_text": analysis_text,
        "label_text": label_text
    }


def extract_grounding_sources(response: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extracts search citation sources from Gemini."""
    sources = []
    try:
        candidates = response.get('candidates', [])
        if not candidates:
            return []

        grounding_metadata = candidates[0].get('groundingMetadata')
        if grounding_metadata and grounding_metadata.get('groundingAttributions'):
            for attribution in grounding_metadata['groundingAttributions']:
                web = attribution.get('web')
                if web and web.get('uri') and web.get('title'):
                    sources.append({
                        "uri": web['uri'],
                        "title": web['title'],
                    })
    except Exception:
        pass
    return sources


def query_gemini_deepfake(image_data: str, mime_type: str = "image/jpeg") -> Optional[Dict[str, Any]]:
    """Performs deepfake inspection via Gemini Vision + Search Grounding."""
    system_prompt = (
        "You are an elite Digital Forensics Expert at FakeSense. Analyze the provided image for signs of AI manipulation with absolute precision.\n\n"
        "Follow this analytical structure:\n"
        "1. SUBJECT & CONTEXT: Identify the subject/event and check if this is a known synthetic hoax or verified photograph.\n"
        "2. VISUAL FORENSICS: Check lighting & reflections, skin texture & smoothing, facial symmetry, edges & hair masking.\n"
        "3. SYNTHESIS: Summarize technical findings.\n\n"
        "End strictly with: 'CLASSIFICATION: LIKELY AUTHENTIC (0)' or 'CLASSIFICATION: LIKELY FAKE (1)'."
    )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": "Perform a deepfake check on this image. Verify its authenticity using search and visual cues."},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": image_data
                        }
                    }
                ]
            }
        ],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1},
        "systemInstruction": {"parts": [{"text": system_prompt}]}
    }

    raw = call_gemini_api(payload)
    if raw.get('status') == 'error':
        return None

    try:
        text_content = raw['candidates'][0]['content']['parts'][0]['text']
        parsed = extract_gemini_classification(text_content)
        sources = extract_grounding_sources(raw)
        return {
            "engine": "Gemini",
            "is_real": parsed['is_real'],
            "analysis": parsed['analysis_text'],
            "label": parsed['label_text'],
            "sources": sources
        }
    except Exception as e:
        print(f"[Gemini Deepfake Error] {e}")
        return None


def query_gemini_news(news_text: str) -> Optional[Dict[str, Any]]:
    """Performs fake news verification via Gemini Search Grounding."""
    system_prompt = (
        "You are an elite Fact-Checking AI at FakeSense. Verify the accuracy of news headlines or text.\n"
        "Cross-reference multiple reliable sources and known facts.\n\n"
        "1. Identify core claims.\n"
        "2. Search for credible corroborating evidence.\n"
        "3. Evaluate sources and veracity.\n"
        "4. Summarize the truth.\n\n"
        "End your response strictly with: 'CLASSIFICATION: LIKELY AUTHENTIC (0)', 'CLASSIFICATION: LIKELY FAKE (1)', or 'CLASSIFICATION: UNVERIFIABLE (1)'."
    )

    payload = {
        "contents": [{"parts": [{"text": f"Verify this claim: {news_text}"}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1},
        "systemInstruction": {"parts": [{"text": system_prompt}]}
    }

    raw = call_gemini_api(payload)
    if raw.get('status') == 'error':
        return None

    try:
        text_content = raw['candidates'][0]['content']['parts'][0]['text']
        parsed = extract_gemini_classification(text_content)
        sources = extract_grounding_sources(raw)
        return {
            "engine": "Gemini",
            "is_real": parsed['is_real'],
            "analysis": parsed['analysis_text'],
            "label": parsed['label_text'],
            "sources": sources
        }
    except Exception as e:
        print(f"[Gemini News Error] {e}")
        return None


# ==============================================================================
# FLASK API ENDPOINTS
# ==============================================================================

@app.route('/api/health', methods=['GET'])
def health_endpoint():
    """Health check endpoint showing Gemini configuration status."""
    return jsonify({
        "status": "online",
        "system": "FakeSense AI Backend",
        "gemini_active": bool(GEMINI_API_KEY),
        "engine": "Google Gemini Multi-Modal Forensics"
    })


@app.route('/api/deepfake/analyze', methods=['POST'])
def deepfake_endpoint():
    if not GEMINI_API_KEY:
        return jsonify({"status": "error", "message": "Gemini API key is not configured in .env"}), 400

    data = request.json or {}
    image_data = data.get('image_data')
    mime_type = data.get('mime_type', 'image/jpeg')
    
    if image_data and "base64," in image_data:
        image_data = image_data.split("base64,")[1]

    if not image_data:
        return jsonify({"status": "error", "message": "Missing image data for forensic analysis."}), 400

    gemini_res = query_gemini_deepfake(image_data, mime_type)
    if not gemini_res:
        return jsonify({
            "status": "error",
            "message": "Gemini forensic inspection could not be completed. Please check your API key, quotas, or network connection."
        })

    verdict_text = 'LIKELY AUTHENTIC (0)' if gemini_res['is_real'] else 'LIKELY FAKE (1)'
    classification_text = (
        "[ Engine: Google Gemini Multi-Modal Forensics ]\n\n"
        f"{gemini_res['analysis']}\n\n"
        f"VERDICT: {verdict_text}"
    )

    return jsonify({
        "status": "success",
        "is_real": gemini_res['is_real'],
        "classification_text": classification_text,
        "sources": gemini_res.get('sources', [])
    })


@app.route('/api/news/verify', methods=['POST'])
def news_endpoint():
    if not GEMINI_API_KEY:
        return jsonify({"status": "error", "message": "Gemini API key is not configured in .env"}), 400

    data = request.json or {}
    news_text = data.get('news_text')
    
    if not news_text or len(news_text.strip()) < 10:
        return jsonify({"status": "error", "message": "Missing or insufficient news text for verification."}), 400

    gemini_res = query_gemini_news(news_text)
    if not gemini_res:
        return jsonify({
            "status": "error",
            "message": "Gemini news verification could not be completed. Please check your API key, quotas, or network connection."
        })

    verdict_text = 'LIKELY AUTHENTIC (0)' if gemini_res['is_real'] else 'LIKELY FAKE (1)'
    classification_text = (
        "[ Engine: Google Gemini Multi-Modal Forensics ]\n\n"
        f"{gemini_res['analysis']}\n\n"
        f"VERDICT: {verdict_text}"
    )

    return jsonify({
        "status": "success",
        "is_real": gemini_res['is_real'],
        "classification_text": classification_text,
        "sources": gemini_res.get('sources', [])
    })


if __name__ == '__main__':
    print("=" * 65)
    print(" FakeSense Forensic AI Backend Service")
    print(f" Gemini Engine : {'ACTIVE (' + GEMINI_MODELS_POOL[0] + ')' if GEMINI_API_KEY else 'DISABLED (No Key)'}")
    print(" Engine Architecture: Google Gemini Multi-Modal Forensics")
    print("=" * 65)
    app.run(host='127.0.0.1', port=5000, debug=False)