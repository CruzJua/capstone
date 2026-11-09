"""Offline exact-text and n-gram leakage checks against a held-out tenant.

Reads existing training data, benchmark and tenant source documents without mutation.
Exact matching cannot rule out paraphrases or establish the remote training input.
"""

import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NGRAM = 6
MIN_PASSAGE_WORDS = 8


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).casefold()).split())


def shingles(words: list[str]) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + NGRAM]) for i in range(len(words) - NGRAM + 1)}


def overlap(text: str, train_shingles: set, train_text: str) -> dict:
    norm = normalize(text)
    words = norm.split()
    grams = shingles(words)
    shared = sum(gram in train_shingles for gram in grams)
    return {
        "words": len(words),
        "exact_substring": bool(norm) and norm in train_text,
        "ngram_overlap": round(shared / len(grams), 4) if grams else None,
    }


def flatten_json_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in flatten_json_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in flatten_json_strings(v)]
    return []


def source_passages(tenant_dir: Path) -> list[str]:
    passages: list[str] = []
    for path in sorted(tenant_dir.iterdir()):
        if path.suffix == ".json":
            passages += flatten_json_strings(json.loads(path.read_text(encoding="utf-8")))
        elif path.suffix == ".md":
            passages += [p for p in re.split(r"\n\s*\n|\n", path.read_text(encoding="utf-8"))]
    return [p for p in passages if len(normalize(p).split()) >= MIN_PASSAGE_WORDS]


def summarize(items: list[dict], key: str) -> dict:
    flagged_exact = [i for i in items if i["exact_substring"]]
    scored = [i["ngram_overlap"] for i in items if i["ngram_overlap"] is not None]
    return {
        "checked": len(items),
        "exact_substring_matches": len(flagged_exact),
        "max_ngram_overlap": max(scored) if scored else None,
        "with_ngram_overlap_at_least_0.5": sum(s >= 0.5 for s in scored),
        "with_ngram_overlap_at_least_0.3": sum(s >= 0.3 for s in scored),
        "top_examples": [{key: i["text"][:160], "ngram_overlap": i["ngram_overlap"],
                          "exact_substring": i["exact_substring"]}
                         for i in sorted(items, key=lambda x: x["ngram_overlap"] or 0, reverse=True)[:5]],
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def check_heldout_leakage(train_csv: Path | str, benchmark_path: Path | str,
                          tenant_dir: Path | str) -> dict:
    """Return an audit report; no input or output files are modified.

    The benchmark metadata identifies the held-out tenant, falling back to the
    source-directory name. The prefix text scan is a review signal, not a verdict.
    """
    train_csv, benchmark_path, tenant_dir = map(Path, (train_csv, benchmark_path, tenant_dir))
    csv.field_size_limit(10 ** 9)
    with train_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    raw_text = "\n".join(" ".join(str(v) for v in row.values()) for row in rows)
    train_text = " " + normalize(raw_text) + " "
    train_shingles = shingles(train_text.split())

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    questions = benchmark["questions"]
    tenant = benchmark.get("metadata", {}).get("held_out_tenant") or tenant_dir.name
    search_word = tenant.split("_")[0]
    quotes = [item["quote"] for q in questions for item in (json.loads(q["evidence_json"]) if isinstance(q.get("evidence_json"), str) else (q.get("evidence_json") or []))
              if isinstance(item, dict) and item.get("quote")]
    passages = source_passages(tenant_dir)

    def score(texts: list[str]) -> list[dict]:
        return [{"text": t, **overlap(t, train_shingles, train_text)} for t in texts]

    report = {
        "inputs": {
            "train_csv": _display_path(train_csv),
            "train_csv_sha256": hashlib.sha256(train_csv.read_bytes()).hexdigest(),
            "train_rows": len(rows),
            "benchmark_sha256": hashlib.sha256(benchmark_path.read_bytes()).hexdigest(),
            "ngram_size": NGRAM,
            "min_passage_words": MIN_PASSAGE_WORDS,
        },
        "tenant_check": {
            "business_values": sorted({row.get("business", "") for row in rows}),
            f"rows_with_business_{tenant}": sum(row.get("business") == tenant for row in rows),
            f"case_insensitive_{search_word}_occurrences_in_all_columns": len(re.findall(re.escape(search_word), raw_text, re.I)),
        },
        "benchmark_questions": summarize(score([q["customer_query"] for q in questions]), "question"),
        "benchmark_evidence_quotes": summarize(score(quotes), "quote"),
        f"{tenant}_source_passages": summarize(score(passages), "passage"),
        "limitations": [
            "Exact and 6-gram matching finds copied text, not paraphrases or topically similar content.",
            "Only the local training CSV is checked; whether the Kaggle job read exactly this file is not verifiable here.",
            "Common short phrases can produce small n-gram overlaps without any leakage.",
        ],
    }
    return report
