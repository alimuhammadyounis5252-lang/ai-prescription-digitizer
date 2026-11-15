"""Approved-record storage with an audit trail (plain JSON files)."""
import json
import re
import threading
import time
from datetime import datetime
from collections import OrderedDict
from pathlib import Path


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class PendingStore:
    """Keeps model outputs in memory until a pharmacist approves or abandons
    them, so the 'original model output' in the audit trail cannot be altered
    by the browser."""

    def __init__(self, max_items=200):
        self._items = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_items

    def put(self, result):
        with self._lock:
            self._items[result["request_id"]] = result
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def pop(self, request_id):
        with self._lock:
            return self._items.pop(request_id, None)

    def get(self, request_id):
        with self._lock:
            return self._items.get(request_id)


def _changes(original_meds, final_meds):
    """List what the pharmacist changed compared with the model output."""
    def view(med):
        return {
            "name": med.get("name") or "",
            "form": med.get("form") or "",
            "strength": (med.get("strength") or {}).get("raw", "") if isinstance(med.get("strength"), dict)
                        else (med.get("strength") or ""),
            "frequency": (med.get("frequency") or {}).get("raw", "") if isinstance(med.get("frequency"), dict)
                         else (med.get("frequency") or ""),
        }
    by_line = {m.get("line_no"): view(m) for m in original_meds}
    changes, seen = [], set()
    for med in final_meds:
        line_no = med.get("line_no")
        if line_no in by_line:
            seen.add(line_no)
            before, after = by_line[line_no], view(med)
            for key in before:
                if before[key].strip() != after[key].strip():
                    changes.append({"line_no": line_no, "field": key,
                                    "model": before[key], "pharmacist": after[key]})
        else:
            changes.append({"line_no": None, "field": "row_added", "model": "", "pharmacist": med.get("name", "")})
    for line_no, before in by_line.items():
        if line_no not in seen:
            changes.append({"line_no": line_no, "field": "row_removed", "model": before["name"], "pharmacist": ""})
    return changes


def save_approved(records_dir, original, final_meds, pharmacist):
    records_dir = Path(records_dir)
    records_dir.mkdir(parents=True, exist_ok=True)
    record_id = "RX-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), original["request_id"][:6])
    record = {
        "record_id": record_id,
        "status": "APPROVED_LOCKED",
        "approved_by": pharmacist,
        "approved_at": now_iso(),
        "image_sha256": original["image_sha256"],
        "model": original["model"],
        "app_version": original["app_version"],
        "formulary_version": original.get("formulary_version"),
        "medicines": final_meds,
        "other_lines": original.get("other_lines", []),
        "audit": {
            "model_output": original["medicines"],
            "changes_by_pharmacist": _changes(original["medicines"], final_meds),
        },
    }
    path = records_dir / (record_id + ".json")
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(records_dir / "audit.log", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": record["approved_at"], "event": "approved", "record_id": record_id,
                             "by": pharmacist, "rows": len(final_meds),
                             "changes": len(record["audit"]["changes_by_pharmacist"])}) + "\n")
    return record


def load_record(records_dir, record_id):
    if not re.fullmatch(r"RX-[0-9]{8}-[0-9]{6}-[0-9a-f]{6}", record_id or ""):
        return None
    path = Path(records_dir) / (record_id + ".json")
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_records(records_dir):
    """Yield every readable, well-formed record. A damaged or foreign file is
    skipped, so one bad file cannot take down the list and statistics pages."""
    for path in sorted(Path(records_dir).glob("RX-*.json"), reverse=True):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            for key in ("record_id", "approved_by", "approved_at", "model", "medicines", "audit"):
                rec[key]
            rec["model"]["model"], rec["audit"]["changes_by_pharmacist"], rec["audit"]["model_output"]
        except (ValueError, OSError, KeyError, TypeError):
            continue
        yield rec


def list_records(records_dir):
    """Newest first. Returns light summaries, not the full records."""
    return [{"record_id": rec["record_id"], "approved_by": rec["approved_by"],
             "approved_at": rec["approved_at"], "model": rec["model"]["model"],
             "medicines": len(rec["medicines"]),
             "corrections": len(rec["audit"]["changes_by_pharmacist"])}
            for rec in _read_records(records_dir)]


def correction_stats(records_dir):
    """How often pharmacists had to correct the model, from approved records.

    This describes real use of the tool. It is not an accuracy figure: it
    depends on how carefully each record was reviewed.
    """
    stats = {"records": 0, "model_rows": 0, "rows_kept_unchanged": 0, "rows_edited": 0,
             "rows_removed": 0, "rows_added": 0, "edits_by_field": {}}
    for rec in _read_records(records_dir):
        stats["records"] += 1
        changes = rec["audit"]["changes_by_pharmacist"]
        model_rows = len(rec["audit"]["model_output"])
        edited = {c["line_no"] for c in changes if c["field"] not in ("row_added", "row_removed")}
        removed = sum(1 for c in changes if c["field"] == "row_removed")
        stats["model_rows"] += model_rows
        stats["rows_edited"] += len(edited)
        stats["rows_removed"] += removed
        stats["rows_added"] += sum(1 for c in changes if c["field"] == "row_added")
        stats["rows_kept_unchanged"] += model_rows - len(edited) - removed
        for c in changes:
            stats["edits_by_field"][c["field"]] = stats["edits_by_field"].get(c["field"], 0) + 1
    return stats
