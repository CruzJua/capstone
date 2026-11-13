"""Create a private configuration for an isolated standard-mode Compose stack."""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets

GGUF_FILENAME = "Llama-3.2-3B-Instruct.Q4_K_M.gguf"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def configure_stack(model_dir: Path, expected_sha256: str, output: Path) -> Path:
    """Verify the source artifact and create, never replace, a mode-0600 env file.

    Fresh hex secrets are URI-safe. Existing .env files and source model files are
    never modified, and configuration values are not returned for logging.
    """
    if output.exists():
        raise FileExistsError("Configuration already exists; keep it to preserve credentials and follow-up tokens.")
    directory = model_dir.expanduser().resolve(strict=True)
    if any(char in str(directory) for char in "\r\n"):
        raise ValueError("The model directory must not contain line breaks.")
    expected_sha256 = expected_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Provide a complete SHA256 digest.")
    source = directory / GGUF_FILENAME
    if not source.is_file():
        raise ValueError(f"The model directory must contain {GGUF_FILENAME}.")
    if file_sha256(source) != expected_sha256:
        raise ValueError("The GGUF checksum does not match; no configuration was written.")
    values = {
        "MONGO_ROOT_USER": "capstone_admin",
        "MONGO_ROOT_PASSWORD": secrets.token_hex(32),
        "MONGODB_DB_NAME": "rag_knowledge_base",
        "CHAT_BACKEND_TOKEN": secrets.token_hex(32),
        "CHAT_FOLLOW_UP_SECRET": secrets.token_hex(32),
        "MODEL_GGUF_DIR": str(directory),
        "MODEL_GGUF_SHA256": expected_sha256,
        "OLLAMA_MODEL": "llama3.2:3b-qlora-hardneg-full01-q4",
        "OLLAMA_IMAGE": "ollama/ollama:0.40.16",
        "GATEWAY_PORT": "4002",
        "DASHBOARD_PORT": "3002",
        "NEXT_PUBLIC_GATEWAY_URL": "http://localhost:4002",
        "ALLOWED_ORIGINS": "http://localhost:3002,http://127.0.0.1:3002",
        "SESSION_COOKIE_NAME": "capstone_sprint6_session",
    }
    content = "# Private local Compose configuration. Preserve this file across restarts.\n"
    content += "\n".join(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in values.items()) + "\n"
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)
    return output
