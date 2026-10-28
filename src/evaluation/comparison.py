"""Reproducible baseline orchestration, compatibility validation, and model comparison.

Provides:
- Compatibility checks across frozen benchmark hashes, context modes, and question coverage.
- Comprehensive metric aggregation:
  - Action accuracy, escalation precision/recall/F1, schema validity.
  - Clearly labeled absent-answer action proxy (explicitly distinct from full hallucination detection).
  - Latency distributions (p50, p90, p95, mean) distinguishing generation from end-to-end timing.
  - Throughput (tokens/second) and hardware metadata.
  - Token usage accounting and configurable API cost per 1,000 queries.
  - Integration of independent LLM judge quality results when compatible judged logs are supplied.
- Explicit teacher recovery calculations (performance ratio and gap closed), safe zero-denominator
  handling, missing-value preservation (no fabricated zeros), and strict refusal to collapse
  unrelated metrics into a single misleading score.
- Configurable teacher adapter interface without hardcoded model names or invented credentials.
- Safe log path generation and collision-free output naming.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable, Dict, List, Literal, Optional, Protocol, Sequence, Tuple, Union

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Pricing and Cost Configurations
# ---------------------------------------------------------------------------

@dataclass
class ModelPricing:
    """Pricing configuration for an evaluated model.

    Separates paid API token costs from local compute.
    Rates are expressed in USD per 1,000,000 tokens ($/M tokens).
    """
    model_name: str
    prompt_cost_per_million: Optional[float] = 0.0
    completion_cost_per_million: Optional[float] = 0.0
    pricing_source: str = "Local inference (0.00 USD token cost)"
    pricing_date: str = "2026-10-25"
    is_local: bool = True

    def calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculates total cost in USD for given token counts."""
        if self.prompt_cost_per_million is None or self.completion_cost_per_million is None:
            return None
        return (
            (prompt_tokens * self.prompt_cost_per_million / 1_000_000.0)
            + (completion_tokens * self.completion_cost_per_million / 1_000_000.0)
        )

    def calculate_cost_per_1k_queries(
        self, avg_prompt_tokens: float, avg_completion_tokens: float
    ) -> float:
        """Calculates expected cost for 1,000 queries based on average token usage."""
        cost_per_query = self.calculate_cost(avg_prompt_tokens, avg_completion_tokens)
        return cost_per_query * 1000.0 if cost_per_query is not None else None


# Standard reference pricing catalog (configurable via CLI or JSON overrides)
DEFAULT_PRICING_CATALOG: Dict[str, ModelPricing] = {
    # Local student models (zero API token cost)
    "llama3.2:3b": ModelPricing(
        model_name="llama3.2:3b",
        prompt_cost_per_million=0.0,
        completion_cost_per_million=0.0,
        pricing_source="Local Ollama execution ($0.00 API token cost; local hardware compute)",
        pricing_date="2026-10-25",
        is_local=True,
    ),
    "llama3.2:3b-instruct": ModelPricing(
        model_name="llama3.2:3b-instruct",
        prompt_cost_per_million=0.0,
        completion_cost_per_million=0.0,
        pricing_source="Local Ollama execution ($0.00 API token cost; local hardware compute)",
        pricing_date="2026-10-25",
        is_local=True,
    ),
    "llama3.2:3b-qlora": ModelPricing(
        model_name="llama3.2:3b-qlora",
        prompt_cost_per_million=0.0,
        completion_cost_per_million=0.0,
        pricing_source="Local fine-tuned student ($0.00 API token cost; local hardware compute)",
        pricing_date="2026-10-25",
        is_local=True,
    ),

}


def get_model_pricing(
    model_name: str, custom_catalog: Optional[Dict[str, ModelPricing]] = None
) -> ModelPricing:
    """Finds pricing configuration for a model, leaving unrecognized model pricing unmeasured."""
    catalog = dict(DEFAULT_PRICING_CATALOG)
    if custom_catalog:
        catalog.update(custom_catalog)

    clean_name = model_name.strip().lower()
    for key, pricing in catalog.items():
        if key.lower() == clean_name:
            return pricing

    return ModelPricing(
        model_name=model_name, prompt_cost_per_million=None,
        completion_cost_per_million=None, pricing_source="Not configured; cost not measured",
        pricing_date="unknown", is_local=False,
    )


# ---------------------------------------------------------------------------
# Hardware and Environmental Metadata Collection
# ---------------------------------------------------------------------------

def get_hardware_metadata() -> Dict[str, Any]:
    """Collects runtime hardware and OS metadata safely without crashing."""
    meta: Dict[str, Any] = {
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "os_name": platform.system(),
        "architecture": platform.machine(),
        "cpu_count_logical": os.cpu_count(),
        "cpu_model": None,
        "ram_total_bytes": None,
        "ram_total_human": None,
        "gpu_info": None,
    }

    # CPU Model from /proc/cpuinfo if on Linux
    if Path("/proc/cpuinfo").exists():
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                for line in f:
                    if "model name" in line:
                        meta["cpu_model"] = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass

    # RAM total from /proc/meminfo if on Linux
    if Path("/proc/meminfo").exists():
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if "MemTotal" in line:
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            kb = int(parts[1])
                            meta["ram_total_bytes"] = kb * 1024
                            meta["ram_total_human"] = f"{kb / (1024 * 1024):.2f} GiB"
                        break
        except Exception:
            pass

    # GPU details via nvidia-smi if available
    try:
        gpu_out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            text=True,
            timeout=2.0,
            stderr=subprocess.DEVNULL,
        ).strip()
        if gpu_out:
            gpu_lines = [line.strip() for line in gpu_out.splitlines() if line.strip()]
            meta["gpu_info"] = gpu_lines
    except Exception:
        meta["gpu_info"] = None

    return meta


# ---------------------------------------------------------------------------
# Benchmark Integrity and Compatibility Verification
# ---------------------------------------------------------------------------

