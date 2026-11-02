"""Loopback HTTP server for a local-only RAG demonstration."""

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from src.demo.service import ChatRequest, DemoService

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def make_handler(service):
    class DemoHandler(BaseHTTPRequestHandler):
        def _headers(self, status, content_type, length=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            if length is not None:
                self.send_header("Content-Length", str(length))
            self.end_headers()

        def _json(self, status, payload):
            body = json.dumps(payload, indent=4, allow_nan=False).encode()
            self._headers(status, "application/json; charset=utf-8", len(body))
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/api/config":
                self._json(200, service.config(refresh=parsed.query == "refresh=1"))
            elif parsed.path in STATIC_ROUTES:
                filename, content_type = STATIC_ROUTES[parsed.path]
                body = (STATIC_DIR / filename).read_bytes()
                self._headers(200, content_type, len(body))
                self.wfile.write(body)
            else:
                self._json(404, {"error": "Not found."})

        def do_POST(self):
            if urlsplit(self.path).path != "/api/chat":
                self._json(404, {"error": "Not found."})
                return
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host')}":
                self._json(403, {"error": "Only same-origin requests are accepted."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 120_000:
                    self._json(413, {"error": "Request is empty or too large."})
                    return
                request = ChatRequest.model_validate_json(self.rfile.read(length))
            except (ValueError, ValidationError):
                self._json(400, {"error": "Invalid request. Provide a business, a question, 1–8 chunks, and at most 12 history messages."})
                return
            self._headers(200, "application/x-ndjson; charset=utf-8")
            try:
                for event in service.chat(request):
                    self.wfile.write((json.dumps(event, allow_nan=False) + "\n").encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format, *args):
            logging.getLogger(__name__).info(format, *args)

    return DemoHandler


def serve(host="127.0.0.1", port=8000):
    service = DemoService()
    server = ThreadingHTTPServer((host, port), make_handler(service))
    server.daemon_threads = True
    print(f"RAG chat demo: http://{host}:{port}", flush=True)
    print("Using .env for Ollama and MongoDB. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()
