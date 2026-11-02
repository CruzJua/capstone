"""Benchmark RAG retrieval accuracy and latency across tenants.

Evaluates:
- Hit Rate@k: at least one relevant document retrieved in top-k.
- Document Recall@k: fraction of relevant documents retrieved in top-k.
- Evidence Span Coverage@k: fraction of ground-truth evidence quotes covered in top-k chunks.
- MRR@k: Mean Reciprocal Rank of the first relevant document.
- Latency (average milliseconds per query).

Enforces strict tenant isolation and documents relationship to the frozen generation benchmark.
Outputs machine-readable summaries and error failure logs.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

# Load environment variables from project root .env
load_dotenv(project_root / ".env")

from src.evaluation.retrieval_metrics import (
    aggregate_retrieval_metrics,
    compare_sample_to_benchmark,
    compute_dataset_sha256,
    evaluate_query_retrieval,
    parse_ground_truth_docs,
    parse_ground_truth_evidence,
    verify_tenant_isolation,
)
from src.rag.retriever import RAGRetriever


def parse_ground_truth(row: pd.Series) -> Set[str]:
    """Extracts ground-truth doc IDs (file stems) from evidence_json and/or cited_sources."""
    return parse_ground_truth_docs(row)


def load_answerable(dataset: Path) -> pd.DataFrame:
    """Loads dataset and filters to answerable tickets with valid ground truth."""
    if dataset.suffix.lower() == ".json":
        payload = json.loads(dataset.read_text(encoding="utf-8"))
        df = pd.DataFrame(payload["questions"]).rename(columns={"tenant": "business"})
    else:
        df = pd.read_csv(dataset)
    answerable = df["is_answerable"].astype(str).str.lower() == "true"
    df = df[answerable].copy()
    df["ground_truth"] = df.apply(parse_ground_truth_docs, axis=1)
    df["ground_truth_evidence"] = df.apply(parse_ground_truth_evidence, axis=1)
    return df[df["ground_truth"].map(len) > 0]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Benchmark RAG retrieval (Hit Rate@k, Document Recall@k, Evidence Span Coverage) against ground-truth tickets."
    )
    parser.add_argument("--tenant", default="all", help="Tenant to benchmark (default: all)")
    parser.add_argument(
        "--dataset",
        default=str(project_root / "data/cleaned/cleaned_tickets.csv"),
        help="Path to evaluation dataset (default: data/cleaned/cleaned_tickets.csv)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=50,
        help="Answerable tickets per tenant to sample (default: 50)",
    )
    parser.add_argument(
        "--k-values",
        type=int,
        nargs="+",
        default=[1, 3, 5],
        help="Top-k evaluation cutoffs (default: 1 3 5)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Sampling seed for reproducible runs (default: 42)",
    )
    parser.add_argument(
        "--max-per-doc",
        type=int,
        default=2,
        help="Max chunks per document for diversity (default: 2)",
    )
    parser.add_argument(
        "--benchmark-file",
        default=str(project_root / "data/evaluation/held_out_benchmark.json"),
        help="Path to frozen generation benchmark for sample relationship audit",
    )
    parser.add_argument(
        "--summary-out",
        default=str(project_root / "logs/retrieval_benchmark_summary.json"),
        help="Path to save machine-readable summary (JSON format)",
    )
    parser.add_argument(
        "--failures-out",
        default=str(project_root / "logs/retrieval_failures.json"),
        help="Where to write queries with no relevant chunk in top max(k) results (JSON format)",
    )
    return parser.parse_args()


def run_benchmark(retriever: RAGRetriever, args) -> Dict[str, Any]:
    if args.sample_size <= 0 or not args.k_values or min(args.k_values) <= 0 or args.max_per_doc <= 0:
        raise ValueError("sample-size, k-values, and max-per-doc must be positive")
    dataset_path = Path(args.dataset)
    if not dataset_path.is_file():
        print(f"Error: dataset file not found: {dataset_path}")
        sys.exit(1)

    dataset_hash = compute_dataset_sha256(dataset_path)
    k_values = sorted(set(args.k_values))
    max_k = max(k_values)

    df = load_answerable(dataset_path)
    tenants = sorted(df["business"].unique()) if args.tenant == "all" else [args.tenant]
    if args.tenant != "all" and args.tenant not in set(df["business"]):
        print(f"Error: tenant '{args.tenant}' has no answerable tickets in {dataset_path}.")
        sys.exit(1)

    failures = []
    all_query_results = []
    all_latencies = []
    tenant_metrics_map = {}
    sample_ids_by_tenant = {}
    benchmark_relations_by_tenant = {}

    table_rows = []

    for tenant in tenants:
        tenant_df = df[df["business"] == tenant]
        sample = tenant_df.sample(n=min(args.sample_size, len(tenant_df)), random_state=args.seed)
        sample_ids = sample["ticket_id"].tolist()
        sample_ids_by_tenant[tenant] = sample_ids

        # Analyze relation to frozen generation benchmark
        bench_rel = compare_sample_to_benchmark(sample_ids, args.benchmark_file, tenant=tenant)
        benchmark_relations_by_tenant[tenant] = bench_rel

        tenant_query_results = []
        tenant_latencies = []

        for _, ticket in sample.iterrows():
            start_time = time.perf_counter()
            results = retriever.retrieve(
                query=ticket["customer_query"],
                tenant_id=tenant,
                top_k=max_k,
                max_per_doc=args.max_per_doc,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            tenant_latencies.append(elapsed_ms)

            # Strict tenant isolation check
            verify_tenant_isolation(results, expected_tenant=tenant)

            truth_docs = ticket["ground_truth"]
            truth_evidence = ticket.get("ground_truth_evidence", [])

            q_metrics = evaluate_query_retrieval(
                ground_truth_docs=truth_docs,
                retrieved_chunks=results,
                k_values=k_values,
                ground_truth_evidence=truth_evidence,
                expected_tenant=tenant,
            )
            tenant_query_results.append(q_metrics)

            retrieved_ids = [r.get("doc_id") for r in results]
            if not truth_docs.intersection(retrieved_ids[:max_k]):
                failures.append({
                    "ticket_id": ticket.get("ticket_id"),
                    "tenant": tenant,
                    "query": ticket["customer_query"],
                    "ground_truth": sorted(truth_docs),
                    "retrieved": [
                        {"doc_id": r.get("doc_id"), "section": r.get("section"), "score": r.get("score")}
                        for r in results
                    ],
                })

        agg = aggregate_retrieval_metrics(tenant_query_results, k_values)
        avg_lat = sum(tenant_latencies) / len(tenant_latencies) if tenant_latencies else 0.0
        agg["avg_latency_ms"] = avg_lat
        tenant_metrics_map[tenant] = agg

        all_query_results.extend(tenant_query_results)
        all_latencies.extend(tenant_latencies)

        table_rows.append({
            "tenant": tenant,
            "n": len(sample),
            "multi_n": agg["multi_doc_count"],
            "hit_rates": agg["hit_rate"],
            "doc_recalls": agg["doc_recall"],
            "span_covs": agg["evidence_span_coverage"],
            "multi_doc_recall": agg["multi_doc_metrics"]["doc_recall"],
            "latency": avg_lat,
        })

    # Overall aggregate
    overall_agg = aggregate_retrieval_metrics(all_query_results, k_values)
    overall_lat = sum(all_latencies) / len(all_latencies) if all_latencies else 0.0
    overall_agg["avg_latency_ms"] = overall_lat

    if len(tenants) > 1:
        table_rows.append({
            "tenant": "OVERALL",
            "n": len(all_query_results),
            "multi_n": overall_agg["multi_doc_count"],
            "hit_rates": overall_agg["hit_rate"],
            "doc_recalls": overall_agg["doc_recall"],
            "span_covs": overall_agg["evidence_span_coverage"],
            "multi_doc_recall": overall_agg["multi_doc_metrics"]["doc_recall"],
            "latency": overall_lat,
        })

    # 1. Print formatted audit table
    print("\n" + "=" * 115)
    print("RETRIEVAL AUDIT BENCHMARK: Hit Rate@k vs Document Recall@k vs Span Coverage@k")
    print("=" * 115)
    print("Definitions:")
    print("  - Hit Rate@k:      Fraction of queries where >=1 relevant document was retrieved.")
    print("  - Doc Recall@k:    Fraction of all required documents retrieved (differs from Hit Rate on multi-doc queries).")
    print("  - Span Cov@k:      Fraction of ground-truth evidence quotes contained in retrieved chunks.")
    print("-" * 115)

    hdr = f"{'Tenant':<18}{'N':>5}{'Multi':>6}"
    for k in k_values:
        hdr += f"{'Hit@' + str(k):>9}{'Rec@' + str(k):>9}"
    max_k_str = str(max_k)
    hdr += f"{'Span@' + max_k_str:>10}{'MultiRec@' + max_k_str:>11}{'Avg ms':>9}"
    print(hdr)
    print("-" * len(hdr))

    for row in table_rows:
        if row["tenant"] == "OVERALL":
            print("-" * len(hdr))
        line = f"{row['tenant']:<18}{row['n']:>5}{row['multi_n']:>6}"
        for k in k_values:
            line += f"{row['hit_rates'][k]:>9.3f}{row['doc_recalls'][k]:>9.3f}"
        span = row["span_covs"][max_k]
        line += f"{span:>10.3f}" if span is not None else f"{'N/A':>10}"
        line += f"{row['multi_doc_recall'][max_k]:>11.3f}"
        line += f"{row['latency']:>9.1f}"
        print(line)
    print("-" * len(hdr))

    # 2. Print Benchmark Relationship Documentation
    print("\nRELATION TO FROZEN GENERATION BENCHMARK (data/evaluation/held_out_benchmark.json):")
    for t, rel in benchmark_relations_by_tenant.items():
        print(f"  [{t}] {rel['relationship']}: {rel['explanation']}")

    # 3. Handle Failures Log
    print(f"\n{len(failures)} queries had no relevant document chunk in top {max_k}.")
    out_path = Path(args.failures_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(failures, indent=4) + "\n", encoding="utf-8")
    print(f"Failure cases written to {out_path}")
    for failure in failures[:3]:
        got = ", ".join(r["doc_id"] for r in failure["retrieved"]) or "(none)"
        print(f"  [{failure['tenant']}] {failure['query'][:80]!r}")
        print(f"      expected: {', '.join(failure['ground_truth'])} | got: {got}")

    # 4. Save Machine-Readable Summary
    summary_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "path": str(dataset_path.resolve()),
            "sha256": dataset_hash,
            "total_answerable_pool": len(df),
        },
        "retrieval_settings": {
            "tenant_arg": args.tenant,
            "sample_size_per_tenant": args.sample_size,
            "k_values": k_values,
            "seed": args.seed,
            "max_per_doc": args.max_per_doc,
            "index_name": retriever.index_name if hasattr(retriever, "index_name") else "vector_index",
        },
        "benchmark_comparison": benchmark_relations_by_tenant,
        "sample_ticket_ids": sample_ids_by_tenant,
        "tenant_metrics": tenant_metrics_map,
        "overall_metrics": overall_agg,
        "failures_count": len(failures),
        "failures_file": str(Path(args.failures_out).resolve()) if failures else None,
    }

    summary_path = Path(args.summary_out)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary_payload, indent=4) + "\n", encoding="utf-8")
    print(f"\nMachine-readable summary written to: {summary_path}")

    return summary_payload


def main():
    args = parse_args()
    print("Loading retriever...")
    retriever = RAGRetriever()
    try:
        run_benchmark(retriever, args)
    finally:
        retriever.client.close()


if __name__ == "__main__":
    main()
