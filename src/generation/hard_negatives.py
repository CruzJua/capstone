"""Teacher-labelled hard negatives for the support student.

The first training run only ever saw an empty context for "not in the documents" tickets, so the
student learned: real context -> answer, "(no relevant documents found)" -> escalate. This module
re-asks the teacher about the SAME customer questions, but with the passages the retriever would
actually return, and lets the teacher decide whether those passages answer the question.

Everything here is local and deterministic. It builds requests, validates the teacher's labels and
assembles records in the format `scripts/business_data_cleaner.py` already reads. No SDK, network
or paid call happens in this module; `scripts/business_data_generator.py` owns that part.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from pydantic import BaseModel, ValidationError

from src.evaluation.training_data_audit import normalize_text

# Escalations carry the retrieved passages as context for the student, not as claimed support.
DISTRACTOR_TYPE = "retrieval_distractor"
ANSWER_TYPE = "single_qa"
DEFAULT_REASONS = ("not_in_docs", "docs_require_human")
MIN_QUOTE_CHARS = 15
SOURCE_SUFFIXES = {".md", ".json", ".txt"}
# Customer-facing text must not leak the prompt's vocabulary.
LEAK_PATTERN = re.compile(r"\b(passages?|retrieved|provided (?:context|documents?))\b", re.I)


class QuoteLabel(BaseModel):
    source: str
    quote: str


class HardNegativeLabel(BaseModel):
    """What the teacher returns for one ticket. The conversation itself is never regenerated."""
    action: Literal["answer", "escalate"]
    escalation_reason: Literal["none", "docs_require_human", "not_in_docs"]
    answer: str
    confidence: float
    rationale: str
    ticket_summary: str
    evidence: list[QuoteLabel]


TEACHER_INSTRUCTIONS = """\
You are the teacher that labels training data for a small customer-support assistant for {business_name}.

The assistant sees ONLY the numbered passages below plus the conversation. The passages were fetched \
automatically, so they are often on-topic but do not contain the fact the customer needs. Judge them honestly.

Decide the correct response to the customer's LAST message using only the passages:
- "answer": the passages fully settle the question. Set escalation_reason="none". Put in `evidence` one or \
more quotes copied VERBATIM (same words, same order, 15-300 characters, never stitched together) from a \
passage, with `source` equal to that passage's source name.
- "escalate" with escalation_reason="not_in_docs": the passages are related but do not state the fact needed \
(a price, time, policy or procedure that is not written there). Do NOT fill the gap from outside knowledge or \
by inference. Say honestly what you cannot confirm, share any directly relevant passage fact, and hand off. \
Leave `evidence` empty.
- "escalate" with escalation_reason="docs_require_human": the passages say a human, emergency or urgent contact \
is needed. Give the documented guidance in `answer` AND escalate. Leave `evidence` empty.

