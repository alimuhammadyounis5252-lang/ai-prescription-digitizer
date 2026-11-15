# Changelog

## 2.1.1 - 2026-11-14

Bug-fix release after a second review. Every fix has a regression test (`tests/test_fixes_v211.py`)
that fails on 2.1.0 and passes now.

### Fixed
- **Double approval.** Two approvals arriving together (double click, two tabs) both returned 201 and
  wrote two audit-log lines for one record. The pending result is now claimed atomically, so only one
  approval succeeds and the other gets a clear message. The button is also disabled while a request runs.
- **`.env` on Windows.** A `.env` saved by Notepad with a BOM silently lost its first line (often
  `VLM_BASE_URL`, so the app said "No model connected" with a correct file). Now read as `utf-8-sig`.
- **`.env` inline comments.** `PORT=5000   # default` was read as the text "5000   # default" and crashed
  at start-up; the commented examples in `.env.example` had the same problem once uncommented.
- **`data/formulary.csv` saved by Excel** (BOM) crashed the whole app with `KeyError: 'brand'`.
- **Photo loading.** A very large image raised an uncaught `DecompressionBombError` (HTTP 500); a
  1-pixel-high strip made the blur metric `NaN`, which is invalid JSON (HTTP 500); a PNG with transparent
  background turned black, so the writing was invisible and the page was rejected as blank. A damaged EXIF
  block also crashed loading.
- **Syrup strength.** `120mg/5ml` was shortened to `120mg`, hiding the concentration. It is kept whole.
- **Damaged record files.** One broken file in `records/` made both the records page and the statistics
  return HTTP 500. Such files are now skipped.
- **`evaluate.py`** stopped at the first model error (for example HTTP 429 rate limit) and lost the whole
  run. A failed image is now scored as "nothing read", listed under its error, and the report says so.
  It also prints safely on Windows consoles.
- **Frontend.** A non-JSON server error was shown as "server not reachable"; a failed approval request was
  ignored silently. A local variable named `share` hid the `share()` function inside `loadRecords`.
- **Docker.** Records were written inside the container and deleted with it; the container ran as root.
  Added a non-root user and the volume instruction.

### Added
- A warning in the log when `HOST` is not local and `APP_ACCESS_CODE` is not set.

### Not changed (known, listed in the README)
- Access code has no limit on wrong attempts. Fine for one trusted PC; add a throttle before exposing it.
- A bare dose such as "5ml" on a syrup line is still read as a strength.

## 2.1.0 - 2026-11-13

### Fixed (found in a review of 2.0.0)
- "Neurobion B12" was split into name "Neurobion B" and strength "12". Numbers glued to a letter now stay in the name.
- "T. Panadol" / "C. Risek" were not recognised as tablet / capsule.
- Words like "apply" or "take" were kept as part of the medicine name.
- "1 x 2" and "1+1" notations were ignored. They are now read, and always marked "confirm" because the times of day are not stated.
- The glare warning fired on every white page; it is off until calibrated. The blur warning default was too strict for the sample photos.
- Timestamps had no colon in the UTC offset (invalid for FHIR). Now ISO 8601.
- Upload limit raised from 10 to 15 MB for phone photos.
- Page script and styles moved out of the HTML so a strict Content-Security-Policy can be used.

### Added
- Second-reader cross-check with a second model (`VLM_MODEL_2`).
- Duplicate medicine and duplicate active-ingredient warnings (source: the reference list).
- Approved-records page with audit trail and pharmacist-correction statistics.
- FHIR R4 export (MedicationRequest + Provenance), structurally validated in tests.
- Optional access code, security headers, `HOST` / `PORT` settings.
- `evaluate.py --model` for comparing models; `tools/records_to_labels.py`; `Dockerfile` (untested).
- `docs/ARCHITECTURE.md`, `docs/VIVA_GUIDE.md`, `AGLE_STEPS.md`. Tests: 60 -> 81.

## 2.0.0 - 2026-11-13

Rebuilt after the audit (docs/AUDIT_SUMMARY.md).

### Removed
- All hardcoded output: filename keywords, aspect-ratio / ink-band rules, the built-in
  sample records and the "fallback" medicines. Old code is kept in `archive/legacy/`.
- Invented confidence scores, "VERIFIED_BY_FORMULARY" status, drug purposes in Urdu,
  drug-to-ICD-10 mapping, built-in interaction rules, WhatsApp link with stored phone number.
- Simulated training / benchmark scripts and their numbers (archived, not to be cited).

### Added
- Real recognition through a vision-language model (OpenAI-compatible endpoint: Hugging Face
  Inference Providers or local Ollama). Transcription-only prompt with an explicit unreadable state.
- Deterministic line parser (form, name, strength, frequency, duration, food) that fills a
  field only when it is written.
- Image quality gate: blank or tiny images are rejected before the model is called.
- Reference-list lookup that suggests and flags, and never replaces what was read.
- Urdu instruction generated only from a complete, unambiguous schedule.
- Pharmacist review with per-row confirmation, approve-and-lock, and an audit trail of every correction.
- `evaluate.py`: CER, WER, medicine precision / recall / F1 / F2 with 95% confidence intervals.
- 60 automated tests.

### Not done yet
- No accuracy has been measured: ground truth must be typed first (README, "Measure accuracy").
- The real model call has been tested against a local stand-in server only, not against a live model.
