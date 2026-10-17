"""
Synthetic Support Ticket Data Cleaner (PRO390 Capstone)

This script loads the raw Gemini batch output from results.jsonl (or multiple files),
validates data format using Pydantic models from business_data_generator.py,
executes the data cleaning pipeline established in notebooks/eda.ipynb:
    1. Strips leading/trailing whitespaces across all text columns.
    2. Drops null or blank customer queries and answers.
    3. Deduplicates customer queries or full conversation threads.
    4. Exports the cleaned dataset to a user-specified CSV (and optionally JSONL)
        for immediate loading into a pandas DataFrame.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# Ensure scripts directory and workspace root are in python search path
CURRENT_DIR = Path(__file__).resolve().parent
ROOT = CURRENT_DIR.parent

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reuse Pydantic models from data generator for schema validation
try:
    from business_data_generator import Evidence, Message, Ticket
except ImportError:
    from scripts.business_data_generator import Evidence, Message, Ticket

DEFAULT_INPUT_FILE = ROOT / "data" / "generated" / "run_v1" / "results.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "cleaned"
DEFAULT_OUTPUT_CSV = DEFAULT_OUTPUT_DIR / "cleaned_tickets.csv"


def extract_tickets_from_raw_text(text: str) -> list[dict[str, Any]]:
    """Clean markdown code fencing if present and parse the inner JSON string."""
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    data = json.loads(cleaned)
    if isinstance(data, dict):
        return data.get("tickets", [])
    elif isinstance(data, list):
        return data
    return []


def validate_ticket_with_pydantic(
    raw_dict: dict[str, Any], strict: bool = False
) -> Ticket | None:
    """Validate a raw ticket dictionary against the Pydantic Ticket model."""
    try:
        return Ticket.model_validate(raw_dict)
    except Exception as e:
        if strict:
            raise ValueError(f"Ticket failed Pydantic validation: {e}") from e
        return None


def resolve_input_paths(file_inputs: list[str | Path]) -> list[Path]:
    """Resolve single or multiple file paths, directories, and glob patterns."""
    resolved: list[Path] = []
    for item in file_inputs:
        path = Path(item)
        if path.is_file():
            resolved.append(path)
        elif path.is_dir():
            found = list(path.glob("**/results.jsonl"))
            if found:
                resolved.extend(found)
            else:
                found_all = list(path.glob("*.jsonl"))
                resolved.extend(found_all)
        elif "*" in str(item):
            # Glob pattern
            base = ROOT if not path.is_absolute() else Path("/")
            matched = list(base.glob(str(item)))
            resolved.extend([m for m in matched if m.is_file()])
        else:
            if path.exists():
                resolved.append(path)

    unique_paths = sorted(list(set(resolved)))
    if not unique_paths:
        raise FileNotFoundError(f"No valid input JSONL files found matching: {file_inputs}")
    return unique_paths


def load_results_to_dataframe(
    file_path: Path | str | list[Path | str] = DEFAULT_INPUT_FILE,
    validate_schema: bool = True,
    strict_schema: bool = False,
) -> pd.DataFrame:
    """
    Read results.jsonl (one or more files), validate tickets against Pydantic,
    and return an unrolled pandas DataFrame where each row represents one ticket.
    """
    if isinstance(file_path, (str, Path)):
        paths = resolve_input_paths([file_path])
    else:
        paths = resolve_input_paths(file_path)

    records: list[dict[str, Any]] = []
    total_parse_errors = 0
    total_schema_errors = 0

    for path in paths:
        with open(path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, start=1):
                line_str = line.strip()
                if not line_str:
                    continue

                try:
                    raw = json.loads(line_str)
                    batch_key = raw.get("key", f"{path.stem}_{line_idx}")
                    business_name = (
                        batch_key.split("-")[0] if "-" in batch_key else path.stem
                    )

                    candidates = raw.get("response", {}).get("candidates", [])
                    if not candidates:
                        total_parse_errors += 1
                        continue

                    parts = candidates[0].get("content", {}).get("parts", [])
                    if not parts or "text" not in parts[0]:
                        total_parse_errors += 1
                        continue

                    raw_text = parts[0]["text"]
                    tickets_raw = extract_tickets_from_raw_text(raw_text)

                    for t_idx, t_dict in enumerate(tickets_raw):
                        if validate_schema:
                            ticket_obj = validate_ticket_with_pydantic(
                                t_dict, strict=strict_schema
                            )
                            if ticket_obj is None:
                                total_schema_errors += 1
                                continue
                            t_data = ticket_obj.model_dump()
                        else:
                            t_data = t_dict

                        msgs = t_data.get("messages", [])
                        customer_msgs = [
                            m.get("content", "")
                            for m in msgs
                            if m.get("role") == "customer"
                        ]
                        latest_customer_query = (
                            customer_msgs[-1] if customer_msgs else ""
                        )

                        record = {
                            "ticket_id": f"{batch_key}_t{t_idx}",
                            "batch_key": batch_key,
                            "business": business_name,
                            "interaction_type": t_data.get("interaction_type"),
                            "category": t_data.get("category"),
                            "action": t_data.get("action"),
                            "is_answerable": t_data.get("is_answerable"),
                            "escalation_reason": t_data.get("escalation_reason"),
                            "confidence": t_data.get("confidence"),
                            "customer_query": latest_customer_query,
                            "answer": t_data.get("answer"),
                            "rationale": t_data.get("rationale"),
                            "ticket_summary": t_data.get("ticket_summary"),
                            "num_messages": len(msgs),
                            "messages_json": json.dumps(msgs, ensure_ascii=False),
                            "evidence_json": json.dumps(
                                t_data.get("evidence", []), ensure_ascii=False
                            ),
                        }
                        records.append(record)

                except Exception as e:
                    total_parse_errors += 1
                    if total_parse_errors <= 3:
                        print(
                            f"[Warning] Failed parsing line {line_idx} in {path.name}: {e}",
                            file=sys.stderr,
                        )

    if total_parse_errors > 0 or total_schema_errors > 0:
        print(
            f"[Info] Parse errors: {total_parse_errors} | Pydantic schema rejections: {total_schema_errors}",
            file=sys.stderr,
        )

    return pd.DataFrame(records)


def clean_dataset(
    df_raw: pd.DataFrame,
    dedupe_by: str = "query",
    dedupe_keep: str = "first",
    min_confidence: float | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """
    Execute the cleaning pipeline:
        1. Strip whitespace on all string columns.
        2. Filter out null/empty queries and answers.
        3. Filter out confidence below min_confidence (if specified).
        4. Deduplicate tickets based on customer_query or messages_json.

    Returns the cleaned DataFrame and a dictionary of filtering statistics.
    """
    stats: dict[str, int] = {"initial_rows": len(df_raw)}
    df = df_raw.copy()

    # Step 1: Strip whitespace across text columns
    text_cols = [
        "customer_query",
        "answer",
        "rationale",
        "ticket_summary",
        "category",
        "business",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Step 2: Remove null / empty customer queries
    empty_queries = df[df["customer_query"].str.len() == 0]
    stats["empty_queries_dropped"] = len(empty_queries)
    df = df[df["customer_query"].str.len() > 0]

    # Step 3: Remove null / empty answers
    empty_answers = df[df["answer"].str.len() == 0]
    stats["empty_answers_dropped"] = len(empty_answers)
    df = df[df["answer"].str.len() > 0]

    # Step 4: Optional confidence threshold filter
    if min_confidence is not None and min_confidence > 0:
        low_conf = df[df["confidence"] < min_confidence]
        stats["low_confidence_dropped"] = len(low_conf)
        df = df[df["confidence"] >= min_confidence]
    else:
        stats["low_confidence_dropped"] = 0

    # Step 5: Deduplication
    if dedupe_by == "query":
        dupes = df[df.duplicated(subset=["customer_query"], keep=dedupe_keep)]
        stats["duplicates_dropped"] = len(dupes)
        df = df.drop_duplicates(subset=["customer_query"], keep=dedupe_keep)
    elif dedupe_by == "dialogue":
        dupes = df[df.duplicated(subset=["messages_json"], keep=dedupe_keep)]
        stats["duplicates_dropped"] = len(dupes)
        df = df.drop_duplicates(subset=["messages_json"], keep=dedupe_keep)
    elif dedupe_by == "none":
        stats["duplicates_dropped"] = 0
    else:
        raise ValueError(
            f"Invalid dedupe_by '{dedupe_by}'. Expected 'query', 'dialogue', or 'none'."
        )

    # Reset index
    df = df.reset_index(drop=True)
    stats["final_rows"] = len(df)
    stats["total_dropped"] = stats["initial_rows"] - stats["final_rows"]

    return df, stats


def export_dataset(
    df: pd.DataFrame,
    csv_path: Path,
    jsonl_path: Path | None = None,
) -> None:
    """Save cleaned DataFrame to CSV and optionally to JSONL."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False, encoding="utf-8")
    print(f"[Export] Saved {len(df):,} cleaned tickets to CSV: {csv_path}")

    if jsonl_path is not None:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        # Parse nested json strings back into objects for clean jsonl output
        records = df.to_dict(orient="records")
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for r in records:
                r_copy = dict(r)
                if isinstance(r_copy.get("messages_json"), str):
                    r_copy["messages"] = json.loads(r_copy.pop("messages_json"))
                if isinstance(r_copy.get("evidence_json"), str):
                    r_copy["evidence"] = json.loads(r_copy.pop("evidence_json"))
                f.write(json.dumps(r_copy, ensure_ascii=False) + "\n")
        print(f"[Export] Saved {len(df):,} cleaned tickets to JSONL: {jsonl_path}")