Rules for every label:
- Never invent a price, number, policy, phone number or procedure that is not in the passages.
- `answer` is written to the customer as the support agent: warm, brief, direct, no markdown headings. Never \
mention "passages", "documents", "context" or file names to the customer.
- `confidence`: direct match >= 0.85; inference 0.6-0.85; any escalation 0.0-0.4.
- `rationale`: 1-3 sentences naming what the passages do or do not state, and how that led to your decision.
- `ticket_summary`: for escalations, a 2-4 sentence hand-off note for a human (who, what, what was advised, \
urgency). Otherwise an empty string.
"""


def select_source_tickets(rows: Iterable[dict], reasons: Iterable[str] = DEFAULT_REASONS,
                          limit: int | None = None, seed: int = 390,
                          exclude_tenants: Iterable[str] = ("harbor_view",)) -> list[dict]:
    """Pick existing tickets whose questions get re-labelled against real retrieved context."""
    reasons, excluded = set(reasons), set(exclude_tenants)
    pool = sorted((r for r in rows if r.get("escalation_reason") in reasons and r.get("business") not in excluded),
                  key=lambda r: r["ticket_id"])
    if limit is not None and limit < len(pool):
        pool = sorted(random.Random(f"{seed}:hardneg").sample(pool, limit), key=lambda r: r["ticket_id"])
    return pool


def retrieval_query(messages: list[dict]) -> str:
    """Same query shaping as the demo service: recent customer turns plus the current question."""
    customer = [m["content"] for m in messages if m.get("role") == "customer"]
    if len(customer) <= 1:
        return customer[-1] if customer else ""
    previous = customer[:-1][-2:]
    return "Previous customer questions:\n" + "\n".join(previous) + "\nCurrent question:\n" + customer[-1]


def resolve_source_name(tenant_dir: Path, doc_id: str) -> str:
    """Training evidence cites file names ('X.md'); retrieval reports stems ('X')."""
    for path in sorted(Path(tenant_dir).glob("*")):
        if path.stem == doc_id and path.suffix.lower() in SOURCE_SUFFIXES:
            return path.name
    return doc_id


def build_context(chunks: list[dict], tenant_dir: Path, max_chars: int = 3000, max_chunks: int = 4) -> list[dict]:
    """Keep retrieved chunks in rank order within a hard character budget.

    The training notebook stops the whole run if one example exceeds its token limit, so an
    oversized chunk is skipped rather than truncated, and the next-ranked chunk is tried.
    """
    context, used = [], 0
    for chunk in chunks:
        text = (chunk.get("text") or "").strip()
        if not text or len(text) > max_chars or used + len(text) > max_chars:
            continue
        context.append({"source": resolve_source_name(tenant_dir, chunk.get("doc_id", "")),
                        "section": chunk.get("section") or "", "quote": text})
        used += len(text)
        if len(context) == max_chunks:
            break
    return context


def build_teacher_prompt(business_name: str, messages: list[dict], context: list[dict]) -> str:
    passages = "\n\n".join(
        f"=== PASSAGE {i} | source: {c['source']}" + (f" | section: {c['section']}" if c["section"] else "")
        + f" ===\n{c['quote']}" for i, c in enumerate(context, 1))
    conversation = "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in messages)
    return (TEACHER_INSTRUCTIONS.format(business_name=business_name)
            + f"\nPassages shown to the assistant:\n\n{passages}\n\nConversation:\n{conversation}\n\n"
            "Return the label for the customer's last message in the `tickets` array (exactly one item).")


def build_request_line(key: str, prompt: str, response_schema: dict, temperature: float = 0.2,
                       thinking_level: str = "low", max_output_tokens: int = 2500) -> dict:
    config: dict[str, Any] = {
        "temperature": temperature, "maxOutputTokens": max_output_tokens,
        "responseMimeType": "application/json", "responseJsonSchema": response_schema,
    }
    if thinking_level:
        config["thinkingConfig"] = {"thinkingLevel": thinking_level.upper()}
    return {"key": key, "request": {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                                    "generationConfig": config}}


def plan_requests(rows: list[dict], retrieve: Callable[[str, str], list[dict]], data_dir: Path,
                  business_names: dict[str, str], max_chars: int = 3000, max_chunks: int = 4,
                  prompt_builder: Callable[..., str] = build_teacher_prompt) -> tuple[dict, dict, list[dict]]:
    """Retrieve context per ticket. Returns (prompts by key, plan sidecar by key, skipped tickets)."""
    prompts, plan, skipped = {}, {}, []
    for index, row in enumerate(rows):
        tenant = row["business"]
        messages = json.loads(row["messages_json"])
        context = build_context(retrieve(retrieval_query(messages), tenant), Path(data_dir) / tenant,
                                max_chars, max_chunks)
        if not context:
            skipped.append({"ticket_id": row["ticket_id"], "reason": "no_retrieved_chunk_within_budget"})
            continue
        key = f"{tenant}-hn{index:04d}"
        prompts[key] = prompt_builder(business_names.get(tenant, tenant), messages, context)
        plan[key] = {"business": tenant, "source_ticket_id": row["ticket_id"],
                     "source_escalation_reason": row["escalation_reason"], "category": row.get("category", ""),
                     "messages": messages, "context": context}
    return prompts, plan, skipped


def _quote_in_passage(quote: str, source: str, context: list[dict]) -> bool:
    normalized = normalize_text(quote)
    if len(normalized) < MIN_QUOTE_CHARS:
        return False
    return any(c["source"] == source and normalized in normalize_text(c["quote"]) for c in context)


def finalize_label(entry: dict, label_data: dict) -> tuple[dict | None, str | None]:
    """Validate one teacher label and assemble a Ticket-shaped dict, or return (None, reason)."""
    try:
        label = HardNegativeLabel.model_validate(label_data)
    except ValidationError:
        return None, "schema_invalid"
    if not label.answer.strip() or not label.rationale.strip():
        return None, "empty_answer_or_rationale"
    if not 0.0 <= label.confidence <= 1.0:
        return None, "confidence_out_of_range"
    if LEAK_PATTERN.search(label.answer):
        return None, "answer_mentions_prompt_vocabulary"
    context = entry["context"]

    if label.action == "answer":
        if label.escalation_reason != "none":
            return None, "action_reason_mismatch"
        if not label.evidence:
            return None, "answer_without_evidence"
        if any(not _quote_in_passage(e.quote, e.source, context) for e in label.evidence):
            return None, "quote_not_verbatim_in_cited_passage"
        evidence = [{"source": e.source, "quote": e.quote.strip()} for e in label.evidence]
        interaction_type, summary = ANSWER_TYPE, ""
    else:
        if label.escalation_reason == "none":
            return None, "action_reason_mismatch"
        # The retrieved passages ARE the context the student is trained to see before escalating.
        evidence = [{"source": c["source"], "quote": c["quote"]} for c in context]
        interaction_type, summary = DISTRACTOR_TYPE, label.ticket_summary.strip()
    return {
        "interaction_type": interaction_type,
        "category": entry["category"] or "general",
        "messages": entry["messages"],
        # The training notebook rejects evidence on rows flagged unanswerable, so rows that carry
        # context are marked answerable; `escalation_reason` and `action` hold the real decision.
        "is_answerable": True,
        "evidence": evidence,
        "rationale": label.rationale.strip(),
        "action": label.action,
        "escalation_reason": label.escalation_reason,
        "answer": label.answer.strip(),
        "confidence": label.confidence,
        "ticket_summary": summary,
    }, None


def result_line(key: str, ticket: dict) -> dict:
    """One line in the Gemini batch result format that the cleaner already parses."""
    text = json.dumps({"tickets": [ticket]}, ensure_ascii=False)
    return {"key": key, "response": {"candidates": [{"content": {"parts": [{"text": text}]}}]}}


def extract_label(raw_line: dict) -> dict | None:
    """Pull the single teacher label out of one raw batch result line."""
    try:
        text = raw_line["response"]["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = re.sub(r"^```(?:json)?|```$", "", text).strip()
        data = json.loads(text)
        tickets = data["tickets"] if isinstance(data, dict) else data
        return tickets[0] if len(tickets) == 1 else None
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None
