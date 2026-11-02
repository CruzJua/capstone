"""Prepare a balanced held-out benchmark and a tenant-isolated training CSV."""

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.evaluation.dataset import (
    load_and_filter_data, sample_balanced_benchmark, save_artifacts
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Prepare a balanced held-out benchmark test set for hallucination and escalation evaluation."
    )
    parser.add_argument(
        "--tenant",
        default="harbor_view",
        help="Business to hold out for evaluation (default: harbor_view)",
    )
    parser.add_argument(
        "--samples-per-class",
        type=int,
        default=50,
        help="Number of answerable and unanswerable tickets each to sample (default: 50 each = 100 total)",
    )
    parser.add_argument(
        "--dataset",
        default=str(project_root / "data/cleaned/cleaned_tickets.csv"),
        help="Path to full cleaned dataset",
    )
    parser.add_argument(
        "--output-benchmark",
        default=str(project_root / "data/evaluation/held_out_benchmark.json"),
        help="Path where the frozen evaluation test set will be saved",
    )
    parser.add_argument(
        "--output-train",
        default=str(project_root / "data/cleaned/train_tickets.csv"),
        help="Path to export the training dataset strictly excluding the held-out tenant",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    dataset_path = Path(args.dataset)
    benchmark_path = Path(args.output_benchmark)
    train_path = Path(args.output_train)
    if dataset_path.resolve() in {benchmark_path.resolve(), train_path.resolve()}:
        raise ValueError("Output paths must not overwrite the source dataset.")
    answerable, unanswerable, remaining = load_and_filter_data(dataset_path, args.tenant)
    payload = sample_balanced_benchmark(answerable, unanswerable, args.samples_per_class, args.seed)
    save_artifacts(payload, remaining, benchmark_path, train_path)
    print(f"Benchmark ready for evaluate_generation.py: {len(payload['questions'])} questions "
          f"from {args.tenant}; tenant excluded from training.")


if __name__ == "__main__":
    main()
