import os
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class RAGRetriever:
    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        db_name: Optional[str] = None,
        collection_name: Optional[str] = None,
        model_name: Optional[str] = None,
        env_file: Optional[Path | str] = None,
        reranker_model_name: Optional[str] = None,
        rerank_candidates: int = 20,
        min_rerank_score: Optional[float] = None,
        query_prefix: Optional[str] = None,
    ):
        # Load environment variables
        if env_file:
            load_dotenv(dotenv_path=env_file, override=False)
        else:
            load_dotenv(find_dotenv(usecwd=True), override=False)

        resolved_uri = mongo_uri or os.getenv("MONGODB_URI")
        if not resolved_uri or "<username>" in resolved_uri or "<password>" in resolved_uri:
            raise ValueError(
                "MongoDB connection URI is missing or contains placeholder values. "
                "Please configure MONGODB_URI in your .env file or pass mongo_uri to RAGRetriever."
            )

        resolved_db = db_name or os.getenv("MONGODB_DB_NAME", "rag_knowledge_base")
        resolved_collection = collection_name or os.getenv("MONGODB_COLLECTION_NAME", "doc_vectors")
        resolved_model = model_name or os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5")

        self.client = MongoClient(resolved_uri)
        self.db = self.client[resolved_db]
        self.collection = self.db[resolved_collection]
        self.index_name = os.getenv("MONGODB_VECTOR_INDEX_NAME", "vector_index")
        self.model = SentenceTransformer(resolved_model, token=os.getenv("HF_TOKEN") or None)

        # BGE retrieval models expect this instruction on queries only (documents stay unprefixed).
        if query_prefix is None:
            query_prefix = BGE_QUERY_PREFIX if "bge-" in resolved_model.lower() else ""
        self.query_prefix = query_prefix

        # The reranker is optional: it is loaded lazily and only when a model name is configured.
        self.reranker_model_name = reranker_model_name or os.getenv("RERANKER_MODEL_NAME") or None
        self.rerank_candidates = rerank_candidates
        if min_rerank_score is None and os.getenv("MIN_RERANK_SCORE"):
            min_rerank_score = float(os.environ["MIN_RERANK_SCORE"])
        self.min_rerank_score = min_rerank_score
        self._reranker = None

    def _rerank(self, query: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Reorders candidates by cross-encoder relevance and drops those under the cutoff."""
        if not self.reranker_model_name or not chunks:
            return chunks
        if self._reranker is None:
            from sentence_transformers import CrossEncoder
            self._reranker = CrossEncoder(self.reranker_model_name)
        scores = self._reranker.predict([(query, c.get("text", "")) for c in chunks])
        ranked = []
        for chunk, score in zip(chunks, scores):
            ranked.append({**chunk, "vector_score": chunk.get("score"), "rerank_score": float(score)})
        ranked.sort(key=lambda c: c["rerank_score"], reverse=True)
        if self.min_rerank_score is not None:
            ranked = [c for c in ranked if c["rerank_score"] >= self.min_rerank_score]
        return ranked

    def retrieve(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 4,
        max_per_doc: Optional[int] = 2,
        num_candidates: int = 100,
    ) -> List[Dict[str, Any]]:
        """Returns the top_k chunks for a query, restricted to a single tenant with document diversity."""
        if not tenant_id:
            # An empty tenant would silently match nothing at best; refuse rather than risk leakage
            raise ValueError("tenant_id is required for retrieval.")

        query_embedding = self.model.encode(self.query_prefix + query).tolist()
        fetch_limit = max(top_k * 4, 20) if max_per_doc else top_k
        if self.reranker_model_name:
            fetch_limit = max(fetch_limit, self.rerank_candidates)
        pipeline = [
            {
                "$vectorSearch": {
                    "index": self.index_name,
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": max(num_candidates, fetch_limit),
                    "limit": fetch_limit,
                    "filter": {
                        "tenant_id": {"$eq": tenant_id}
                    }
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "tenant_id": 1,
                    "text": 1,
                    "doc_id": 1,
                    "section": 1,
                    "chunk_index": 1,
                    "source_id": 1,
                    "source_sha256": 1,
                    "source_locator": 1,
                    "source_context": 1,
                    "source_block_index": 1,
                    "parser_version": 1,
                    "score": {"$meta": "vectorSearchScore"}
                }
            }
        ]
        raw_results = list(self.collection.aggregate(pipeline))

        # Defense in depth: drop anything that is not this tenant's
        filtered_results = self._rerank(query, [r for r in raw_results if r.get("tenant_id") == tenant_id])

        if not max_per_doc:
            return filtered_results[:top_k]

        # Enforce document diversity: at most max_per_doc chunks per doc_id
        doc_counts: Dict[str, int] = {}
        diverse_results: List[Dict[str, Any]] = []
        overflow_results: List[Dict[str, Any]] = []

        for r in filtered_results:
            d_id = r.get("doc_id", "")
            if doc_counts.get(d_id, 0) < max_per_doc:
                doc_counts[d_id] = doc_counts.get(d_id, 0) + 1
                diverse_results.append(r)
                if len(diverse_results) == top_k:
                    break
            else:
                overflow_results.append(r)

        # Backfill from overflow if diversity leaves us under top_k
        if len(diverse_results) < top_k:
            for r in overflow_results:
                diverse_results.append(r)
                if len(diverse_results) == top_k:
                    break

        return diverse_results

    @staticmethod
    def format_context(chunks: List[Dict[str, Any]]) -> str:
        """Formats retrieved chunks into source-tagged blocks for prompt injection."""
        blocks = []
        for chunk in chunks:
            doc_id = chunk.get("doc_id", "unknown")
            section = chunk.get("section", "")
            header = f"[Source: {doc_id} - {section}]" if section else f"[Source: {doc_id}]"
            blocks.append(
                f'<context source="{doc_id}">\n{header}\n{chunk.get("text", "").strip()}\n</context>'
            )
        return "\n\n".join(blocks)
