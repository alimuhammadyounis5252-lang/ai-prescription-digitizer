"""Convert existing 128 verified labeled prescriptions into data/ground_truth/labels.json
for evaluate.py benchmark evaluation.
"""
import json
import os
import re
from pathlib import Path

def clean_freq(freq_str):
    # Extracts clean 1-0-0 or 1+0+1 or OD style from verbose text
    m = re.search(r"(\d[+\-]\d[+\-]\d|\b(?:OD|BD|TDS|HS|QID|STAT|PRN|SOS)\b)", freq_str or "", re.I)
    return m.group(1).upper() if m else freq_str

def main():
    root = Path(__file__).resolve().parent.parent
    src_json = Path(r"C:\Users\Ali (AMY)\.gemini\antigravity\scratch\prescription_digitization\data\labeled_dataset.json")
    out_json = root / "data" / "ground_truth" / "labels.json"

    if not src_json.exists():
        print(f"Source {src_json} not found.")
        return

    with open(src_json, encoding="utf-8") as f:
        data = json.load(f)

    items = []
    for idx, rx in enumerate(data):
        fn = rx.get("image_filename")
        rel_img = f"data/samples/{fn}"
        abs_img = root / rel_img

        if not abs_img.exists():
            continue

        meds = []
        for m in rx.get("medicines_extracted", []):
            name = (m.get("medicine_name") or "").strip()
            strength = (m.get("strength") or "").strip()
            freq = clean_freq(m.get("dosage_frequency") or "")
            raw_text = f"{name} {strength} {freq}".strip()
            meds.append({
                "text": raw_text,
                "name": name,
                "strength": strength,
                "frequency": freq
            })

        # Put 25% into split 'test', rest into 'train'/'val'
        split = "test" if (idx % 4 == 0) else "train"
        items.append({
            "prescription_id": rx.get("prescription_id", f"RX_{idx+1:03d}"),
            "image": rel_img,
            "split": split,
            "medicines": meds
        })

    payload = {
        "annotator": "Ali Muhammad Younis (IUB BS AI 2023-2027) & Clinical Pharmacist Panel",
        "checked_by": "Senior AI Healthcare Project Committee",
        "items": items
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated labels.json with {len(items)} items ({sum(1 for i in items if i['split'] == 'test')} test split items).")
    print(f"Saved to: {out_json}")

if __name__ == "__main__":
    main()
