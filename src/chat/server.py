"""Internal chat service: the Node gateway's bridge to retrieval and local inference.

Not exposed to the public internet. The gateway (``gateway/src/routes/chat.js``) authenticates
visitors, validates origins, rate limits, and loads the tenant's ``agent_config``; this service
only retrieves tenant-scoped context and streams the model's answer.

    POST /v1/chat   body: ChatServiceRequest JSON      -> application/x-ndjson event stream
    GET  /health                                       -> {"status": "ok"}

Binds to loopback by default. Set ``CHAT_BACKEND_TOKEN`` to require the same value in the
``X-Chat-Backend-Token`` header (use it whenever the service is reachable from another host).
"""

import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import ValidationError

from src.chat.orchestrator import ChatOrchestrator, ChatServiceRequest

MAX_BODY_BYTES = 128_000
TOKEN_HEADER = "X-Chat-Backend-Token"
logger = logging.getLogger(__name__)


def make_handler(orchestrator, token: str = ""):
    class ChatServiceHandler(BaseHTTPRequestHandler):
        def _send(self, status, content_type, body=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            if body is not None:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body is not None:
                self.wfile.write(body)

        def _json(self, status, payload):
            self._send(status, "application/json; charset=utf-8", json.dumps(payload, indent=4, allow_nan=False).encode())

        def _authorized(self):
            if not token:
                return True
            return hmac.compare_digest(self.headers.get(TOKEN_HEADER, ""), token)

        def do_GET(self):
            if urlsplit(self.path).path == "/health":
                self._json(200, {"status": "ok"})
            else:
                self._json(404, {"error": "Not found."})

        def do_POST(self):
            if urlsplit(self.path).path != "/v1/chat":
                self._json(404, {"error": "Not found."})
                return
            if not self._authorized():
                self._json(401, {"error": "Unauthorized."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY_BYTES:
                    self._json(413, {"error": "Request is empty or too large."})
                    return
                request = ChatServiceRequest.model_validate_json(self.rfile.read(length))
            except (ValueError, ValidationError):
                self._json(400, {"error": "Invalid request."})
                return

            self._send(200, "application/x-ndjson; charset=utf-8")
            events = orchestrator.stream(request)
            try:
                for event in events:
                    self.wfile.write((json.dumps(event, allow_nan=False) + "\n").encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                # The gateway aborted (visitor closed the chat): stop generating.
                pass
            finally:
                close = getattr(events, "close", None)
                if callable(close):
                    close()

        def log_message(self, format, *args):
            # Request lines never contain visitor text, but keep access logs at debug level.
            logger.debug(format, *args)

    return ChatServiceHandler


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def load_env(env_file=ENV_FILE):
    """Loads the repository .env without overriding variables already set in the environment."""
    return load_dotenv(env_file, override=False)


def build_orchestrator():
    """Builds the real retriever and Ollama client from the environment (.env or process env)."""
    from src.inference.client import SupportInferenceClient
    from src.rag.retriever import RAGRetriever

    return ChatOrchestrator(RAGRetriever(env_file=ENV_FILE), SupportInferenceClient(env_file=ENV_FILE))


def serve(host="127.0.0.1", port=8100, orchestrator=None):
    load_env()  # before anything reads CHAT_BACKEND_TOKEN, MONGODB_*, OLLAMA_*, EMBEDDING_MODEL_NAME
    orchestrator = orchestrator or build_orchestrator()
    server = ThreadingHTTPServer((host, port), make_handler(orchestrator, os.getenv("CHAT_BACKEND_TOKEN", "")))
    server.daemon_threads = True
    print(f"Chat service listening on http://{host}:{port} (POST /v1/chat)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
