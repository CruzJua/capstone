"""Compute hallucination rates (answer present vs absent) from judged-result files.

Reads existing judged logs only: no model, benchmark run, or API call is made.

Example:
    uv run python scripts/compute_hallucination_rate.py logs/judged/*gpt-5.4-mini*.json --format markdown
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.hallucination import (
    build_review_rows, compute_for_files, compute_recovery, format_markdown, load_generation_records,
    load_judged_state, paired_pass_comparison, summarize_review_labels, write_review_csv,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("judged_files", nargs="*", help="Judged-result JSON files (read only).")
    parser.add_argument("--review-csv", type=Path, metavar="OUT.csv",
                        help="Write a human-review sheet of every answered answer-absent question from the given "
                             "judged files (labels left empty; refuses to overwrite an existing file).")
    parser.add_argument("--summarize-review", type=Path, metavar="LABELLED.csv",
                        help="Compute fabrication rates from a human-labelled review sheet and exit.")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--text-signals", action="store_true",
                        help="Also compute regex text signals (answer says information is missing / hands off; "
                             "flagged claims about the handoff). Reads each generation log, verified by sha256.")
    parser.add_argument("--recovery", nargs=3, metavar=("STUDENT", "BASE", "TEACHER"), type=Path,
                        help="Standard recovery (student - base) / (teacher - base) from three judged files "
                             "of one context mode, then exit.")
    parser.add_argument("--paired", nargs=2, metavar=("A", "B"), type=Path,
                        help="Question-by-question strict-pass comparison of two judged files, then exit.")
    args = parser.parse_args()
    if args.recovery:
        print(json.dumps(compute_recovery(*(load_judged_state(p) for p in args.recovery)), indent=4))
        return 0
    if args.paired:
        print(json.dumps(paired_pass_comparison(*(load_judged_state(p) for p in args.paired)), indent=4))
        return 0
    if args.summarize_review:
        print(json.dumps(summarize_review_labels(args.summarize_review), indent=4))
        return 0
    if not args.judged_files:
        parser.error("Provide judged files (or --summarize-review).")
    if args.review_csv:
        rows = []
        for path in args.judged_files:
            state = load_judged_state(path)
            rows += build_review_rows(state, load_generation_records(state))
        write_review_csv(args.review_csv, rows)
        print(f"Wrote {len(rows)} rows to {args.review_csv}")
        return 0
    results = compute_for_files(args.judged_files, with_text_signals=args.text_signals)
    if args.format == "json":
        print(json.dumps(results, indent=4, ensure_ascii=False))
    else:
        print(format_markdown(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
