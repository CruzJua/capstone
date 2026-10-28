"""Read-only training artifact summarizer and experiment inventory generator.

Accepts explicitly supplied run directories or search paths.
Inspects configurations, trial counts, successful/failed trials, selected checkpoints,
losses, and available artifact paths.

Strict classification rules:
- Distinguishes: smoke tests, short hyperparameter trials, full runs, resumed runs, and updated-dataset iterations.
- Never counts periodic checkpoints (checkpoint-*) as independent fine-tuning experiments.
- Never counts quantization formats (Q4_K_M GGUF, FP16) as independent fine-tuning experiments.
- Never counts retries or resumed attempts (attempt_02) as independent fine-tuning experiments.
- Never infers completed runs from search code alone; unexecuted or pending runs are marked as pending.
"""

import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))


from src.evaluation.training_inventory import inspect_single_run_directory, summarize_runs, format_markdown_report


def main():
    parser = argparse.ArgumentParser(
        description="Summarize fine-tuning training runs and audit experiment inventory."
    )
    parser.add_argument(
        "run_dirs",
        nargs="*",
        default=[],
        help="Explicit run directories or parent directories to inspect",
    )
    parser.add_argument(
        "--runs-dir",
        default="",
        help="Optional directory containing run folders (e.g. Capstone_Models)",
    )
    parser.add_argument(
        "--no-pending",
        action="store_true",
        help="Compatibility option; remote runs are never inferred",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="Path to export machine-readable JSON inventory",
    )
    parser.add_argument(
        "--markdown-out",
        default="",
        help="Path to export markdown inventory report",
    )
    args = parser.parse_args()

    dirs_to_check = list(args.run_dirs)
    if args.runs_dir:
        dirs_to_check.append(args.runs_dir)

    inventory = summarize_runs(dirs_to_check, include_pending=not args.no_pending)
    md_report = format_markdown_report(inventory)

    print(md_report)

    if args.json_out:
        out_p = Path(args.json_out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(inventory, indent=4) + "\n", encoding="utf-8")
        print(f"\nSaved machine-readable JSON inventory to: {out_p}")

    if args.markdown_out:
        out_md = Path(args.markdown_out)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(md_report + "\n", encoding="utf-8")
        print(f"Saved Markdown inventory to: {out_md}")


if __name__ == "__main__":
    main()
