"""Read-only evidence provenance audit of an existing training/development CSV.

Defaults to the original training CSV. Does not repair targets, regenerate data,
read the frozen benchmark, call a model, or connect to a database. Without
--output, prints only the summary and writes nothing.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.documents.provenance import audit_evidence_csv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=Path("data/cleaned/train_tickets.csv"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--tenant", action="append", help="Optional explicit tenant filter; repeatable")
    parser.add_argument("--include-verified", action="store_true", help="Include unflagged rows in the machine report")
    parser.add_argument("--output", type=Path, help="New JSON report outside the data directory; datasets are never overwritten")
    args = parser.parse_args()
    try:
        if args.output:
            output = args.output.resolve()
            if output == args.csv.resolve() or output.is_relative_to(args.data_root.resolve()):
                raise ValueError("Report output must be outside data-root and cannot replace the input CSV")
            if output.exists():
                raise ValueError("Report already exists; choose a new output path")
        report = audit_evidence_csv(args.csv, args.data_root,
                                   tenants=set(args.tenant) if args.tenant else None,
                                   include_verified=args.include_verified)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, indent=4, ensure_ascii=False, allow_nan=False)
                handle.write("\n")
        print(json.dumps({"input_csv": report["input_csv"], "input_sha256": report["input_sha256"],
                          "summary": report["summary"], "limitations": report["limitations"],
                          "report_path": str(args.output.resolve()) if args.output else None}, indent=4))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
