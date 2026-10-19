import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Set

import pandas as pd
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

# Load environment variables from project root .env
load_dotenv(project_root / ".env")

from src.rag.retriever import RAGRetriever


def parse_ground_truth(row: pd.Series) -> Set[str]:
    """Extracts ground-truth doc IDs (file stems) from evidence_json and/or cited_sources."""
    sources: List[str] = []

    evidence = row.get("evidence_json")
    if isinstance(evidence, str) and evidence.strip():
        try:
            for item in json.loads(evidence):
                if isinstance(item, dict) and item.get("source"):
                    sources.append(item["source"])
        except json.JSONDecodeError:
            pass

    cited = row.get("cited_sources")
    if isinstance(cited, str) and cited.strip():
        try:
            parsed = json.loads(cited)
            sources.extend(parsed if isinstance(parsed, list) else [parsed])
        except json.JSONDecodeError:
            sources.extend(s.strip() for s in cited.split(","))

    return {Path(str(s).strip()).stem for s in sources if str(s).strip()}


def load_answerable(dataset: Path) -> pd.DataFrame:
    df = pd.read_csv(dataset)
    answerable = df["is_answerable"].astype(str).str.lower() == "true"
    df = df[answerable].copy()
    df["ground_truth"] = df.apply(parse_ground_truth, axis=1)
    return df[df["ground_truth"].map(len) > 0]


def main():
    parser = argparse.ArgumentParser(description="Benchmark RAG retrieval Recall@k against ground-truth tickets.")
    parser.add_argument("--tenant", default="all", help="Tenant to benchmark (default: all)")
    parser.add_argument("--dataset", default=str(project_root / "data/cleaned/cleaned_tickets.csv"))
    parser.add_argument("--sample-size", type=int, default=50, help="Answerable tickets per tenant (default: 50)")
    parser.add_argument("--k-values", type=int, nargs="+", default=[1, 3, 5])
    parser.add_argument("--seed", type=int, default=42, help="Sampling seed for reproducible runs")
    parser.add_argument(
        "--failures-out",
        default=str(project_root / "logs/retrieval_failures.jsonl"),
        help="Where to write queries with no relevant chunk in the top max(k) results",
    )
    args = parser.parse_args()

    k_values = sorted(set(args.k_values))
    max_k = max(k_values)

    df = load_answerable(Path(args.dataset))
    tenants = sorted(df["business"].unique()) if args.tenant == "all" else [args.tenant]
    if args.tenant != "all" and args.tenant not in set(df["business"]):
        print(f"Error: tenant '{args.tenant}' has no answerable tickets in {args.dataset}.")
        sys.exit(1)

    print("Loading retriever...")
    retriever = RAGRetriever()

    rows = []
    failures = []
    all_hits = {k: 0 for k in k_values}
    all_count = 0
    all_latency = 0.0

    for tenant in tenants:
        tenant_df = df[df["business"] == tenant]
        sample = tenant_df.sample(n=min(args.sample_size, len(tenant_df)), random_state=args.seed)

        hits = {k: 0 for k in k_values}
        latencies = []

        for _, ticket in sample.iterrows():
            start = time.perf_counter()
            results = retriever.retrieve(query=ticket["customer_query"], tenant_id=tenant, top_k=max_k)
            latencies.append((time.perf_counter() - start) * 1000)

            leaked = [r for r in results if r.get("tenant_id") != tenant]
            if leaked:
                raise RuntimeError(f"Cross-tenant leakage detected for tenant '{tenant}': {leaked[:1]}")

            retrieved_ids = [r.get("doc_id") for r in results]
            truth = ticket["ground_truth"]
            for k in k_values:
                if truth.intersection(retrieved_ids[:k]):
                    hits[k] += 1

            if not truth.intersection(retrieved_ids[:max_k]):
                failures.append({
                    "ticket_id": ticket.get("ticket_id"),
                    "tenant": tenant,
                    "query": ticket["customer_query"],
                    "ground_truth": sorted(truth),
                    "retrieved": [
                        {"doc_id": r.get("doc_id"), "section": r.get("section"), "score": r.get("score")}
                        for r in results
                    ],
                })

        n = len(sample)
        rows.append({
            "tenant": tenant,
            "n": n,
            **{k: hits[k] / n if n else 0.0 for k in k_values},
            "latency": sum(latencies) / n if n else 0.0,
        })
        for k in k_values:
            all_hits[k] += hits[k]
        all_count += n
        all_latency += sum(latencies)

    if len(rows) > 1:
        rows.append({
            "tenant": "OVERALL",
            "n": all_count,
            **{k: all_hits[k] / all_count if all_count else 0.0 for k in k_values},
            "latency": all_latency / all_count if all_count else 0.0,
        })

    # Report table
    header = f"{'Tenant':<18}{'Samples':>9}" + "".join(f"{'Recall@' + str(k):>11}" for k in k_values) + f"{'Avg ms':>10}"
    print()
    print(header)
    print("-" * len(header))
    for row in rows:
        if row["tenant"] == "OVERALL":
            print("-" * len(header))
        line = f"{row['tenant']:<18}{row['n']:>9}" + "".join(f"{row[k]:>11.3f}" for k in k_values)
        print(line + f"{row['latency']:>10.1f}")

    # Failure log
    print(f"\n{len(failures)} queries had no relevant chunk in the top {max_k}.")
    if failures:
        out_path = Path(args.failures_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for failure in failures:
                f.write(json.dumps(failure) + "\n")
        print(f"Failure cases written to {out_path}")
        for failure in failures[:5]:
            got = ", ".join(r["doc_id"] for r in failure["retrieved"]) or "(none)"
            print(f"  [{failure['tenant']}] {failure['query'][:80]!r}")
            print(f"      expected: {', '.join(failure['ground_truth'])} | got: {got}")


if __name__ == "__main__":
    main()
