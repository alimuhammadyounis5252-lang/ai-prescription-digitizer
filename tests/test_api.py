import io
import json

from conftest import FakeRecognizer, make_image

LINES_A = {"readable": True, "lines": [
    {"text": "Patient: Test Person 45y", "kind": "patient", "unclear": False},
    {"text": "Tab Alpha 500mg 1+0+1 after meal", "kind": "medicine", "unclear": False},
    {"text": "Cap Be[?]a 20mg OD", "kind": "medicine", "unclear": True},
    {"text": "Hb 12.6", "kind": "lab", "unclear": False}]}
LINES_B = {"readable": True, "lines": [{"text": "Syp Gamma 2 tsp TDS", "kind": "medicine", "unclear": False}]}


def upload(client, data, name="rx.jpg"):
    return client.post("/api/recognize", data={"file": (io.BytesIO(data), name)}, content_type="multipart/form-data")


def test_health(client):
    body = client.get("/api/health").get_json()
    assert body["model_configured"] is True and body["formulary"]["entries"] > 0
    assert "api_key" not in json.dumps(body).lower()


def test_no_model_means_no_medicines(settings):
    from app import create_app
    client = create_app(settings).test_client()          # nothing configured
    assert client.get("/api/health").get_json()["model_configured"] is False
    res = upload(client, make_image())
    assert res.status_code == 503 and res.get_json()["code"] == "model_not_configured"
    assert "medicines" not in res.get_json()


def test_output_comes_only_from_the_model(client, fake):
    fake.reply = LINES_A
    body = upload(client, make_image()).get_json()
    assert body["status"] == "ok"
    assert [m["name"] for m in body["medicines"]] == ["Alpha", "Be[?]a"]
    assert body["medicines"][0]["raw_text"] == "Tab Alpha 500mg 1+0+1 after meal"
    assert body["medicines"][1]["needs_attention"] is True
    assert body["other_lines"] == [{"text": "Hb 12.6", "kind": "lab", "unclear": False}]
    assert "Test Person" not in json.dumps(body)          # patient line is dropped
    assert "confidence_score" not in json.dumps(body)     # no invented confidence numbers


def test_filename_never_decides_the_result(client, fake):
    """Regression for the old app: 'capoten_slip.jpg' used to return Capoten 50mg."""
    fake.reply = LINES_B
    for name in ("capoten_slip.jpg", "cbc_enic.jpg", "WhatsApp Image 2026-11-09.jpeg"):
        body = upload(client, make_image(), name).get_json()
        assert [m["name"] for m in body["medicines"]] == ["Gamma"]
        assert "Capoten" not in json.dumps(body)


def test_consecutive_uploads_are_independent(client, fake):
    fake.reply = LINES_A
    first = upload(client, make_image(("one",))).get_json()
    fake.reply = LINES_B
    second = upload(client, make_image(("two",))).get_json()
    assert first["request_id"] != second["request_id"]
    assert [m["name"] for m in second["medicines"]] == ["Gamma"]


def test_blank_page_is_rejected_without_calling_the_model(client, fake):
    fake.reply = LINES_A
    body = upload(client, make_image(blank=True)).get_json()
    assert body["status"] == "rejected_quality" and body["medicines"] == []
    assert fake.calls == 0


def test_tiny_image_is_rejected(client, fake):
    body = upload(client, make_image(size=(120, 90))).get_json()
    assert body["status"] == "rejected_quality" and fake.calls == 0


def test_unreadable_and_empty_results(client, fake):
    fake.reply = {"readable": False, "lines": []}
    assert upload(client, make_image()).get_json()["status"] == "unreadable"
    fake.reply = {"readable": True, "lines": [{"text": "CBC", "kind": "lab", "unclear": False}]}
    body = upload(client, make_image()).get_json()
    assert body["status"] == "no_medicines" and body["medicines"] == []


def test_invalid_uploads(client):
    assert client.post("/api/recognize").status_code == 400
    assert upload(client, b"not an image", "x.jpg").status_code == 400
    assert upload(client, b"MZ...", "virus.exe").status_code == 400
    assert upload(client, b"", "empty.png").status_code == 400


def test_model_failure_is_reported_not_hidden(settings):
    from app import create_app
    from rxcore.recognizer import RecognitionError

    class Broken(FakeRecognizer):
        def transcribe(self, jpeg_bytes):
            raise RecognitionError("Model server returned HTTP 500")

    res = upload(create_app(settings, Broken()).test_client(), make_image())
    assert res.status_code == 502 and "medicines" not in res.get_json()


def _row(med, **over):
    row = {"line_no": med["line_no"], "raw_text": med["raw_text"], "form": med["form"] or "",
           "name": med["name"], "strength": med["strength"]["raw"] if med["strength"] else "",
           "frequency": med["frequency"]["raw"] if med["frequency"] else "", "duration": "", "food": "", "checked": True}
    row.update(over)
    return row


def test_approval_rules_and_audit_trail(client, fake, settings):
    fake.reply = LINES_A
    result = upload(client, make_image()).get_json()
    rows = [_row(m) for m in result["medicines"]]

    res = client.post("/api/records", json={"request_id": result["request_id"], "pharmacist": "", "medicines": rows})
    assert res.status_code == 422 and "Pharmacist name" in " ".join(res.get_json()["details"])

    unchecked = [dict(rows[0], checked=False), rows[1]]
    res = client.post("/api/records", json={"request_id": result["request_id"], "pharmacist": "A. Pharmacist", "medicines": unchecked})
    assert res.status_code == 422 and "Row 1 is not ticked" in " ".join(res.get_json()["details"])

    rows[1]["name"], rows[1]["frequency"] = "Beta", "1+0+0"            # pharmacist corrects row 2
    rows.append({"line_no": None, "raw_text": "", "form": "Tablet", "name": "Delta", "strength": "5mg",
                 "frequency": "0+0+1", "checked": True})                  # and adds a row
    res = client.post("/api/records", json={"request_id": result["request_id"], "pharmacist": "A. Pharmacist", "medicines": rows})
    assert res.status_code == 201
    record = res.get_json()
    assert record["status"] == "APPROVED_LOCKED" and record["approved_by"] == "A. Pharmacist"
    changes = {(c["field"], c["model"], c["pharmacist"]) for c in record["audit"]["changes_by_pharmacist"]}
    assert ("name", "Be[?]a", "Beta") in changes and ("frequency", "OD", "1+0+0") in changes
    assert ("row_added", "", "Delta") in changes
    assert record["medicines"][1]["urdu"]["text"] == "صبح ایک کیپسول۔"
    assert record["audit"]["model_output"][1]["name"] == "Be[?]a"         # original is preserved

    assert client.get("/api/records/" + record["record_id"]).get_json()["record_id"] == record["record_id"]
    assert (settings.records_dir / "audit.log").read_text(encoding="utf-8").count("approved") == 1
    # a locked record cannot be approved a second time
    res = client.post("/api/records", json={"request_id": result["request_id"], "pharmacist": "A. Pharmacist", "medicines": rows})
    assert res.status_code == 422


def test_record_lookup_is_safe(client):
    assert client.get("/api/records/..%2F..%2Fapp").status_code == 404
    assert client.get("/api/records/RX-20260101-000000-abcdef").status_code == 404


def test_urdu_endpoint_follows_edits(client):
    res = client.post("/api/urdu", json={"medicines": [
        {"form": "Tablet", "frequency": "1+0+1", "food": "after meal"}, {"form": "Tablet", "frequency": ""}]})
    out = res.get_json()["medicines"]
    assert out[0]["complete"] is True and out[1]["complete"] is False
