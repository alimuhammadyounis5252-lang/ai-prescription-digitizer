"""End-to-end processing of one prescription image.

quality gate -> model transcription -> line parsing -> reference lookup -> Urdu
"""
import hashlib
import re
import time
from datetime import datetime
import uuid

from . import __version__
from .agreement import compare_readings
from .parser import parse_medicine_line, parse_frequency, parse_duration, parse_food
from .recognizer import ModelNotConfigured, RecognitionError
from .quality import assess_quality, load_image, to_jpeg_bytes
from .urdu import urdu_instruction

# Lines of these kinds are identity data. They are dropped, not stored or shown.
PRIVATE_KINDS = {"patient"}


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_medicine(line_no, raw_text, unclear, formulary):
    med = parse_medicine_line(raw_text, unclear=unclear)
    med["line_no"] = line_no
    ref = formulary.lookup(med["name"], med["strength"]) if formulary else {
        "match_type": "none", "entry": None, "suggestions": [], "flags": []}
    med["reference"] = {k: ref[k] for k in ("match_type", "entry", "suggestions")}
    med["flags"].extend(ref["flags"])
    str_raw = med["strength"].get("raw") if isinstance(med.get("strength"), dict) else None
    med["urdu"] = urdu_instruction(med["form"], med["frequency"], med["duration"], med["food"],
                                   name=med.get("name"), strength=str_raw)
    return med


def _norm_name(name):
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def flag_duplicates(medicines):
    """Flag rows that repeat a name, or that share an active ingredient
    according to the reference list. Source of the check: data/formulary.csv."""
    by_name, by_generic = {}, {}
    for med in medicines:
        if _norm_name(med["name"]):
            by_name.setdefault(_norm_name(med["name"]), []).append(med)
        entry = med["reference"]["entry"]
        if entry and entry.get("generic"):
            by_generic.setdefault(entry["generic"].lower(), []).append(med)
    for group in by_name.values():
        if len(group) > 1:
            rows = ", ".join(str(m["line_no"]) for m in group)
            for med in group:
                med["flags"].append({"code": "duplicate_name", "severity": "warning",
                                     "message": "The same medicine name appears on lines %s. Verify it is intended." % rows})
    for generic, group in by_generic.items():
        if len({_norm_name(m["name"]) for m in group}) > 1:
            names = ", ".join(m["name"] for m in group)
            for med in group:
                med["flags"].append({"code": "duplicate_ingredient", "severity": "warning",
                                     "message": "%s have the same active ingredient (%s) in the reference list. "
                                                "Verify with the prescriber." % (names, group[0]["reference"]["entry"]["generic"])})


def process_image(data, recognizer, settings, formulary, second=None):
    """Return the result dict for one upload. Raises InvalidImage,
    ModelNotConfigured or RecognitionError; callers map those to HTTP codes."""
    started = time.time()
    img = load_image(data)
    quality = assess_quality(img, settings.quality)
    result = {
        "request_id": uuid.uuid4().hex,
        "created_at": now_iso(),
        "app_version": __version__,
        "image_sha256": hashlib.sha256(data).hexdigest(),
        "image_quality": quality,
        "model": recognizer.describe(),
        "formulary_version": formulary.version if formulary else None,
        "second_reader": {"enabled": False},
        "status": "ok",
        "message": "",
        "medicines": [],
        "other_lines": [],
        "confidence_note": "The model gives no calibrated confidence. Flags mark "
                           "what must be checked; every row needs pharmacist review.",
    }

    if not quality["ok"]:
        result["status"] = "rejected_quality"
        result["message"] = " ".join(quality["reject_reasons"])
        return result

    transcription = recognizer.transcribe(to_jpeg_bytes(img, settings.max_image_side))
    if not transcription["readable"]:
        result["status"] = "unreadable"
        result["message"] = ("The model could not read this image. Retake the photo "
                             "or type the prescription manually.")
        return result

    n = 0
    for line in transcription["lines"]:
        if line["kind"] in PRIVATE_KINDS:
            continue

        text = (line.get("text") or "").strip()
        is_dosage_note = False
        if line.get("kind") == "note" and result["medicines"]:
            f_parsed, _ = parse_frequency(text)
            d_parsed, _ = parse_duration(text)
            fd_parsed, _ = parse_food(text)
            if f_parsed or d_parsed or fd_parsed or re.search(r"روزانہ|صبح|شام|رات|دوپہر|لگائیں|چمچ|خوراک|گولی|کیپسول|ہفتہ", text):
                is_dosage_note = True

        if line["kind"] == "medicine" or is_dosage_note:
            candidate = build_medicine(n + 1, text, line.get("unclear", False), formulary)
            if not candidate["name"] and result["medicines"]:
                prev = result["medicines"][-1]
                merged_text = (prev["raw_text"] + " " + text).strip()
                merged_unclear = prev.get("unclear", False) or line.get("unclear", False)
                result["medicines"][-1] = build_medicine(prev["line_no"], merged_text, merged_unclear, formulary)
            elif line["kind"] == "medicine":
                n += 1
                result["medicines"].append(candidate)
            else:
                result["other_lines"].append(line)
        else:
            result["other_lines"].append(line)

    if second is not None:
        result["second_reader"] = {"enabled": True, "model": second.describe()["model"]}
        try:
            other = second.transcribe(to_jpeg_bytes(img, settings.max_image_side))
            summary = compare_readings(result["medicines"], other["lines"])
            # Lines only the second model saw are offered to the pharmacist as
            # candidate rows. They are never added to the record automatically.
            summary["only_second_rows"] = []
            for text in summary["only_second"]:
                row = build_medicine(None, text, True, formulary)
                row["flags"] = [f for f in row["flags"] if f["code"] != "line_unclear"]
                row["flags"].insert(0, {"code": "second_reader_only", "severity": "critical",
                                        "message": "Only the second model read this line. Check the original."})
                row["needs_attention"] = True
                summary["only_second_rows"].append(row)
            result["second_reader"].update(summary)
        except (ModelNotConfigured, RecognitionError) as exc:
            # The first reading stands; the pharmacist is told the cross-check did not run.
            result["second_reader"].update({"enabled": False, "error": str(exc)})

    flag_duplicates(result["medicines"])
    for med in result["medicines"]:
        med["needs_attention"] = any(f["severity"] == "critical" for f in med["flags"])

    if not result["medicines"]:
        result["status"] = "no_medicines"
        result["message"] = "No medicine lines were read on this image."
    result["elapsed_s"] = round(time.time() - started, 2)
    return result
