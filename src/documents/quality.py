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
