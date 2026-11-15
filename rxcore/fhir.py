"""FHIR R4 export of an approved record.

Produces a Bundle (type "collection") with one MedicationRequest per medicine
and one Provenance resource for the pharmacist's verification.

Honest scope:
  * Only data that exists in the approved record is exported.
  * Medicines carry text only, no code: the project has no licensed drug
    terminology to code against.
  * Patient identity is not stored by this system, so `subject` has a display
    text and no reference.
  * This is a FHIR-formatted export. It has not been sent to, or accepted by,
    any hospital system.
"""
import uuid

NO_PATIENT = "Patient identity is not stored by this system"


def _dosage_text(med):
    parts = [med.get("frequency"), med.get("duration"), med.get("food")]
    return ", ".join(p for p in parts if p)


def record_to_fhir_bundle(record):
    entries, targets = [], []
    for med in record["medicines"]:
        full_url = "urn:uuid:%s" % uuid.uuid4()
        label = " ".join(p for p in (med.get("form"), med.get("name"), med.get("strength")) if p)
        resource = {
            "resourceType": "MedicationRequest",
            "status": "active",
            "intent": "order",
            "medicationCodeableConcept": {"text": label},
            "subject": {"display": NO_PATIENT},
            "authoredOn": record["approved_at"],
            "note": [{"text": "Transcribed from a handwritten prescription by model %s and verified by "
                              "pharmacist %s. Record %s." % (record["model"]["model"], record["approved_by"],
                                                             record["record_id"])}],
        }
        dosage = {}
        if _dosage_text(med):
            dosage["text"] = _dosage_text(med)
        if (med.get("urdu") or {}).get("complete"):
            dosage["patientInstruction"] = med["urdu"]["text"]
        if dosage:
            resource["dosageInstruction"] = [dosage]
        entries.append({"fullUrl": full_url, "resource": resource})
        targets.append({"reference": full_url})

    if targets:
        entries.append({"fullUrl": "urn:uuid:%s" % uuid.uuid4(), "resource": {
            "resourceType": "Provenance",
            "target": targets,
            "recorded": record["approved_at"],
            "agent": [
                {"type": {"text": "verifier"}, "who": {"display": record["approved_by"]}},
                {"type": {"text": "assembler"},
                 "who": {"display": "AI Prescription Digitizer %s (%s)" % (record["app_version"], record["model"]["model"])}},
            ],
        }})
    return {"resourceType": "Bundle", "type": "collection", "timestamp": record["approved_at"], "entry": entries}
