import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

SEGMENT = re.compile(r'<s id="(\d+)">(.*?)</s>', re.DOTALL)

PAGE_TEXT = "# Pump manual\n\nThe pump starts after the valve is open. Check the pressure every week."


class FakeServer:
    """Answers like a vision model for doc-extract and like a text model for office-translate."""

    def __init__(self):
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                outer.requests.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                if isinstance(body["messages"][0]["content"], list):
                    text = PAGE_TEXT
                else:
                    # Echo each segment in upper case, in the format office-translate expects.
                    user = body["messages"][1]["content"]
                    text = "\n".join(f'<s id="{i}">{s.upper()}</s>' for i, s in SEGMENT.findall(user))
                payload = {
                    "id": "x",
                    "object": "chat.completion",
                    "created": 0,
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": text},
                        }
                    ],
                }
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def models(self):
        return [r["body"]["model"] for r in self.requests]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.stop()


@pytest.fixture
def settings(server):
    from doc_tools_demo.core import Settings

    return Settings(server.base_url, "text-model", "vision-model")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    prefixes = ("DOC_EXTRACT_", "OFFICE_TRANSLATE_", "DOC_CHUNKER_", "DOC_TOOLS_DEMO_")
    for name in list(os.environ):
        if name.startswith(prefixes) or name == "OPENAI_API_KEY":
            monkeypatch.delenv(name)


@pytest.fixture
def make_image(tmp_path):
    from PIL import Image

    def _make(name="scan.png"):
        path = tmp_path / name
        Image.new("RGB", (200, 100), (255, 255, 255)).save(path)
        return path

    return _make


@pytest.fixture
def make_pdf(tmp_path):
    import pypdfium2 as pdfium

    def _make(name="scan.pdf", pages=2):
        pdf = pdfium.PdfDocument.new()
        for i in range(pages):
            pdf.new_page(200 + i * 10, 100)
        path = tmp_path / name
        pdf.save(str(path))
        pdf.close()
        return path

    return _make
