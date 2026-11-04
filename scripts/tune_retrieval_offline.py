"""Compare retrieval configurations and sweep the reranker cutoff with no network connection.

Builds an in-memory index from data/<tenant>/ (cached embedding model, no Atlas), then:
  1. Compares baseline / BGE query prefix / prefix + cross-encoder reranker on answerable tickets.
  2. Sweeps MIN_RERANK_SCORE: how many answerable tickets keep their relevant evidence versus how many
     unanswerable tickets correctly receive no context (so the model can escalate).

The frozen held-out tenant is excluded by default so the cutoff is never chosen on benchmark data.
Models must already be in the local Hugging Face cache; set HF_HUB_OFFLINE=1 to enforce that.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src.evaluation.retrieval_metrics import (
    compute_evidence_coverage,
    compute_hit_rate,
    parse_ground_truth_docs,
    parse_ground_truth_evidence,
)
from src.rag.offline import build_offline_retriever

DEFAULT_RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"
TOP_K = 4


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(project_root / "data/cleaned/cleaned_tickets.csv"))
    parser.add_argument("--tenants-root", default=str(project_root / "data"))
    parser.add_argument("--exclude-tenants", nargs="*", default=["harbor_view"],
                        help="Tenants kept out of tuning (default: the held-out benchmark tenant)")
    parser.add_argument("--sample-size", type=int, default=60,
                        help="Answerable and unanswerable tickets per tenant (default: 60 each)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reranker", default=DEFAULT_RERANKER)
    parser.add_argument("--out", default=str(project_root / "logs/offline_retrieval_tuning.json"))
    return parser.parse_args()


def sample_tickets(dataset: Path, exclude: List[str], sample_size: int, seed: int) -> pd.DataFrame:
    df = pd.read_csv(dataset)
    df = df[~df["business"].isin(exclude)].copy()
    df["answerable"] = df["is_answerable"].astype(str).str.lower() == "true"
    df["ground_truth"] = df.apply(parse_ground_truth_docs, axis=1)
    df["ground_truth_evidence"] = df.apply(parse_ground_truth_evidence, axis=1)
    # Answerable tickets without a cited document cannot be scored for retrieval.
    df = df[~df["answerable"] | (df["ground_truth"].map(len) > 0)]
    parts = []
    for (_, answerable), group in df.groupby(["business", "answerable"]):
        parts.append(group.sample(n=min(sample_size, len(group)), random_state=seed))
    return pd.concat(parts).reset_index(drop=True)


def score_answerable(retriever, tickets: pd.DataFrame) -> Dict[str, Any]:
    hits, evidence = [], []
    for _, row in tickets.iterrows():
        chunks = retriever.retrieve(row["customer_query"], row["business"], top_k=TOP_K)
        hits.append(compute_hit_rate(row["ground_truth"], [c["doc_id"] for c in chunks], TOP_K))
        if row["ground_truth_evidence"]:
            coverage = compute_evidence_coverage(row["ground_truth_evidence"], chunks, TOP_K)
            evidence.append(coverage["evidence_hit_rate"])
    return {
        "queries": len(tickets),
        "hit_rate_at_4": round(float(np.mean(hits)), 4),
        "evidence_hit_rate_at_4": round(float(np.mean(evidence)), 4) if evidence else None,
    }


def best_scores(retriever, tickets: pd.DataFrame, key: str) -> np.ndarray:
    """Highest relevance score among the chunks a query would receive (reranker or vector similarity)."""
    values = []
    for _, row in tickets.iterrows():
        chunks = retriever.retrieve(row["customer_query"], row["business"], top_k=TOP_K)
        values.append(max((c.get(key, c.get("score", float("-inf"))) for c in chunks), default=float("-inf")))
    return np.asarray(values)


def sweep(answerable_scores: np.ndarray, unanswerable_scores: np.ndarray) -> List[Dict[str, float]]:
    pooled = np.concatenate([answerable_scores, unanswerable_scores])
    cutoffs = np.unique(np.quantile(pooled[np.isfinite(pooled)], np.linspace(0.02, 0.98, 25)))
    rows = []
    for cutoff in cutoffs:
        kept = float(np.mean(answerable_scores >= cutoff))
        rejected = float(np.mean(unanswerable_scores < cutoff))
        rows.append({
            "cutoff": round(float(cutoff), 3),
            "answerable_kept": round(kept, 3),
            "unanswerable_rejected": round(rejected, 3),
            "balanced_accuracy": round((kept + rejected) / 2, 3),
        })
    return rows


def main():
    args = parse_args()
    tickets = sample_tickets(Path(args.dataset), args.exclude_tenants, args.sample_size, args.seed)
    tenants = sorted(tickets["business"].unique())
    print(f"Tuning on {len(tickets)} tickets across {tenants} (excluded: {args.exclude_tenants})")

    retriever = build_offline_retriever(Path(args.tenants_root), tenants, query_prefix="")
    answerable = tickets[tickets["answerable"]]
    unanswerable = tickets[~tickets["answerable"]]
    print(f"{len(retriever.collection.documents)} chunks indexed; {len(answerable)} answerable, "
          f"{len(unanswerable)} unanswerable queries")

    results: Dict[str, Any] = {"tenants": tenants, "excluded_tenants": args.exclude_tenants, "seed": args.seed,
                               "reranker": args.reranker, "configurations": {}}

    results["configurations"]["baseline_no_prefix"] = score_answerable(retriever, answerable)
    retriever.query_prefix = "Represent this sentence for searching relevant passages: "
    results["configurations"]["bge_prefix"] = score_answerable(retriever, answerable)
    vector_sweep = sweep(best_scores(retriever, answerable, "score"), best_scores(retriever, unanswerable, "score"))

    retriever.reranker_model_name = args.reranker
    results["configurations"]["bge_prefix_plus_reranker"] = score_answerable(retriever, answerable)
    rerank_sweep = sweep(best_scores(retriever, answerable, "rerank_score"),
                         best_scores(retriever, unanswerable, "rerank_score"))

    results["cutoff_sweep"] = {"vector_similarity": vector_sweep, "reranker": rerank_sweep}
    results["best_reranker_cutoff_by_balanced_accuracy"] = max(rerank_sweep, key=lambda r: r["balanced_accuracy"])
    results["best_vector_cutoff_by_balanced_accuracy"] = max(vector_sweep, key=lambda r: r["balanced_accuracy"])

    for name, metrics in results["configurations"].items():
        print(f"{name:28s} {metrics}")
    print("best reranker cutoff:", results["best_reranker_cutoff_by_balanced_accuracy"])
    print("best vector cutoff:  ", results["best_vector_cutoff_by_balanced_accuracy"])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=4) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
