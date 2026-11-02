"""CLI runner for single-document RAG ingestion into MongoDB Atlas doc_vectors."""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.documents.parser import (
    DocumentParseError,
    UnsupportedDocumentError,
    parse_document,
)
from src.rag.ingestor import RAGDocumentIngestor as DocumentIngestor


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: '{value}'")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse, embed (BAAI/bge-small-en-v1.5), and ingest a single document into MongoDB Atlas doc_vectors."
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Path to the uploaded .md or .json file.",
    )
    parser.add_argument(
        "--tenant",
        required=True,
        help="Target tenant_id namespace.",
    )
    parser.add_argument(
        "--overwrite",
        nargs="?",
        const=True,
        default=True,
        type=parse_bool,
        help="Overwrite existing chunks for this doc_id if present (true/false).",
    )
    parser.add_argument(
        "--doc-id",
        default=None,
        help="Optional explicit doc_id override (defaults to filename stem).",
    )
    parser.add_argument(
        "--db-name",
        default=None,
        help="Explicit MongoDB database name selected by the Orchestration Gateway.",
    )
    return parser


def ingest_single_document(
    file_path: Path,
    tenant_id: str,
    overwrite: bool = True,
    doc_id_override: str | None = None,
    db_name_override: str | None = None,
) -> dict:
    caller_db_name = (db_name_override or os.environ.get("MONGODB_DB_NAME") or "").strip()
    load_dotenv(PROJECT_ROOT / ".env", override=True)

    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    file_path = Path(file_path).resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix not in {".md", ".json"}:
        raise UnsupportedDocumentError(
            f"Unsupported file extension '{suffix}'. Only .md and .json files are supported."
        )

    tenant_id = tenant_id.strip()
    if not tenant_id:
        raise ValueError("tenant_id must be a non-empty string.")

    doc_id = (doc_id_override or file_path.stem).strip()
    if not doc_id:
        raise ValueError("doc_id must be a non-empty string.")

    # Validate file integrity using the shared document parser
    parse_document(file_path, source_id=doc_id)

    db_name = caller_db_name or os.getenv("MONGODB_DB_NAME", "rag_knowledge_base")
    collection_name = os.getenv("MONGODB_COLLECTION_NAME", "doc_vectors")

    with contextlib.redirect_stdout(sys.stderr):
        ingestor = DocumentIngestor(
            db_name=db_name,
            collection_name=collection_name,
            env_file=PROJECT_ROOT / ".env",
        )

        existing_count = ingestor.collection.count_documents(
            {"tenant_id": tenant_id, "doc_id": doc_id},
            limit=1,
        )
        if existing_count > 0 and not overwrite:
            raise FileExistsError(
                f"Document '{doc_id}' already exists for tenant '{tenant_id}'. Enable overwrite to replace it."
            )

        raw_chunks = ingestor._parse_file(file_path)
        for chunk in raw_chunks:
            chunk["doc_id"] = doc_id

        if not raw_chunks:
            raise DocumentParseError(
                f"Document '{doc_id}' produced 0 chunks. Ensure the file is not empty."
            )

        texts = [c["text"] for c in raw_chunks]
        embeddings = ingestor.model.encode(
            texts,
            batch_size=32,
            show_progress_bar=False,
        )

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        doc_format = suffix.lstrip(".")
        documents = []
        for idx, chunk in enumerate(raw_chunks):
            documents.append(
                {
                    "tenant_id": tenant_id,
                    "doc_id": doc_id,
                    "format": doc_format,
                    "section": chunk.get("section") or "Overview",
                    "chunk_index": idx,
                    "text": chunk["text"],
                    "embedding": embeddings[idx].tolist(),
                    "created_at": now_iso,
                }
            )

        if existing_count > 0:
            ingestor.collection.delete_many(
                {"tenant_id": tenant_id, "doc_id": doc_id}
            )

        ingestor.collection.insert_many(documents)
        ingestor.client.close()

    return {
        "status": "success",
        "tenant_id": tenant_id,
        "doc_id": doc_id,
        "format": doc_format,
        "chunks_created": len(documents),
    }


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        result = ingest_single_document(
            file_path=Path(args.file),
            tenant_id=args.tenant,
            overwrite=args.overwrite,
            doc_id_override=args.doc_id,
            db_name_override=args.db_name,
        )
        print(json.dumps(result))
    except FileExistsError as exc:
        error_payload = {
            "status": "error",
            "code": "DOCUMENT_EXISTS",
            "error": str(exc),
        }
        print(json.dumps(error_payload))
        sys.exit(2)
    except (DocumentParseError, UnsupportedDocumentError, ValueError, FileNotFoundError) as exc:
        error_payload = {
            "status": "error",
            "code": "VALIDATION_ERROR",
            "error": str(exc),
        }
        print(json.dumps(error_payload))
        sys.exit(1)
    except Exception as exc:
        error_payload = {
            "status": "error",
            "code": "INGESTION_ERROR",
            "error": str(exc),
        }
        print(json.dumps(error_payload))
        sys.exit(1)


if __name__ == "__main__":
    main()

