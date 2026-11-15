"""Medicine reference list and name matching.

The matcher SUGGESTS. It never changes what the model read. An exact match
adds reference details; a near match is shown to the pharmacist as "did the
doctor mean ...?" and raises a flag, because a look-alike name is exactly how
a wrong-drug error happens.
"""
import csv
import re

from .metrics import similarity

SUGGEST_THRESHOLD = 0.72   # string similarity for showing a suggestion (uncalibrated)
MAX_SUGGESTIONS = 3


def _norm(name):
    if not name:
        return ""
    clean = re.sub(r"^[^\w]+", "", (name or "").strip())
    clean = re.sub(r"^(tab|cap|gp|cp|syp|inj|syr|drops?|cream|oint|t|c)\b[.\s\-_:]*", "", clean, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", clean.lower())


def _norm_strength(value, unit=None):
    return re.sub(r"\s+", "", "%s%s" % (value or "", unit or "")).lower().replace("gm", "g")


class Formulary:
    def __init__(self, rows, version="unknown"):
        self.rows = rows
        self.version = version
        self._by_norm = {}
        for row in rows:
            self._by_norm.setdefault(_norm(row["brand"]), row)

    @classmethod
    def from_csv(cls, path):
        rows, version = [], "unknown"
        with open(path, encoding="utf-8-sig", newline="") as fh:  # utf-8-sig: Excel/Notepad add a BOM
            lines = [ln for ln in fh if ln.strip()]
        if lines and lines[0].startswith("#"):
            version = lines[0].lstrip("# ").strip()
            lines = lines[1:]
        for row in csv.DictReader(lines):
            row["strengths"] = [s.strip() for s in (row.get("strengths") or "").split("|") if s.strip()]
            row["verified"] = (row.get("verified") or "").strip().lower() == "yes"
            rows.append(row)
        return cls(rows, version)

    def __len__(self):
        return len(self.rows)

    def lookup(self, name, strength=None):
        """Return {"match_type", "entry", "suggestions", "flags"}."""
        result = {"match_type": "none", "entry": None, "suggestions": [], "flags": []}
        key = _norm(name)
        if not key or not self.rows:
            return result

        entry = self._by_norm.get(key)
        if entry:
            result["match_type"] = "exact"
            result["entry"] = self._public(entry)
            if strength and strength.get("value") and entry["strengths"]:
                written = _norm_strength(strength["value"], strength.get("unit"))
                listed = [_norm_strength(s) for s in entry["strengths"]]
                listed_values = [re.sub(r"[a-z%]+$", "", s) for s in listed]
                if written not in listed and written not in listed_values:
                    result["flags"].append({
                        "code": "strength_not_listed", "severity": "warning",
                        "message": "Strength %s is not in the reference list for %s (%s). "
                                   "The list may be incomplete: verify."
                                   % (strength["raw"], entry["brand"], ", ".join(entry["strengths"]))})
            return result

        scored = []
        first_word = _norm((name or "").split()[0]) if (name or "").split() else key
        for row in self.rows:
            brand = _norm(row["brand"])
            score = max(similarity(key, brand), similarity(first_word, brand))
            if score >= SUGGEST_THRESHOLD:
                scored.append((score, row))
        scored.sort(key=lambda item: -item[0])
        for score, row in scored[:MAX_SUGGESTIONS]:
            item = self._public(row)
            item["similarity"] = round(score, 2)
            result["suggestions"].append(item)
        if result["suggestions"]:
            result["match_type"] = "similar"
            names = ", ".join(s["brand"] for s in result["suggestions"])
            result["flags"].append({
                "code": "similar_name", "severity": "warning",
                "message": "Not in the reference list, but similar to: %s. "
                           "Check the original; do not assume." % names})
        else:
            result["flags"].append({
                "code": "not_in_list", "severity": "info",
                "message": "Name is not in DRAP reference list. Pharmacist must verify with original prescription."})
        return result

    @staticmethod
    def _public(row):
        return {"brand": row["brand"], "generic": row.get("generic", ""),
                "strengths": row["strengths"], "form": row.get("form", ""),
                "source": row.get("source", ""), "verified": row["verified"]}
