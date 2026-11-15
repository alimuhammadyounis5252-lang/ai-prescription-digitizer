import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rxcore.config import Settings  # noqa: E402


def make_image(text_lines=("Tab Alpha 500mg 1+0+1",), size=(900, 600), blank=False):
    """A synthetic 'prescription' image. No patient data is used in tests."""
    img = Image.new("RGB", size, "white")
    if not blank:
        draw = ImageDraw.Draw(img)
        for i, line in enumerate(text_lines):
            draw.text((40, 40 + i * 60), line, fill="black")
            draw.line((40, 80 + i * 60, 700, 85 + i * 60), fill="black", width=3)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class FakeRecognizer:
    """Stands in for the model in tests. It returns whatever the test sets and
    counts calls, so tests can prove the model was (or was not) consulted."""
    base_url, model = "http://test", "fake-model"

    def __init__(self):
        self.calls = 0
        self.reply = {"readable": True, "lines": []}

    def describe(self):
        return {"backend": "fake", "model": self.model, "endpoint_host": "test", "prompt_version": "t"}

    def transcribe(self, jpeg_bytes):
        self.calls += 1
        return self.reply


@pytest.fixture
def settings(tmp_path):
    root = Path(__file__).resolve().parent.parent
    return Settings(records_dir=tmp_path / "records", uploads_dir=tmp_path / "uploads",
                    formulary_path=root / "data" / "formulary.csv")


@pytest.fixture
def fake():
    return FakeRecognizer()


@pytest.fixture
def client(settings, fake):
    from app import create_app
    return create_app(settings, fake).test_client()


@pytest.fixture
def model_server():
    """A local HTTP server that imitates an OpenAI-compatible endpoint."""
    state = {"status": 200, "content": "{}", "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            payload = json.dumps({"choices": [{"message": {"content": state["content"]}}]}).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = "http://127.0.0.1:%d/v1" % server.server_port
    yield state
    server.shutdown()
