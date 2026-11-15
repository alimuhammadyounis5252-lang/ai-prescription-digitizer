"""Regression tests for the bugs fixed in 2.1.1. Each test failed before its fix."""
import io
import json
import os
import threading

import pytest
from PIL import Image

from conftest import FakeRecognizer, make_image
from rxcore.config import load_dotenv
from rxcore.formulary import Formulary
from rxcore.parser import parse_medicine_line
from rxcore.quality import InvalidImage, assess_quality, load_image
from rxcore.recognizer import RecognitionError
from rxcore.storage import correction_stats, list_records


def _png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_dotenv_reads_bom_and_ignores_inline_comment(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"\xef\xbb\xbfRX_T_FIRST=abc\nRX_T_PORT=5000   # default port\nRX_T_QUOTED=\"a # b\"\nRX_T_EMPTY=   # nothing\n")
    for key in ("RX_T_FIRST", "RX_T_PORT", "RX_T_QUOTED", "RX_T_EMPTY"):
        os.environ.pop(key, None)
    try:
        load_dotenv(path)
        assert os.environ["RX_T_FIRST"] == "abc"          # first line was lost before (BOM)
        assert os.environ["RX_T_PORT"] == "5000"          # was "5000   # default port"
        assert os.environ["RX_T_QUOTED"] == "a # b"
        assert os.environ["RX_T_EMPTY"] == ""
    finally:
        for key in ("RX_T_FIRST", "RX_T_PORT", "RX_T_QUOTED", "RX_T_EMPTY"):
            os.environ.pop(key, None)


def test_formulary_loads_csv_saved_with_bom(tmp_path):
    path = tmp_path / "f.csv"
    path.write_bytes(b"\xef\xbb\xbf# formulary test\nbrand,generic,strengths,form,source,verified\n"
                     b"Panadol,Paracetamol,500mg,Tablet,test,no\n")
    formulary = Formulary.from_csv(path)
    assert len(formulary) == 1 and formulary.version == "formulary test"


def test_decompression_bomb_is_a_clean_rejection():
    data = _png(Image.new("RGB", (200, 200), "white"))
    old = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = 1000
    try:
        with pytest.raises(InvalidImage):
            load_image(data)
    finally:
        Image.MAX_IMAGE_PIXELS = old


def test_quality_metrics_stay_valid_json_for_a_one_pixel_strip():
    quality = assess_quality(load_image(_png(Image.new("RGB", (2000, 1), "white"))))
    json.dumps(quality, allow_nan=False)                  # raised on NaN before
    assert not quality["ok"]


def test_transparent_png_is_placed_on_white_not_black():
    img = Image.new("RGBA", (600, 400), (0, 0, 0, 0))
    for x in range(40, 300):
        for y in range(100, 106):
            img.putpixel((x, y), (0, 0, 0, 255))          # opaque black "handwriting"
    loaded = load_image(_png(img))
    assert loaded.getpixel((5, 5)) == (255, 255, 255)
    assert loaded.getpixel((100, 102)) == (0, 0, 0)


def test_syrup_concentration_stays_in_the_strength():
    med = parse_medicine_line("Syp Calpol 120mg/5ml 1+1+1 x 5 days")
    assert med["strength"]["raw"] == "120mg/5ml"
    assert med["strength"]["unit"] == "mg/5ml"
    assert med["name"] == "Calpol"
    plain = parse_medicine_line("Tab Panadol 500mg 1+0+1")
    assert plain["strength"]["raw"] == "500mg" and plain["strength"]["unit"] == "mg"


def _approved_body(client, fake):
    fake.reply = {"readable": True, "lines": [{"text": "Tab Panadol 500mg 1+0+1", "kind": "medicine", "unclear": False}]}
    res = client.post("/api/recognize", data={"file": (io.BytesIO(make_image()), "a.jpg")},
                      content_type="multipart/form-data").get_json()
    return {"request_id": res["request_id"], "pharmacist": "Test Pharmacist",
            "medicines": [{"line_no": 1, "raw_text": "x", "name": "Panadol", "form": "Tablet", "strength": "500mg",
                           "frequency": "1+0+1", "duration": "", "food": "", "checked": True}]}


def test_simultaneous_approvals_save_exactly_one_record(settings):
    from app import create_app
    fake = FakeRecognizer()
    app = create_app(settings, fake)
    body = _approved_body(app.test_client(), fake)
    codes = []

    def go():
        codes.append(app.test_client().post("/api/records", json=body).status_code)

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes.count(201) == 1                          # two 201s before the fix
    assert len(list(settings.records_dir.glob("RX-*.json"))) == 1
    log_lines = (settings.records_dir / "audit.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 1


def test_a_damaged_record_does_not_break_list_or_stats(client, fake, settings):
    body = _approved_body(client, fake)
    assert client.post("/api/records", json=body).status_code == 201
    (settings.records_dir / "RX-20260101-000000-abcdef.json").write_text('{"record_id": "x"}', encoding="utf-8")
    (settings.records_dir / "RX-20260102-000000-abcdef.json").write_text("not json", encoding="utf-8")
    assert len(list_records(settings.records_dir)) == 1
    assert correction_stats(settings.records_dir)["records"] == 1
    assert client.get("/api/records").status_code == 200
    assert client.get("/api/stats").status_code == 200


def test_evaluation_continues_after_a_model_error():
    import evaluate

    def predict(path):
        if path == "bad.jpg":
            raise RecognitionError("Model server returned HTTP 429")
        return [{"text": "Tab A 5mg", "name": "A", "strength": "5mg", "frequency": ""}], "ok"

    truth = [{"text": "Tab A 5mg", "name": "A", "strength": "5mg", "frequency": ""}]
    summary, per_item = evaluate.evaluate_items(
        [{"image": "bad.jpg", "medicines": truth}, {"image": "good.jpg", "medicines": truth}], predict)
    assert len(per_item) == 2                             # whole run crashed before
    assert summary["counts"]["tp"] == 1 and summary["counts"]["fn"] == 1
    assert any(status.startswith("error") for status in summary["statuses"])
