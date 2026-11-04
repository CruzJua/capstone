"""Offline stand-in for MongoDB Atlas so retrieval can be tuned without a network connection.

The in-memory collection answers the same ``$vectorSearch`` pipeline that
``RAGRetriever.retrieve`` sends to Atlas (cosine similarity, tenant pre-filter, limit),
so reranking, prefix and cutoff changes can be evaluated against real chunks.
It is an evaluation aid, not a production store.
"""

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

from src.rag.ingestor import RAGDocumentIngestor
from src.rag.retriever import RAGRetriever


class InMemoryVectorCollection:
    """Minimal ``aggregate`` implementation for a single ``$vectorSearch`` + ``$project`` pipeline."""

    def __init__(self, documents: List[Dict[str, Any]]):
        self.documents = documents
        self._matrix = (
            np.asarray([d["embedding"] for d in documents], dtype=np.float32) if documents else np.zeros((0, 0))
        )
        norms = np.linalg.norm(self._matrix, axis=1, keepdims=True) if documents else None
        if norms is not None:
            norms[norms == 0] = 1.0
            self._matrix = self._matrix / norms

    def aggregate(self, pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        stage = pipeline[0].get("$vectorSearch")
        if stage is None:
            raise ValueError("InMemoryVectorCollection only supports a leading $vectorSearch stage")
        if not self.documents:
            return []
        query = np.asarray(stage["queryVector"], dtype=np.float32)
        norm = np.linalg.norm(query)
        query = query / norm if norm else query
        required = stage.get("filter", {}).get("tenant_id", {}).get("$eq")
        scores = self._matrix @ query
        order = np.argsort(-scores)
        results: List[Dict[str, Any]] = []
        for index in order:
            document = self.documents[int(index)]
            if required is not None and document.get("tenant_id") != required:
                continue
            row = {key: value for key, value in document.items() if key not in {"embedding", "_id"}}
            # Atlas reports cosine similarity rescaled to 0-1.
            row["score"] = float((scores[index] + 1.0) / 2.0)
            results.append(row)
            if len(results) == stage["limit"]:
                break
        return results


def build_offline_collection(
    tenants_root: Path,
    tenants: Iterable[str],
    embedding_model: Any,
    chunk_size: int = 500,
    chunk_overlap: int = 75,
    document_parser: str = "legacy",
) -> InMemoryVectorCollection:
    """Chunks and embeds each tenant folder with the production ingestion code, in memory only."""
    # collect_tenant_chunks never touches MongoDB, so skip the connecting constructor.
    chunker = RAGDocumentIngestor.__new__(RAGDocumentIngestor)
    chunker.document_parser = document_parser
    chunker.chunk_size = chunk_size
    chunker.chunk_overlap = chunk_overlap

    documents: List[Dict[str, Any]] = []
    for tenant_id in tenants:
        chunks = chunker.collect_tenant_chunks(Path(tenants_root) / tenant_id)
        if not chunks:
            continue
        embeddings = embedding_model.encode([c["text"] for c in chunks], batch_size=32, show_progress_bar=False)
        for index, chunk in enumerate(chunks):
            documents.append({
                "tenant_id": tenant_id,
                "doc_id": chunk["doc_id"],
                "section": chunk["section"],
                "chunk_index": index,
                "text": chunk["text"],
                "embedding": embeddings[index].tolist(),
            })
    return InMemoryVectorCollection(documents)


def build_offline_retriever(
    tenants_root: Path,
    tenants: Iterable[str],
    model_name: Optional[str] = None,
    **retriever_options: Any,
) -> RAGRetriever:
    """A RAGRetriever backed by the in-memory index. Embeddings are computed once and shared."""
    retriever = RAGRetriever(collection=InMemoryVectorCollection([]), model_name=model_name, **retriever_options)
    retriever.collection = build_offline_collection(tenants_root, tenants, retriever.model)
    return retriever
