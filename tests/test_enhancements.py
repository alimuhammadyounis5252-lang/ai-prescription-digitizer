import io

import pytest

from conftest import FakeRecognizer, make_image
from rxcore.agreement import compare_readings
from rxcore.fhir import record_to_fhir_bundle
from rxcore.parser import parse_frequency, parse_medicine_line
from rxcore.pipeline import build_medicine, flag_duplicates
from rxcore.formulary import Formulary
from rxcore.storage import correction_stats


def lines(*texts):
    return {"readable": True, "lines": [{"text": t, "kind": "medicine", "unclear": False} for t in texts]}


def upload(client, name="rx.jpg"):
    return client.post("/api/recognize", data={"file": (io.BytesIO(make_image()), name)},
                       content_type="multipart/form-data")


def codes(med):
    return [f["code"] for f in med["flags"]]


# ---- parser fixes found in the v2.0 review -----------------------------------
def test_vitamin_number_stays_in_the_name():
    med = parse_medicine_line("Tab Neurobion B12 1+0+0")
    assert med["name"] == "Neurobion B12" and med["strength"] is None


def test_single_letter_form_prefix():
    assert parse_medicine_line("T. Panadol 500mg 1+1+1")["form"] == "Tablet"
    assert parse_medicine_line("C. Risek 40mg 1+0+0")["form"] == "Capsule"


def test_instruction_words_are_not_part_of_the_name():
    assert parse_medicine_line("Cream Dermovate apply BD")["name"] == "Dermovate"


@pytest.mark.parametrize("text,code", [("1 x 2", "1x2"), ("1+1", "1+1")])
def test_short_notations_are_parsed_but_ambiguous(text, code):
    freq = parse_frequency("Tab Alpha 5mg " + text)[0]
    assert freq["code"] == code and freq["ambiguous"] is True


def test_times_notation_is_not_confused_with_duration():
    med = parse_medicine_line("Tab Beta 5mg 1 x 5 days")
    assert med["frequency"] is None and med["duration"]["value"] == 5


# ---- second reader -------------------------------------------------------------
def meds_from(*texts):
    return [dict(build_medicine(i, t, False, None)) for i, t in enumerate(texts, 1)]


def test_readers_agree():
    meds = meds_from("Tab Alpha 500mg 1+0+1", "Cap Beta 20mg OD")
    out = compare_readings(meds, lines("Tab. Alpha 500 mg 1-0-1", "Cap Beta 20mg once daily")["lines"])
    assert (out["agreed"], out["disagreed"], out["only_first"], out["only_second"]) == (2, 0, 0, [])
    assert "readers_disagree" not in codes(meds[0]) + codes(meds[1])


def test_name_disagreement_is_critical_and_not_merged():
    meds = meds_from("Tab Capoten 50mg 1+0+0")
    out = compare_readings(meds, lines("Tab Capozide 50mg 1+0+0")["lines"])
    assert out["disagreed"] == 1
    flag = [f for f in meds[0]["flags"] if f["code"] == "readers_disagree"][0]
    assert flag["severity"] == "critical" and "Capoten" in flag["message"] and "Capozide" in flag["message"]
    assert meds[0]["name"] == "Capoten" and meds[0]["second_reading"] == "Tab Capozide 50mg 1+0+0"


def test_strength_disagreement_is_critical():
    meds = meds_from("Tab Alpha 5mg 1+0+0")
    assert compare_readings(meds, lines("Tab Alpha 50mg 1+0+0")["lines"])["disagreed"] == 1


def test_lines_seen_by_one_reader_only():
    meds = meds_from("Tab Alpha 5mg 1+0+0", "Syp Zzzz 5ml TDS")
    out = compare_readings(meds, lines("Tab Alpha 5mg 1+0+0", "Inj Gamma 1g stat")["lines"])
    assert out["only_first"] == 1 and out["only_second"] == ["Inj Gamma 1g stat"]
    assert "second_reader_missing" in codes(meds[1])


def test_second_reader_through_the_api(settings):
    from app import create_app
    first, second = FakeRecognizer(), FakeRecognizer()
    second.model = "second-model"
    first.reply = lines("Tab Capoten 50mg 1+0+0")
    second.reply = lines("Tab Capozide 50mg 1+0+0", "Tab Extra 10mg 0+0+1")
    client = create_app(settings, first, second).test_client()
    assert client.get("/api/health").get_json()["second_reader"] == "second-model"
    body = upload(client).get_json()
    assert body["second_reader"]["disagreed"] == 1
    assert body["second_reader"]["only_second"] == ["Tab Extra 10mg 0+0+1"]
    assert body["medicines"][0]["needs_attention"] is True
    assert len(body["medicines"]) == 1                      # the extra line is shown, never auto-added
    extra = body["second_reader"]["only_second_rows"][0]
    assert (extra["name"], extra["strength"]["raw"], extra["line_no"]) == ("Extra", "10mg", None)
    assert extra["flags"][0]["code"] == "second_reader_only" and extra["needs_attention"] is True


def test_second_reader_failure_does_not_hide_the_first(settings):
    from app import create_app
    from rxcore.recognizer import RecognitionError

    class Broken(FakeRecognizer):
        def transcribe(self, jpeg_bytes):
            raise RecognitionError("Model server returned HTTP 500")

    first = FakeRecognizer()
    first.reply = lines("Tab Alpha 5mg 1+0+0")
    body = upload(create_app(settings, first, Broken()).test_client()).get_json()
    assert body["status"] == "ok" and len(body["medicines"]) == 1
    assert body["second_reader"]["enabled"] is False and "HTTP 500" in body["second_reader"]["error"]


