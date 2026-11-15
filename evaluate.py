"""Measure the system on hand-typed ground truth.

Usage:
    python evaluate.py                      # evaluates items with "split": "test"
    python evaluate.py --split all
    python evaluate.py --labels data/ground_truth/labels.json --out reports
    python evaluate.py --model another/model-id      # same test set, different model

Every number this project reports must come from this script. It needs a real
model (configured in .env) and labels typed by a person from the photos.
"""
import argparse
import json
import platform
import sys
import time
from pathlib import Path

from rxcore import __version__
from rxcore.metrics import levenshtein, normalise_text, prf, wilson_interval
from rxcore.parser import parse_frequency
from rxcore.quality import InvalidImage
from rxcore.recognizer import RecognitionError

if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to a legacy code page
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent


def _name_key(name):
    return "".join(ch for ch in normalise_text(name) if ch.isalnum())


def _strength_key(value):
    return normalise_text(value).replace(" ", "")


def _freq_key(value):
    parsed, _ = parse_frequency(value or "")
    return parsed["code"] if parsed else normalise_text(value)


def score_item(truth_meds, pred_meds):
    """Compare one prescription. truth/pred are lists of
    {"text", "name", "strength", "frequency"}; pred may also carry "flagged"."""
    ref_text = normalise_text(" ".join(m.get("text", "") for m in truth_meds))
    hyp_text = normalise_text(" ".join(m.get("text", "") for m in pred_meds))
    out = {
        "char_edits": levenshtein(ref_text, hyp_text), "ref_chars": len(ref_text),
        "word_edits": levenshtein(ref_text.split(), hyp_text.split()), "ref_words": len(ref_text.split()),
        "tp": 0, "fp": 0, "fn": 0,
        "strength_total": 0, "strength_correct": 0,
        "frequency_total": 0, "frequency_correct": 0,
        "wrong_pred": 0, "wrong_pred_flagged": 0,
        "missed": [], "extra": [],
    }
    remaining = list(pred_meds)
    for truth in truth_meds:
        key = _name_key(truth.get("name", ""))
        hit = next((p for p in remaining if _name_key(p.get("name", "")) == key), None)
        if hit is None:
            out["fn"] += 1
            out["missed"].append(truth.get("name", ""))
            continue
        remaining.remove(hit)
        out["tp"] += 1
        if truth.get("strength"):
            out["strength_total"] += 1
            out["strength_correct"] += _strength_key(truth["strength"]) == _strength_key(hit.get("strength", ""))
        if truth.get("frequency"):
            out["frequency_total"] += 1
            out["frequency_correct"] += _freq_key(truth["frequency"]) == _freq_key(hit.get("frequency", ""))
    for pred in remaining:                       # names the model produced that are not in the truth
        out["fp"] += 1
        out["wrong_pred"] += 1
        out["wrong_pred_flagged"] += bool(pred.get("flagged"))
        out["extra"].append(pred.get("name", ""))
    return out


def aggregate(per_item):
    keys = ["char_edits", "ref_chars", "word_edits", "ref_words", "tp", "fp", "fn", "strength_total",
            "strength_correct", "frequency_total", "frequency_correct", "wrong_pred", "wrong_pred_flagged"]
    t = {k: sum(item[k] for item in per_item) for k in keys}
    precision, recall, f1 = prf(t["tp"], t["fp"], t["fn"], 1.0)
    _, _, f2 = prf(t["tp"], t["fp"], t["fn"], 2.0)

    def rate(num, den):
        return round(num / den, 4) if den else None

    def ci(num, den):
        return [round(x, 4) for x in wilson_interval(num, den)] if den else None

    return {
        "cer": rate(t["char_edits"], t["ref_chars"]),
        "wer": rate(t["word_edits"], t["ref_words"]),
        "medicine_precision": round(precision, 4), "medicine_precision_ci95": ci(t["tp"], t["tp"] + t["fp"]),
        "medicine_recall": round(recall, 4), "medicine_recall_ci95": ci(t["tp"], t["tp"] + t["fn"]),
        "medicine_f1": round(f1, 4), "medicine_f2": round(f2, 4),
        "strength_exact_match": rate(t["strength_correct"], t["strength_total"]),
        "frequency_exact_match": rate(t["frequency_correct"], t["frequency_total"]),
        "missed_medicine_rate": rate(t["fn"], t["tp"] + t["fn"]),
        "wrong_or_invented_medicine_rate": rate(t["fp"], t["tp"] + t["fp"]),
        "wrong_predictions_flagged_share": rate(t["wrong_pred_flagged"], t["wrong_pred"]),
        "counts": t,
    }


def evaluate_items(items, predict):
    """predict(image_path) -> (list of predicted meds, status string)."""
    per_item, statuses = [], {}
    total = len(items)
    for idx, item in enumerate(items, 1):
        img_name = Path(item["image"]).name
        print(f"[{idx}/{total}] Processing {img_name}...", end=" ", flush=True)
        try:
            preds, status = predict(item["image"])
            print(f"done ({len(preds)} meds, status: {status})")
        except (RecognitionError, InvalidImage) as exc:
            preds, status = [], "error: %s" % exc
            print(f"FAILED ({status})")
        statuses[status] = statuses.get(status, 0) + 1
        scored = score_item(item["medicines"], preds)
        scored["image"] = img_name
        scored["status"] = status
        per_item.append(scored)
        if idx < total:
            time.sleep(2.5)  # Backoff to respect Groq free tier TPM limits
    summary = aggregate(per_item) if per_item else {}
    summary["statuses"] = statuses
    return summary, per_item