def compute_file_sha256(path: Path | str) -> str:
    """Computes SHA256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_questions_sha256(question_ids: Sequence[str]) -> str:
    """Computes canonical hash for an ordered sequence of question ticket IDs."""
    data = "\n".join(question_ids).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass
class CompatibilityIssue:
    severity: Literal["ERROR", "WARNING", "INFO"]
    category: str
    message: str


@dataclass
class CompatibilityReport:
    is_compatible: bool
    context_modes: List[str]
    benchmark_hashes: Dict[str, str]
    question_counts: Dict[str, int]
    shared_questions_count: int
    issues: List[CompatibilityIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "ERROR" for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(issue.severity == "WARNING" for issue in self.issues)


def check_comparison_compatibility(logs: Sequence[Dict[str, Any]]) -> CompatibilityReport:
    """Validates whether a collection of evaluation logs can be fairly compared.

    Checks:
    - Context mode consistency (mixing ground-truth context and live-RAG is flagged).
    - Benchmark hash and question set consistency.
    - Question coverage and overlap.
    """
    issues: List[CompatibilityIssue] = []
    if not logs:
        return CompatibilityReport(
            is_compatible=False,
            context_modes=[],
            benchmark_hashes={},
            question_counts={},
            shared_questions_count=0,
            issues=[CompatibilityIssue("ERROR", "empty", "No evaluation logs provided for comparison.")],
        )

    context_modes: Dict[str, str] = {}
    benchmark_hashes: Dict[str, str] = {}
    question_counts: Dict[str, int] = {}
    all_question_sets: List[set[str]] = []

    for index, log in enumerate(logs):
        model_name = f"{index}:{log.get('model', 'unknown')}"
        metrics = log.get("metrics", {})
        records = log.get("records", [])

        # Context mode
        c_mode = metrics.get("context_mode") or log.get("context_mode", "unknown")
        context_modes[model_name] = c_mode

        # Benchmark hash or file
        b_hash = (
            metrics.get("benchmark_sha256")
            or log.get("benchmark_sha256")
            or "unknown"
        )
        benchmark_hashes[model_name] = str(b_hash)

        # Question IDs
        q_ids = [r.get("ticket_id") for r in records if r.get("ticket_id")]
        question_counts[model_name] = len(q_ids)
        all_question_sets.append(set(q_ids))
        if not q_ids or len(q_ids) != len(records) or len(set(q_ids)) != len(q_ids):
            issues.append(CompatibilityIssue("ERROR", "invalid_question_ids", f"{model_name}: missing, empty, or duplicate ticket IDs."))

    # Check 1: Context mode consistency
    unique_modes = sorted(set(context_modes.values()))
    if len(unique_modes) > 1:
        issues.append(CompatibilityIssue(
            severity="ERROR",
            category="context_mode_mismatch",
            message=(
                f"Mixed context modes detected across logs: {unique_modes}. "
                "Comparing ground-truth context runs directly with live-RAG runs conflates retrieval "
                "failures with model generation capabilities. Partition comparisons by context mode."
            ),
        ))

    if any(mode not in {"ground_truth", "retriever"} for mode in unique_modes):
        issues.append(CompatibilityIssue("ERROR", "unknown_context_mode", "Context mode must be recorded."))
    hashes = set(benchmark_hashes.values())
    if "unknown" in hashes or len(hashes) != 1:
        issues.append(CompatibilityIssue("ERROR", "benchmark_hash_mismatch", "Every log must record the same benchmark SHA-256; a filename is insufficient."))
    # Matching IDs alone cannot establish matching question text, targets, or context.
    signatures = []
    for log in logs:
        rows = {r.get("ticket_id"): {key: r.get(key) for key in
                ("customer_query", "ground_truth_action", "is_answerable", "context")}
                for r in log.get("records", [])}
        signatures.append(json.dumps(rows, sort_keys=True))
    if len(set(signatures)) > 1:
        issues.append(CompatibilityIssue("ERROR", "question_or_context_mismatch", "Questions, targets, or supplied context differ across logs."))
    for field_name in ("generation_settings", "retrieval_settings"):
        values = [json.dumps(log.get(field_name), sort_keys=True) for log in logs]
        if len(set(values)) > 1 or "null" in values:
            severity = "ERROR" if len(set(values) - {"null"}) > 1 else "WARNING"
            issues.append(CompatibilityIssue(severity, field_name, "Settings differ or are unrecorded; inspect before interpreting performance."))

    # Model weights may differ intentionally. Serving wrappers and runtime
    # settings must still match for an isolated model comparison. Legacy logs
    # remain readable but cannot silently imply verified serving parity.
    serving = [log.get("serving_settings") or {} for log in logs]
    if any(item.get("capture_status") != "recorded" for item in serving):
        issues.append(CompatibilityIssue("WARNING", "serving_provenance_missing",
                                        "Serving provenance is missing/incomplete; effective configuration parity is unverified."))
    for item in serving:
        if item.get("identity_changed_during_run") or item.get("runtime_identity_mismatch"):
            issues.append(CompatibilityIssue("ERROR", "model_identity_changed", "Installed/runtime model identity changed within an evaluation."))
    for field in ("template_sha256", "context_length"):
        known = {json.dumps(item[field], sort_keys=True) for item in serving if item.get(field) is not None}
        if len(known) > 1:
            issues.append(CompatibilityIssue("ERROR", "serving_" + field,
                                            f"Effective serving {field} differs; compare deployed configurations separately."))
    option_names = {key for item in serving for key in item.get("effective_options", {})}
    for key in sorted(option_names):
        values = [item.get("effective_options", {}).get(key) for item in serving]
        known = {json.dumps(value, sort_keys=True) for value in values if value is not None}
        if len(known) > 1:
            issues.append(CompatibilityIssue("ERROR", "serving_option_" + key, f"Effective serving option {key} differs."))
        elif any(value is None for value in values):
            issues.append(CompatibilityIssue("WARNING", "serving_option_" + key, f"Effective serving option {key} is unrecorded for some models."))
    identities = {}
    for log, item in zip(logs, serving):
        digest = item.get("model_digest")
        if digest:
            identities.setdefault(log.get("model", "unknown"), set()).add(digest)
    if any(len(digests) > 1 for digests in identities.values()):
        issues.append(CompatibilityIssue("ERROR", "model_digest_mismatch", "The same model tag resolves to different model digests across runs."))

    # Check 2: Question coverage and equality
    shared_questions = set.intersection(*all_question_sets) if all_question_sets else set()
    total_distinct_questions = set.union(*all_question_sets) if all_question_sets else set()

    counts = list(question_counts.values())
    if len(set(counts)) > 1:
        issues.append(CompatibilityIssue(
            severity="ERROR",
            category="question_count_mismatch",
            message=(
                f"Evaluated question counts differ across logs: {question_counts}. "
                "Fair model comparisons require identical question counts on the frozen benchmark."
            ),
        ))

    if len(shared_questions) < len(total_distinct_questions):
        issues.append(CompatibilityIssue(
            severity="ERROR",
            category="question_set_disjoint",
            message=(
                f"Logs evaluate disjoint or non-identical question sets. "
                f"Only {len(shared_questions)} questions are shared across all {len(total_distinct_questions)} unique questions evaluated."
            ),
        ))

    is_compatible = not any(i.severity == "ERROR" for i in issues)
    return CompatibilityReport(
        is_compatible=is_compatible,
        context_modes=unique_modes,
        benchmark_hashes=benchmark_hashes,
        question_counts=question_counts,
        shared_questions_count=len(shared_questions),
        issues=issues,
    )


# ---------------------------------------------------------------------------
# Statistics and Metric Calculations
# ---------------------------------------------------------------------------

def compute_percentiles(values: Sequence[float], percentiles: Sequence[float] = (50, 90, 95)) -> Dict[str, float]:
    """Computes exact empirical percentiles (quantiles) using linear interpolation."""
    if not values:
        return {f"p{int(p)}": 0.0 for p in percentiles}
    sorted_v = sorted(values)
    n = len(sorted_v)
    results = {}
    for p in percentiles:
        if n == 1:
            results[f"p{int(p)}"] = sorted_v[0]
            continue
        rank = (p / 100.0) * (n - 1)
        low = int(math.floor(rank))
        high = int(math.ceil(rank))
        weight = rank - low
        val = (1.0 - weight) * sorted_v[low] + weight * sorted_v[high]
        results[f"p{int(p)}"] = round(val, 2)
    return results


@dataclass
class LatencyDistribution:
    """Latency distribution summary metrics in milliseconds."""
    p50_ms: float
    p90_ms: float
    p95_ms: float
    mean_ms: float
    min_ms: float
    max_ms: float
    sample_count: int

    @classmethod
    def from_latencies(cls, latencies: Sequence[float]) -> Optional[LatencyDistribution]:
        if not latencies:
            return None
        pcts = compute_percentiles(latencies, (50, 90, 95))
        return cls(
            p50_ms=pcts["p50"],
            p90_ms=pcts["p90"],
            p95_ms=pcts["p95"],
            mean_ms=round(mean(latencies), 2),
            min_ms=round(min(latencies), 2),
            max_ms=round(max(latencies), 2),
            sample_count=len(latencies),
        )


@dataclass
class TokenCostMetrics:
    """Token accounting and cost projections."""
    total_prompt_tokens: Optional[int]
    total_completion_tokens: Optional[int]
    total_tokens: Optional[int]
    avg_prompt_tokens: Optional[float]
    avg_completion_tokens: Optional[float]
    avg_total_tokens: Optional[float]
    cost_per_1k_queries: Optional[float]
    pricing_source: str
    pricing_date: str
    is_local: bool


def calculate_token_metrics(
    records: Sequence[Dict[str, Any]], pricing: ModelPricing
) -> TokenCostMetrics:
    """Calculates actual token usage and cost per 1,000 queries where measurable.

    Never fabricates zeros: if token counts are absent from the records, fields are None.
    """
    prompt_tokens_list: List[int] = []
    eval_tokens_list: List[int] = []

    for r in records:
        # Prompt tokens (if recorded)
        if "prompt_tokens" in r and r["prompt_tokens"] is not None:
            prompt_tokens_list.append(int(r["prompt_tokens"]))
        elif "eval_prompt_tokens" in r and r["eval_prompt_tokens"] is not None:
            prompt_tokens_list.append(int(r["eval_prompt_tokens"]))

        # Completion / eval tokens (standard in generation_eval logs)
        if "eval_tokens" in r and r["eval_tokens"] is not None:
            eval_tokens_list.append(int(r["eval_tokens"]))
        elif "completion_tokens" in r and r["completion_tokens"] is not None:
            eval_tokens_list.append(int(r["completion_tokens"]))

    n = len(records)
    has_completion = n > 0 and len(eval_tokens_list) == n
    has_prompt = n > 0 and len(prompt_tokens_list) == n

    total_eval = sum(eval_tokens_list) if has_completion else None
    total_prompt = sum(prompt_tokens_list) if has_prompt else None
    avg_eval = (total_eval / len(eval_tokens_list)) if has_completion else None
    avg_prompt = (total_prompt / len(prompt_tokens_list)) if has_prompt else None

    total_tokens: Optional[int] = None
    avg_total_tokens: Optional[float] = None
    if has_completion and has_prompt:
        total_tokens = (total_prompt or 0) + (total_eval or 0)
        avg_total_tokens = (avg_prompt or 0.0) + (avg_eval or 0.0)

    # Cost calculation:
    # If model is local, API token cost is strictly 0.0 USD.
    # If model is a paid API, both prompt and completion tokens are needed for an accurate projection.
    cost_per_1k: Optional[float] = None
    if pricing.is_local:
        cost_per_1k = 0.0
    elif has_completion and has_prompt and avg_prompt is not None and avg_eval is not None:
        cost = pricing.calculate_cost_per_1k_queries(avg_prompt, avg_eval)
        cost_per_1k = round(cost, 6) if cost is not None else None
    elif has_completion and avg_eval is not None and pricing.prompt_cost_per_million == 0.0:
        # If prompt tokens are free on this endpoint
        cost_per_1k = round(pricing.calculate_cost_per_1k_queries(0.0, avg_eval), 4)
    else:
        # Prompt tokens are unmeasured for paid API -> cannot fabricate cost
        cost_per_1k = None

    return TokenCostMetrics(
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_eval,
        total_tokens=total_tokens,
        avg_prompt_tokens=round(avg_prompt, 2) if avg_prompt is not None else None,
        avg_completion_tokens=round(avg_eval, 2) if avg_eval is not None else None,
        avg_total_tokens=round(avg_total_tokens, 2) if avg_total_tokens is not None else None,
        cost_per_1k_queries=cost_per_1k,
        pricing_source=pricing.pricing_source,
        pricing_date=pricing.pricing_date,
        is_local=pricing.is_local,
    )


# ---------------------------------------------------------------------------
# Teacher Recovery Calculations
# ---------------------------------------------------------------------------

@dataclass
class TeacherRecoveryResult:
    """Explicit teacher-recovery calculations for an individual metric.

    Definitions:
    - recovery_ratio: student / teacher (relative capability preservation).
      For inverse metrics (where lower is better): teacher / student.
    - gap_closed: (student - base) / (teacher - base).
      For inverse metrics: (base - student) / (base - teacher).

    Zero denominators and missing inputs are strictly handled and preserved as None.
    Unrelated metrics are never collapsed into a single composite score.
    """
    metric_name: str
    student_value: Optional[float]
    teacher_value: Optional[float]
    base_value: Optional[float]
    recovery_ratio: Optional[float]
    gap_closed: Optional[float]
    is_inverse: bool
    status: Literal["valid", "zero_denominator", "missing_data", "missing_base", "no_teacher"]
    notes: str


def calculate_teacher_recovery(
    metric_name: str,
    student_value: Optional[float],
    teacher_value: Optional[float],
    base_value: Optional[float] = None,
    is_inverse: bool = False,
) -> TeacherRecoveryResult:
    """Calculates teacher recovery ratio and gap closed with zero-denominator safety."""
    if student_value is None or teacher_value is None:
        return TeacherRecoveryResult(
            metric_name=metric_name,
            student_value=student_value,
            teacher_value=teacher_value,
            base_value=base_value,
            recovery_ratio=None,
            gap_closed=None,
            is_inverse=is_inverse,
            status="missing_data",
            notes="Missing student or teacher measurement; cannot compute recovery.",
        )

    # 1. Recovery ratio (student / teacher or teacher / student for inverse)
    recovery_ratio: Optional[float] = None
    ratio_notes = []

    if is_inverse:
        if student_value == 0.0 and teacher_value == 0.0:
            recovery_ratio = None
            ratio_notes.append("Both values are zero; ratio undefined.")
        elif student_value == 0.0:
            recovery_ratio = None
            ratio_notes.append("Student inverse metric is 0; ratio undefined.")
        else:
            recovery_ratio = round(teacher_value / student_value, 4)
    else:
        if teacher_value == 0.0 and student_value == 0.0:
            recovery_ratio = None
            ratio_notes.append("Both values are zero; ratio undefined.")
        elif teacher_value == 0.0:
            recovery_ratio = None
            ratio_notes.append("Teacher metric is 0; recovery ratio has zero denominator.")
        else:
            recovery_ratio = round(student_value / teacher_value, 4)

    # 2. Gap closed relative to base student
    gap_closed: Optional[float] = None
    status: Literal["valid", "zero_denominator", "missing_data", "missing_base", "no_teacher"] = "valid"

    if base_value is None:
        status = "missing_base"
        ratio_notes.append("Base student value not supplied; gap closed not measured.")
    else:
        if is_inverse:
            denom = base_value - teacher_value
            numer = base_value - student_value
        else:
            denom = teacher_value - base_value
            numer = student_value - base_value

        if denom == 0.0:
            gap_closed = None
            status = "zero_denominator"
            ratio_notes.append("Teacher performance equals base student; gap closed denominator is zero.")
        else:
            gap_closed = round(numer / denom, 4)

    return TeacherRecoveryResult(
        metric_name=metric_name,
        student_value=round(student_value, 4),
        teacher_value=round(teacher_value, 4),
        base_value=round(base_value, 4) if base_value is not None else None,
        recovery_ratio=recovery_ratio,
        gap_closed=gap_closed,
        is_inverse=is_inverse,
        status=status,
        notes="; ".join(ratio_notes) if ratio_notes else "Clean calculation",
    )


# ---------------------------------------------------------------------------
# Independent Judged Quality Integration
# ---------------------------------------------------------------------------

@dataclass
class JudgedMetrics:
    """Summary of independently judged quality metrics."""
    judge_model: str
    rubric_version: str
    total_records: int
    judged_records: int
    failed_records: int
    coverage_rate: float
    overall_pass_rate: Optional[float]
    correctness_rate: Optional[float]
    groundedness_rate: Optional[float]
    citation_support_rate: Optional[float]
    escalation_validity_rate: Optional[float]
    source_log_sha256: str
    rubric_sha256: str = ""
    judge_provider: str = ""


def extract_judged_metrics(
    judged_payload: Dict[str, Any], expected_log_sha256: Optional[str] = None,
    source_log_path: Optional[Union[str, Path]] = None,
) -> Optional[JudgedMetrics]:
    """Extracts judged metrics from an independent judge output log.

    Modern logs are validated and aggregated from records, never cached rates.
    Summary-only legacy files remain readable with an explicit validation warning.
    """
    if not isinstance(judged_payload, dict):
        return None

    source_info = judged_payload.get("source", {})
    actual_source_sha = source_info.get("sha256", "")

    if expected_log_sha256 and expected_log_sha256 != actual_source_sha:
        return None  # Incompatible judged log for this generation log

    if "judgments" in judged_payload:
        from src.evaluation.judge import (
            JudgeIdentity, JudgeOutputError, Rubric, check_resume_compatible,
            expected_rubric_decision, load_generation_log, parse_verdict,
            summarize_judgments, compute_passed,
        )
        entries = judged_payload["judgments"]
        if not isinstance(entries, list) or not entries:
            raise ValueError("Judged log must contain a non-empty judgments list.")
        # A copied artifact can retain an old machine's absolute source path.
        # Prefer the caller's actual generation log, whose bytes are still
        # checked against the saved hash before any verdict is accepted.
        source_path = source_log_path or source_info.get("path")
        if source_path:
            try:
                log = load_generation_log(source_path)
                identity = JudgeIdentity(**judged_payload["judge"])
                rubric_info = judged_payload["rubric"]
                # Comparison permits historical rubric hashes; it enforces the
                # current software consistency rules, not a new rubric identity.
                rubric = Rubric(rubric_info["version"], rubric_info["sha256"], "", Path(source_path))
                check_resume_compatible(judged_payload, log, identity, rubric)
            except (KeyError, TypeError, OSError) as exc:
                raise ValueError("Cannot verify judged log: restore its source log and identity metadata.") from exc
        else:
            warnings.warn(
                "Judged log has no source path: only saved record metadata can be verified; "
                "citation/source provenance cannot be checked.", RuntimeWarning, stacklevel=2,
            )
        verified = []
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("ticket_id") or entry["ticket_id"] in seen:
                raise ValueError("Judged log has invalid or duplicate ticket IDs.")
            seen.add(entry["ticket_id"])
            checked = dict(entry)
            status = entry.get("status")
            if status not in ("judged", "failed", "pending", "skipped_invalid_response"):
                raise ValueError("Judged log has an unknown record status.")
            if status == "judged":
                verdict = parse_verdict(json.dumps(entry.get("verdict")))
                action = entry.get("model_action")
                if verdict.decision != expected_rubric_decision(
                    entry.get("expected_action"), action, verdict.evidence_sufficient,
                ):
                    raise JudgeOutputError("inconsistent_verdict", "saved decision contradicts rubric table")
                if (action == "escalate") != (verdict.correctness == "not_applicable"):
                    raise JudgeOutputError("inconsistent_verdict", "saved correctness contradicts response action")
                missing = entry.get("citations_missing_from_evidence")
                if not isinstance(missing, list) or not all(isinstance(c, str) for c in missing):
                    raise ValueError("Judged log has no valid saved citation check.")
                checked["verdict"] = verdict.model_dump()
                checked["passed"] = compute_passed(verdict, missing)
            elif entry.get("verdict") is not None or entry.get("passed") is not None:
                raise ValueError("Unscored judgment must not carry a verdict or pass result.")
            verified.append(checked)
        summary = summarize_judgments(verified)
    else:
        if "schema_version" in judged_payload:
            raise ValueError("Modern judged log is missing its judgments; cached summary is not sufficient.")
        warnings.warn(
            "Legacy summary-only judged log: verdict consistency and source evidence cannot be verified; "
            "reported rates are historical, unvalidated summaries.", RuntimeWarning, stacklevel=2,
        )
        summary = judged_payload.get("summary", {})
    overall = summary.get("overall", {})
    judge_info = judged_payload.get("judge", {})
    rubric_info = judged_payload.get("rubric", {})

    total = overall.get("records", overall.get("total", len(judged_payload.get("judgments", []))))
    judged = overall.get("judged", 0)
    failed = overall.get("failed_judgments", overall.get("failed", 0))

    rates = overall.get("rates", {})
    dimensions = overall.get("dimensions", {})
    def dimension_rate(name, label, denominator):
        return dimensions.get(name, {}).get(label, 0) / denominator if denominator else None
    answer_count = overall.get("answer_responses_judged", 0)
    citation_counts = dimensions.get("citation_support", {})
    citation_count = judged - citation_counts.get("not_applicable", 0)
    escalations = [e for e in judged_payload.get("judgments", []) if e.get("status") == "judged" and e.get("model_action") == "escalate"]
    coverage = (judged / total) if total > 0 else 0.0

    return JudgedMetrics(
        judge_model=judge_info.get("model", "unknown"),
        rubric_version=rubric_info.get("version", "unknown"),
        total_records=total,
        judged_records=judged,
        failed_records=failed,
        coverage_rate=round(coverage, 4),
        overall_pass_rate=overall.get("strict_pass_rate", rates.get("passed")),
        correctness_rate=dimension_rate("correctness", "correct", answer_count) if dimensions else rates.get("correctness"),
        groundedness_rate=dimension_rate("groundedness", "fully_grounded", judged) if dimensions else rates.get("groundedness"),
        citation_support_rate=dimension_rate("citation_support", "supported", citation_count) if dimensions else rates.get("citation_support"),
        escalation_validity_rate=(sum(e["verdict"]["decision"] == "appropriate" for e in escalations) / len(escalations) if escalations else rates.get("escalation_validity")),
        source_log_sha256=actual_source_sha,
        rubric_sha256=rubric_info.get("sha256", ""),
        judge_provider=judge_info.get("provider", ""),
    )


# ---------------------------------------------------------------------------
# Unified Model Evaluation Summary
# ---------------------------------------------------------------------------

@dataclass
class ModelEvaluationSummary:
    """Standardized summary of an evaluation run for comparison."""
    model_name: str
    model_role: str  # "base_student", "finetuned_student", "teacher", or "other"
    context_mode: str  # "ground_truth" or "retriever"
    timestamp: str
    total_eval: int
    benchmark_file: str
    benchmark_sha256: Optional[str]

    # Core Decisions and Groundedness
    action_accuracy: Optional[float]
    escalation_precision: Optional[float]
    escalation_recall: Optional[float]
    escalation_f1: Optional[float]
    schema_validity_rate: Optional[float]
    # Explicitly labeled proxy metric:
    absent_answer_action_proxy: Optional[float]

    # Latency Distributions (distinguishing generation from end-to-end)
    generation_latency: Optional[LatencyDistribution]
    e2e_latency: Optional[LatencyDistribution]
    avg_tokens_per_second: Optional[float]

    # Token and Cost Accounting
    tokens_and_cost: TokenCostMetrics

    # Hardware Metadata
    hardware: Optional[Dict[str, Any]]

    # Independently Judged Quality (optional)
    judged_metrics: Optional[JudgedMetrics] = None


def summarize_evaluation_log(
    log_data: Dict[str, Any],
    log_path: Optional[Path | str] = None,
    judged_payload: Optional[Dict[str, Any]] = None,
    pricing: Optional[ModelPricing] = None,
) -> ModelEvaluationSummary:
    """Parses and computes standardized metrics from a generation evaluation log."""
    if log_data.get("run_status") not in (None, "completed"):
        raise ValueError("Incomplete evaluation logs are diagnostic artifacts, not completed comparison baselines.")
    model_name = log_data.get("model", "unknown_model")
    metrics = log_data.get("metrics", {})
    records = log_data.get("records", [])
    counts = metrics.get("counts", {})

    total_eval = metrics.get("total_eval") or counts.get("total_eval") or len(records)
    context_mode = metrics.get("context_mode") or log_data.get("context_mode", "unknown")

    # Determine role heuristic
    name_lower = model_name.lower()
    if "qlora" in name_lower or "finetuned" in name_lower or "student-ft" in name_lower:
        role = "finetuned_student"
    elif "gemini" in name_lower or "claude" in name_lower or "gpt" in name_lower or "teacher" in name_lower:
        role = "teacher"
    else:
        role = "base_student"

    role = log_data.get("model_role") or role

    # Core Decision Metrics
    action_accuracy = float(metrics["action_accuracy"]) if metrics.get("action_accuracy") is not None else None
    esc_p = float(metrics["escalation_precision"]) if metrics.get("escalation_precision") is not None else None
    esc_r = float(metrics["escalation_recall"]) if metrics.get("escalation_recall") is not None else None
    esc_f1 = float(metrics["escalation_f1"]) if metrics.get("escalation_f1") is not None else None
    schema_validity = float(metrics["schema_validity_rate"]) if metrics.get("schema_validity_rate") is not None else None

    # Absent-answer action proxy (labeled proxy, NOT full hallucination detection)
    absent_total = counts.get("absent_total", 0)
    absent_hallucinated = counts.get("absent_hallucinated", 0)
    if absent_total > 0:
        absent_proxy = absent_hallucinated / absent_total
    elif "absent_total" not in counts and "hallucination_rate" in metrics:
        absent_proxy = float(metrics["hallucination_rate"])
    else:
        absent_proxy = None

    # Latencies
    gen_latencies: List[float] = []
    e2e_latencies: List[float] = []
    tokens_per_sec: List[float] = []

    for r in records:
        if "generation_latency_ms" in r and r["generation_latency_ms"] is not None:
            gen_latencies.append(float(r["generation_latency_ms"]))
        elif "latency_ms" in r and r["latency_ms"] is not None:
            gen_latencies.append(float(r["latency_ms"]))

        if "e2e_latency_ms" in r and r["e2e_latency_ms"] is not None:
            e2e_latencies.append(float(r["e2e_latency_ms"]))

        if "tokens_per_second" in r and r["tokens_per_second"] is not None:
            tokens_per_sec.append(float(r["tokens_per_second"]))

    gen_dist = LatencyDistribution.from_latencies(gen_latencies)
    e2e_dist = LatencyDistribution.from_latencies(e2e_latencies) if e2e_latencies else None

    avg_speed = round(mean(tokens_per_sec), 2) if tokens_per_sec else metrics.get("avg_tokens_per_second")

    # Pricing & Tokens
    resolved_pricing = pricing or get_model_pricing(model_name)
    token_metrics = calculate_token_metrics(records, resolved_pricing)
    stored_cost = metrics.get("token_cost_metrics")
    if pricing is None and isinstance(stored_cost, dict):
        token_metrics = TokenCostMetrics(**stored_cost)

    # Hardware metadata
    hw = log_data.get("hardware") or metrics.get("hardware")

    # Benchmark metadata
    b_file = metrics.get("benchmark_file") or log_data.get("benchmark_file") or "unknown"
    b_sha = metrics.get("benchmark_sha256") or log_data.get("benchmark_sha256")

    # Judged metrics if supplied
    log_sha = compute_file_sha256(log_path) if log_path and Path(log_path).exists() else None
    judged_metrics = extract_judged_metrics(judged_payload, log_sha, log_path) if judged_payload else None

    return ModelEvaluationSummary(
        model_name=model_name,
        model_role=role,
        context_mode=context_mode,
        timestamp=log_data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        total_eval=total_eval,
        benchmark_file=b_file,
        benchmark_sha256=b_sha,
        action_accuracy=round(action_accuracy, 4) if action_accuracy is not None else None,
        escalation_precision=round(esc_p, 4) if esc_p is not None else None,
        escalation_recall=round(esc_r, 4) if esc_r is not None else None,
        escalation_f1=round(esc_f1, 4) if esc_f1 is not None else None,
        schema_validity_rate=round(schema_validity, 4) if schema_validity is not None else None,
        absent_answer_action_proxy=round(absent_proxy, 4) if absent_proxy is not None else None,
        generation_latency=gen_dist,
        e2e_latency=e2e_dist,
        avg_tokens_per_second=avg_speed,
        tokens_and_cost=token_metrics,
        hardware=hw,
        judged_metrics=judged_metrics,
    )


# ---------------------------------------------------------------------------
# Multi-Model Comparison Engine
# ---------------------------------------------------------------------------

@dataclass
class ComparisonReport:
    """Complete comparative analysis across multiple models."""
    generated_at: str
    compatibility: CompatibilityReport
    summaries: List[ModelEvaluationSummary]
    teacher_recoveries: List[TeacherRecoveryResult]
    notes: List[str] = field(default_factory=list)


def compare_evaluations(
    logs: Sequence[Dict[str, Any]],
    log_paths: Optional[Sequence[Path | str]] = None,
    judged_payloads: Optional[Sequence[Optional[Dict[str, Any]]]] = None,
    pricing_catalog: Optional[Dict[str, ModelPricing]] = None,
    base_model_name: Optional[str] = None,
    teacher_model_name: Optional[str] = None,
) -> ComparisonReport:
    """Executes a full comparison across multiple model evaluation logs."""
    compatibility = check_comparison_compatibility(logs)

    summaries: List[ModelEvaluationSummary] = []
    for idx, log in enumerate(logs):
        l_path = log_paths[idx] if log_paths and idx < len(log_paths) else None
        j_payload = judged_payloads[idx] if judged_payloads and idx < len(judged_payloads) else None
        model_name = log.get("model", f"model_{idx}")
        pricing = get_model_pricing(model_name, pricing_catalog) if pricing_catalog else None
        summary = summarize_evaluation_log(log, l_path, j_payload, pricing)
        summaries.append(summary)

    # Identify base student, fine-tuned student, and teacher
    base_summary: Optional[ModelEvaluationSummary] = None
    teacher_summary: Optional[ModelEvaluationSummary] = None
    student_summary: Optional[ModelEvaluationSummary] = None

    for s in summaries:
        if teacher_model_name and s.model_name == teacher_model_name:
            teacher_summary = s
        elif s.model_role == "teacher" and teacher_summary is None:
            teacher_summary = s

        if base_model_name and s.model_name == base_model_name:
            base_summary = s
        elif s.model_role == "base_student" and base_summary is None:
            base_summary = s

        if s.model_role == "finetuned_student" and student_summary is None:
            student_summary = s

    # Fallback assignment if only 2 models are compared
    if student_summary is None and len(summaries) >= 2:
        for s in summaries:
            if s != base_summary and s != teacher_summary:
                student_summary = s
                break

    # Calculate Teacher Recovery metrics
    recoveries: List[TeacherRecoveryResult] = []
    if teacher_summary and student_summary and compatibility.is_compatible:
        target_student = student_summary
        b_sum = base_summary

        metrics_to_evaluate = [
            ("action_accuracy", target_student.action_accuracy, teacher_summary.action_accuracy, b_sum.action_accuracy if b_sum else None, False),
            ("escalation_f1", target_student.escalation_f1, teacher_summary.escalation_f1, b_sum.escalation_f1 if b_sum else None, False),
            ("escalation_recall", target_student.escalation_recall, teacher_summary.escalation_recall, b_sum.escalation_recall if b_sum else None, False),
            ("schema_validity_rate", target_student.schema_validity_rate, teacher_summary.schema_validity_rate, b_sum.schema_validity_rate if b_sum else None, False),
            ("absent_answer_action_proxy", target_student.absent_answer_action_proxy, teacher_summary.absent_answer_action_proxy, b_sum.absent_answer_action_proxy if b_sum else None, True),
        ]

        # Add judged metric if available on both
        if (target_student.judged_metrics and teacher_summary.judged_metrics
            and target_student.judged_metrics.coverage_rate == 1.0
            and teacher_summary.judged_metrics.coverage_rate == 1.0
            and target_student.judged_metrics.judge_model == teacher_summary.judged_metrics.judge_model
            and target_student.judged_metrics.rubric_version == teacher_summary.judged_metrics.rubric_version
            and target_student.judged_metrics.rubric_sha256 == teacher_summary.judged_metrics.rubric_sha256
            and target_student.judged_metrics.judge_provider == teacher_summary.judged_metrics.judge_provider):
            metrics_to_evaluate.append((
                "judged_pass_rate",
                target_student.judged_metrics.overall_pass_rate,
                teacher_summary.judged_metrics.overall_pass_rate,
                b_sum.judged_metrics.overall_pass_rate if (b_sum and b_sum.judged_metrics) else None,
                False,
            ))

        if any(item[0] == "judged_pass_rate" for item in metrics_to_evaluate):
            metrics_to_evaluate.append((
                "judged_groundedness_rate", target_student.judged_metrics.groundedness_rate,
                teacher_summary.judged_metrics.groundedness_rate, None, False,
            ))

        for name, s_val, t_val, b_val, is_inv in metrics_to_evaluate:
            rec = calculate_teacher_recovery(
                metric_name=name,
                student_value=s_val,
                teacher_value=t_val,
                base_value=b_val,
                is_inverse=is_inv,
            )
            recoveries.append(rec)

    notes = [
        "Absent-Answer Action Proxy measures the rate of answering provably absent questions. It is an empirical action proxy, NOT comprehensive hallucination detection.",
        "Local models exhibit $0.00 API token cost. Local compute, memory, and energy requirements are reported separately under hardware metadata.",
        "Unrelated metrics are intentionally kept distinct; no composite single score is computed to prevent obscuring critical trade-offs.",
    ]

    return ComparisonReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        compatibility=compatibility,
        summaries=summaries,
        teacher_recoveries=recoveries,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Formatting and Reporting (Markdown and Text Tables)
# ---------------------------------------------------------------------------

def _fmt_pct(val: Optional[float]) -> str:
    return f"{val * 100:.1f}%" if val is not None else "N/A"


def _fmt_ms(val: Optional[float]) -> str:
    return f"{val:.1f} ms" if val is not None else "N/A"


def _fmt_cost(val: Optional[float], is_local: bool) -> str:
    if is_local:
        return "$0.00 (Local)"
    return f"${val:.4f}" if val is not None else "Not measured"


def format_comparison_markdown(report: ComparisonReport) -> str:
    """Renders comprehensive comparison report in GitHub-flavored Markdown."""
    lines: List[str] = [
        "# Model Baseline & Comparison Report",
        "",
        f"**Generated:** `{report.generated_at}`  ",
        f"**Evaluation Compatibility:** {'✅ Compatible' if report.compatibility.is_compatible else '⚠️ Warnings/Incompatible'}",
        "",
    ]

    if report.compatibility.issues:
        lines.append("### Compatibility Notice")
        for issue in report.compatibility.issues:
            icon = "🔴" if issue.severity == "ERROR" else "⚠️" if issue.severity == "WARNING" else "ℹ️"
            lines.append(f"- {icon} **{issue.category}**: {issue.message}")
        lines.append("")

    # Table 1: Core Decisions & Quality
    lines.extend([
        "## 1. Decision Quality & Groundedness",
        "",
        "| Model | Role | Context Mode | Questions | Schema Valid | Action Acc | Esc Precision | Esc Recall | Esc F1 | Absent-Answer Proxy* | Judged Pass Rate (all records) | Judge Coverage |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for s in report.summaries:
        judged_str = _fmt_pct(s.judged_metrics.overall_pass_rate) if s.judged_metrics else "Not Judged"
        lines.append(
            f"| `{s.model_name}` | {s.model_role} | `{s.context_mode}` | {s.total_eval} | "
            f"{_fmt_pct(s.schema_validity_rate)} | {_fmt_pct(s.action_accuracy)} | "
            f"{_fmt_pct(s.escalation_precision)} | {_fmt_pct(s.escalation_recall)} | "
            f"{_fmt_pct(s.escalation_f1)} | {_fmt_pct(s.absent_answer_action_proxy)} | {judged_str} | {_fmt_pct(s.judged_metrics.coverage_rate) if s.judged_metrics else 'N/A'} |"
        )
    lines.extend([
        "",
        "> `*` **Absent-Answer Action Proxy**: Rate of answering unanswerable questions where documentation is absent. "
        "This is an empirical action proxy, **not comprehensive hallucination detection**.",
        "",
    ])

    # Table 2: Latency & Throughput
    lines.extend([
        "## 2. Latency Distributions & Throughput",
        "",
        "| Model | Gen Latency p50 | Gen Latency p90 | Gen Latency p95 | Gen Mean | E2E Latency p50 | E2E Latency p95 | Throughput |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for s in report.summaries:
        g = s.generation_latency
        e = s.e2e_latency
        speed = f"{s.avg_tokens_per_second:.1f} t/s" if s.avg_tokens_per_second is not None else "N/A"
        lines.append(
            f"| `{s.model_name}` | {_fmt_ms(g.p50_ms if g else None)} | {_fmt_ms(g.p90_ms if g else None)} | "
            f"{_fmt_ms(g.p95_ms if g else None)} | {_fmt_ms(g.mean_ms if g else None)} | "
            f"{_fmt_ms(e.p50_ms if e else None)} | {_fmt_ms(e.p95_ms if e else None)} | {speed} |"
        )
    lines.append("")

    # Table 3: Token Usage & Cost
    lines.extend([
        "## 3. Token Usage & Cost Projections (per 1,000 Queries)",
        "",
        "| Model | Avg Prompt Tok | Avg Compl Tok | Avg Total Tok | Cost / 1k Queries | Pricing Source |",
        "| :--- | :---: | :---: | :---: | :---: | :--- |",
    ])
    for s in report.summaries:
        tc = s.tokens_and_cost
        cost_str = _fmt_cost(tc.cost_per_1k_queries, tc.is_local)
        lines.append(
            f"| `{s.model_name}` | {tc.avg_prompt_tokens if tc.avg_prompt_tokens is not None else 'N/A'} | {tc.avg_completion_tokens if tc.avg_completion_tokens is not None else 'N/A'} | "
            f"{tc.avg_total_tokens if tc.avg_total_tokens is not None else 'N/A'} | **{cost_str}** | {tc.pricing_source} |"
        )
    lines.append("")

    # Table 4: Teacher Recovery (if applicable)
    if report.teacher_recoveries:
        lines.extend([
            "## 4. Teacher Recovery & Gap Analysis",
            "",
            "Explicit comparison of the student model against the teacher target.",
            "",
            "| Metric | Base Student | Fine-Tuned Student | Teacher Model | Student/Teacher Ratio | Gap Closed (vs Base) | Status / Notes |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
        ])
        for r in report.teacher_recoveries:
            fmt = _fmt_pct
            s_val = fmt(r.student_value)
            t_val = fmt(r.teacher_value)
            b_val = fmt(r.base_value) if r.base_value is not None else "None"
            ratio_str = _fmt_pct(r.recovery_ratio) if r.recovery_ratio is not None else "N/A"
            gap_str = _fmt_pct(r.gap_closed) if r.gap_closed is not None else "N/A"
            lines.append(
                f"| `{r.metric_name}` | {b_val} | **{s_val}** | {t_val} | {ratio_str} | **{gap_str}** | {r.notes} |"
            )
        lines.extend([
            "",
            "> **Formulas:**",
            "> - **Performance Ratio:** `Student / Teacher` (for inverse metrics: `Teacher / Student`).",
            "> - **Gap Closed:** `(Student - Base) / (Teacher - Base)` (for inverse metrics: `(Base - Student) / (Base - Teacher)`).",
            "> - Missing values are left as `N/A` (never zero). Zero denominators are explicitly guarded and reported as `N/A`.",
            "",
        ])

    # Table 5: Hardware Metadata
    lines.extend([
        "## 5. Hardware & Environment Metadata",
        "",
        "| Model | OS / Platform | CPU Model | Logical Cores | System RAM | GPU Details |",
        "| :--- | :--- | :--- | :---: | :--- | :--- |",
    ])
    for s in report.summaries:
        h = s.hardware or {}
        gpu_desc = ", ".join(h.get("gpu_info") or []) if h.get("gpu_info") else "None detected"
        lines.append(
            f"| `{s.model_name}` | {h.get('os_name', 'Linux')} ({h.get('architecture', 'x86_64')}) | "
            f"{h.get('cpu_model', 'Unknown CPU')} | {h.get('cpu_count_logical', 'N/A')} | "
            f"{h.get('ram_total_human', 'N/A')} | {gpu_desc} |"
        )
    lines.append("")

    return "\n".join(lines)


def format_comparison_text(report: ComparisonReport) -> str:
    """Renders formatted ASCII table summary for terminal viewing."""
    out: List[str] = [
        "=" * 100,
        "MODEL BASELINE COMPARISON & BENCHMARK SCORECARD",
        f"Generated: {report.generated_at}",
        f"Compatibility: {'Compatible' if report.compatibility.is_compatible else 'Incompatible / Warnings'}",
        "=" * 100,
        "",
        f"{'Model':<24} {'Context':<14} {'Questions':<10} {'Schema':<9} {'ActionAcc':<11} {'EscF1':<9} {'AbsentProxy*':<13} {'PassRate':<10}",
        "-" * 100,
    ]
    for s in report.summaries:
        judged_str = _fmt_pct(s.judged_metrics.overall_pass_rate) if s.judged_metrics else "N/A"
        out.append(
            f"{s.model_name:<24} {s.context_mode:<14} {s.total_eval:<10} "
            f"{_fmt_pct(s.schema_validity_rate):<9} {_fmt_pct(s.action_accuracy):<11} "
            f"{_fmt_pct(s.escalation_f1):<9} {_fmt_pct(s.absent_answer_action_proxy):<13} {judged_str:<10}"
        )
    out.extend([
        "-" * 100,
        "* Absent-Answer Action Proxy: Empirical proxy only; not full hallucination detection.",
        "",
        "LATENCY DISTRIBUTIONS & THROUGHPUT:",
        f"{'Model':<24} {'Gen p50':<12} {'Gen p95':<12} {'Gen Mean':<12} {'E2E p50':<12} {'E2E p95':<12} {'Speed':<12}",
        "-" * 100,
    ])
    for s in report.summaries:
        g = s.generation_latency
        e = s.e2e_latency
        speed = f"{s.avg_tokens_per_second:.1f} t/s" if s.avg_tokens_per_second is not None else "N/A"
        out.append(
            f"{s.model_name:<24} {_fmt_ms(g.p50_ms if g else None):<12} {_fmt_ms(g.p95_ms if g else None):<12} "
            f"{_fmt_ms(g.mean_ms if g else None):<12} {_fmt_ms(e.p50_ms if e else None):<12} "
            f"{_fmt_ms(e.p95_ms if e else None):<12} {speed:<12}"
        )
    out.extend([
        "-" * 100,
        "",
        "COST PROJECTIONS PER 1,000 QUERIES:",
        f"{'Model':<24} {'Prompt Tok':<14} {'Compl Tok':<14} {'Cost / 1k Queries':<20} {'Source':<26}",
        "-" * 100,
    ])
    for s in report.summaries:
        tc = s.tokens_and_cost
        cost_str = _fmt_cost(tc.cost_per_1k_queries, tc.is_local)
        out.append(
            f"{s.model_name:<24} {str(tc.avg_prompt_tokens or 'N/A'):<14} {str(tc.avg_completion_tokens or 'N/A'):<14} "
            f"{cost_str:<20} {tc.pricing_source[:26]:<26}"
        )

    if report.teacher_recoveries:
        out.extend([
            "-" * 100,
            "",
            "TEACHER RECOVERY & GAP ANALYSIS:",
            f"{'Metric':<28} {'Base':<10} {'Student':<10} {'Teacher':<10} {'Ratio':<12} {'Gap Closed':<12}",
            "-" * 100,
        ])
        for r in report.teacher_recoveries:
            s_val = _fmt_pct(r.student_value)
            t_val = _fmt_pct(r.teacher_value)
            b_val = _fmt_pct(r.base_value) if r.base_value is not None else "N/A"
            ratio_str = _fmt_pct(r.recovery_ratio) if r.recovery_ratio is not None else "N/A"
            gap_str = _fmt_pct(r.gap_closed) if r.gap_closed is not None else "N/A"
            out.append(f"{r.metric_name:<28} {b_val:<10} {s_val:<10} {t_val:<10} {ratio_str:<12} {gap_str:<12}")

    out.append("=" * 100)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Safe Output Naming
# ---------------------------------------------------------------------------

def generate_safe_log_path(
    base_dir: Path | str, prefix: str, model_name: str, context_mode: str, ext: str = ".json"
) -> Path:
    """Generates a collision-safe output path that never overwrites existing files."""
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    safe_model = re.sub(r"[^\w.-]+", "_", model_name)
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d_%H%M%S")

    # Start with standard timestamp
    candidate = base / f"{prefix}_{safe_model}_{context_mode}_{timestamp}{ext}"
    if not candidate.exists():
        return candidate

    # Append counter if file exists
    counter = 1
    while True:
        candidate = base / f"{prefix}_{safe_model}_{context_mode}_{timestamp}_{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


# ---------------------------------------------------------------------------
# Pluggable Teacher Adapter Interface and Implementations
# ---------------------------------------------------------------------------

class TeacherAdapter(Protocol):
    """Protocol for model inference adapters matching the client.generate_raw interface."""
    model: str

    def generate_raw(
        self, query: str, context: str, history: Optional[list] = None
    ) -> Tuple[str, Dict[str, float]]:
        """Returns raw JSON string and timing/metrics dictionary."""
        ...


class MockTeacherAdapter:
    """Offline test adapter returning synthetic responses without network calls or GPU usage."""

    def __init__(
        self,
        model: str = "mock-teacher",
        action: Literal["answer", "escalate"] = "answer",
        latency_ms: float = 120.0,
        tokens_per_second: float = 85.0,
        prompt_tokens: int = 450,
        eval_tokens: int = 65,
    ):
        self.model = model
        self.action = action
        self.latency_ms = latency_ms
        self.tokens_per_second = tokens_per_second
        self.prompt_tokens = prompt_tokens
        self.eval_tokens = eval_tokens

    def generate_raw(
        self, query: str, context: str, history: Optional[list] = None
    ) -> Tuple[str, Dict[str, float]]:
        time.sleep(0.001)  # tiny sleep for measurement realism
        if self.action == "answer":
            content = {
                "answer": f"Mock teacher answer for: {query[:30]}",
                "cited_sources": ["mock_doc.md"],
                "confidence": 0.95,
                "action": "answer",
            }
        else:
            content = {
                "answer": "This request requires escalation to a human representative.",
                "cited_sources": [],
                "confidence": 0.90,
                "action": "escalate",
            }
        timing = {
            "latency_ms": self.latency_ms,
            "eval_tokens": self.eval_tokens,
            "prompt_tokens": self.prompt_tokens,
            "total_tokens": self.prompt_tokens + self.eval_tokens,
            "tokens_per_second": self.tokens_per_second,
        }
        return json.dumps(content), timing


class TeacherRequestError(RuntimeError):
    """A remote request failed; its message deliberately excludes provider content."""

    def __init__(self, error_type: str, http_status: Optional[int] = None,
                 diagnostics: Optional[dict] = None):
        self.error_type = error_type
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        self.diagnostics = dict(diagnostics or {})
        status = f"; HTTP {self.http_status}" if self.http_status is not None else ""
        super().__init__(f"Gemini request failed ({error_type}{status}).")


def _http_error_status(exc: Exception) -> Optional[int]:
    """Extract only a numeric HTTP status, never provider text or request data."""
    for value in (getattr(exc, "http_status", None), getattr(exc, "code", None),
                  getattr(exc, "status_code", None), getattr(getattr(exc, "response", None), "status_code", None)):
        if type(value) is int and 100 <= value <= 599:
            return value
    return None


def _teacher_error_diagnostics(exc: Exception) -> dict:
    """Keep allowlisted quota codes and numeric delays, never provider messages.

    Interactions errors expose a body and HTTP response. Do not serialize either:
    they can contain prompts, credentials, project identifiers and request URLs.
    """
    allowed_codes = {"rate_limit_exceeded", "quota_exceeded", "too_many_requests", "resource_exhausted"}
    result = {}
    # Already-redacted adapter errors also pass through baseline/probe handling.
    saved = getattr(exc, "diagnostics", None)
    if isinstance(saved, dict):
        if isinstance(saved.get("provider_code"), str) and saved["provider_code"] in allowed_codes:
            result["provider_code"] = saved["provider_code"]
        delay = saved.get("retry_after_seconds")
        if type(delay) in (int, float) and math.isfinite(delay) and delay >= 0:
            result["retry_after_seconds"] = delay
        return result

    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    if not isinstance(error, dict):
        error = {}
    for field in ("code", "status"):
        code = error.get(field)
        if isinstance(code, str) and code.lower() in allowed_codes:
            result["provider_code"] = code.lower()
            break

    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    delay = headers.get("retry-after") if headers is not None else None
    if isinstance(delay, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", delay) and len(delay) <= 20:
        result["retry_after_seconds"] = float(delay)
    else:
        details = error.get("details", [])
        for detail in details if isinstance(details, list) else []:
            if isinstance(detail, dict) and detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                delay = detail.get("retryDelay")
                if isinstance(delay, str) and len(delay) <= 21 and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?s", delay):
                    result["retry_after_seconds"] = float(delay[:-1])
                    break
    return result


class BaselineExecutionError(RuntimeError):
    """An incomplete run was saved separately from completed baseline runs."""


def validate_teacher_runtime(timeout_seconds: float, max_attempts: int) -> None:
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or not math.isfinite(timeout_seconds * 1000)
            or timeout_seconds <= 0
            or timeout_seconds * 1000 < 1):
        raise ValueError("teacher timeout must be finite and at least 0.001 seconds")
    if type(max_attempts) is not int or max_attempts < 1:
        raise ValueError("teacher max attempts must be a positive integer (including the initial request)")


def resolve_gemini_api_key(api_key: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Return (key, source), preferring the project .env over the shell.

    Read .env directly so an inherited shell key cannot shadow the project key.
    The source label is safe to log; the credential is not.
    """
    if api_key:
        return api_key, "argument"
    from dotenv import dotenv_values, find_dotenv
    dotenv_file = find_dotenv(usecwd=True)
    env_file_key = dotenv_values(dotenv_file).get("GEMINI_API_KEY") if dotenv_file else None
    if env_file_key:
        return env_file_key, ".env"
    shell_key = os.getenv("GEMINI_API_KEY")
    return (shell_key, "environment") if shell_key else (None, None)


