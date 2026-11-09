import os
import json
import re
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
from datetime import datetime, timezone
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer
from src.rag.table_parser import MarkdownTableParser
from src.rag.vector_index import DEFAULT_INDEX_NAME, ensure_vector_index

class RAGDocumentIngestor:
    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        db_name: Optional[str] = None,
        collection_name: Optional[str] = None,
        model_name: Optional[str] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 75,
        env_file: Optional[Path | str] = None,
        document_parser: str = "legacy",
    ):
        if document_parser not in {"legacy", "structured"}:
            raise ValueError("document_parser must be legacy or structured")
        self.document_parser = document_parser
        # Load environment variables
        if env_file:
            load_dotenv(dotenv_path=env_file, override=False)
        else:
            load_dotenv(find_dotenv(usecwd=True), override=False)

        resolved_uri = mongo_uri or os.getenv("MONGODB_URI")
        if not resolved_uri or "<username>" in resolved_uri or "<password>" in resolved_uri:
            raise ValueError(
                "MongoDB connection URI is missing or contains placeholder values. "
                "Please configure MONGODB_URI in your .env file or pass mongo_uri to RAGDocumentIngestor."
            )

        resolved_db = db_name or os.getenv("MONGODB_DB_NAME", "rag_knowledge_base")
        resolved_collection = collection_name or os.getenv("MONGODB_COLLECTION_NAME", "doc_vectors")
        resolved_model = model_name or os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5")

        self.client = MongoClient(resolved_uri)
        self.db = self.client[resolved_db]
        self.collection = self.db[resolved_collection]
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.model = SentenceTransformer(resolved_model, token=os.getenv("HF_TOKEN") or None)
        self.num_dimensions = (
            self.model.get_embedding_dimension()
            if hasattr(self.model, "get_embedding_dimension")
            else self.model.get_sentence_embedding_dimension()
        )

    def ensure_vector_search_index(self, index_name: Optional[str] = None) -> Dict[str, Any]:
        """Ensures the collection and the Atlas Vector Search index exist (idempotent, never waits for the build).

        Returns {"name", "state", "collection_created", "index_created"[, "message"]}; ``state`` is one of
        missing/building/ready/failed/misconfigured. Raises VectorIndexPermissionError with a clear message
        when the database user may not create collections or search indexes.
        """
        resolved_index_name = index_name or os.getenv("MONGODB_VECTOR_INDEX_NAME", DEFAULT_INDEX_NAME)
        return ensure_vector_index(
            self.db, self.collection.name, resolved_index_name, self.num_dimensions
        )

    def _chunk_text(self, text: str) -> List[str]:
        words = text.split()
        if not words:
            return []
        chunks = []
        i = 0
        step = max(1, self.chunk_size - self.chunk_overlap)
        while i < len(words):
            chunk = " ".join(words[i : i + self.chunk_size])
            chunks.append(chunk)
            i += step
        return chunks

    def _parse_file(self, file_path: Path, source_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if getattr(self, "document_parser", "legacy") == "structured":
            from src.documents.parser import parse_document
            from src.documents.integration import document_chunks
            return document_chunks(parse_document(file_path, source_id=source_id), self.chunk_size)
        results = []
        doc_id = file_path.stem
        
        if file_path.suffix == ".md":
            raw_content = file_path.read_text(encoding="utf-8")
            # Linearize markdown tables to augment raw tables with semantic summaries
            content = MarkdownTableParser.linearize_tables(raw_content, mode="augment")
            # Split sections by markdown headers (H1-H3)
            sections = re.split(r"(^#{1,3}\s+.*$)", content, flags=re.MULTILINE)
            current_header = "Overview"
            
            buffer = ""
            for part in sections:
                if part.strip().startswith("#"):
                    if buffer.strip():
                        for chunk in self._chunk_text(buffer):
                            results.append({
                                "doc_id": doc_id,
                                "section": current_header,
                                "text": chunk
                            })
                        buffer = ""
                    current_header = part.strip().lstrip("#").strip()
                else:
                    buffer += "\n" + part
            
            if buffer.strip():
                for chunk in self._chunk_text(buffer):
                    results.append({
                        "doc_id": doc_id,
                        "section": current_header,
                        "text": chunk
                    })

        elif file_path.suffix == ".json":
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    text_representation = json.dumps(item, indent=2)
                    results.append({
                        "doc_id": doc_id,
                        "section": "Structured Data",
                        "text": text_representation
                    })
            elif isinstance(data, dict):
                for key, val in data.items():
                    if isinstance(val, list):
                        for i, item in enumerate(val):
                            item_id = item.get("id") or item.get("name") if isinstance(item, dict) else i
                            section_name = f"{key} - {item_id}"
                            results.append({
                                "doc_id": doc_id,
                                "section": section_name,
                                "text": json.dumps(item, indent=4) if isinstance(item, (dict, list)) else str(item)
                            })
                    else:
                        text_representation = f"{key}:\n{json.dumps(val, indent=4)}"
                        results.append({
                        "doc_id": doc_id,
                        "section": key,
                        "text": text_representation
                        })
        return results

    def collect_tenant_chunks(self, tenant_dir: Path) -> List[Dict[str, Any]]:
        """Parses every eligible document in a tenant folder into chunks, without embedding or storing."""
        raw_chunks = []

        # Traverse markdown and json files
        structured = getattr(self, "document_parser", "legacy") == "structured"
        if structured:
            from src.documents.integration import discover_document_paths
            tenant_dir = Path(tenant_dir).resolve()
            candidates = discover_document_paths(tenant_dir)
        else:
            candidates = tenant_dir.glob("*.*")
        for file_path in candidates:
            if not file_path.is_file() or file_path.suffix.lower() not in ([".md", ".json", ".txt"] if structured else [".md", ".json"]):
                continue
            if not structured and "generation_reference" in str(file_path):
                continue
            raw_chunks.extend(self._parse_file(file_path, file_path.relative_to(tenant_dir).as_posix())
                              if structured else self._parse_file(file_path))
        return raw_chunks

    def ingest_tenant_directory(self, tenant_id: str, tenant_dir: Path) -> int:
        """Parses, embeds, and stores all documents in a tenant folder."""
        structured = getattr(self, "document_parser", "legacy") == "structured"
        raw_chunks = self.collect_tenant_chunks(tenant_dir)

        if not raw_chunks:
            return 0

        # Batch embed the chunk strings
        texts = [c["text"] for c in raw_chunks]
        if structured:
            tokenizer = getattr(self.model, "tokenizer", None)
            limit = getattr(self.model, "max_seq_length", None)
            if tokenizer is None or type(limit) is not int or limit < 1:
                raise ValueError("Structured ingestion requires a tokenizer and a known embedding token limit")
            for index, text in enumerate(texts):
                token_ids = tokenizer(text, truncation=False, add_special_tokens=True)["input_ids"]
                if len(token_ids) > limit:
                    raise ValueError(f"Atomic block {index} exceeds the embedding token limit; no text was truncated or indexed")
        embeddings = self.model.encode(texts, batch_size=32, show_progress_bar=False)

        now_iso = datetime.now(timezone.utc).isoformat()
        documents = []
        for i, chunk in enumerate(raw_chunks):
            document = {
                "tenant_id": tenant_id,
                "doc_id": chunk["doc_id"],
                "section": chunk["section"],
                "chunk_index": i,
                "text": chunk["text"],
                "embedding": embeddings[i].tolist(),
                "created_at": now_iso
            }
            if structured:
                for key in ("source_id", "source_sha256", "source_locator", "source_context", "source_block_index", "parser_version"):
                    document[key] = chunk[key]
            documents.append(document)

        # Purge prior embeddings for this tenant to allow clean re-indexing
        self.collection.delete_many({"tenant_id": tenant_id})
        self.collection.insert_many(documents)
        return len(documents)
