"""Compare generation evaluation logs, compute teacher recovery, and format scorecards.

Reads generation evaluation logs (and optional independent judge logs), checks for benchmark
and context compatibility, computes latency percentiles, estimates token costs per 1k queries,
and formats comprehensive comparison tables in Markdown, terminal text, or JSON.

Usage Examples:
    # Compare existing logs in text format:
    python scripts/compare_evaluations.py logs/generation_eval_*.json

    # Compare logs with markdown output saved to a file:
    python scripts/compare_evaluations.py --logs logs/baselines/*.json --format markdown --output evaluation/comparison_report.md

    # Include independent judge logs:
    python scripts/compare_evaluations.py --logs logs/generation_eval_X.json logs/generation_eval_Y.json \\
        --judged-logs logs/judged/judged_X.json logs/judged/judged_Y.json

    # Require strict benchmark and coverage compatibility:
    python scripts/compare_evaluations.py logs/baselines/*.json --require-compatible
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.comparison import (
    ComparisonReport,
    ModelPricing,
    compute_file_sha256,
    compare_evaluations,
    format_comparison_markdown,
    format_comparison_text,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "log_files",
        nargs="*",
        default=[],
        help="Positional generation evaluation log files to compare",
    )
    parser.add_argument(
        "--logs",
        nargs="+",
        default=[],
        help="Evaluation log files or glob patterns (e.g. --logs logs/baselines/*.json)",
    )
    parser.add_argument(
        "--judged-logs",
        nargs="+",
        default=[],
        help="Optional independent judge logs corresponding to the generation logs",
    )
    parser.add_argument(
        "--base-model",
        default=None,
        help="Base student model name for gap-closed calculation (default: auto-detected base student)",
    )
    parser.add_argument(
        "--teacher-model",
        default=None,
        help="Teacher model name for recovery calculations (default: auto-detected teacher)",
    )
    parser.add_argument(
        "--pricing-file",
        default=None,
        help="JSON file with custom pricing catalog mapping model names to pricing structures",
    )
    parser.add_argument(
        "--format",
        choices=["text", "markdown", "json", "all"],
        default="all",
        help="Output display/report format (default: all)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="File path to save the generated report (markdown or json based on format)",
    )
    parser.add_argument(
        "--require-compatible",
        action="store_true",
        help="Fail with an error code if evaluation logs have compatibility mismatches",
    )
    return parser.parse_args()


def resolve_file_paths(patterns: List[str]) -> List[Path]:
    """Expands list of files and glob patterns into sorted unique Path objects."""
    found: set[Path] = set()
    for item in patterns:
        path = Path(item)
        if path.is_file():
            found.add(path.resolve())
        else:
            # Try glob
            matched = glob.glob(item, recursive=True)
            for m in matched:
                p = Path(m)
                if p.is_file():
                    found.add(p.resolve())
    return sorted(found)


def load_pricing_catalog(path_str: Optional[str]) -> Optional[Dict[str, ModelPricing]]:
    if not path_str:
        return None
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Pricing file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    catalog = {}
    for key, val in raw.items():
        if isinstance(val, dict):
            import math
            for field in ("prompt_cost_per_million", "completion_cost_per_million"):
                if field not in val or not math.isfinite(float(val[field])) or float(val[field]) < 0:
                    raise ValueError(f"{key}: supply a finite nonnegative {field}")
            if not val.get("pricing_source") or not val.get("pricing_date"):
                raise ValueError(f"{key}: pricing_source and pricing_date are required")
            catalog[key] = ModelPricing(
                model_name=key,
                prompt_cost_per_million=float(val["prompt_cost_per_million"]),
                completion_cost_per_million=float(val["completion_cost_per_million"]),
                pricing_source=val.get("pricing_source", "Custom configuration file"),
                pricing_date=val.get("pricing_date", "Custom"),
                is_local=bool(val.get("is_local", False)),
            )
    return catalog


def main() -> int:
    args = parse_args()

    # Collect input files
    raw_inputs = list(args.log_files) + list(args.logs)
    resolved_logs = resolve_file_paths(raw_inputs)

    if not resolved_logs:
        print("Error: No evaluation log files provided or found.", file=sys.stderr)
        print("Provide paths via arguments: python scripts/compare_evaluations.py logs/*.json", file=sys.stderr)
        return 1

    # Load generation logs
    loaded_logs: List[Dict[str, Any]] = []
    valid_log_paths: List[Path] = []
    for p in resolved_logs:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "records" in data:
                loaded_logs.append(data)
                valid_log_paths.append(p)
            else:
                print(f"Warning: Skipping {p} (does not appear to be a valid evaluation log).", file=sys.stderr)
        except Exception as exc:
            print(f"Warning: Could not read {p}: {exc}", file=sys.stderr)

    if not loaded_logs:
        print("Error: None of the provided files were valid evaluation logs.", file=sys.stderr)
        return 1

    # Load judged logs if provided
    judged_payloads: List[Optional[Dict[str, Any]]] = [None] * len(loaded_logs)
    if args.judged_logs:
        resolved_judged = resolve_file_paths(args.judged_logs)
        loaded_judged_list = []
        for jp in resolved_judged:
            try:
                j_data = json.loads(jp.read_text(encoding="utf-8"))
                loaded_judged_list.append(j_data)
            except Exception:
                pass

        # Match judged logs to generation logs via source sha256 or source path
        for i, (g_log, g_path) in enumerate(zip(loaded_logs, valid_log_paths)):
            g_path_str = str(g_path.resolve())
            for j_data in loaded_judged_list:
                src = j_data.get("source", {})
                if src.get("sha256") == compute_file_sha256(g_path):
                    judged_payloads[i] = j_data
                    break

    pricing_catalog = load_pricing_catalog(args.pricing_file)

    report = compare_evaluations(
        logs=loaded_logs,
        log_paths=valid_log_paths,
        judged_payloads=judged_payloads,
        pricing_catalog=pricing_catalog,
        base_model_name=args.base_model,
        teacher_model_name=args.teacher_model,
    )

    if args.require_compatible and not report.compatibility.is_compatible:
        print("Error: Compatibility check failed and --require-compatible was set.", file=sys.stderr)
        for issue in report.compatibility.issues:
            if issue.severity == "ERROR":
                print(f"  - [{issue.category}] {issue.message}", file=sys.stderr)
        return 2

    # Render output formats
    text_table = format_comparison_text(report)
    md_table = format_comparison_markdown(report)

    if args.format in ("text", "all"):
        print(text_table)

    if args.format == "markdown":
        print(md_table)

    if args.format == "json":
        # Convert report to json
        serializable = {
            "generated_at": report.generated_at,
            "is_compatible": report.compatibility.is_compatible,
            "compatibility_issues": [issue.__dict__ for issue in report.compatibility.issues],
            "summaries": [asdict(s) for s in report.summaries],
            "teacher_recoveries": [r.__dict__ for r in report.teacher_recoveries],
            "notes": report.notes,
        }
        print(json.dumps(serializable, indent=4, default=str))

    # Save to file if requested
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if args.format == "json" or out_path.suffix == ".json":
            serializable = {
                "generated_at": report.generated_at,
                "is_compatible": report.compatibility.is_compatible,
                "compatibility_issues": [issue.__dict__ for issue in report.compatibility.issues],
                "summaries": [asdict(s) for s in report.summaries],
                "teacher_recoveries": [r.__dict__ for r in report.teacher_recoveries],
                "notes": report.notes,
            }
            out_path.write_text(json.dumps(serializable, indent=4, default=str) + "\n", encoding="utf-8")
        else:
            out_path.write_text(md_table + "\n", encoding="utf-8")
        print(f"\nReport written to: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
