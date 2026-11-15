"""Handwriting recognition through a vision-language model (VLM).

One backend: any server that speaks the OpenAI chat-completions API with image
input. That covers, with the same code:
  * Hugging Face Inference Providers  (https://router.huggingface.co/v1)
  * a local Ollama / LM Studio server (http://localhost:11434/v1)
  * any other OpenAI-compatible endpoint

The model is asked ONLY to transcribe what is written, line by line. It is not
asked for generic names, purposes or corrections; structured fields are derived
afterwards by deterministic code in parser.py, so every field can be traced
back to raw text the model actually returned.

If no model is configured the recognizer raises ModelNotConfigured. There is
no fallback that produces medicines without a model.
"""
import base64
import json
import re

import requests

PROMPT_VERSION = "drap-v2.2"

SYSTEM_PROMPT = (
    "You transcribe handwritten medical prescriptions written by doctors in Pakistan. "
    "You are a medical transcription tool. You understand standard Pakistani pharmaceutical "
    "brand names registered under DRAP (Drug Regulatory Authority of Pakistan), and clinical abbreviations."
)

USER_PROMPT = """Transcribe the handwriting in this Pakistani medical prescription image.

Rules:
1. Copy what is written, line by line, top to bottom. Keep the original language
   and script (English, Urdu, or mixed). Do not translate.
2. Prioritize Pakistani DRAP registered brand names over foreign brands.
   For example, recognize Pakistani brands like Mabil (not Mobic), Rulling (not Pulmo),
   Empaglimet, Pregy (not Preg), Solosin SR, Delanzo DR, Extor, Ascard, Rast, Caflam,
   Hyo-C, Zeyab, Risek, Augmentin, Panadol, Capoten, Concor, Glucophage, Lipiget, etc.
3. Crucial: "OD" is a standard medical abbreviation meaning "Once Daily".
   Never transcribe "OD" as the digit "0" or letter "O".
   Standard Pakistani dosage frequencies: OD (once daily), BD (twice daily),
   TDS (3 times daily), HS (at bedtime), 1+0+1, 1-1-1, 1-0-0, 0-0-1.
4. If strength (e.g. 50mg, 40mg, 12.5/500) or frequency is written directly beside
   or directly beneath a medicine name, COMBINE THEM ON THE SAME LINE.
   Example: "Tab. Capoten 50mg OD". Do NOT split into a separate medicine line for just dosage.
5. Do NOT guess. If a word cannot be read, write [?] in its place.
6. Classify each line with one kind:
   "medicine"  - a pharmaceutical drug to be taken (tablets, capsules, syrups, injections)
   "lab"       - diagnostic investigations, tests, or lab values (e.g. CBC / Blood CP, LFT, RFT,
                 HBsAg, Anti-HCV, Hepatitis tests, HCG / Pregnancy, Urine R/E, Stool R/E,
                 USG / Ultrasound, RBS / Blood Sugar 256, HbA1c, Lipid Profile, TSH, Widal,
                 Typhidot, ESR, ECG, X-Ray). NEVER classify a lab test as a medicine!
   "patient"   - patient name, age, sex, weight
   "doctor"    - doctor name / clinic title
   "note"      - provisional diagnosis (e.g. DM-2, HTN, OA), advice, dietary instructions
7. Set "unclear": true for any line where you were not sure of one or more characters.
8. Be concise: Focus on handwritten medicine lines, patient vitals, diagnosis, and doctor name.
   Ignore repetitive boilerplate printed clinic footers or printed disclaimers.
9. If the image is not a prescription or nothing can be read, return
   {"readable": false, "lines": []}.

Answer with JSON only, in exactly this shape:
{"readable": true, "lines": [{"text": "...", "kind": "medicine", "unclear": false}]}"""

KINDS = {"medicine", "lab", "patient", "doctor", "note"}


class RecognitionError(RuntimeError):
    """The model could not be reached or returned something unusable."""


class ModelNotConfigured(RecognitionError):
    pass


def _extract_json(text):
    """Pull the JSON object out of a model reply (tolerates ``` fences and cutoffs)."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1:
        raise RecognitionError("Model reply contained no JSON object")
    if end <= start:
        candidate = text[start:] + ']}'
    else:
        candidate = text[start:end + 1]

    # Clean trailing commas before closing braces/brackets
    candidate = re.sub(r",\s*([\]}])", r"\1", candidate)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # If cut off mid-list, attempt to rescue up to the last complete item
        last_item = candidate.rfind("}")
        if last_item > start:
            salvaged = candidate[:last_item + 1]
            if "lines" in salvaged and not salvaged.rstrip().endswith("]"):
                salvaged += "]}"
            try:
                return json.loads(salvaged)
            except Exception:
                pass
        raise RecognitionError("Model reply was not valid JSON")


def normalise_transcription(payload):
    """Validate the model's JSON. Anything malformed is dropped, never repaired
    by invention."""
    if not isinstance(payload, dict):
        raise RecognitionError("Model reply JSON was not an object")
    lines = []
    for item in payload.get("lines") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        kind = str(item.get("kind") or "note").strip().lower()
        if kind not in KINDS:
            kind = "note"
        unclear = bool(item.get("unclear")) or "[?]" in text or "[unreadable]" in text.lower()
        lines.append({"text": text, "kind": kind, "unclear": unclear})
    readable = bool(payload.get("readable", bool(lines))) and bool(lines)
    return {"readable": readable, "lines": lines if readable else []}


class VLMRecognizer:
    def __init__(self, base_url, model, api_key="", timeout_s=120.0, session=None):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model or ""
        self.api_key = api_key or ""
        self.timeout_s = timeout_s
        self._http = session or requests

    def describe(self):
        return {
            "backend": "openai-compatible-vlm",
            "model": self.model,
            "endpoint_host": re.sub(r"^https?://([^/]+).*$", r"\1", self.base_url),
            "prompt_version": PROMPT_VERSION,
        }

    def transcribe(self, jpeg_bytes):
        if not (self.base_url and self.model):
            raise ModelNotConfigured(
                "No recognition model is configured. Set VLM_BASE_URL and "
                "VLM_MODEL in the .env file (see README)."
            )
        data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 800,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": USER_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]},
            ],
        }
        import time
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        resp = None
        for attempt in range(3):
            try:
                resp = self._http.post(self.base_url + "/chat/completions",
                                       json=body, headers=headers, timeout=self.timeout_s)
                if resp.status_code == 429 and attempt < 2:
                    wait_s = 6.0
                    try:
                        err_text = resp.text
                        m_wait = re.search(r"try again in (\d+(?:\.\d+)?)s", err_text, re.I)
                        if m_wait:
                            wait_s = float(m_wait.group(1)) + 1.0
                        elif "retry-after" in resp.headers:
                            wait_s = float(resp.headers["retry-after"]) + 1.0
                    except Exception:
                        pass
                    time.sleep(min(wait_s, 10.0))
                    continue
                break
            except requests.RequestException as exc:
                if attempt == 2:
                    raise RecognitionError("Could not reach the model server: %s" % type(exc).__name__) from exc
                time.sleep(2)
        if resp.status_code >= 400:
            err_msg = ""
            try:
                err_msg = resp.json().get("error", {}).get("message", "")
            except Exception:
                pass
            raise RecognitionError("Model server returned HTTP %d: %s" % (resp.status_code, err_msg))
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RecognitionError("Model server reply had an unexpected format") from exc
        if isinstance(content, list):  # some servers return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return normalise_transcription(_extract_json(str(content)))
