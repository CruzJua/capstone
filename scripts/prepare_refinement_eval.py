"""Create disjoint development fixtures without changing training data or calling APIs."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.refinement_dataset import prepare_refinement_datasets, save_refinement_datasets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/cleaned/train_tickets.csv")
    parser.add_argument("--dev-output", type=Path, default=ROOT / "data/evaluation/refinement_dev.json")
    parser.add_argument("--validation-output", type=Path,
                        default=ROOT / "data/evaluation/refinement_validation.json")
    parser.add_argument("--seed", type=int, default=390)
    args = parser.parse_args()
    payloads = prepare_refinement_datasets(args.source, args.seed)
    save_refinement_datasets(payloads, args.dev_output, args.validation_output, args.source)
    print(json.dumps({split: {"path": str(path), "questions": payloads[split]["metadata"]["total_questions"],
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                      for split, path in (("dev", args.dev_output), ("validation", args.validation_output))},
                     indent=4))


if __name__ == "__main__":
    main()