def make_predictor(model_override=None):
    from rxcore.config import get_settings
    from rxcore.formulary import Formulary
    from rxcore.pipeline import process_image
    from rxcore.recognizer import VLMRecognizer

    settings = get_settings()
    if model_override:
        settings.vlm_model = model_override
    if not settings.model_configured:
        sys.exit("No model configured. Fill in .env first (see README).")
    recognizer = VLMRecognizer(settings.vlm_base_url, settings.vlm_model,
                               settings.vlm_api_key, settings.vlm_timeout_s)
    formulary = Formulary.from_csv(settings.formulary_path)

    def predict(image_path):
        data = (ROOT / image_path).read_bytes()
        result = process_image(data, recognizer, settings, formulary)
        preds = [{
            "text": m["raw_text"], "name": m["name"],
            "strength": m["strength"]["raw"] if m["strength"] else "",
            "frequency": m["frequency"]["raw"] if m["frequency"] else "",
            "flagged": any(f["severity"] in ("critical", "warning") for f in m["flags"]),
        } for m in result["medicines"]]
        return preds, result["status"]

    return predict, recognizer.describe()


def write_report(out_dir, meta, summary, per_item):
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    payload = {"meta": meta, "summary": summary, "per_image": per_item}
    (out_dir / ("eval-%s.json" % stamp)).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def pct(value):
        return "n/a" if value is None else "%.1f%%" % (100 * value)

    def ci(value):
        return "" if not value else " (95%% CI %.1f-%.1f%%)" % (100 * value[0], 100 * value[1])

    c = summary["counts"]
    lines = [
        "# Evaluation report", "",
        "- Date: %s" % meta["date"],
        "- Model: %s via %s (prompt %s)" % (meta["model"]["model"], meta["model"]["endpoint_host"], meta["model"]["prompt_version"]),
        "- App version: %s, formulary: %s" % (meta["app_version"], meta["formulary_version"]),
        "- Images evaluated: %d (split: %s), medicine lines in ground truth: %d" % (meta["n_images"], meta["split"], c["tp"] + c["fn"]),
        "- Ground truth typed by: %s; second check by: %s" % (meta["annotator"] or "NOT RECORDED", meta["checked_by"] or "NOT DONE"),
        "- Machine: %s" % meta["machine"], "",
        "| Metric | Value |", "|---|---|",
        "| Character error rate (CER) | %s |" % pct(summary["cer"]),
        "| Word error rate (WER) | %s |" % pct(summary["wer"]),
        "| Medicine name precision | %s%s |" % (pct(summary["medicine_precision"]), ci(summary["medicine_precision_ci95"])),
        "| Medicine name recall | %s%s |" % (pct(summary["medicine_recall"]), ci(summary["medicine_recall_ci95"])),
        "| Medicine F1 / F2 | %s / %s |" % (pct(summary["medicine_f1"]), pct(summary["medicine_f2"])),
        "| Strength exact match (on correctly named medicines) | %s |" % pct(summary["strength_exact_match"]),
        "| Frequency exact match (on correctly named medicines) | %s |" % pct(summary["frequency_exact_match"]),
        "| Missed medicine rate | %s |" % pct(summary["missed_medicine_rate"]),
        "| Wrong or invented medicine rate | %s |" % pct(summary["wrong_or_invented_medicine_rate"]),
        "| Share of wrong medicines that carried a flag | %s |" % pct(summary["wrong_predictions_flagged_share"]),
        "", "Pipeline status per image: %s" % json.dumps(summary["statuses"]), "",
        "## Limitations", "",
        "- %d images is a small sample; the confidence intervals above show how uncertain the figures are." % meta["n_images"],
        "- A medicine counts as correct only when the name matches the ground truth exactly (ignoring case, spaces and punctuation).",
        "- Results apply to this model, this prompt and these handwriting styles only.",
    ]
    failed = sum(n for status, n in summary["statuses"].items() if status.startswith("error"))
    if failed:
        lines.append("- %d image(s) failed with a model or file error and were scored as nothing read. "
                     "Re-run before quoting these numbers." % failed)
    if not meta["checked_by"]:
        lines.append("- The ground truth has not been checked by a second person yet.")
    path = out_dir / ("eval-%s.md" % stamp)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default="data/ground_truth/labels.json")
    ap.add_argument("--split", default="test", help="test | dev | all")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--model", default=None,
                    help="evaluate this model id instead of VLM_MODEL (to compare models on the same test set)")
    args = ap.parse_args()

    labels_path = ROOT / args.labels
    if not labels_path.exists():
        sys.exit("No labels file at %s. Create it from labels.template.json (see README)." % args.labels)
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    items = [i for i in labels.get("items", [])
             if not i.get("example") and (args.split == "all" or i.get("split") == args.split)]
    items = [i for i in items if i.get("medicines") is not None and (ROOT / i["image"]).exists()]
    if not items:
        sys.exit("No labelled images found for split '%s'." % args.split)

    predict, model = make_predictor(args.model)
    print("Evaluating %d images with %s ..." % (len(items), model["model"]))
    summary, per_item = evaluate_items(items, predict)
    from rxcore.formulary import Formulary
    from rxcore.config import get_settings
    meta = {
        "date": time.strftime("%Y-%m-%d %H:%M"), "model": model, "app_version": __version__,
        "formulary_version": Formulary.from_csv(get_settings().formulary_path).version,
        "n_images": len(items), "split": args.split,
        "annotator": labels.get("annotator", ""), "checked_by": labels.get("checked_by", ""),
        "machine": "%s, Python %s" % (platform.platform(), platform.python_version()),
    }
    path = write_report(ROOT / args.out, meta, summary, per_item)
    print(path.read_text(encoding="utf-8"))
    print("Saved: %s" % path)


if __name__ == "__main__":
    main()