# ---- duplicates ----------------------------------------------------------------
def test_duplicate_name_and_duplicate_ingredient(settings):
    formulary = Formulary.from_csv(settings.formulary_path)
    meds = [build_medicine(1, "Tab Ascard 75mg 0+1+0", False, formulary),
            build_medicine(2, "Tab Disprin 300mg 0+0+1", False, formulary),      # both aspirin in the list
            build_medicine(3, "Tab Ascard 75mg 1+0+0", False, formulary)]
    flag_duplicates(meds)
    assert "duplicate_ingredient" in codes(meds[0]) and "duplicate_ingredient" in codes(meds[1])
    assert "duplicate_name" in codes(meds[0]) and "duplicate_name" in codes(meds[2])
    assert "duplicate_name" not in codes(meds[1])
    assert all(f["severity"] == "warning" for m in meds for f in m["flags"] if f["code"].startswith("duplicate"))


def test_no_duplicate_flag_for_unrelated_medicines(settings):
    formulary = Formulary.from_csv(settings.formulary_path)
    meds = [build_medicine(1, "Tab Capoten 50mg 1+0+0", False, formulary),
            build_medicine(2, "Tab Panadol 500mg 1+1+1", False, formulary)]
    flag_duplicates(meds)
    assert not any(c.startswith("duplicate") for m in meds for c in codes(m))


# ---- records, stats, FHIR --------------------------------------------------------
def approve_one(client, fake, edit=False):
    fake.reply = lines("Tab Alpha 500mg 1+0+1 after meal", "Cap Beta 20mg OD")
    result = upload(client).get_json()
    rows = [{"line_no": m["line_no"], "raw_text": m["raw_text"], "form": m["form"], "name": m["name"],
             "strength": m["strength"]["raw"], "frequency": m["frequency"]["raw"],
             "food": "after meal" if m["food"] else "", "checked": True} for m in result["medicines"]]
    if edit:
        rows[1]["frequency"] = "1+0+0"
    return client.post("/api/records", json={"request_id": result["request_id"], "pharmacist": "A. Pharmacist",
                                             "medicines": rows}).get_json()


def test_record_list_and_stats(client, fake, settings):
    assert client.get("/api/records").get_json() == {"records": []}
    approve_one(client, fake)
    approve_one(client, fake, edit=True)
    listed = client.get("/api/records").get_json()["records"]
    assert len(listed) == 2 and {r["corrections"] for r in listed} == {0, 1}
    stats = client.get("/api/stats").get_json()
    assert stats == correction_stats(settings.records_dir)
    assert (stats["records"], stats["model_rows"], stats["rows_kept_unchanged"], stats["rows_edited"]) == (2, 4, 3, 1)
    assert stats["edits_by_field"] == {"frequency": 1}


def test_timestamps_are_iso_8601_with_offset(client, fake):
    record = approve_one(client, fake)
    assert record["approved_at"][10] == "T" and record["approved_at"][-3] == ":"


def test_fhir_bundle_contents(client, fake):
    record = approve_one(client, fake, edit=True)
    bundle = client.get("/api/records/%s/fhir" % record["record_id"]).get_json()
    kinds = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert kinds == ["MedicationRequest", "MedicationRequest", "Provenance"]
    first = bundle["entry"][0]["resource"]
    assert first["medicationCodeableConcept"] == {"text": "Tablet Alpha 500mg"}
    assert "coding" not in first["medicationCodeableConcept"]             # no invented codes
    assert "reference" not in first["subject"]                             # no invented patient
    assert first["dosageInstruction"][0]["text"] == "1+0+1, after meal"
    assert first["dosageInstruction"][0]["patientInstruction"].startswith("صبح ایک گولی")
    prov = bundle["entry"][2]["resource"]
    assert [t["reference"] for t in prov["target"]] == [e["fullUrl"] for e in bundle["entry"][:2]]
    assert prov["agent"][0]["who"]["display"] == "A. Pharmacist"
    assert "reasonCode" not in str(bundle) and "Condition" not in str(bundle)   # no diagnosis
    assert client.get("/api/records/RX-20260101-000000-abcdef/fhir").status_code == 404


def test_fhir_bundle_is_structurally_valid_r4b(client, fake):
    bundle_model = pytest.importorskip("fhir.resources.R4B.bundle")
    record = approve_one(client, fake)
    bundle_model.Bundle.model_validate(record_to_fhir_bundle(record))


# ---- access code and headers ---------------------------------------------------------
def test_access_code(settings, fake):
    from app import create_app
    settings.access_code = "open-sesame"
    client = create_app(settings, fake).test_client()
    assert client.get("/api/health").get_json()["login_required"] is True
    assert client.get("/api/records").status_code == 401
    assert upload(client).status_code == 401 and fake.calls == 0
    assert client.post("/api/login", json={"code": "wrong"}).status_code == 403
    assert client.post("/api/login", json={"code": "open-sesame"}).status_code == 200
    assert client.get("/api/records").status_code == 200
    assert client.get("/api/health").get_json()["login_required"] is False


def test_no_access_code_means_open(client):
    assert client.get("/api/health").get_json()["login_required"] is False
    assert client.get("/api/records").status_code == 200


def test_static_files_and_security_headers(client):
    page = client.get("/")
    assert page.status_code == 200 and b"/static/app.js" in page.data
    assert b"<script>" not in page.data and b"onclick=" not in page.data      # nothing inline
    csp = page.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "unsafe-inline" not in csp
    assert page.headers["X-Content-Type-Options"] == "nosniff"
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/../app.py").status_code == 404
    assert client.get("/api/health").headers["Cache-Control"] == "no-store"
