"""Turn pharmacist-approved records into DRAFT ground-truth entries.

    python tools/records_to_labels.py

A record is matched to its photo in data/samples by the image fingerprint
(SHA-256). New entries get "split": "dev".

Important: these labels were made while looking at the model's output, so they
are biased toward the model. Use them for development only. The TEST split must
be typed by hand from the photo without seeing any model output.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "data" / "ground_truth" / "labels.json"
SAMPLES = ROOT / "data" / "samples"
RECORDS = ROOT / "records"


def main():
    by_hash = {hashlib.sha256(p.read_bytes()).hexdigest(): "data/samples/" + p.name
               for p in SAMPLES.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")}
    labels = (json.loads(LABELS.read_text(encoding="utf-8")) if LABELS.exists()
              else {"annotator": "", "checked_by": "", "items": []})
    labels["items"] = [i for i in labels["items"] if not i.get("example")]
    index = {i["image"]: i for i in labels["items"]}
    added = skipped = 0
    for path in sorted(RECORDS.glob("RX-*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        image = by_hash.get(record["image_sha256"])
        if image is None:
            skipped += 1
            continue
        entry = index.get(image)
        if entry and entry.get("medicines") is not None:
            continue                                   # never overwrite typed labels
        meds = [{"text": " ".join(x for x in (m.get("form"), m["name"], m.get("strength"), m.get("frequency")) if x),
                 "name": m["name"], "strength": m.get("strength", ""), "frequency": m.get("frequency", "")}
                for m in record["medicines"]]
        new = {"image": image, "split": "dev", "medicines": meds,
               "source": "approved record %s (model-assisted, dev only)" % record["record_id"]}
        if entry:
            entry.update(new)
        else:
            labels["items"].append(new)
            index[image] = new
        added += 1
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    LABELS.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Added %d draft entries (split: dev). %d records had no matching photo in data/samples." % (added, skipped))


if __name__ == "__main__":
    main()
