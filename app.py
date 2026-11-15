"""AI Prescription Digitizer - Flask server.

Run:  python app.py      then open http://127.0.0.1:5000

The server never produces a medicine that a model did not read from the image.
With no model configured, /api/recognize answers 503 and says how to set one up.
"""
import hmac
import logging
import os
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, session

from rxcore import __version__
from rxcore.config import get_settings
from rxcore.formulary import Formulary
from rxcore.parser import parse_duration, parse_food, parse_frequency
from rxcore.pipeline import process_image
from rxcore.quality import InvalidImage
from rxcore.recognizer import ModelNotConfigured, RecognitionError, VLMRecognizer
from rxcore.fhir import record_to_fhir_bundle
from rxcore.storage import (PendingStore, correction_stats, list_records, load_record,
                            save_approved)
from rxcore.urdu import urdu_instruction

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
WEB_DIR = Path(__file__).resolve().parent / "web"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _clean(value, limit=200):
    return str(value or "").strip()[:limit]


def finalise_medicine(row):
    """Turn one pharmacist-edited row (plain text fields) into a stored entry.
    Schedule and Urdu are re-derived from the edited text."""
    frequency, _ = parse_frequency(_clean(row.get("frequency")))
    duration, _ = parse_duration(_clean(row.get("duration")))
    food, _ = parse_food(_clean(row.get("food")))
    form = _clean(row.get("form"), 30) or None
    name = _clean(row.get("name"))
    strength = _clean(row.get("strength"), 60)
    return {
        "line_no": row.get("line_no") if isinstance(row.get("line_no"), int) else None,
        "raw_text": _clean(row.get("raw_text"), 500),
        "name": name,
        "form": form,
        "strength": strength,
        "frequency": _clean(row.get("frequency"), 60),
        "duration": _clean(row.get("duration"), 60),
        "food": _clean(row.get("food"), 60),
        "frequency_parsed": frequency,
        "urdu": urdu_instruction(form, frequency, duration, food, name=name, strength=strength),
        "checked_against_original": bool(row.get("checked")),
    }


