"""Add an empty entry to data/ground_truth/labels.json for every photo in
data/samples that has no entry yet. Fill the entries in by hand afterwards.

    python tools/new_label_entries.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "data" / "ground_truth" / "labels.json"
SAMPLES = ROOT / "data" / "samples"


def main():
    labels = (json.loads(LABELS.read_text(encoding="utf-8")) if LABELS.exists()
              else {"annotator": "", "checked_by": "", "items": []})
    labels["items"] = [i for i in labels["items"] if not i.get("example")]
    known = {i["image"] for i in labels["items"]}
    added = 0
    for path in sorted(SAMPLES.iterdir()):
        rel = "data/samples/" + path.name
        if path.suffix.lower() in (".jpg", ".jpeg", ".png") and rel not in known:
            labels["items"].append({"image": rel, "split": "dev", "medicines": None})
            added += 1
    LABELS.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Added %d entries. Total: %d. Entries with medicines = null are skipped by evaluate.py "
          "until you type them." % (added, len(labels["items"])))


if __name__ == "__main__":
    main()
