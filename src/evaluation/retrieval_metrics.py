"""Retrieval evaluation metrics and audit utilities.

Distinguishes:
- Hit Rate@k: at least one relevant document retrieved in top-k.
- Document Recall@k: fraction of relevant documents retrieved in top-k.
- Evidence Span Coverage@k: fraction of ground-truth evidence quote spans covered in top-k chunks.
- Mean Reciprocal Rank (MRR@k): reciprocal rank of the first relevant document.

Provides tenant-isolation enforcement, multi-document ticket analysis,
and audit comparison against frozen generation benchmarks.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

import pandas as pd


def normalize_text_span(text: str) -> str:
    """Normalizes whitespace and lowercases text for robust span matching."""
    if not text:
        return ""
    # Lowercase, replace whitespace and normalize quotes
    cleaned = re.sub(r"\s+", " ", str(text)).strip().lower()
    return cleaned


def parse_ground_truth_docs(row_or_dict: Union[pd.Series, Dict[str, Any]]) -> Set[str]:
    """Extracts ground-truth document IDs (file stems without extension) from a ticket record.

    Inspects both `evidence_json` and `cited_sources`.
    """
    sources: List[str] = []

    # 1. Parse evidence_json
    evidence = row_or_dict.get("evidence_json")
    if isinstance(evidence, str) and evidence.strip():
        try:
            parsed = json.loads(evidence)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and item.get("source"):
                        sources.append(item["source"])
                    elif isinstance(item, str):
                        sources.append(item)
        except json.JSONDecodeError:
            pass
    elif isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict) and item.get("source"):
                sources.append(item["source"])
            elif isinstance(item, str):
                sources.append(item)

    # 2. Parse cited_sources
    cited = row_or_dict.get("cited_sources")
    if isinstance(cited, str) and cited.strip():
        try:
            parsed = json.loads(cited)
            if isinstance(parsed, list):
                sources.extend(parsed)
            elif isinstance(parsed, str):
                sources.append(parsed)
        except json.JSONDecodeError:
            sources.extend(s.strip() for s in cited.split(",") if s.strip())
    elif isinstance(cited, list):
        for item in cited:
            if isinstance(item, str):
                sources.append(item)

    # Extract stem (e.g., 'CATERING_AND_CUSTOM_CAKES.md' -> 'CATERING_AND_CUSTOM_CAKES')
    doc_ids = {Path(str(s).strip()).stem for s in sources if str(s).strip()}
    return doc_ids


def parse_ground_truth_evidence(
    row_or_dict: Union[pd.Series, Dict[str, Any]]
) -> List[Dict[str, str]]:
    """Extracts ground-truth evidence quotes and their source document IDs.

    Returns a list of dicts: [{"doc_id": "...", "quote": "...", "section": "..."}, ...]
    """
    evidence = row_or_dict.get("evidence_json")
    items: List[Dict[str, Any]] = []

    if isinstance(evidence, str) and evidence.strip():
        try:
            parsed = json.loads(evidence)
            if isinstance(parsed, list):
                items = parsed
        except json.JSONDecodeError:
            items = []
    elif isinstance(evidence, list):
        items = evidence

    results: List[Dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            source = item.get("source", "")
            quote = item.get("quote", "")
            if source and quote:
                results.append({
                    "doc_id": Path(str(source).strip()).stem,
                    "quote": str(quote).strip(),
                    "section": str(item.get("section", "")).strip(),
                })
    return results


def compute_hit_rate(ground_truth_docs: Set[str], retrieved_doc_ids: Sequence[str], k: int) -> float:
    """Computes Hit Rate@k: 1.0 if at least one relevant document is in top-k, else 0.0.

    If ground_truth_docs is empty (e.g. unanswerable), returns 0.0.
    """
    if not ground_truth_docs:
        return 0.0
    top_k_ids = set(retrieved_doc_ids[:k])
    return 1.0 if len(ground_truth_docs.intersection(top_k_ids)) > 0 else 0.0


def compute_doc_recall(ground_truth_docs: Set[str], retrieved_doc_ids: Sequence[str], k: int) -> float:
    """Computes Document Recall@k: fraction of relevant documents retrieved in top-k.

    When ground_truth has 1 document, Hit Rate@k == Document Recall@k.
    When ground_truth has multiple documents (e.g. 2 docs), retrieving only 1 gives 0.5 recall,
    even though Hit Rate@k is 1.0.
    """
    if not ground_truth_docs:
        return 0.0
    top_k_ids = set(retrieved_doc_ids[:k])
    retrieved_count = len(ground_truth_docs.intersection(top_k_ids))
    return retrieved_count / len(ground_truth_docs)


def compute_mrr(ground_truth_docs: Set[str], retrieved_doc_ids: Sequence[str], k: int) -> float:
    """Computes Mean Reciprocal Rank (MRR@k): 1 / rank of first relevant doc if <= k, else 0.0."""
    if not ground_truth_docs:
        return 0.0
    for rank, doc_id in enumerate(retrieved_doc_ids[:k], start=1):
        if doc_id in ground_truth_docs:
            return 1.0 / rank
    return 0.0


def compute_evidence_coverage(
    ground_truth_evidence: Sequence[Dict[str, str]],
    retrieved_chunks: Sequence[Dict[str, Any]],
    k: int,
) -> Dict[str, Any]:
    """Computes evidence quote coverage in top-k retrieved chunks.

    Returns:
        {
            "measurable": bool,
            "total_quotes": int,
            "covered_quotes": int,
            "evidence_hit_rate": float (1.0 if >=1 quote covered else 0.0),
            "evidence_span_coverage": float (covered_quotes / total_quotes),
        }
    """
    if not ground_truth_evidence:
        return {
            "measurable": False,
            "total_quotes": 0,
            "covered_quotes": 0,
            "evidence_hit_rate": 0.0,
            "evidence_span_coverage": 0.0,
        }

    top_chunks = retrieved_chunks[:k]
    # Prepare normalized chunk representations: map doc_id -> list of normalized texts
    doc_chunk_texts: Dict[str, List[str]] = {}
    for chunk in top_chunks:
        doc_id = chunk.get("doc_id", "")
        text = normalize_text_span(chunk.get("text", ""))
        doc_chunk_texts.setdefault(doc_id, []).append(text)

    covered_count = 0
    for ev in ground_truth_evidence:
        ev_doc = ev["doc_id"]
        ev_quote = normalize_text_span(ev["quote"])
        if not ev_quote:
            continue
        ev_trimmed = ev_quote.strip(" \t\n\r\"'.,;:!?-")
        # Check if the normalized quote appears in any chunk from the same doc_id
        chunk_texts = doc_chunk_texts.get(ev_doc, [])
        is_covered = any(
            (ev_quote in ct) or (bool(ev_trimmed) and ev_trimmed in ct)
            for ct in chunk_texts
        )
        if is_covered:
            covered_count += 1

    total_quotes = len(ground_truth_evidence)
    return {
        "measurable": True,
        "total_quotes": total_quotes,
        "covered_quotes": covered_count,
        "evidence_hit_rate": 1.0 if covered_count > 0 else 0.0,
        "evidence_span_coverage": covered_count / total_quotes if total_quotes > 0 else 0.0,
    }


def verify_tenant_isolation(
    retrieved_chunks: Sequence[Dict[str, Any]], expected_tenant: str
) -> None:
    """Enforces strict tenant isolation. Raises RuntimeError if any chunk leaks from another tenant."""
    leaked = [
        c for c in retrieved_chunks if c.get("tenant_id") != expected_tenant
    ]
    if leaked:
        raise RuntimeError(
            f"Tenant isolation breach detected! Query for tenant '{expected_tenant}' retrieved "
            f"chunks belonging to '{leaked[0].get('tenant_id')}': {leaked[:2]}"
        )


def evaluate_query_retrieval(
    ground_truth_docs: Set[str],
    retrieved_chunks: Sequence[Dict[str, Any]],
    k_values: Sequence[int],
    ground_truth_evidence: Optional[Sequence[Dict[str, str]]] = None,
    expected_tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluates retrieval performance for a single query across multiple k values."""
    if expected_tenant:
        verify_tenant_isolation(retrieved_chunks, expected_tenant)

    retrieved_doc_ids = [c.get("doc_id", "") for c in retrieved_chunks]

    metrics: Dict[str, Any] = {
        "is_multi_doc": len(ground_truth_docs) > 1,
        "ground_truth_doc_count": len(ground_truth_docs),
        "hit_rate": {},
        "doc_recall": {},
        "mrr": {},
        "evidence_hit_rate": {},
        "evidence_span_coverage": {},
        "evidence_measurable": bool(ground_truth_evidence and len(ground_truth_evidence) > 0),
    }

    for k in k_values:
        metrics["hit_rate"][k] = compute_hit_rate(ground_truth_docs, retrieved_doc_ids, k)
        metrics["doc_recall"][k] = compute_doc_recall(ground_truth_docs, retrieved_doc_ids, k)
        metrics["mrr"][k] = compute_mrr(ground_truth_docs, retrieved_doc_ids, k)

        if metrics["evidence_measurable"] and ground_truth_evidence is not None:
            cov = compute_evidence_coverage(ground_truth_evidence, retrieved_chunks, k)
            metrics["evidence_hit_rate"][k] = cov["evidence_hit_rate"]
            metrics["evidence_span_coverage"][k] = cov["evidence_span_coverage"]

    return metrics


