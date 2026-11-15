"""Compare two independent readings of the same prescription.

When a second model is configured, both models transcribe the image. Where they
agree nothing changes. Where they differ on a medicine name or strength, or
where one model saw a line the other did not, the row is flagged for the
pharmacist. Disagreement between two readers is a real uncertainty signal; it
replaces the invented confidence percentages of the old version.

Outputs are never merged or averaged: the first model's text stays as the row,
and the second reading is shown beside it.
"""
import re

from .metrics import normalise_text, similarity
from .parser import parse_medicine_line

SAME_LINE_THRESHOLD = 0.45     # how alike two lines must be to count as the same line


def _key(text):
    return re.sub(r"[^a-z0-9]", "", normalise_text(text))


def _strength_key(strength):
    if not strength:
        return ""
    return _key("%s%s" % (strength.get("value", ""), strength.get("unit") or ""))


def compare_readings(medicines, second_lines):
    """Add flags to `medicines` (built from the first model) using the second
    model's medicine lines. Returns a summary dict."""
    second = [parse_medicine_line(line["text"], line.get("unclear", False))
              for line in second_lines if line.get("kind") == "medicine"]
    unused = list(range(len(second)))
    summary = {"agreed": 0, "disagreed": 0, "only_first": 0, "only_second": []}

    for med in medicines:
        best, best_score = None, 0.0
        for idx in unused:
            score = max(similarity(_key(med["raw_text"]), _key(second[idx]["raw_text"])),
                        similarity(_key(med["name"]), _key(second[idx]["name"])))
            if score > best_score:
                best, best_score = idx, score
        if best is None or best_score < SAME_LINE_THRESHOLD:
            summary["only_first"] += 1
            med["second_reading"] = None
            med["flags"].append({"code": "second_reader_missing", "severity": "warning",
                                 "message": "The second model did not read this line. Check that it is really on the page."})
            continue
        unused.remove(best)
        other = second[best]
        med["second_reading"] = other["raw_text"]
        differences = []
        if _key(med["name"]) != _key(other["name"]):
            differences.append("name '%s' vs '%s'" % (med["name"], other["name"]))
        if _strength_key(med["strength"]) != _strength_key(other["strength"]):
            differences.append("strength '%s' vs '%s'" % (
                med["strength"]["raw"] if med["strength"] else "none",
                other["strength"]["raw"] if other["strength"] else "none"))
        if differences:
            summary["disagreed"] += 1
            med["flags"].append({"code": "readers_disagree", "severity": "critical",
                                 "message": "Two models read this line differently (%s). Read the original."
                                            % "; ".join(differences)})
        else:
            summary["agreed"] += 1

    summary["only_second"] = [second[idx]["raw_text"] for idx in unused]
    return summary