def create_app(settings=None, recognizer=None, second=None):
    settings = settings or get_settings()
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_mb * 1024 * 1024
    log = logging.getLogger("rx")

    formulary = (Formulary.from_csv(settings.formulary_path)
                 if Path(settings.formulary_path).exists() else Formulary([], "missing"))
    recognizer = recognizer or VLMRecognizer(settings.vlm_base_url, settings.vlm_model,
                                             settings.vlm_api_key, settings.vlm_timeout_s)
    if second is None and settings.vlm_model_2:
        second = VLMRecognizer(settings.vlm_base_url_2 or settings.vlm_base_url, settings.vlm_model_2,
                               settings.vlm_api_key_2 or settings.vlm_api_key, settings.vlm_timeout_s)
    pending = PendingStore()

    if settings.host not in ("127.0.0.1", "localhost") and not settings.access_code:
        log.warning("The app is reachable from other devices (HOST=%s) and APP_ACCESS_CODE is not set. "
                    "Anyone on the network can read and approve prescriptions. Set APP_ACCESS_CODE.", settings.host)

    # Sessions only matter when an access code is set. The key is random per start,
    # so everyone must sign in again after a restart.
    app.secret_key = os.urandom(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")

    @app.before_request
    def require_access_code():
        if not settings.access_code or not request.path.startswith("/api/"):
            return None
        if request.path in ("/api/health", "/api/login") or session.get("ok"):
            return None
        return jsonify({"error": "Access code required.", "code": "login_required"}), 401

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; object-src 'none'; base-uri 'none'; form-action 'self'")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/api/login")
    def login():
        code = _clean((request.get_json(silent=True) or {}).get("code"), 200)
        if settings.access_code and hmac.compare_digest(code.encode(), settings.access_code.encode()):
            session["ok"] = True
            return jsonify({"status": "ok"})
        return jsonify({"error": "Wrong access code."}), 403

    @app.get("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory(WEB_DIR, filename)

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/api/health")
    def health():
        return jsonify({
            "status": "ok",
            "version": __version__,
            "model_configured": bool(recognizer.base_url and recognizer.model),
            "model": recognizer.describe(),
            "second_reader": second.describe()["model"] if second else None,
            "login_required": bool(settings.access_code) and not session.get("ok"),
            "formulary": {"version": formulary.version, "entries": len(formulary),
                          "verified_entries": sum(1 for r in formulary.rows if r["verified"])},
        })

    @app.post("/api/recognize")
    def recognize():
        file = request.files.get("file")
        if file is None or not file.filename:
            return jsonify({"error": "No file uploaded."}), 400
        if Path(file.filename).suffix.lower() not in ALLOWED_EXT:
            return jsonify({"error": "Unsupported file type. Upload a JPG or PNG photo."}), 400
        data = file.read()
        if not data:
            return jsonify({"error": "The uploaded file is empty."}), 400
        try:
            result = process_image(data, recognizer, settings, formulary, second)
        except InvalidImage as exc:
            return jsonify({"error": str(exc)}), 400
        except ModelNotConfigured as exc:
            return jsonify({"error": str(exc), "code": "model_not_configured"}), 503
        except RecognitionError as exc:
            log.warning("recognition failed: %s", exc)  # no patient data in logs
            return jsonify({"error": str(exc), "code": "model_error"}), 502
        if settings.keep_uploads:
            settings.uploads_dir.mkdir(parents=True, exist_ok=True)
            (settings.uploads_dir / (result["request_id"] + ".img")).write_bytes(data)
        pending.put(result)
        log.info("recognize id=%s status=%s medicines=%d", result["request_id"][:8],
                 result["status"], len(result["medicines"]))
        return jsonify(result)

    @app.post("/api/urdu")
    def urdu():
        body = request.get_json(silent=True) or {}
        rows = body.get("medicines")
        if not isinstance(rows, list):
            return jsonify({"error": "medicines must be a list."}), 400
        return jsonify({"medicines": [finalise_medicine(r)["urdu"] for r in rows if isinstance(r, dict)]})

    @app.get("/api/tts")
    def tts():
        import asyncio, urllib.parse, urllib.request
        from flask import Response
        text = _clean(request.args.get("text"), 400)
        if not text:
            return jsonify({"error": "No text provided"}), 400

        voice = request.args.get("voice", "female")
        voice_name = "ur-PK-AsadNeural" if voice == "male" else "ur-PK-UzmaNeural"

        # 1. Primary: Microsoft Edge Neural TTS (Free, Natural Human Urdu Voice)
        try:
            import edge_tts
            async def _generate():
                comm = edge_tts.Communicate(text, voice=voice_name, rate="+0%", pitch="+0Hz")
                chunks = []
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        chunks.append(chunk["data"])
                return b"".join(chunks)

            audio_data = asyncio.run(_generate())
            if audio_data:
                return Response(audio_data, mimetype="audio/mpeg", headers={
                    "Cache-Control": "public, max-age=86400",
                    "Content-Disposition": "inline"
                })
        except Exception as exc:
            log.warning("edge-tts failed (%s), falling back to secondary TTS", exc)

        # 2. Secondary fallback: Google Translate TTS
        try:
            url = f"https://translate.google.com/translate_tts?ie=UTF-8&tl=ur&client=tw-ob&q={urllib.parse.quote(text)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
            return Response(data, mimetype="audio/mpeg")
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.post("/api/records")
    def approve():
        body = request.get_json(silent=True) or {}
        pharmacist = _clean(body.get("pharmacist"), 80)
        rows = body.get("medicines")
        original = pending.get(_clean(body.get("request_id"), 64))
        errors = []
        if original is None:
            errors.append("Unknown or expired request. Upload the prescription again.")
        if len(pharmacist) < 3:
            errors.append("Pharmacist name is required for approval.")
        if not isinstance(rows, list) or not rows:
            errors.append("At least one medicine row is required.")
            rows = []
        final = [finalise_medicine(r) for r in rows if isinstance(r, dict)]
        for i, med in enumerate(final, 1):
            if not med["name"]:
                errors.append("Row %d has no medicine name." % i)
            if not med["checked_against_original"]:
                errors.append("Row %d is not ticked as checked against the original." % i)
        if errors:
            return jsonify({"error": "Record not approved.", "details": errors}), 422
        # Claim the pending result atomically: of two simultaneous approvals
        # (double click, two tabs) only one gets it, so no duplicate record is saved.
        claimed = pending.pop(original["request_id"])
        if claimed is None:
            return jsonify({"error": "This prescription was already approved.",
                            "details": ["Open the Approved records tab to see it."]}), 409
        try:
            record = save_approved(settings.records_dir, claimed, final, pharmacist)
        except OSError as exc:
            pending.put(claimed)                      # let the pharmacist try again
            log.error("could not save record: %s", type(exc).__name__)
            return jsonify({"error": "The record could not be saved to disk. Nothing was approved; try again."}), 500
        return jsonify(record), 201

    @app.get("/api/records")
    def records():
        return jsonify({"records": list_records(settings.records_dir)})

    @app.get("/api/stats")
    def stats():
        return jsonify(correction_stats(settings.records_dir))

    @app.get("/api/records/<record_id>/fhir")
    def get_record_fhir(record_id):
        record = load_record(settings.records_dir, record_id)
        if record is None:
            return jsonify({"error": "Record not found."}), 404
        return jsonify(record_to_fhir_bundle(record))

    @app.get("/api/records/<record_id>")
    def get_record(record_id):
        record = load_record(settings.records_dir, record_id)
        if record is None:
            return jsonify({"error": "Record not found."}), 404
        return jsonify(record)

    @app.errorhandler(413)
    def too_large(_):
        return jsonify({"error": "File is larger than %d MB." % settings.max_upload_mb}), 413

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    application = create_app()
    cfg = get_settings()
    print("\n AI Prescription Digitizer v%s" % __version__)
    print(" Open:  http://%s:%d" % ("127.0.0.1" if cfg.host in ("0.0.0.0", "127.0.0.1") else cfg.host, cfg.port))
    print(" Model: %s" % (cfg.vlm_model if cfg.model_configured
                          else "NOT CONFIGURED - see README, section 'Connect a model'"))
    print(" Second reader: %s" % (cfg.vlm_model_2 or "off"))
    print(" Access code: %s\n" % ("on" if cfg.access_code else "off (use only on a trusted computer)"))
    application.run(host=cfg.host, port=cfg.port, debug=False)
