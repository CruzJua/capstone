"""Read-only synthetic training-data integrity audit; never trains or rewrites data."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.training_data_audit import audit_training_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/cleaned/train_tickets.csv")
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--held-out-tenant", default="harbor_view")
    parser.add_argument("--split-manifest", type=Path)
    parser.add_argument("--screening-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Avoid accidental replacement of an input via the output argument.
    output = args.output.resolve()
    protected = [args.input.resolve(), *(p.resolve() for p in (args.split_manifest,) if p)]
    for root in (args.data_root, args.screening_root):
        if root and (output == root.resolve() or root.resolve() in output.parents):
            parser.error("Output must be outside source data/screening directories.")
    if output in protected:
        parser.error("Output cannot overwrite an input.")
    report = audit_training_data(args.input, args.data_root, args.held_out_tenant,
                                 args.split_manifest, args.screening_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "rows": report["audit"]["rows"],
                      "error_counts": report["audit"]["error_counts"],
                      "review_signal_counts": report["audit"]["review_signal_counts"],
                      "quote_counts": report["audit"]["evidence_quote_counts"],
                      "input_preservation": report["input_preservation"]}, indent=4))
    return 1 if report["audit"]["confirmed_structural_errors"] or report.get("split_audit", {}).get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
