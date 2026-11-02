"""Offline, nonmutating integrity checks for synthetic training tickets.

Structural violations are errors; evidence-text mismatches are review signals.
Substring checks cannot certify answer correctness, entailment, or source quality.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def fingerprint(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def normalize_text(text: str) -> str:
    """Normalize presentation, preserving numbers, units, negation, and word order."""
    text = unicodedata.normalize("NFKC", text).translate(str.maketrans({
        "’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-",
    }))
    text = re.sub(r"\s+", " ", text.replace("*", "").replace("`", "")).strip().casefold()
    # Teachers sometimes include enclosing quotation marks in the quote field.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text


def _json_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False)] + [s for child in value.values() for s in _json_strings(child)]
    if isinstance(value, list):
        return [json.dumps(value, ensure_ascii=False)] + [s for child in value for s in _json_strings(child)]
    return []


def load_documents(data_root: Path, tenants: set[str]) -> tuple[dict, list[dict]]:
    """Read only direct tenant source documents; never generation_reference/docs."""
    catalog: dict[str, dict[str, dict]] = {}
    files = []
    for tenant in sorted(tenants):
        catalog[tenant] = {}
        for path in sorted((data_root / tenant).glob("*")):
            if not path.is_file() or path.suffix.lower() not in {".json", ".md"}:
                continue
            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw) if path.suffix == ".json" else None
            searchable = [raw] + (_json_strings(parsed) if parsed is not None else [])
            entry = {"path": str(path.resolve()), "text": raw,
                     "normalized": [normalize_text(s) for s in searchable]}
            catalog[tenant][path.name] = entry
            files.append(fingerprint(path))
            # FAQ entry IDs resolve only within their tenant, with an explicit alias.
            if isinstance(parsed, dict):
                for faq in parsed.get("faqs", []):
                    if isinstance(faq, dict) and isinstance(faq.get("id"), str):
                        catalog[tenant][faq["id"]] = {
                            "path": str(path.resolve()), "alias": path.name,
                            "text": json.dumps(faq, ensure_ascii=False),
                            "normalized": [normalize_text(s) for s in _json_strings(faq)],
                        }
    return catalog, files


def audit_rows(rows: list[dict], catalog: dict, held_out_tenant: str = "harbor_view") -> dict:
    errors, signals = [], []
    quote_counts: Counter = Counter()
    seen: dict[str, dict[str, list[str]]] = {key: defaultdict(list) for key in (
        "ticket_id", "customer_query", "messages_json")}

    def add(target: list, code: str, row: dict, **extra: Any) -> None:
        target.append({"code": code, "ticket_id": row.get("ticket_id"),
                       "business": row.get("business"), "customer_query": row.get("customer_query"),
                       "target_answer": row.get("answer"), "target_action": row.get("action"), **extra})

    for row in rows:
        for key in ("ticket_id", "batch_key", "business", "customer_query", "answer", "rationale"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                add(errors, "missing_required_text", row, field=key)
        tenant = row.get("business", "")
        if tenant.strip().casefold() == held_out_tenant.casefold():
            add(errors, "held_out_tenant_in_training", row)
        for key in seen:
            seen[key][normalize_text(row.get(key, ""))].append(row.get("ticket_id", ""))
        action = row.get("action")
        if action not in {"answer", "escalate"}:
            add(errors, "invalid_action", row)
        boolean = str(row.get("is_answerable", "")).strip().lower()
        answerable = {"true": True, "1": True, "false": False, "0": False}.get(boolean)
        if answerable is None:
            add(errors, "invalid_answerability", row)
        if answerable is False and action != "escalate":
            add(errors, "unanswerable_answer_target", row)
        try:
            confidence = float(row.get("confidence", ""))
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError()
        except (ValueError, TypeError):
            add(errors, "invalid_confidence", row)
        reason = row.get("escalation_reason")
        expected_reason = "none" if action == "answer" else (
            "docs_require_human" if answerable else "not_in_docs")
        if reason != expected_reason:
            add(errors, "action_reason_inconsistency", row, actual=reason, expected=expected_reason)
        try:
            messages = json.loads(row.get("messages_json", ""))
            if not isinstance(messages, list) or not messages or any(
                not isinstance(m, dict) or m.get("role") not in {"customer", "agent"}
                or not isinstance(m.get("content"), str) or not m["content"].strip() for m in messages
            ):
                raise ValueError()
            customer_messages = [m["content"] for m in messages if m["role"] == "customer"]
            if not customer_messages or customer_messages[-1].strip() != row.get("customer_query", "").strip():
                add(errors, "conversation_query_mismatch", row)
        except (ValueError, TypeError):
            add(errors, "invalid_messages_schema", row)
        try:
            evidence = json.loads(row.get("evidence_json", ""))
            if not isinstance(evidence, list) or any(
                not isinstance(e, dict) or any(not isinstance(e.get(k), str) or not e[k].strip()
                                              for k in ("source", "quote")) for e in evidence
            ):
                raise ValueError()
        except (ValueError, TypeError):
            add(errors, "invalid_evidence_schema", row)
            continue
        if answerable is True and not evidence:
            add(errors, "answer_present_without_evidence", row)
        if answerable is False and evidence:
            add(errors, "answer_absent_with_evidence", row)
        for index, item in enumerate(evidence):
            source, quote = item["source"], item["quote"]
            doc = catalog.get(tenant, {}).get(source)
            details = {"evidence_index": index, "source": source, "quote": quote}
            if doc is None:
                quote_counts["unknown_source"] += 1
                add(errors, "unknown_evidence_source", row, **details)
                continue
            if "alias" in doc:
                add(signals, "source_id_alias", row, canonical_source=doc["alias"], **details)
            normalized_quote = normalize_text(quote)
            if quote in doc["text"]:
                quote_counts["exact"] += 1
            elif any(normalized_quote in text for text in doc["normalized"]):
                quote_counts["presentation_normalized"] += 1
            else:
                quote_counts["not_found_in_cited_source"] += 1
                alternatives = sorted({entry.get("alias", name) for name, entry in catalog.get(tenant, {}).items()
                                       if name != source and any(normalized_quote in text for text in entry["normalized"])})
                add(signals, "quote_not_found_in_cited_source", row,
                    other_documents_with_normalized_quote=alternatives, **details)
    duplicates = []
    for field, groups in seen.items():
        for value, ids in groups.items():
            if value and len(ids) > 1:
                duplicates.append({"field": field, "ticket_ids": ids})
                if field in {"ticket_id", "customer_query"}:
                    errors.append({"code": "duplicate_" + field, "ticket_ids": ids})
    return {
        "rows": len(rows), "tenants": dict(sorted(Counter(r.get("business") for r in rows).items())),
        "actions": dict(Counter(r.get("action") for r in rows)),
        "confirmed_structural_errors": errors, "review_signals": signals,
        "error_counts": dict(Counter(e["code"] for e in errors)),
        "review_signal_counts": dict(Counter(e["code"] for e in signals)),
        "evidence_quote_counts": dict(quote_counts), "duplicate_groups": duplicates,
        "limitations": [
            "Quote mismatch is not proof of a false answer: presentation, paraphrase, truncation, and wrong source attribution need review.",
            "Exact source quotes do not certify that the target answer follows from them or that an escalation annotation is semantically correct.",
            "Answerable escalations are valid human-handoff examples; they are not automatically contradictions.",
        ],
    }


def audit_split(rows: list[dict], manifest: dict, data_sha256: str) -> dict:
    errors = []
    train, validation = manifest.get("train_ticket_ids", []), manifest.get("validation_ticket_ids", [])
    known = {row["ticket_id"]: row for row in rows}
    for field, ids in (("train", train), ("validation", validation)):
        if len(ids) != len(set(ids)):
            errors.append({"code": "duplicate_split_ids", "split": field})
        missing = sorted(set(ids) - known.keys())
        if missing:
            errors.append({"code": "unknown_split_ids", "split": field, "ticket_ids": missing})
    overlap = sorted(set(train) & set(validation))
    if overlap:
        errors.append({"code": "ticket_overlap", "ticket_ids": overlap})
    uncovered = sorted(known.keys() - (set(train) | set(validation)))
    if uncovered:
        errors.append({"code": "tickets_not_in_manifest", "ticket_ids": uncovered})
    if manifest.get("data_sha256") != data_sha256:
        errors.append({"code": "data_hash_mismatch"})
    train_batches = {(known[i]["business"], known[i]["batch_key"]) for i in train if i in known}
    validation_batches = {(known[i]["business"], known[i]["batch_key"]) for i in validation if i in known}
    if train_batches & validation_batches:
        errors.append({"code": "batch_overlap", "batches": sorted(train_batches & validation_batches)})
    return {"train_tickets": len(train), "validation_tickets": len(validation),
            "train_batches": len(train_batches), "validation_batches": len(validation_batches),
            "errors": errors, "hash_matches": manifest.get("data_sha256") == data_sha256,
            "scope": "Actual saved training manifest; no inferred or newly generated split."}


def inspect_screening_artifacts(root: Path) -> dict:
    """Bounded metadata inventory; does not read weights, secrets, or call Kaggle."""
    inspected, selections, individual = [], [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".log", ".csv"} or path.stat().st_size > 10_000_000:
            continue
        if any(part in {"adapter", "checkpoints"} for part in path.relative_to(root).parts):
            continue
        inspected.append(fingerprint(path))
        if path.suffix != ".json":
            continue
        try:
            payload = json.loads(path.read_text())
        except (ValueError, UnicodeError):
            continue
        if path.name == "promoted_search_selection.json":
            selections.append({"artifact": fingerprint(path), "selection": payload})
        elif isinstance(payload, dict) and (
            path.name in {"search_results.json", "best_hyperparameters.json"}
            or ("trial_id" in payload and ("validation_loss" in payload or "status" in payload))
        ):
            individual.append({"artifact": fingerprint(path), "result": payload})
    return {
        "root": str(root.resolve()), "exists": root.is_dir(), "inspected_metadata_files": inspected,
        "promoted_selections": selections, "individual_search_artifacts": individual,
        "conclusion": ("Individual search metadata found; review results before counting experiments." if individual else
                       "No individual trial/search-results metadata found in this local metadata inventory. Promotion summary alone reports four successful screenings."),
        "required_download_if_missing": ["search_results.json", "search_plan.json", "best_hyperparameters.json",
                                         "trials/trial_*/result.json", "trials/trial_*/attempt_*/hyperparameters.json",
                                         "search split/subset manifest and per-trial loss histories, if exported"],
        "limitations": "Metadata files limited to JSON/CSV/log <=10 MB, excluding adapter/checkpoints. No archive contents or remote Kaggle outputs inspected.",
    }


def audit_training_data(csv_path: Path, data_root: Path, held_out_tenant: str = "harbor_view",
                        split_manifest: Path | None = None, screening_root: Path | None = None) -> dict:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    tenants = {row.get("business", "") for row in rows}
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", tenant) for tenant in tenants):
        raise ValueError("Tenant IDs must be simple names, not paths.")
    catalog, source_files = load_documents(data_root, tenants)
    input_files = [fingerprint(csv_path), *source_files]
    report = {"schema_version": 1, "nonmutating": True, "dataset": input_files[0],
              "audit": audit_rows(rows, catalog, held_out_tenant), "source_files": source_files}
    report["audit"]["flagged_ticket_count"] = len({item["ticket_id"] for item in report["audit"]["review_signals"]})
    if split_manifest:
        input_files.append(fingerprint(split_manifest))
        report["split_manifest"] = input_files[-1]
        manifest = json.loads(split_manifest.read_text())
        report["split_audit"] = audit_split(rows, manifest, input_files[0]["sha256"])
        validation_ids, train_ids = set(manifest.get("validation_ticket_ids", [])), set(manifest.get("train_ticket_ids", []))
        for signal in report["audit"]["review_signals"]:
            signal["actual_saved_split"] = ("train" if signal["ticket_id"] in train_ids else
                                            "validation" if signal["ticket_id"] in validation_ids else "unassigned")
    if screening_root:
        report["screening_inventory"] = inspect_screening_artifacts(screening_root)
    report["input_preservation"] = {"all_unchanged": all(fingerprint(Path(item["path"])) == item for item in input_files),
                                    "files_checked": len(input_files)}
    return report
