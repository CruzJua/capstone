"""Retrieval + streamed generation for one visitor message.

``ChatOrchestrator.stream`` is a generator of plain event dicts consumed by the Node gateway
(see ``src/chat/server.py``). It reuses ``RAGRetriever`` (tenant pre-filtered ``$vectorSearch``)
and the Ollama client from ``SupportInferenceClient``; it adds no retrieval or prompt logic of
its own beyond applying the tenant's runtime configuration.

Event sequence for a successful reply::

    {"type": "sources", "sources": [{"doc_id", "section", "score"}, ...]}
    {"type": "token", "text": "..."}            (zero or more)
    {"type": "done", "action": "answer" | "escalate", "confidence": 0.9, "cited_sources": [...]}

``action``, ``confidence`` and ``cited_sources`` are consumed by the gateway to open a human-review
ticket on escalation; they are never shown to the visitor.

A failure is reported as ``{"type": "error", "code": ..., "message": ...}`` and ends the stream.
"""

import logging
import threading
from typing import Iterator, Literal

from pydantic import BaseModel, Field, ValidationError

from src.chat.answer_stream import AnswerStreamer
from src.inference.client import SYSTEM_PROMPT, SupportInferenceClient
from src.inference.schema import SupportResponse

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


class ChatServiceRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    query: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)
    agent_config: AgentConfig = Field(default_factory=AgentConfig)


def build_system_prompt(config: AgentConfig) -> str:
    """Keeps the trained base prompt verbatim and appends the tenant's instructions after it."""
    extras = []
    if config.system_prompt.strip():
        extras.append(config.system_prompt.strip())
    if config.agent_tone.strip():
        extras.append(f"Tone: {config.agent_tone.strip()}")
    if not extras:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + "\n\nBusiness instructions:\n" + "\n".join(extras)


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
        messages = [
            {"role": "system", "content": build_system_prompt(config)},
            {"role": "user", "content": self.client.build_user_prompt(request.query, context, history)},
        ]
        streamer = AnswerStreamer()
        raw = []
        stream = None
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
                    delta = streamer.feed(piece)
                    if delta:
                        yield {"type": "token", "text": delta}
            response = SupportResponse.model_validate_json("".join(raw))
            if not streamer.answer_started:
                # The model emitted a valid object without streaming the answer incrementally.
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
            yield {"type": "error", "code": "generation_failed", "message": "The assistant ran into a problem."}
        finally:
            # Closing the Ollama stream disconnects from the server, which stops generation.
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
