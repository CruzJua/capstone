import os
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer

class RAGRetriever:
    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        db_name: Optional[str] = None,
        collection_name: Optional[str] = None,
        model_name: Optional[str] = None,
        env_file: Optional[Path | str] = None,
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
        self.model = SentenceTransformer(resolved_model)

    def retrieve(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 4,
        num_candidates: int = 100
    ) -> List[Dict[str, Any]]:
        """Returns the top_k chunks for a query, restricted to a single tenant."""
        if not tenant_id:
            # An empty tenant would silently match nothing at best; refuse rather than risk leakage
            raise ValueError("tenant_id is required for retrieval.")

        query_embedding = self.model.encode(query).tolist()
        pipeline = [
            {
                "$vectorSearch": {
                    "index": self.index_name,
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": max(num_candidates, top_k),
                    "limit": top_k,
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
                    "score": {"$meta": "vectorSearchScore"}
                }
            }
        ]
        results = list(self.collection.aggregate(pipeline))

        # Defense stuff: drop anything that is not this tenant's, even though the index filter should guarantee it
        return [r for r in results if r.get("tenant_id") == tenant_id]

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
