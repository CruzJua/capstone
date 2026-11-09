"""Run the internal chat service used by the Orchestration Gateway's POST /api/chat.

    uv run python scripts/run_chat_service.py --port 8100

Reads MONGODB_URI, MONGODB_DB_NAME, OLLAMA_HOST, OLLAMA_MODEL and EMBEDDING_MODEL_NAME from the
environment or .env. Set CHAT_BACKEND_TOKEN to require a shared secret from the gateway.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.chat.server import serve  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: loopback only).")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