class GeminiTeacherAdapter:
    """Stateless synchronous Interactions API teacher with explicit usage accounting."""

    GENERATION_CONFIG = {"thinking_level": "medium", "max_output_tokens": 65536}

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = 60.0,
        max_attempts: int = 1,
    ):
        validate_teacher_runtime(timeout_seconds, max_attempts)
        from dotenv import find_dotenv, load_dotenv
        load_dotenv(find_dotenv(usecwd=True), override=False)

        requested_model = model or os.getenv("TEACHER_MODEL")
        if not requested_model or not requested_model.strip():
            raise ValueError("Set TEACHER_MODEL to the actual model used for dataset generation.")
        # Keep the billing/log identity stable when callers use the resource form.
        self.model = requested_model.removeprefix("models/")
        if not self.model or "/" in self.model:
            raise ValueError("Use a Gemini model ID or its models/MODEL resource name.")
        self.api_model = f"models/{self.model}"
        resolved_key, key_source = resolve_gemini_api_key(api_key)
        if not resolved_key or "<api-key>" in resolved_key or "your_" in resolved_key:
            raise ValueError(
                "Gemini API key is missing or contains placeholders. "
                "Set GEMINI_API_KEY in your .env or run with --dry-run."
            )

        from google import genai
        from google.genai import types
        self.request_settings = {"api": "interactions", "model_resource": self.api_model,
                                 "timeout_seconds": float(timeout_seconds), "timeout_scope": "client_transport_only",
                                 "server_timeout_header": False, "max_attempts": max_attempts,
                                 "attempts_include_initial_request": True, "store": False,
                                 "api_key_source": key_source}
        self.generation_config = dict(self.GENERATION_CONFIG)
        self.client = genai.Client(
            api_key=resolved_key,
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=max_attempts),
            ),
        )
        # SDK 2.30.1 clamps attempts=0 to 1, then its Interactions bridge
        # interprets attempts as *retries*. Set the generated resource's retry
        # budget explicitly so CLI total attempts never cause an extra call.
        # Real-SDK MockTransport tests guard this integration boundary.
        self.client.interactions.sdk_configuration.retry_config.max_retries = max_attempts - 1
        self.temperature = None

    @staticmethod
    def _build_user_prompt(query: str, context: str, history: Optional[list] = None) -> str:
        from src.inference.client import SupportInferenceClient
        return SupportInferenceClient.build_user_prompt(query, context, history)

    def request_interaction(self, text: str, *, system_instruction: Optional[str] = None,
                            response_schema: Optional[dict] = None):
        """Make a synchronous request; never poll or reuse state across questions."""
        arguments = {"model": self.api_model, "input": text,
                     "generation_config": dict(self.generation_config), "store": False,
                     "background": False, "stream": False,
                     # SDK Interactions per-call timeout is in seconds and is
                     # applied to the HTTP transport, not a server deadline.
                     "timeout": self.request_settings["timeout_seconds"]}
        if system_instruction is not None:
            arguments["system_instruction"] = system_instruction
        if response_schema is not None:
            arguments["response_format"] = {"type": "text", "mime_type": "application/json",
                                            "schema": response_schema}
        try:
            interaction = self.client.interactions.create(**arguments)
        except Exception as exc:
            raise TeacherRequestError(type(exc).__name__, _http_error_status(exc),
                                      _teacher_error_diagnostics(exc)) from None
        if getattr(interaction, "status", None) != "completed":
            raise TeacherRequestError("InteractionNotCompleted")
        return interaction

    @staticmethod
    def output_text(interaction) -> str:
        text = getattr(interaction, "output_text", None)
        if isinstance(text, str) and text:
            return text
        # Never treat thought summaries, user inputs, or tool output as an answer.
        for step in reversed(getattr(interaction, "steps", None) or []):
            if getattr(step, "type", None) == "model_output":
                return "".join(part.text for part in (getattr(step, "content", None) or [])
                               if getattr(part, "type", None) == "text" and isinstance(getattr(part, "text", None), str))
        return ""

    @staticmethod
    def token_usage(interaction) -> dict:
        usage = getattr(interaction, "usage", None)
        return {key: value if type(value) is int and value >= 0 else None
                for key in ("total_input_tokens", "total_output_tokens", "total_thought_tokens", "total_tokens")
                for value in (getattr(usage, key, None),)}

    def generate_raw(
        self, query: str, context: str, history: Optional[list] = None
    ) -> Tuple[str, Dict[str, float]]:
        from src.inference.client import SYSTEM_PROMPT
        from src.inference.schema import SupportResponse

        user_content = self._build_user_prompt(query, context, history)
        start_time = time.perf_counter()
        interaction = self.request_interaction(user_content, system_instruction=SYSTEM_PROMPT,
                                               response_schema=SupportResponse.model_json_schema())
        duration_sec = time.perf_counter() - start_time
        latency_ms = duration_sec * 1000.0
        raw_text = self.output_text(interaction)
        usage = self.token_usage(interaction)
        prompt_tokens = usage["total_input_tokens"]
        output_tokens, thoughts = usage["total_output_tokens"], usage["total_thought_tokens"]
        eval_tokens = None
        if output_tokens is not None and thoughts is not None:
            eval_tokens = output_tokens + thoughts
        elif (prompt_tokens is not None and usage["total_tokens"] is not None
              and usage["total_tokens"] >= prompt_tokens):
            # No tools are enabled. The remaining total includes internal thinking.
            eval_tokens = usage["total_tokens"] - prompt_tokens

        tokens_per_sec = (eval_tokens / duration_sec) if eval_tokens is not None and duration_sec > 0 else 0.0
        timing = {
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "eval_tokens": eval_tokens,
            "output_tokens": output_tokens,
            "thought_tokens": thoughts,
            "total_tokens": (prompt_tokens + eval_tokens) if prompt_tokens is not None and eval_tokens is not None else None,
            "tokens_per_second": tokens_per_sec,
        }
        return raw_text, timing


