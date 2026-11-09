"""Reuse Atlas retrieval and Ollama inference for the local chat demo."""

import logging
import os
import threading
import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from src.inference.client import SupportInferenceClient
from src.inference.schema import SupportResponse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    tenant: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=4, ge=1, le=8, strict=True)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)

    @field_validator("tenant", "query")
    @classmethod
    def reject_blank(cls, value):
        if not value.strip():
            raise ValueError("Must not be blank.")
        return value.strip()


class DemoService:
    def __init__(self, client=None, retriever=None, collection=None):
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        self.client = client or SupportInferenceClient()
        self.retriever = retriever
        self.collection = collection
        self._mongo_client = None
        self._model_lock = threading.Lock()
        self._retriever_lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._tenant_ids = set()
        self._config = None

    def _collection(self):
        if self.collection is None:
            from pymongo import MongoClient

            uri = os.getenv("MONGODB_URI", "")
            if not uri or "<username>" in uri or "<password>" in uri:
                raise ValueError("MongoDB URI is not configured.")
            self._mongo_client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
            self.collection = self._mongo_client[
                os.getenv("MONGODB_TRAINING_DB_NAME", "rag_knowledge_base")
            ][os.getenv("MONGODB_COLLECTION_NAME", "doc_vectors")]
        return self.collection

    def config(self, refresh=False):
        with self._config_lock:
            if self._config is not None and not refresh:
                return self._config
            warnings = []
            try:
                tenant_ids = self._collection().distinct("tenant_id")
                tenant_ids = sorted(value for value in tenant_ids if isinstance(value, str) and value)
                rag_ready = bool(tenant_ids)
                if not rag_ready:
                    warnings.append("No tenant documents found. Check your MongoDB database/collection and ingestion.")
            except Exception as exc:
                logger.warning("Tenant discovery failed (%s)", type(exc).__name__)
                tenant_ids = []
                rag_ready = False
                warnings.append("Cannot reach MongoDB. Check MONGODB_URI, Atlas network access, and the database settings in .env.")
            self._tenant_ids = set(tenant_ids)
            try:
                models = self.client.client.list()
                installed = {model.model for model in models.models}
                ollama_ready = self.client.model in installed
                if not ollama_ready:
                    warnings.append(f"The configured model {self.client.model} is not installed. Use ollama list and set OLLAMA_MODEL in .env.")
            except Exception as exc:
                logger.warning("Ollama discovery failed (%s)", type(exc).__name__)
                ollama_ready = False
                warnings.append("Ollama is not reachable. Start it with ollama serve, then refresh the connection.")
            self._config = {
                "model": self.client.model,
                "tenants": [{"id": tenant, "name": tenant.replace("_", " ").title()} for tenant in tenant_ids],
                "rag_ready": rag_ready,
                "ollama_ready": ollama_ready,
                "warnings": warnings,
            }
            return self._config

    def _retriever(self):
        with self._retriever_lock:
            if self.retriever is None:
                from src.rag.retriever import RAGRetriever

                self.retriever = RAGRetriever(env_file=PROJECT_ROOT / ".env", db_name="capstone_dev")
            return self.retriever

    def chat(self, request: ChatRequest):
        """Yield progress, fetched evidence, then a schema-validated answer."""
        if self._config is None:
            self.config()
        if request.tenant not in self._tenant_ids:
            yield {"type": "error", "message": "Select a business from the available tenants."}
            return
        started = time.perf_counter()
        history = [turn.model_dump() for turn in request.history]
        previous_queries = [turn.content for turn in request.history if turn.role == "user"][-2:]
        retrieval_query = request.query
        if previous_queries:
            retrieval_query = "Previous customer questions:\n" + "\n".join(previous_queries) + "\nCurrent question:\n" + request.query
        stage = "retrieval"
        try:
            yield {"type": "status", "message": "Finding relevant passages…"}
            retriever = self._retriever()
            retrieval_started = time.perf_counter()
            with self._retriever_lock:
                chunks = retriever.retrieve(query=retrieval_query, tenant_id=request.tenant, top_k=request.top_k)
            if any(chunk.get("tenant_id") != request.tenant for chunk in chunks):
                raise RuntimeError("Cross-tenant retrieval was rejected.")
            retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
            context = retriever.format_context(chunks)
            sources = [{
                "doc_id": chunk.get("doc_id", "unknown"),
                "section": chunk.get("section", ""),
                "chunk_index": chunk.get("chunk_index"),
                "score": chunk.get("score"),
                "text": chunk.get("text", ""),
            } for chunk in chunks]
            yield {
                "type": "retrieved", "tenant": request.tenant, "query": retrieval_query,
                "sources": sources, "context": context, "retrieval_ms": retrieval_ms,
            }
            stage = "generation"
            yield {"type": "status", "message": "Llama is reading the retrieved context…"}
            with self._model_lock:
                raw, timing = self.client.generate_raw(request.query, context, history=history)
            response = SupportResponse.model_validate_json(raw)
            yield {
                "type": "answer", "model": self.client.model,
                "response": response.model_dump(), "timing": {
                    **timing, "retrieval_ms": retrieval_ms,
                    "total_ms": (time.perf_counter() - started) * 1000,
                },
            }
        except Exception as exc:
            # Driver exception text can contain connection details; don't return it to the browser.
            logger.error("Chat %s failed (%s)", stage, type(exc).__name__)
            message = (
                "Retrieval failed. Check MongoDB Atlas connectivity, vector_index, and the embedding model configuration."
                if stage == "retrieval" else
                "Model generation failed. Check that Ollama is running and OLLAMA_MODEL matches an installed model. Retrieved passages are still shown."
            )
            yield {"type": "error", "message": message}

    def close(self):
        if self._mongo_client is not None:
            self._mongo_client.close()
        if self.retriever is not None:
            self.retriever.client.close()
