"""Prepare development-only evaluation fixtures from existing training tickets.

These fixtures measure behavior on training-exposed tenants, not generalization.
No training input or frozen held-out benchmark is written by this module.
"""

import csv
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from src.evaluation.dataset import normalize_answerable

TENANTS = ("cinder_and_salt", "iron_and_oak", "kettle_and_loom", "northstar_auto")
QUOTAS = {"supported_answer": 5, "absent_escalation": 3, "human_required": 2}
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _stratum(row):
    answerable = normalize_answerable(row["is_answerable"])
    if row["action"] == "answer" and answerable:
        return "supported_answer"
    if row["action"] == "escalate" and not answerable:
        return "absent_escalation"
    if (row["action"] == "escalate" and answerable
            and row["escalation_reason"] == "docs_require_human"):
        return "human_required"
    raise ValueError(f"Unsupported action/answerability combination: {row['ticket_id']}")


def _question(row, stratum):
    evidence = json.loads(row["evidence_json"] or "[]")
    if not isinstance(evidence, list) or any(
        not isinstance(item, dict) or not all(
            isinstance(item.get(field), str) and item[field].strip()
            for field in ("source", "quote")
        ) for item in evidence
    ):
        raise ValueError(f"Invalid evidence: {row['ticket_id']}")
    answerable = normalize_answerable(row["is_answerable"])
    if answerable != bool(evidence):
        raise ValueError(f"Evidence does not match answerability: {row['ticket_id']}")
    return {
        "ticket_id": row["ticket_id"],
        "batch_key": row["batch_key"],
        "tenant": row["business"],
        "category": row["category"],
        "refinement_stratum": stratum,
        "customer_query": row["customer_query"],
        "ground_truth_action": row["action"],
        "is_answerable": answerable,
        "escalation_reason": row["escalation_reason"],
        "ground_truth_answer": row["answer"],
        "evidence_json": evidence,
        "cited_sources": list(dict.fromkeys(item["source"] for item in evidence))
        if row["action"] == "answer" else [],
    }


def prepare_refinement_datasets(source_path, seed=390):
    """Return deterministic dev/validation payloads; never mutate the source.

    Reserve every selected ticket's source batch and normalized exact question
    across both splits. This is not a semantic paraphrase-leakage guarantee.
    """
    source_path = Path(source_path)
    source_bytes = source_path.read_bytes()
    with source_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"ticket_id", "batch_key", "business", "category", "customer_query",
                    "action", "is_answerable", "escalation_reason", "answer", "evidence_json"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")
        rows = [row for row in reader if row["business"] in TENANTS]
    pools = {(tenant, stratum): [] for tenant in TENANTS for stratum in QUOTAS}
    seen_ids = set()
    for row in rows:
        if any(not row[field].strip() for field in ("ticket_id", "batch_key", "customer_query")):
            raise ValueError("Ticket ID, batch key, and customer query must be nonempty")
        if row["ticket_id"] in seen_ids:
            raise ValueError(f"Duplicate ticket ID: {row['ticket_id']}")
        seen_ids.add(row["ticket_id"])
        pools[(row["business"], _stratum(row))].append(row)
    rng = random.Random(seed)
    for pool in pools.values():
        pool.sort(key=lambda row: row["ticket_id"])
        rng.shuffle(pool)
    used_batches, used_queries = set(), set()
    payloads = {}
    for split in ("dev", "validation"):
        questions = []
        for tenant in TENANTS:
            for stratum, quota in QUOTAS.items():
                selected = []
                for row in pools[(tenant, stratum)]:
                    batch = (tenant, row["batch_key"])
                    query = " ".join(row["customer_query"].casefold().split())
                    if batch in used_batches or query in used_queries:
                        continue
                    selected.append(_question(row, stratum))
                    used_batches.add(batch)
                    used_queries.add(query)
                    if len(selected) == quota:
                        break
                if len(selected) != quota:
                    raise ValueError(f"Insufficient disjoint {tenant}/{stratum} rows for {split}: "
                                     f"need {quota}, found {len(selected)}")
                questions.extend(selected)
        rng.shuffle(questions)
        try:
            source_label = str(source_path.resolve().relative_to(PROJECT_ROOT))
        except ValueError:
            source_label = str(source_path.resolve())
        payloads[split] = {
            "metadata": {
                "purpose": "runtime_refinement_development_only",
                "split": split,
                "training_exposure": "Sampled from training tickets on training-exposed tenants; "
                                     "not an unseen-tenant or unseen-training-example evaluation.",
                "usage": "Use dev for adjustments; freeze decisions before validation. "
                         "Do not use harbor_view or the frozen held-out benchmark for tuning.",
                "source": source_label,
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "seed": seed,
                "tenants": list(TENANTS),
                "excluded_tenants": ["harbor_view"],
                "disjoint_split_rule": "Ticket IDs, tenant+batch_key groups, and normalized exact "
                                       "customer queries are disjoint across both splits; semantic "
                                       "paraphrase overlap is not assessed.",
                "total_questions": len(questions),
                "answer_present_count": sum(q["is_answerable"] for q in questions),
                "provably_absent_count": sum(not q["is_answerable"] for q in questions),
                "stratum_counts": dict(Counter(q["refinement_stratum"] for q in questions)),
                "tenant_counts": dict(Counter(q["tenant"] for q in questions)),
                "per_tenant_stratum_quotas": dict(QUOTAS),
            },
            "questions": questions,
        }
    return payloads


def save_refinement_datasets(payloads, dev_path, validation_path, source_path):
    """Create new fixture files, refusing existing files or protected targets."""
    paths = [Path(dev_path), Path(validation_path)]
    resolved = [path.resolve() for path in paths]
    if resolved[0] == resolved[1]:
        raise ValueError("Dev and validation outputs must be different paths")
    protected = (PROJECT_ROOT / "data" / "cleaned").resolve()
    for path, target in zip(paths, resolved):
        if (target == Path(source_path).resolve() or protected == target or protected in target.parents
                or target.name == "held_out_benchmark.json" or target.suffix != ".json"):
            raise ValueError(f"Unsafe fixture output: {path}")
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Refusing to overwrite existing fixture: {path}")
    # Validate/serialize both before creating either output.
    serialized = [json.dumps(payloads[split], indent=4, ensure_ascii=False, allow_nan=False) + "\n"
                  for split in ("dev", "validation")]
    for path, content in zip(paths, serialized):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