def compute_dataset_sha256(dataset_path: Union[str, Path]) -> str:
    """Calculates SHA-256 fingerprint of the dataset file."""
    path = Path(dataset_path)
    if not path.is_file():
        return ""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def compare_sample_to_benchmark(
    sample_ticket_ids: Sequence[str],
    benchmark_path: Union[str, Path],
    tenant: str,
) -> Dict[str, Any]:
    """Analyzes exact relation between the retrieval sample and the frozen generation benchmark.

    Never implies samples are identical unless ticket IDs match exactly.
    """
    path = Path(benchmark_path)
    if not path.is_file():
        return {
            "benchmark_file": str(benchmark_path),
            "status": "benchmark_file_not_found",
            "relationship": "unknown",
            "matching_ids_count": 0,
            "sample_ids_count": len(sample_ticket_ids),
            "is_identical_sample": False,
            "explanation": f"Benchmark file {benchmark_path} does not exist.",
        }

    benchmark_data = json.loads(path.read_text(encoding="utf-8"))
    b_meta = benchmark_data.get("metadata", {})
    b_questions = benchmark_data.get("questions", [])

    b_held_out = b_meta.get("held_out_tenant", "harbor_view")
    b_all_ids = {q["ticket_id"] for q in b_questions}
    b_ans_ids = {q["ticket_id"] for q in b_questions if q.get("is_answerable")}
    b_unans_ids = {q["ticket_id"] for q in b_questions if not q.get("is_answerable")}

    sample_id_set = set(sample_ticket_ids)
    overlap_all = sample_id_set.intersection(b_all_ids)
    overlap_ans = sample_id_set.intersection(b_ans_ids)

    is_identical_to_full = (sample_id_set == b_all_ids)
    is_identical_to_ans = (sample_id_set == b_ans_ids)

    if tenant != b_held_out:
        relationship = "disjoint_tenant"
        explanation = (
            f"Retrieval evaluated tenant '{tenant}', whereas the frozen generation benchmark "
            f"evaluates held-out tenant '{b_held_out}'. These are completely distinct sets."
        )
    elif is_identical_to_full:
        relationship = "identical_to_full_benchmark"
        explanation = "Retrieval sample ticket IDs match the full 100-question generation benchmark exactly."
    elif is_identical_to_ans:
        relationship = "identical_to_benchmark_answerable_subset"
        explanation = (
            f"Retrieval sample ticket IDs match the {len(b_ans_ids)} answerable tickets of the frozen "
            f"generation benchmark exactly. The benchmark's {len(b_unans_ids)} unanswerable tickets "
            "are excluded from retrieval benchmarking because they contain no document targets."
        )
    elif overlap_ans:
        relationship = "partial_overlap"
        explanation = (
            f"Retrieval sample contains {len(overlap_ans)}/{len(b_ans_ids)} answerable benchmark tickets "
            f"and {len(sample_id_set - b_ans_ids)} non-benchmark tickets."
        )
    else:
        relationship = "disjoint_same_tenant"
        explanation = (
            f"Retrieval evaluated tenant '{tenant}', but none of the {len(sample_ticket_ids)} sample IDs "
            f"match the {len(b_questions)} tickets in the frozen benchmark."
        )

    return {
        "benchmark_file": str(path.resolve()),
        "benchmark_held_out_tenant": b_held_out,
        "benchmark_total_questions": len(b_questions),
        "benchmark_answerable_count": len(b_ans_ids),
        "benchmark_unanswerable_count": len(b_unans_ids),
        "sample_ids_count": len(sample_ticket_ids),
        "overlap_with_benchmark_answerable": len(overlap_ans),
        "is_identical_to_full_benchmark": is_identical_to_full,
        "is_identical_to_benchmark_answerable_subset": is_identical_to_ans,
        "relationship": relationship,
        "explanation": explanation,
    }


