"""Offline consistency repair with immutable judge and generation provenance.

Only the rubric's deterministic decision field is mechanically derived. The
other dimensions remain the original judge's assessments, not newly certified
semantic truth. Failed judgments need fresh, independently validated verdicts.
"""

import copy
import hashlib
import json
import shlex
from pathlib import Path

from src.evaluation.judge import (
    JudgeIdentity, JudgeVerdict, LoadedLog, STATUS_JUDGED,
    build_judge_payload, check_resume_compatible, check_verdict_against_response,
    citations_missing_from_evidence, compute_passed, load_generation_log,
    expected_rubric_decision, load_rubric, serialize_payload, summarize_judgments,
)


METHOD = "rubric_decision_table_mechanical_correction_v1"
LIMITATIONS = (
    "Decision-only corrections apply the frozen rubric table to the original "
    "judge's evidence_sufficient flag. They are not fresh semantic judgments. "
    "Inherited correctness, groundedness, citations, explanation, and evidence "
    "sufficiency can still be wrong. Unresolved records have no fabricated "
    "verdict and stay in all-record denominators. Unsupported-claim rates are "
    "judge assessments, not established factual hallucination ground truth."
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_hashed_json(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return result, hashlib.sha256(raw).hexdigest()


def _fingerprint(record: dict) -> str:
    return hashlib.sha256(serialize_payload(build_judge_payload(record)).encode()).hexdigest()


def write_new_json(path: Path, payload: dict, protected: set[Path] | None = None) -> None:
    """Create a new artifact, or accept an identical prior result; never overwrite."""
    if protected and path.resolve() in protected:
        raise ValueError("Output would overwrite an input artifact")
    data = json.dumps(payload, indent=4, ensure_ascii=False, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(data)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != data:
            raise ValueError(f"Refusing to overwrite different artifact: {path}") from None


def load_verified_judgment(path: Path) -> tuple[dict, LoadedLog, str]:
    """Check source bytes, frozen rubric, identity and per-record payload provenance."""
    state, judged_sha256 = _read_hashed_json(path)
    source = Path(state["source"]["path"])
    log = load_generation_log(source)
    rubric = load_rubric()
    # check_resume_compatible also detects completed decision-table violations
    # after validator upgrades. Those are precisely what this offline tool repairs,
    # so validate the original resume identity with neutral pending statuses.
    identity_only = copy.deepcopy(state)
    for entry in identity_only["judgments"]:
        entry["status"] = "pending"
    check_resume_compatible(identity_only, log, JudgeIdentity(**state["judge"]), rubric)
    records = {record["ticket_id"]: record for record in log.records}
    for entry in state["judgments"]:
        record = records[entry["ticket_id"]]
        if entry.get("input_fingerprint") != _fingerprint(record):
            raise ValueError(f"Payload fingerprint mismatch: {entry['ticket_id']}")
        expected = {
            "source_model": log.model, "context_mode": log.context_mode,
            "model_action": record["model_action"],
            "expected_action": record["ground_truth_action"],
            "case_type": "answer_present" if record["is_answerable"] else "answer_absent",
        }
        if any(entry.get(key) != value for key, value in expected.items()):
            raise ValueError(f"Record metadata mismatch: {entry['ticket_id']}")
        missing = citations_missing_from_evidence(record["model_sources"], record.get("context") or "")
        if entry.get("citations_missing_from_evidence") != missing:
            raise ValueError(f"Citation provenance mismatch: {entry['ticket_id']}")
    return state, log, judged_sha256


def prepare_retry_subset(judged_path: Path, output_dir: Path) -> dict | None:
    """Save only unresolved generation records. No model calls are made here."""
    state, log, judged_sha256 = load_verified_judgment(judged_path)
    unresolved = {entry["ticket_id"] for entry in state["judgments"]
                  if entry["status"] != STATUS_JUDGED}
    if not unresolved:
        return None
    subset, generation_sha256 = _read_hashed_json(log.path)
    if generation_sha256 != log.sha256:
        raise ValueError("Generation input changed while preparing retry subset")
    subset["records"] = [record for record in log.records if record["ticket_id"] in unresolved]
    subset["metrics"] = {
        "context_mode": log.context_mode, "benchmark_file": log.benchmark_file,
        "subset_only": True,
    }
    subset["retry_provenance"] = {
        "selection": "Only unresolved judgments; not a new generation experiment",
        "original_generation_path": str(log.path.resolve()),
        "original_generation_sha256": log.sha256,
        "original_judged_path": str(judged_path.resolve()),
        "original_judged_sha256": judged_sha256,
        "selected_ticket_ids": [r["ticket_id"] for r in subset["records"]],
    }
    source_path = output_dir / "retry_inputs" / (judged_path.stem + "_unresolved_generation.json")
    result_path = output_dir / "retry_results" / (judged_path.stem + "_retry.json")
    protected = {judged_path.resolve(), log.path.resolve()}
    write_new_json(source_path, subset, protected)
    judge = state["judge"]
    command = [".venv/bin/python", "scripts/judge_generation.py", "--input", str(source_path.resolve()),
               "--provider", judge["provider"], "--model", judge["model"],
               "--output", str(result_path.resolve()), "--execute", "--max-calls", str(len(unresolved) * 2)]
    if judge["provider"] == "ollama":
        command.extend(["--base-url", "http://localhost:11434", "--timeout", "120"])
        for name in ("think", "num_ctx", "num_predict"):
            if judge.get(name) is not None:
                value = str(judge[name]).lower() if name == "think" else str(judge[name])
                command.extend(["--" + name.replace("_", "-"), value])
    return {
        "input_path": str(source_path.resolve()), "input_sha256": sha256_file(source_path),
        "output_path": str(result_path.resolve()), "records": len(unresolved),
        "ticket_ids": subset["retry_provenance"]["selected_ticket_ids"],
        "command": shlex.join(command),
        "original_judged_sha256": judged_sha256,
        "original_generation_sha256": log.sha256,
    }


def prepare_retry_plan(judged_paths: list[Path], output_dir: Path) -> dict:
    plans = [plan for path in judged_paths if (plan := prepare_retry_subset(path, output_dir))]
    plan = {"model_calls_made": 0, "total_records": sum(p["records"] for p in plans),
            "run_sequentially": True, "plans": plans}
    write_new_json(output_dir / "retry_plan.json", plan, {p.resolve() for p in judged_paths})
    return plan


def _validate_accepted(entry: dict, record: dict, *, case_aware: bool) -> JudgeVerdict:
    verdict = JudgeVerdict.model_validate(entry["verdict"], strict=True)
    payload = build_judge_payload(record)
    check_verdict_against_response(verdict, payload["response"], payload["case"] if case_aware else None)
    missing = citations_missing_from_evidence(payload["response"]["cited_sources"], payload["evidence"])
    if type(entry.get("passed")) is not bool or entry["passed"] != compute_passed(verdict, missing):
        raise ValueError(f"Stored pass flag differs from rubric calculation: {entry['ticket_id']}")
    return verdict


def _summary(entries: list[dict]) -> dict:
    summary = summarize_judgments(entries)
    groups = [summary["overall"]]
    groups.extend(stats for split in summary["per_split"].values() for stats in split.values())
    for stats in groups:
        stats["unresolved_records"] = stats["records"] - stats["judged"]
        stats["dimension_denominator"] = stats["judged"]
        stats["all_record_denominator"] = stats["records"]
        stats["strict_pass_rate_lower_bound"] = stats["strict_pass_rate"]
        stats["strict_pass_rate_upper_bound"] = (
            (stats["passed"] + stats["unresolved_records"]) / stats["records"]
            if stats["records"] else None
        )
        stats["dimensions_are_judge_assessments"] = True
    summary["limitations"] = LIMITATIONS
    return summary


def _verified_retries(retry_paths: list[Path], originals: dict[str, tuple]) -> dict[tuple[str, str], tuple]:
    results = {}
    for path in retry_paths:
        state, log, retry_sha256 = load_verified_judgment(path)
        subset, subset_sha256 = _read_hashed_json(log.path)
        if subset_sha256 != log.sha256:
            raise ValueError("Retry subset changed while verifying provenance")
        provenance = subset.get("retry_provenance") or {}
        original_hash = provenance.get("original_judged_sha256")
        if original_hash not in originals:
            raise ValueError(f"Retry does not belong to one of the supplied original judgments: {path}")
        _, original_state, original_log = originals[original_hash]
        if provenance.get("original_generation_sha256") != original_log.sha256:
            raise ValueError(f"Retry generation ancestry mismatch: {path}")
        if state["judge"] != original_state["judge"]:
            raise ValueError(f"Retry judge identity differs from original: {path}")
        original_records = {r["ticket_id"]: r for r in original_log.records}
        original_entries = {e["ticket_id"]: e for e in original_state["judgments"]}
        for entry, record in zip(state["judgments"], log.records):
            ticket = entry["ticket_id"]
            if ticket not in original_records or record != original_records[ticket]:
                raise ValueError(f"Retry record differs from original response/context: {ticket}")
            if original_entries[ticket]["status"] == STATUS_JUDGED:
                raise ValueError(f"Retry targets an already judged record: {ticket}")
            key = (original_hash, ticket)
            if key in results:
                raise ValueError(f"Multiple retry results for the same record: {ticket}")
            if entry["status"] == STATUS_JUDGED:
                _validate_accepted(entry, record, case_aware=True)
            elif entry.get("verdict") is not None or entry.get("passed") is not None:
                raise ValueError(f"Unresolved retry has a fabricated score: {ticket}")
            results[key] = (path, log, entry, retry_sha256)
    return results


def repair_judgments(judged_paths: list[Path], retry_paths: list[Path] | None = None) -> list[tuple[Path, dict]]:
    """Return repaired copies, preserving every original verdict in provenance.

    The deterministic table consumes the saved evidence_sufficient flag without
    certifying it. Fresh subset scores are accepted only for previously unresolved
    records after source-byte, record-content, rubric and judge-identity checks.
    """
    originals = {}
    for path in judged_paths:
        state, log, digest = load_verified_judgment(path)
        if digest in originals:
            raise ValueError("Duplicate original judged input")
        originals[digest] = (path, state, log)
    retries = _verified_retries(retry_paths or [], originals)
    repaired = []
    for digest, (path, state, log) in originals.items():
        updated = copy.deepcopy(state)
        records = {record["ticket_id"]: record for record in log.records}
        changed, fresh, unresolved = 0, 0, 0
        for entry in updated["judgments"]:
            record = records[entry["ticket_id"]]
            if entry["status"] == STATUS_JUDGED:
                verdict = _validate_accepted(entry, record, case_aware=False)
                decision = expected_rubric_decision(
                    record["ground_truth_action"], record["model_action"], verdict.evidence_sufficient
                )
                if verdict.decision != decision:
                    changed += 1
                    entry["repair"] = {
                        "method": METHOD, "original_verdict": copy.deepcopy(entry["verdict"]),
                        "original_passed": entry["passed"], "derived_decision": decision,
                        "evidence_sufficient_source": "original_judge_verdict_not_semantically_revalidated",
                        "other_semantic_dimensions": "inherited_without_fresh_judging",
                        "new_model_calls": 0,
                    }
                    entry["verdict"]["decision"] = decision
                    entry["verdict"]["explanation"] = (
                        "Mechanical decision-table correction using the original judge's evidence_sufficient flag. "
                        "Other semantic dimensions are inherited; the unchanged original verdict and explanation "
                        "are preserved in repair.original_verdict. This is not fresh semantic adjudication."
                    )
                    verdict = JudgeVerdict.model_validate(entry["verdict"], strict=True)
                    entry["passed"] = compute_passed(verdict, entry["citations_missing_from_evidence"])
                _validate_accepted(entry, record, case_aware=True)
            else:
                if entry.get("verdict") is not None or entry.get("passed") is not None:
                    raise ValueError(f"Unresolved original has a score: {entry['ticket_id']}")
                retry = retries.get((digest, entry["ticket_id"]))
                if retry:
                    retry_path, retry_log, retry_entry, retry_sha256 = retry
                    original = copy.deepcopy(entry)
                    for key in ("status", "verdict", "passed", "error", "judged_at"):
                        entry[key] = copy.deepcopy(retry_entry[key])
                    entry["attempts"] += retry_entry["attempts"]
                    for token in ("prompt_tokens", "completion_tokens"):
                        entry["usage"][token] += retry_entry["usage"][token]
                    diagnostics = copy.deepcopy(retry_entry.get("attempt_diagnostics", []))
                    for diagnostic in diagnostics:
                        diagnostic["attempt"] += original["attempts"]
                    entry.setdefault("attempt_diagnostics", []).extend(diagnostics)
                    entry["repair"] = {
                        "method": "fresh_independent_judge_retry" if entry["status"] == STATUS_JUDGED else "unresolved_after_retry",
                        "original_judgment": original,
                        "retry_judged_path": str(retry_path.resolve()),
                        "retry_judged_sha256": retry_sha256,
                        "retry_generation_sha256": retry_log.sha256,
                        "new_model_calls": retry_entry["attempts"],
                    }
                    if entry["status"] == STATUS_JUDGED:
                        fresh += 1
                        _validate_accepted(entry, record, case_aware=True)
                if entry["status"] != STATUS_JUDGED:
                    unresolved += 1
        updated["repair"] = {
            "schema_version": 1, "method": METHOD,
            "original_judged_path": str(path.resolve()), "original_judged_sha256": digest,
            "original_generation_sha256": log.sha256,
            "mechanically_corrected_decisions": changed,
            "fresh_semantic_judgments": fresh, "unresolved_records": unresolved,
            "inherited_semantic_judgments": sum(e["status"] == STATUS_JUDGED for e in updated["judgments"]) - fresh,
            "limitations": LIMITATIONS,
        }
        updated["summary"] = _summary(updated["judgments"])
        updated["limitations"] = state.get("limitations", "") + " " + LIMITATIONS
        repaired.append((path, updated))
    return repaired


def write_repair_bundle(judged_paths: list[Path], output_dir: Path, retry_paths: list[Path] | None = None) -> dict:
    """Write new corrected artifacts, split metrics, and an auditable manifest."""
    repaired = repair_judgments(judged_paths, retry_paths)
    protected = {path.resolve() for path in judged_paths + (retry_paths or [])}
    protected.update(Path(state["source"]["path"]).resolve() for _, state in repaired)
    manifest = {
        "repair_schema_version": 1, "method": METHOD, "limitations": LIMITATIONS,
        "offline_repair_model_calls": 0, "files": [],
    }
    all_entries = []
    for original, state in repaired:
        target = output_dir / "corrected" / original.name
        write_new_json(target, state, protected)
        all_entries.extend(state["judgments"])
        manifest["files"].append({
            "original_judged_path": str(original.resolve()),
            "original_judged_sha256": state["repair"]["original_judged_sha256"],
            "original_generation_path": state["source"]["path"],
            "original_generation_sha256": state["source"]["sha256"],
            "corrected_path": str(target.resolve()), "corrected_sha256": sha256_file(target),
            "model": state["source"]["model"], "context_mode": state["source"]["context_mode"],
            "mechanically_corrected_decisions": state["repair"]["mechanically_corrected_decisions"],
            "fresh_semantic_judgments": state["repair"]["fresh_semantic_judgments"],
            "unresolved_records": state["repair"]["unresolved_records"],
            "summary": state["summary"],
        })
    manifest["summary"] = _summary(all_entries)
    manifest["mechanically_corrected_decisions"] = sum(item["mechanically_corrected_decisions"] for item in manifest["files"])
    manifest["fresh_semantic_judgments"] = sum(item["fresh_semantic_judgments"] for item in manifest["files"])
    write_new_json(output_dir / "repair_manifest.json", manifest, protected)
    return manifest
