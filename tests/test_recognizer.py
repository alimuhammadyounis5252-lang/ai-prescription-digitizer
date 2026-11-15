import json

import pytest

from rxcore.recognizer import (ModelNotConfigured, RecognitionError, VLMRecognizer,
                               normalise_transcription)

JPEG = b"\xff\xd8fake"


def test_not_configured_raises_and_never_fabricates():
    with pytest.raises(ModelNotConfigured):
        VLMRecognizer("", "").transcribe(JPEG)


def test_request_format_and_parsing(model_server):
    model_server["content"] = json.dumps({"readable": True, "lines": [
        {"text": "Tab Alpha 500mg 1+0+1", "kind": "medicine", "unclear": False},
        {"text": "Hb 12.6", "kind": "lab", "unclear": False}]})
    out = VLMRecognizer(model_server["url"], "some/model", "secret").transcribe(JPEG)
    assert [line["kind"] for line in out["lines"]] == ["medicine", "lab"]
    req = model_server["requests"][0]
    assert req["path"] == "/v1/chat/completions" and req["auth"] == "Bearer secret"
    assert req["body"]["model"] == "some/model" and req["body"]["temperature"] == 0
    image_part = req["body"]["messages"][1]["content"][1]
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_fenced_json_is_accepted(model_server):
    model_server["content"] = 'Here you go:\n```json\n{"readable": true, "lines": [{"text": "Cap Beta", "kind": "medicine"}]}\n```'
    out = VLMRecognizer(model_server["url"], "m").transcribe(JPEG)
    assert out["lines"][0]["text"] == "Cap Beta"


@pytest.mark.parametrize("content", ["I cannot read this.", "{not json}", "[]"])
def test_bad_replies_raise(model_server, content):
    model_server["content"] = content
    with pytest.raises(RecognitionError):
        VLMRecognizer(model_server["url"], "m").transcribe(JPEG)


def test_http_error_raises(model_server):
    model_server["status"] = 500
    with pytest.raises(RecognitionError):
        VLMRecognizer(model_server["url"], "m").transcribe(JPEG)


def test_unreachable_server_raises():
    with pytest.raises(RecognitionError):
        VLMRecognizer("http://127.0.0.1:9", "m", timeout_s=2).transcribe(JPEG)


def test_normalise_transcription():
    out = normalise_transcription({"readable": True, "lines": [
        {"text": " Tab A[?]x ", "kind": "MEDICINE"}, {"text": "", "kind": "medicine"},
        {"text": "x", "kind": "weird"}, "junk"]})
    assert out["lines"] == [{"text": "Tab A[?]x", "kind": "medicine", "unclear": True},
                            {"text": "x", "kind": "note", "unclear": False}]
    assert normalise_transcription({"readable": False, "lines": [{"text": "a", "kind": "note"}]}) == {"readable": False, "lines": []}
    assert normalise_transcription({"lines": []})["readable"] is False
