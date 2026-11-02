"""Repair deterministic judge contradictions offline, preserving all originals.

No model calls are made. --prepare-retries writes small generation subsets and
explicit commands for independently judging unresolved records. Re-run with a
new --output-dir and --retry-result after those commands finish to merge scores.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation.adjudication import prepare_retry_plan, write_repair_bundle
from src.evaluation.judge import JudgeError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judged-dir", type=Path, default=Path("logs/sprint3_audit_20261026/judged"))
    parser.add_argument("--input", type=Path, action="append", help="Explicit original judged file; repeatable")
    parser.add_argument("--output-dir", type=Path, required=True, help="New artifact directory; existing differing files are never overwritten")
    parser.add_argument("--prepare-retries", action="store_true", help="Write unresolved-only subsets and commands; does not execute them")
    parser.add_argument("--retry-result", type=Path, action="append", default=[], help="Fresh targeted judged result to verify and merge; repeatable")
    args = parser.parse_args()
    paths = args.input or sorted(args.judged_dir.glob("*.json"))
    if not paths:
        parser.error("No original judged files found")
    try:
        if args.prepare_retries:
            plan = prepare_retry_plan(paths, args.output_dir)
            print(f"Prepared {plan['total_records']} unresolved records; model calls made: 0")
        manifest = write_repair_bundle(paths, args.output_dir, args.retry_result)
    except (ValueError, KeyError, OSError, JudgeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    overall = manifest["summary"]["overall"]
    print(json.dumps({
        "manifest": str((args.output_dir / "repair_manifest.json").resolve()),
        "mechanically_corrected_decisions": manifest["mechanically_corrected_decisions"],
        "fresh_semantic_judgments": manifest["fresh_semantic_judgments"],
        "judged": overall["judged"], "unresolved": overall["unresolved_records"],
        "passed": overall["passed"], "all_record_denominator": overall["records"],
        "limitations": manifest["limitations"],
    }, indent=4))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