# ---------------------------------------------------------------------------
# Baseline Evaluation Orchestration Runner
# ---------------------------------------------------------------------------

def run_baseline_evaluation(
    client: Any,
    retriever: Any,
    questions: Sequence[Dict[str, Any]],
    use_retriever: bool = False,
    benchmark_file: Optional[Path | str] = None,
    benchmark_metadata: Optional[Dict[str, Any]] = None,
    output_dir: Optional[Path | str] = None,
    pricing: Optional[ModelPricing] = None,
    model_role: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Path]:
    """Runs generation evaluation on a model, recording end-to-end and generation latency.

    Safe output naming prevents overwriting existing logs.
    """
    from src.evaluation.generation import (
        build_ground_truth_context,
        calculate_metrics,
        PROJECT_ROOT,
    )
    from src.inference.schema import SupportResponse
    from pydantic import ValidationError

    if use_retriever and retriever is None:
        raise ValueError("A retriever is required when use_retriever=True.")

    counts = dict.fromkeys([
        "TP", "FP", "FN", "TN", "total_eval", "schema_valid", "schema_invalid",
        "absent_total", "absent_hallucinated", "invalid_absent",
    ], 0)

    records: List[Dict[str, Any]] = []
    gen_latencies: List[float] = []
    e2e_latencies: List[float] = []
    tokens_per_sec: List[float] = []

    model_name = getattr(client, "model", "unknown_model")
    context_mode = "retriever" if use_retriever else "ground_truth"

    # Read-only discovery before/after the run. Mocks and remote teachers do not
    # pretend to expose local Ollama configuration, or make extra API requests.
    from src.inference.client import SupportInferenceClient
    serving_before = client.get_serving_metadata() if isinstance(client, SupportInferenceClient) else None
    run_failure = None

    for index, question in enumerate(questions, 1):
        query, expected = question["customer_query"], question["ground_truth_action"]

        e2e_start = time.perf_counter()
        retrieval_ms = 0.0

        if use_retriever:
            r_start = time.perf_counter()
            chunks = retriever.retrieve(query=query, tenant_id=question["tenant"])
            retrieval_ms = (time.perf_counter() - r_start) * 1000.0
            if any(chunk.get("tenant_id") != question["tenant"] for chunk in chunks):
                raise RuntimeError(f"Cross-tenant retrieval detected for {question['ticket_id']}")
            context = retriever.format_context(chunks)
        else:
            context = build_ground_truth_context(question.get("evidence_json"))

        print(f"[{index}/{len(questions)}] REQUEST START | Model: {model_name} | "
              f"Mode: {context_mode} | Ticket: {question['ticket_id']}", flush=True)
        request_started = time.perf_counter()
        try:
            raw, timing = client.generate_raw(query, context)
        except (Exception, KeyboardInterrupt) as exc:
            run_failure = {"error_type": getattr(exc, "error_type", type(exc).__name__),
                           "phase": "generation_request", "question_index": index,
                           "ticket_id": question["ticket_id"],
                           "failed_request_elapsed_ms": round(max(0.0, time.perf_counter() - request_started) * 1000, 2),
                           "interrupted": isinstance(exc, KeyboardInterrupt)}
            http_status = _http_error_status(exc)
            if http_status is not None:
                run_failure["http_status"] = http_status
            diagnostics = _teacher_error_diagnostics(exc)
            if diagnostics:
                run_failure["provider_diagnostics"] = diagnostics
            break
        e2e_ms = (time.perf_counter() - e2e_start) * 1000.0

        response = None
        data = None
        error = None
        try:
            data = json.loads(raw)
            response = SupportResponse.model_validate(data, strict=True)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            error = str(exc)

        action = data.get("action") if isinstance(data, dict) else None
        if action not in ("answer", "escalate"):
            action = None

        valid = response is not None
        counts["total_eval"] += 1
        counts["schema_valid" if valid else "schema_invalid"] += 1

        if expected == "escalate":
            counts["TP" if valid and action == "escalate" else "FN"] += 1
        elif valid:
            counts["FP" if action == "escalate" else "TN"] += 1

        if question.get("is_answerable") is False:
            counts["absent_total"] += 1
            counts["absent_hallucinated"] += int(action == "answer")
            counts["invalid_absent"] += int(not valid)

        gen_ms = float(timing.get("latency_ms", 0.0))
        speed = float(timing.get("tokens_per_second", 0.0))
        eval_tok = timing.get("eval_tokens")
        prompt_tok = timing.get("prompt_tokens")

        gen_latencies.append(gen_ms)
        e2e_latencies.append(e2e_ms)
        tokens_per_sec.append(speed)

        records.append({
            **question,
            "context": context,
            "raw": raw,
            "schema_valid": valid,
            "error": error,
            "model_action": action,
            "model_answer": response.answer if valid else None,
            "model_confidence": response.confidence if valid else None,
            "model_sources": response.cited_sources if valid else [],
            "action_correct": valid and action == expected,
            "latency_ms": gen_ms,
            "generation_latency_ms": gen_ms,
            "e2e_latency_ms": round(e2e_ms, 2),
            "retrieval_latency_ms": round(retrieval_ms, 2),
            "eval_tokens": eval_tok,
            "prompt_tokens": prompt_tok,
            **({"output_tokens": timing.get("output_tokens"), "thought_tokens": timing.get("thought_tokens")}
               if isinstance(client, GeminiTeacherAdapter) else {}),
            "tokens_per_second": speed,
        })

        status = "INVALID" if not valid else "OK" if action == expected else "MISS"
        print(
            f"[{index}/{len(questions)}] {status} | Expected: {expected} | "
            f"Model: {action or '-'} | {gen_ms / 1000:.2f}s",
            flush=True,
        )

    # Base metrics calculation
    metrics = calculate_metrics(counts, gen_latencies, tokens_per_sec)
    metrics["context_mode"] = context_mode

    # Benchmark metadata and hash
    b_path_str = str(benchmark_file) if benchmark_file else str(PROJECT_ROOT / "data/evaluation/held_out_benchmark.json")
    metrics["benchmark_file"] = b_path_str
    if Path(b_path_str).exists():
        metrics["benchmark_sha256"] = compute_file_sha256(b_path_str)
    if benchmark_metadata:
        metrics["benchmark_metadata"] = benchmark_metadata

    # Hardware metadata
    hw = get_hardware_metadata()
    hw["scope"] = "evaluation client host; remote inference hardware and measured peak memory are not established"

    # Latency distributions
    gen_dist = LatencyDistribution.from_latencies(gen_latencies)
    e2e_dist = LatencyDistribution.from_latencies(e2e_latencies)
    metrics["generation_latency_distribution"] = asdict(gen_dist) if gen_dist else None
    metrics["e2e_latency_distribution"] = asdict(e2e_dist) if e2e_dist else None

    # Pricing & Cost
    res_pricing = pricing or get_model_pricing(model_name)
    token_metrics = calculate_token_metrics(records, res_pricing)
    metrics["token_cost_metrics"] = asdict(token_metrics)

    # Save to collision-free file
    target_dir = Path(output_dir) if output_dir else (PROJECT_ROOT / "logs" / "baselines")
    log_file_path = generate_safe_log_path(
        base_dir=target_dir,
        prefix="baseline_incomplete" if run_failure else "baseline_eval",
        model_name=model_name,
        context_mode=context_mode,
    )

    from src.inference.client import SYSTEM_PROMPT
    if serving_before is not None:
        serving_settings = client.get_serving_metadata()
        serving_settings["initial_model_digest"] = serving_before.get("model_digest")
        serving_settings["identity_changed_during_run"] = bool(
            serving_before.get("model_digest") and serving_settings.get("model_digest")
            and serving_before["model_digest"] != serving_settings["model_digest"]
        )
    else:
        serving_settings = {"capture_status": "unrecorded", "model_requested": model_name,
                            "limitations": ["Effective remote/custom serving configuration is not exposed by this adapter."]}
    payload = {
        "model_role": model_role,
        "run_status": ("interrupted" if run_failure["interrupted"] else "failed") if run_failure else "completed",
        "requested_records": len(questions),
        "completed_records": len(records),
        "failure": run_failure,
        "serving_settings": serving_settings,
        "generation_settings": {
            "temperature": getattr(client, "temperature", None) if isinstance(getattr(client, "temperature", None), (int, float)) else None,
            "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
            "prompt_template": "SupportInferenceClient.build_user_prompt/v1",
            "response_schema": SupportResponse.model_json_schema(),
        },
        "retrieval_settings": ({
            "index_name": getattr(retriever, "index_name", None),
            "top_k": 4, "max_per_doc": 2, "num_candidates": 100,
            "embedding_model": os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5"),
            "database": getattr(getattr(retriever, "db", None), "name", None),
            "collection": getattr(getattr(retriever, "collection", None), "name", None),
        } if use_retriever else {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "context_mode": context_mode,
        "metrics": metrics,
        "hardware": hw,
        "records": records,
    }
    if isinstance(getattr(client, "request_settings", None), dict):
        payload["teacher_request_settings"] = dict(client.request_settings)
    if isinstance(client, GeminiTeacherAdapter):
        payload["generation_settings"].update({"api": "interactions", **client.generation_config})

    log_file_path.write_text(
        json.dumps(payload, indent=4, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    if run_failure:
        status = f"; HTTP {run_failure['http_status']}" if "http_status" in run_failure else ""
        diagnostics = run_failure.get("provider_diagnostics", {})
        if "provider_code" in diagnostics:
            status += f"; code={diagnostics['provider_code']}"
        if "retry_after_seconds" in diagnostics:
            status += f"; retry-after={diagnostics['retry_after_seconds']:g}s"
        raise BaselineExecutionError(
            f"Generation request failed ({run_failure['error_type']}{status}); {len(records)}/{len(questions)} "
            f"responses completed. Incomplete run saved to: {log_file_path}"
        ) from None
    return metrics, records, log_file_path
