"""Uniform evidence screening; reports or quarantines rows without repairing them."""

import json
from pathlib import Path


def screen_records(records: list[dict], data_root: Path, mode: str = "report") -> tuple[list[dict], dict]:
    if mode not in {"report", "quarantine"}:
        raise ValueError("mode must be report or quarantine")
    from src.documents.provenance import EvidenceProvenanceValidator, load_tenant_corpus

    root = Path(data_root).resolve()
    validators = {}
    manifests = {}
    accepted_rows, assessments = [], []
    for index, row in enumerate(records):
        tenant = row.get("business")
        try:
            if (not isinstance(tenant, str) or not tenant or tenant.startswith(".")
                    or Path(tenant).name != tenant or "/" in tenant or "\\" in tenant):
                raise ValueError("Invalid tenant directory identifier")
            directory = (root / tenant).resolve()
            if root not in directory.parents or not directory.is_dir():
                raise ValueError("Tenant corpus directory is missing or outside data root")
            if tenant not in validators:
                corpus = load_tenant_corpus(directory)
                validators[tenant] = EvidenceProvenanceValidator(corpus)
                manifests[tenant] = {name: document.sha256 for name, document in corpus.items()}
            evidence = row.get("evidence_json", row.get("evidence"))
            if isinstance(evidence, str):
                evidence = json.loads(evidence)
            result = validators[tenant].validate_evidence(evidence)
            target_findings = []
            if row.get("action") == "answer" and not evidence:
                target_findings.append("answer_target_without_evidence")
            answerable = row.get("is_answerable")
            if isinstance(answerable, str):
                normalized = answerable.strip().casefold()
                if normalized in {"false", "0"}:
                    answerable = False
                elif normalized in {"true", "1"}:
                    answerable = True
                else:
                    target_findings.append("invalid_answerability_label")
            if row.get("action") == "answer" and (answerable is False
                    or row.get("escalation_reason") in {"not_in_docs", "docs_require_human"}):
                target_findings.append("answer_target_conflicts_with_escalation_label")
            if target_findings:
                result = {**result, "accepted": False, "requires_review": True,
                          "quarantine_recommended": True, "target_schema_findings": target_findings}
        except (ValueError, TypeError, OSError) as exc:
            # Report exception categories, not arbitrary document/provider content.
            result = {"accepted": False, "requires_review": True,
                      "quarantine_recommended": True, "semantic_correctness_assessed": False,
                      "error_type": type(exc).__name__}
        accepted = result.get("accepted") is True
        if mode == "report" or accepted:
            accepted_rows.append(row)
        assessments.append({"row_index": index, "ticket_id": row.get("ticket_id"),
                            "business": tenant, "assessment": result})
    accepted_count = sum(r["assessment"].get("accepted") is True for r in assessments)
    return accepted_rows, {
        "schema_version": 1, "mode": mode, "input_rows": len(records),
        "provenance_accepted_rows": accepted_count,
        "rows_requiring_review": len(records) - accepted_count,
        "output_rows": len(accepted_rows), "rows": assessments,
        "corpus_sha256": manifests, "source_rows_modified": False,
        "semantic_correctness_assessed": False,
        "policy": "No automatic citation relabelling, target rewriting, tenant exceptions, or ticket exceptions.",
    }


# Rows of these types carry retrieved passages as *context shown to the student*, not quotes
# that a teacher claims support an answer, so there is nothing to verify against a cited source.
CONTEXT_ONLY_INTERACTION_TYPES = frozenset({"retrieval_distractor"})


def screen_cited_quotes(records: list[dict], data_root: Path, mode: str = "quarantine") -> tuple[list[dict], dict]:
    """Drop rows whose cited evidence quote is not found in the cited source document.

    This is the narrow rule from the sprint-3 audit (`quote_not_found_in_cited_source`): a quote
    must appear in the document it cites, after presentation-only normalization (case, whitespace,
    markdown emphasis, curly quotes). Matches in a *different* document do not rescue a row,
    because the citation would still be wrong. Rows are removed, never edited.
    """
    if mode not in {"report", "quarantine"}:
        raise ValueError("mode must be report or quarantine")
    from src.evaluation.training_data_audit import load_documents, normalize_text

    root = Path(data_root).resolve()
    tenants = {r["business"] for r in records
               if isinstance(r.get("business"), str) and r["business"] and not r["business"].startswith(".")
               and Path(r["business"]).name == r["business"]}
    catalog, _ = load_documents(root, tenants)

    kept, findings, flagged_rows, context_rows = [], [], set(), 0
    for index, row in enumerate(records):
        tenant = row.get("business")
        if row.get("interaction_type") in CONTEXT_ONLY_INTERACTION_TYPES:
            context_rows += 1
            kept.append(row)
            continue
        row_findings = []
        try:
            evidence = row.get("evidence_json", row.get("evidence"))
            if isinstance(evidence, str):
                evidence = json.loads(evidence) if evidence.strip() else []
            if not isinstance(evidence, list):
                raise ValueError("evidence is not a list")
            for position, item in enumerate(evidence):
                source, quote = item["source"], item["quote"]
                document = catalog.get(tenant, {}).get(source)
                if document is None:
                    row_findings.append({"evidence_index": position, "source": source, "code": "unknown_source"})
                    continue
                normalized_quote = normalize_text(quote)
                if quote in document["text"] or any(normalized_quote in text for text in document["normalized"]):
                    continue
                elsewhere = sorted({entry.get("alias", name) for name, entry in catalog.get(tenant, {}).items()
                                    if name != source and any(normalized_quote in text for text in entry["normalized"])})
                row_findings.append({"evidence_index": position, "source": source,
                                     "code": "quote_not_found_in_cited_source",
                                     "other_documents_with_quote": elsewhere})
        except (ValueError, TypeError, KeyError):
            row_findings.append({"evidence_index": None, "source": None, "code": "unreadable_evidence"})
        if row_findings:
            flagged_rows.add(index)
            findings.extend({"row_index": index, "ticket_id": row.get("ticket_id"), "business": tenant, **f}
                            for f in row_findings)
        if mode == "report" or not row_findings:
            kept.append(row)

    codes: dict[str, int] = {}
    for finding in findings:
        codes[finding["code"]] = codes.get(finding["code"], 0) + 1
    return kept, {
        "schema_version": 1, "mode": "report" if mode == "report" else "quarantine-quotes",
        "input_rows": len(records), "rows_requiring_review": len(flagged_rows),
        "rows_skipped_as_context_only": context_rows, "output_rows": len(kept),
        "finding_counts": codes, "findings": findings, "source_rows_modified": False,
        "semantic_correctness_assessed": False,
        "policy": "Rows with a cited quote missing from its cited source are removed uniformly; "
                  "no row, label, citation, tenant or ticket is exempted or repaired.",
    }
