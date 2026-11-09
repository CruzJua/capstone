"""Evaluate model decisions against a frozen benchmark without judging answer quality."""

import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from statistics import mean

from pydantic import ValidationError

from src.inference.schema import SupportResponse

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_benchmark(benchmark_path: Path, limit: int | None = None):
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive.")
    with Path(benchmark_path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Benchmark must be an object with metadata and questions.")
    metadata, questions = payload.get("metadata"), payload.get("questions")
    if not isinstance(metadata, dict) or not isinstance(questions, list):
        raise ValueError("Benchmark requires a metadata object and questions list.")
    if not questions:
        raise ValueError("Benchmark contains no questions.")
    for index, question in enumerate(questions, 1):
        if not isinstance(question, dict):
            raise ValueError(f"Question {index} must be an object.")
        for field in ("ticket_id", "tenant", "customer_query"):
            if not isinstance(question.get(field), str) or not question[field].strip():
                raise ValueError(f"Question {index} requires a nonempty {field}.")
        if question.get("ground_truth_action") not in {"answer", "escalate"}:
            raise ValueError(f"Question {index} has an invalid ground_truth_action.")
        if type(question.get("is_answerable")) is not bool:
            raise ValueError(f"Question {index} requires a boolean is_answerable.")
        if not question["is_answerable"] and question["ground_truth_action"] != "escalate":
            raise ValueError(f"Unanswerable question {index} must expect escalation.")
        if metadata.get("held_out_tenant") and question["tenant"] != metadata["held_out_tenant"]:
            raise ValueError(f"Question {index} does not belong to the held-out tenant.")
    return metadata, questions[:limit] if limit is not None else questions


def build_ground_truth_context(evidence_json) -> str:
    if isinstance(evidence_json, str):
        try:
            evidence_json = json.loads(evidence_json)
        except json.JSONDecodeError:
            return ""
    if not isinstance(evidence_json, list):
        return ""
    grouped = {}
    for item in evidence_json:
        if not isinstance(item, dict):
            continue
        source, quote = item.get("source"), item.get("quote")
        if isinstance(source, str) and source.strip() and isinstance(quote, str) and quote.strip():
            grouped.setdefault(source, []).append(quote.strip())
    return "\n\n".join(
        f'<context source="{escape(source, quote=True)}">\n[Source: {source}]\n'
        + "\n".join(quotes) + "\n</context>"
        for source, quotes in grouped.items()
    )


def initialize_services(model_name: str | None = None, use_retriever: bool = False,
                        query_prefix: str | None = None, db_name: str | None = None):
    """Build the inference client and optional retriever.

    query_prefix=None keeps the retriever default (BGE query prefix on); "" turns it off,
    which is only meant for reproducing historical runs made before the prefix existed.
    """
    from src.inference.client import SupportInferenceClient

    client = SupportInferenceClient(model=model_name)
    retriever = None
    if use_retriever:
        from src.rag.retriever import RAGRetriever

        retriever = RAGRetriever(query_prefix=query_prefix, db_name=db_name)
    return client, retriever


def run_evaluation_loop(client, retriever, questions: list, use_retriever: bool = False):
    """Return counts, records, latencies and decoding speeds.

    Invalid responses never earn correct-decision credit. An explicit 'answer'
    in a schema-invalid object still counts as hallucination on an absent item.
    Requests that fail at the service layer propagate, rather than producing a
    misleading model score for an unavailable service.
    """
    if use_retriever and retriever is None:
        raise ValueError("A retriever is required when use_retriever=True.")
    counts = dict.fromkeys([
        "TP", "FP", "FN", "TN", "total_eval", "schema_valid", "schema_invalid",
        "absent_total", "absent_hallucinated", "invalid_absent",
    ], 0)
    records, latencies, tokens_per_sec = [], [], []
    for index, question in enumerate(questions, 1):
        query, expected = question["customer_query"], question["ground_truth_action"]
        if use_retriever:
            chunks = retriever.retrieve(query=query, tenant_id=question["tenant"])
            if any(chunk.get("tenant_id") != question["tenant"] for chunk in chunks):
                raise RuntimeError(f"Cross-tenant retrieval detected for {question['ticket_id']}")
            context = retriever.format_context(chunks)
        else:
            context = build_ground_truth_context(question.get("evidence_json"))

        raw, timing = client.generate_raw(query, context)
        response, data, error = None, None, None
        try:
            data = json.loads(raw)
            response = SupportResponse.model_validate(data, strict=True)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            error = str(exc)
        # Retain an observable action even if another response field is invalid.
        action = data.get("action") if isinstance(data, dict) else None
        if action not in ("answer", "escalate"):
            action = None
        valid = response is not None
        counts["total_eval"] += 1
        counts["schema_valid" if valid else "schema_invalid"] += 1
        if expected == "escalate":
            # Invalid responses are missed escalations, not successful refusals.
            counts["TP" if valid and action == "escalate" else "FN"] += 1
        elif valid:
            counts["FP" if action == "escalate" else "TN"] += 1
        if question["is_answerable"] is False:
            counts["absent_total"] += 1
            counts["absent_hallucinated"] += int(action == "answer")
            counts["invalid_absent"] += int(not valid)
        latency, speed = timing.get("latency_ms", 0.0), timing.get("tokens_per_second", 0.0)
        latencies.append(latency)
        tokens_per_sec.append(speed)
        records.append({
            **question,
            "context": context,
            "raw": raw,
            "schema_valid": valid,
            "error": error,
            "model_action": action,
            "model_answer": response.answer if valid else None,
            "model_confidence": response.confidence if valid else None,
            "model_sources": response.cited_sources if valid else [],
            "action_correct": valid and action == expected,
            "latency_ms": latency,
            "eval_tokens": timing.get("eval_tokens", 0),
            "tokens_per_second": speed,
        })
        status = "INVALID" if not valid else "OK" if action == expected else "MISS"
        print(f"[{index}/{len(questions)}] {status} | Expected: {expected} | Model: {action or '-'}")
    return counts, records, latencies, tokens_per_sec


def calculate_metrics(counts: dict, latencies: list, tokens_per_sec: list) -> dict:
    def ratio(numerator, denominator):
        return numerator / denominator if denominator else 0.0

    tp, fp, fn, tn = (counts.get(key, 0) for key in ("TP", "FP", "FN", "TN"))
    total = counts.get("total_eval", 0)
    precision, recall = ratio(tp, tp + fp), ratio(tp, tp + fn)
    return {
        "hallucination_rate": ratio(counts.get("absent_hallucinated", 0), counts.get("absent_total", 0)),
        "schema_validity_rate": ratio(counts.get("schema_valid", 0), total),
        "escalation_precision": precision,
        "escalation_recall": recall,
        "escalation_f1": ratio(2 * precision * recall, precision + recall),
        "action_accuracy": ratio(tp + tn, total),
        "avg_latency_ms": mean(latencies) if latencies else 0.0,
        "avg_tokens_per_second": mean(tokens_per_sec) if tokens_per_sec else 0.0,
        "counts": dict(counts),
    }


def print_scorecard(metrics: dict, model_name: str, total_eval: int):
    print(f"\nGeneration evaluation: {model_name}\nQuestions evaluated: {total_eval}")
    print(f"Schema validity:              {metrics['schema_validity_rate']:.2%} (target: 100%)")
    print(f"Countable hallucination:      {metrics['hallucination_rate']:.2%} (target: < 5%)")
    print(f"Escalation precision:         {metrics['escalation_precision']:.2%}")
    print(f"Escalation recall:            {metrics['escalation_recall']:.2%}")
    print(f"Escalation F1:                {metrics['escalation_f1']:.2%}")
    print(f"Action accuracy:              {metrics['action_accuracy']:.2%}")
    print(f"Average generation latency:   {metrics['avg_latency_ms']:.1f} ms")
    print(f"Average decoding throughput:  {metrics['avg_tokens_per_second']:.1f} tokens/sec")
    if not metrics["counts"].get("absent_total"):
        print("No provably-absent questions evaluated; hallucination rate is not measured.")
    if metrics["counts"].get("invalid_absent"):
        print("Invalid absent responses are reported separately; a low hallucination rate alone is insufficient.")


def save_evaluation_log(metrics: dict, records: list, model_name: str, output_path: str | None = None):
    now = datetime.now(timezone.utc)
    safe_model = re.sub(r"[^\w.-]+", "_", model_name)
    path = Path(output_path) if output_path else (
        PROJECT_ROOT / "logs" / f"generation_eval_{safe_model}_{now:%Y%m%d_%H%M%S_%f}.json"
    )
    payload = {
        "timestamp": now.isoformat(), "model": model_name, "metrics": metrics, "records": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=4, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Evaluation log saved to {path}")
    return path
