"""Retrieval and validated generation for one visitor message.

``ChatOrchestrator.stream`` is a generator of plain event dicts consumed by the Node gateway
(see ``src/chat/server.py``). It reuses ``RAGRetriever`` (tenant pre-filtered ``$vectorSearch``)
and the Ollama client from ``SupportInferenceClient``. Visitor answer text is buffered until
schema validation and the live product-capability safeguard complete.

Event sequence for a successful reply::

    {"type": "sources", "sources": [{"doc_id", "section", "score"}, ...]}
    {"type": "progress"}                       (content-free cancellation heartbeat)
    {"type": "token", "text": "..."}            (one validated answer)
    {"type": "done", "action": "answer" | "escalate", "confidence": 0.9, "cited_sources": [...]}

``action``, ``confidence`` and ``cited_sources`` are consumed by the gateway to open a human-review
ticket on escalation; they are never shown to the visitor.

A failure is reported as ``{"type": "error", "code": ..., "message": ...}`` and ends the stream.
"""

import json
import logging
import threading
import time
from typing import Iterator, Literal

from pydantic import BaseModel, Field, ValidationError

from src.inference.client import SupportInferenceClient
from src.inference.schema import SupportResponse
from src.inference.policy import build_policy_prompt, requires_handoff_safeguard, SAFE_FOLLOWUP_ANSWER

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 12


class AgentConfig(BaseModel):
    """Per-tenant runtime configuration (businesses.agent_config)."""

    system_prompt: str = Field(default="", max_length=4000)
    agent_tone: str = Field(default="", max_length=200)
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    max_context_chunks: int = Field(default=4, ge=1, le=8)
    similarity_threshold: float = Field(default=0.70, ge=0.0, le=1.0)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class BusinessContact(BaseModel):
    """Public contact data supplied by the trusted gateway, never the visitor."""

    email: str = Field(default="", max_length=254, pattern=r"^[^\r\n]*$")
    phone: str = Field(default="", max_length=80, pattern=r"^[^\r\n]*$")


class ChatServiceRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    query: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)
    agent_config: AgentConfig = Field(default_factory=AgentConfig)
    business_contact: BusinessContact = Field(default_factory=BusinessContact)


def build_system_prompt(config: AgentConfig) -> str:
    """Tenant instructions are customization, never a replacement for core policy."""
    return build_policy_prompt(config.system_prompt, config.agent_tone)


class ChatOrchestrator:
    def __init__(self, retriever, client: SupportInferenceClient):
        self.retriever = retriever
        self.client = client
        self._retriever_lock = threading.Lock()
        self._model_lock = threading.Lock()

    def _retrieve(self, request: ChatServiceRequest):
        config = request.agent_config
        previous_queries = [turn.content for turn in request.history if turn.role == "user"][-2:]
        retrieval_query = request.query
        if previous_queries:
            retrieval_query = (
                "Previous customer questions:\n" + "\n".join(previous_queries)
                + "\nCurrent question:\n" + request.query
            )
        with self._retriever_lock:
            chunks = self.retriever.retrieve(
                query=retrieval_query, tenant_id=request.tenant_id, top_k=config.max_context_chunks
            )
        # Fail closed: a chunk from any other tenant means retrieval is not trustworthy.
        if any(chunk.get("tenant_id") != request.tenant_id for chunk in chunks):
            raise RuntimeError("Cross-tenant retrieval was rejected.")
        return [
            chunk for chunk in chunks
            if isinstance(chunk.get("score"), (int, float)) and chunk["score"] >= config.similarity_threshold
        ]

    def stream(self, request: ChatServiceRequest) -> Iterator[dict]:
        config = request.agent_config
        try:
            chunks = self._retrieve(request)
            context = self.retriever.format_context(chunks)
        except Exception as exc:
            # Driver exception text can contain connection details; keep it out of responses.
            logger.error("Retrieval failed (%s)", type(exc).__name__)
            yield {"type": "error", "code": "retrieval_failed", "message": "Retrieval failed."}
            return

        yield {
            "type": "sources",
            "sources": [
                {"doc_id": chunk.get("doc_id", "unknown"), "section": chunk.get("section", ""), "score": chunk["score"]}
                for chunk in chunks
            ],
        }

        history = [turn.model_dump() for turn in request.history]
        contact = request.business_contact
        contact_text = ""
        if contact.email or contact.phone:
            # Gateway metadata is distinct from retrieved documents and conversation history.
            contact_text = "\n\nVerified business contact information:\n" + json.dumps(
                contact.model_dump(exclude_defaults=True), ensure_ascii=False, indent=4
            )
        messages = [
            {"role": "system", "content": build_system_prompt(config)},
            {"role": "user", "content": self.client.build_user_prompt(request.query, context, history) + contact_text},
        ]
        raw = []
        stream = None
        last_progress = 0.0
        try:
            with self._model_lock:
                stream = self.client.client.chat(
                    model=self.client.model,
                    messages=messages,
                    format=SupportResponse.model_json_schema(),
                    options={"temperature": config.temperature},
                    stream=True,
                )
                for part in stream:
                    piece = part.message.content or ""
                    if not piece:
                        continue
                    raw.append(piece)
                    now = time.monotonic()
                    if now - last_progress >= 0.5:
                        # No answer text: writes let the HTTP server detect an aborted visitor
                        # and close this generator/Ollama stream during buffered generation.
                        yield {"type": "progress"}
                        last_progress = now
            response = SupportResponse.model_validate_json("".join(raw))
            raw_action = response.action
            reason = "none"
            if requires_handoff_safeguard(response.answer):
                reason = "unsupported_handoff_promise"
                response = SupportResponse(
                    answer=SAFE_FOLLOWUP_ANSWER, action="escalate", confidence=0.0, cited_sources=[]
                )
            log_result = logger.warning if reason != "none" else logger.info
            log_result("Support response raw_action=%s effective_action=%s safeguard=%s",
                       raw_action, response.action, reason)
            # Buffer until validation and capability checks finish: unsafe text cannot be retracted.
            yield {"type": "token", "text": response.answer}
            # action / confidence / cited_sources are for the gateway only (human escalation review);
            # the gateway never forwards them to the visitor.
            yield {
                "type": "done",
                "action": response.action,
                "confidence": response.confidence,
                "cited_sources": response.cited_sources,
            }
        except GeneratorExit:
            raise
        except (ValidationError, ValueError) as exc:
            logger.error("Model returned an invalid response (%s)", type(exc).__name__)
            yield {"type": "error", "code": "generation_failed", "message": "The assistant ran into a problem."}
        except Exception as exc:
            logger.error("Generation failed (%s)", type(exc).__name__)
            # A model server that cannot be reached is reported separately so operators (and the
            # gateway's log) can tell "Ollama is down" from "the model produced bad output".
            code = "model_unavailable" if isinstance(exc, ConnectionError) or "Connect" in type(exc).__name__ else "generation_failed"
            yield {"type": "error", "code": code, "message": "The assistant ran into a problem."}
        finally:
            # Closing the Ollama stream disconnects from the server, which stops generation.
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
