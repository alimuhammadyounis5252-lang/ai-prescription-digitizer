# Architecture

## Purpose and boundary

Input: a photo of a handwritten prescription. Output: a pharmacist-approved, structured record.
The AI proposes; a pharmacist decides. The system never prescribes, diagnoses, changes a dose or
approves anything.

## Pipeline

| Step | Module | What it does | Why it is built this way |
|---|---|---|---|
| 1. Quality gate | `rxcore/quality.py` | Rejects blank or tiny images; warns on dark or blurred ones | A model asked to read an empty page may invent text. Rejecting first makes that impossible |
| 2. Transcription | `rxcore/recognizer.py` | A vision-language model copies the handwriting line by line, marks unclear parts with `[?]`, and labels each line (medicine, lab, patient, doctor, note) | The model is used only for the task it is needed for: reading. It is told not to add generics, doses or corrections |
| 3. Cross-check (optional) | `rxcore/agreement.py` | A second model reads the same photo; differences are flagged | Disagreement between two readers is an honest uncertainty signal. The models give no calibrated confidence |
| 4. Parsing | `rxcore/parser.py` | Regular expressions split each medicine line into form, name, strength, frequency, duration, food | Deterministic and explainable. A field is filled only if it is written, so every value can be traced to the raw text |
| 5. Reference lookup | `rxcore/formulary.py` | Exact name match adds reference details; near match (Levenshtein similarity >= 0.72) becomes a flagged suggestion | Auto-correcting to the nearest listed drug is how a wrong-drug error would be created, so the matcher never replaces text |
| 6. Safety flags | `rxcore/pipeline.py` | Unclear line, missing or unit-less strength, missing or ambiguous frequency, duplicate name or ingredient | Flags direct the pharmacist's attention. Critical flags mark the row red |
| 7. Urdu instruction | `rxcore/urdu.py` | Builds the sentence from a complete schedule; otherwise says "not clear, confirm with pharmacist" | A patient instruction must never be built from a guess |
| 8. Review and approval | `web/`, `app.py` | Pharmacist edits, ticks every row, enters a name, approves. Record is locked | Human in the loop is enforced by the server, not only by the page |
| 9. Record and audit | `rxcore/storage.py` | Saves final rows, the model's original output and every correction | Shows who decided what, and gives real-use correction statistics |
| 10. Export | `rxcore/fhir.py` | JSON, FHIR R4 Bundle, print, share Urdu text | Interoperable format without inventing patient ids, codes or diagnoses |

Patient identity lines are dropped at step 2-3 and never stored. Uploaded photos are not kept
unless `KEEP_UPLOADS=1`.

## API

| Method and path | Purpose |
|---|---|
| `GET /api/health` | Model, second reader, formulary version, whether login is required |
| `POST /api/recognize` | Upload a photo, get the extraction result |
| `POST /api/urdu` | Re-generate Urdu text for edited rows |
| `POST /api/records` | Approve and lock (needs pharmacist name and every row ticked) |
| `GET /api/records`, `/api/records/<id>`, `/api/records/<id>/fhir` | List, read, export |
| `GET /api/stats` | Pharmacist-correction statistics |
| `POST /api/login` | Access code, when one is set |

Errors: 400 bad file, 401 login needed, 413 too large, 422 approval rules not met,
502 model failed, 503 no model configured. A failure never returns medicines.

## Model interface

Any OpenAI-compatible chat-completions endpoint with image input. Temperature 0. The prompt
(`PROMPT_VERSION` in `recognizer.py`) is versioned and recorded in every result, with the model
id, so a result can be reproduced.

## Security and privacy measures in place

Secrets only in `.env`; optional access code; strict Content-Security-Policy and no inline
script; no patient data in logs; identity lines dropped; uploads not retained by default;
records and sample photos excluded from git. No legal compliance is claimed.

## What is not built (future work)

Drug-drug interaction and dose-range checks (need a licensed clinical source); a reference list
built from official DRAP publications; calibrated per-field confidence; user accounts and roles;
fine-tuning or physician-specific adaptation; other regional languages; hospital integration.