def aggregate_retrieval_metrics(
    query_results: Sequence[Dict[str, Any]], k_values: Sequence[int]
) -> Dict[str, Any]:
    """Aggregates metrics across evaluated queries."""
    n = len(query_results)
    if n == 0:
        return {
            "n": 0,
            "hit_rate": {k: 0.0 for k in k_values},
            "doc_recall": {k: 0.0 for k in k_values},
            "mrr": {k: 0.0 for k in k_values},
            "evidence_span_coverage": {k: None for k in k_values},
            "evidence_measurable_count": 0,
            "evidence_hit_rate": {k: None for k in k_values},
            "multi_doc_metrics": {"count": 0, "hit_rate": {k: None for k in k_values}, "doc_recall": {k: None for k in k_values}},
            "multi_doc_count": 0,
            "single_doc_count": 0,
        }

    hit_rates = {k: sum(r["hit_rate"][k] for r in query_results) / n for k in k_values}
    doc_recalls = {k: sum(r["doc_recall"][k] for r in query_results) / n for k in k_values}
    mrrs = {k: sum(r["mrr"][k] for r in query_results) / n for k in k_values}

    # Evidence coverage over queries where evidence was measurable
    measurable_results = [r for r in query_results if r.get("evidence_measurable")]
    m_count = len(measurable_results)
    if m_count > 0:
        ev_hit_rates = {
            k: sum(r["evidence_hit_rate"][k] for r in measurable_results) / m_count
            for k in k_values
        }
        ev_coverages = {
            k: sum(r["evidence_span_coverage"][k] for r in measurable_results) / m_count
            for k in k_values
        }
    else:
        ev_hit_rates = {k: None for k in k_values}
        ev_coverages = {k: None for k in k_values}

    # Multi-doc breakdown
    multi_results = [r for r in query_results if r.get("is_multi_doc")]
    multi_count = len(multi_results)
    single_count = n - multi_count

    multi_hit_rates = (
        {k: sum(r["hit_rate"][k] for r in multi_results) / multi_count for k in k_values}
        if multi_count > 0
        else {k: 0.0 for k in k_values}
    )
    multi_recalls = (
        {k: sum(r["doc_recall"][k] for r in multi_results) / multi_count for k in k_values}
        if multi_count > 0
        else {k: 0.0 for k in k_values}
    )

    return {
        "n": n,
        "single_doc_count": single_count,
        "multi_doc_count": multi_count,
        "hit_rate": hit_rates,
        "doc_recall": doc_recalls,
        "mrr": mrrs,
        "evidence_measurable_count": m_count,
        "evidence_hit_rate": ev_hit_rates,
        "evidence_span_coverage": ev_coverages,
        "multi_doc_metrics": {
            "count": multi_count,
            "hit_rate": multi_hit_rates,
            "doc_recall": multi_recalls,
        },
    }
