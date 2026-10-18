import os
import json
import re
from typing import List, Dict, Any, Generator, Optional
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel
from sentence_transformers import SentenceTransformer

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
        self.model = SentenceTransformer(resolved_model)
        self.num_dimensions = (
            self.model.get_embedding_dimension()
            if hasattr(self.model, "get_embedding_dimension")
            else self.model.get_sentence_embedding_dimension()
        )

    def ensure_vector_search_index(self, index_name: Optional[str] = None):
        """Ensures the MongoDB collection and Atlas Vector Search index exist with tenant filtering."""
        # 1. Automatically create collection if it does not exist yet
        if self.collection.name not in self.db.list_collection_names():
            print(f"Creating collection '{self.collection.name}' in database '{self.db.name}'...")
            self.db.create_collection(self.collection.name)

        # 2. Check if search index already exists
        resolved_index_name = index_name or os.getenv("MONGODB_VECTOR_INDEX_NAME", "vector_index")
        try:
            existing_indexes = list(self.collection.list_search_indexes())
            if any(idx.get("name") == resolved_index_name for idx in existing_indexes):
                print(f"Vector search index '{resolved_index_name}' already exists.")
                return
        except Exception:
            pass

        # 3. Create the Atlas Search Index model
        definition = {
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": self.num_dimensions,
                    "similarity": "cosine"
                },
                {
                    "type": "filter",
                    "path": "tenant_id"
                },
                {
                    "type": "filter",
                    "path": "doc_id"
                }
            ]
        }
        search_index_model = SearchIndexModel(
            definition=definition,
            name=resolved_index_name,
            type="vectorSearch"
        )
        try:
            self.collection.create_search_index(model=search_index_model)
            print(f"Vector search index '{resolved_index_name}' successfully submitted to Atlas.")
        except Exception as e:
            # Handle duplicate or in-progress index creation gracefully
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                print(f"Vector search index '{resolved_index_name}' is already being built.")
            else:
                raise

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

    def _parse_file(self, file_path: Path) -> List[Dict[str, Any]]:
        results = []
        doc_id = file_path.stem
        
        if file_path.suffix == ".md":
            content = file_path.read_text(encoding="utf-8")
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
                    text_representation = f"{key}:\n{json.dumps(val, indent=2)}"
                    results.append({
                        "doc_id": doc_id,
                        "section": key,
                        "text": text_representation
                    })
        return results

    def ingest_tenant_directory(self, tenant_id: str, tenant_dir: Path) -> int:
        """Parses, embeds, and stores all documents in a tenant folder."""
        raw_chunks = []
        
        # Traverse markdown and json files
        for file_path in tenant_dir.glob("*.*"):
            if file_path.suffix not in [".md", ".json"]:
                continue
            if "generation_reference" in str(file_path):
                continue
            raw_chunks.extend(self._parse_file(file_path))

        if not raw_chunks:
            return 0

        # Batch embed the chunk strings
        texts = [c["text"] for c in raw_chunks]
        embeddings = self.model.encode(texts, batch_size=32, show_progress_bar=False)

        documents = []
        for i, chunk in enumerate(raw_chunks):
            documents.append({
                "tenant_id": tenant_id,
                "doc_id": chunk["doc_id"],
                "section": chunk["section"],
                "chunk_index": i,
                "text": chunk["text"],
                "embedding": embeddings[i].tolist()
            })

        # Purge prior embeddings for this tenant to allow clean re-indexing
        self.collection.delete_many({"tenant_id": tenant_id})
        self.collection.insert_many(documents)
        return len(documents)