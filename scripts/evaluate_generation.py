"""Evaluate generation decisions, schema validity and speed on a frozen benchmark."""

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.evaluation.generation import (
    load_benchmark, build_ground_truth_context, initialize_services,
    run_evaluation_loop, calculate_metrics, print_scorecard, save_evaluation_log,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run evaluation harness on held-out benchmark to measure hallucination rate and escalation accuracy."
    )
    # Model configuration
    parser.add_argument(
        "--model",
        default=None,
        help="Ollama model to evaluate (default: $OLLAMA_MODEL or llama3.2:3b)",
    )
    parser.add_argument(
        "--benchmark-file",
        default=str(project_root / "data/evaluation/held_out_benchmark.json"),
        help="Path to frozen held-out benchmark test set",
    )
    # Context source mode:
    # Default (isolated mode): uses ground-truth document quotes from evidence_json to measure PURE generation.
    # Flag --use-retriever: connects end-to-end RAG retrieval pipeline from MongoDB Atlas.
    parser.add_argument(
        "--use-retriever",
        action="store_true",
        help="Use live RAGRetriever from MongoDB Atlas instead of ground-truth evidence quotes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of evaluation questions (useful for a quick smoke test)",
    )
    parser.add_argument(
        "--output-log",
        default=None,
        help="Custom path to save full evaluation result log (defaults to logs/generation_eval_<timestamp>.json)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    metadata, questions = load_benchmark(Path(args.benchmark_file), args.limit)
    print(f"Loaded {len(questions)} questions for {metadata.get('held_out_tenant', 'unknown tenant')}.")
    print("Context mode: " + ("live retrieval" if args.use_retriever else "ground-truth evidence"))
    client, retriever = initialize_services(args.model, args.use_retriever)
    try:
        counts, records, latencies, speeds = run_evaluation_loop(
            client, retriever, questions, args.use_retriever
        )
        metrics = calculate_metrics(counts, latencies, speeds)
        metrics["benchmark_metadata"] = metadata
        metrics["benchmark_file"] = str(Path(args.benchmark_file).resolve())
        metrics["context_mode"] = "retriever" if args.use_retriever else "ground_truth"
        print_scorecard(metrics, client.model, counts["total_eval"])
        save_evaluation_log(metrics, records, client.model, args.output_log)
    finally:
        if retriever is not None:
            retriever.client.close()


if __name__ == "__main__":
    main()
