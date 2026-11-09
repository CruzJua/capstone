"""Audit held-out text leakage without changing training data or calling models.

Example, from the repository root:
    uv run python scripts/check_heldout_leakage.py --output /tmp/heldout_leakage_check.json
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.heldout_leakage import check_heldout_leakage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train-csv", type=Path, default=ROOT / "data/cleaned/hardneg_v1/train_tickets.csv")
    parser.add_argument("--benchmark", type=Path, default=ROOT / "data/evaluation/held_out_benchmark.json")
    parser.add_argument("--tenant-dir", type=Path, default=ROOT / "data/harbor_view")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Refusing to overwrite an existing output file.")
    report = check_heldout_leakage(args.train_csv, args.benchmark, args.tenant_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=4, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "inputs" and k != "limitations"},
                     indent=4, ensure_ascii=False)[:5000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