def print_summary_report(stats: dict[str, int], df_cleaned: pd.DataFrame) -> None:
    """Print an executive before-and-after cleaning summary."""
    print("\n" + "=" * 80)
    print(" DATA CLEANING PIPELINE SUMMARY")
    print("=" * 80)
    print(f" Initial Tickets Loaded : {stats['initial_rows']:,}")
    print(f" Empty Queries Dropped  : {stats['empty_queries_dropped']:,}")
    print(f" Empty Answers Dropped  : {stats['empty_answers_dropped']:,}")
    print(f" Low Confidence Dropped : {stats['low_confidence_dropped']:,}")
    print(f" Duplicates Dropped     : {stats['duplicates_dropped']:,}")
    print(f" Total Rows Removed     : {stats['total_dropped']:,}")
    print(f" Final Cleaned Tickets  : {stats['final_rows']:,}")
    print("-" * 80)

    print("\n--- Distribution by Interaction Type ---")
    type_counts = df_cleaned["interaction_type"].value_counts()
    for itype, count in type_counts.items():
        pct = (count / len(df_cleaned)) * 100
        print(f"  • {itype:<15}: {count:5,d} ({pct:5.1f}%)")

    print("\n--- Distribution by Action ---")
    action_counts = df_cleaned["action"].value_counts()
    for act, count in action_counts.items():
        pct = (count / len(df_cleaned)) * 100
        print(f"  • {act:<15}: {count:5,d} ({pct:5.1f}%)")

    if "business" in df_cleaned.columns and df_cleaned["business"].nunique() > 1:
        print("\n--- Tickets per Business ---")
        biz_counts = df_cleaned["business"].value_counts()
        for biz, count in biz_counts.items():
            pct = (count / len(df_cleaned)) * 100
            print(f"  • {biz:<22}: {count:5,d} ({pct:5.1f}%)")

    print("=" * 80 + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean synthetic customer support tickets and export to CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--files",
        "-f",
        nargs="+",
        default=[str(DEFAULT_INPUT_FILE)],
        help=(
            f"Input JSONL file(s), directory, or glob pattern "
            f"(default: {DEFAULT_INPUT_FILE})"
        ),
    )
    parser.add_argument(
        "--output-csv",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help=f"Destination path for cleaned CSV (default: {DEFAULT_OUTPUT_CSV})",
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=None,
        help="Optional destination path for cleaned JSONL format.",
    )
    parser.add_argument(
        "--dedupe-by",
        choices=["query", "dialogue", "none"],
        default="query",
        help=(
            "Deduplication mode: 'query' (dedupe identical customer questions), "
            "'dialogue' (dedupe identical message threads), or 'none' (default: query)"
        ),
    )
    parser.add_argument(
        "--dedupe-keep",
        choices=["first", "last"],
        default="first",
        help="Which duplicate instance to preserve: 'first' or 'last' (default: first)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="Optional minimum confidence score threshold (e.g. 0.5)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip Pydantic schema validation during ingestion (faster, less strict).",
    )
    parser.add_argument(
        "--strict-schema",
        action="store_true",
        help="Raise an error immediately if any ticket fails Pydantic validation.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress summary printout to console.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    print(f"Loading raw ticket data from: {args.files}...")
    df_raw = load_results_to_dataframe(
        file_path=args.files,
        validate_schema=not args.skip_validation,
        strict_schema=args.strict_schema,
    )

    print(f"Cleaning {len(df_raw):,} records (dedupe by: '{args.dedupe_by}')...")
    df_cleaned, stats = clean_dataset(
        df_raw,
        dedupe_by=args.dedupe_by,
        dedupe_keep=args.dedupe_keep,
        min_confidence=args.min_confidence,
    )

    if not args.quiet:
        print_summary_report(stats, df_cleaned)

    export_dataset(
        df_cleaned,
        csv_path=args.output_csv,
        jsonl_path=args.output_jsonl,
    )


if __name__ == "__main__":
    main()