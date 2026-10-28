"""Prepare reproducible, tenant-isolated generation benchmarks."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def normalize_answerable(value) -> bool:
    """Accept CSV boolean representations without treating 'False' as truthy."""
    normalized = str(value).strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(f"Invalid is_answerable value: {value!r}")


def load_and_filter_data(dataset_path: Path, held_out_tenant: str):
    df = pd.read_csv(dataset_path)
    required = {
        "ticket_id", "business", "category", "customer_query", "action",
        "is_answerable", "escalation_reason", "answer", "evidence_json",
    }
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Dataset is missing columns: {', '.join(sorted(missing))}")
    if df["business"].isna().any():
        raise ValueError("Dataset contains tickets without a business; cannot ensure tenant isolation.")
    held_out = df["business"] == held_out_tenant
    if not held_out.any():
        raise ValueError(f"Tenant {held_out_tenant!r} not found in {dataset_path}")
    tenant_df = df[held_out].copy()
    tenant_df["is_answerable"] = tenant_df["is_answerable"].map(normalize_answerable)
    if not tenant_df["action"].isin(["answer", "escalate"]).all():
        raise ValueError("Held-out tickets contain invalid action labels.")
    if (tenant_df["is_answerable"].eq(False) & tenant_df["action"].ne("escalate")).any():
        raise ValueError("Unanswerable tickets must have action='escalate'.")
    return (
        tenant_df[tenant_df["is_answerable"]].copy(),
        tenant_df[~tenant_df["is_answerable"]].copy(),
        df[~held_out].copy(),
    )


def sample_balanced_benchmark(answerable_pool, unanswerable_pool, samples_per_class: int, seed: int):
    if samples_per_class <= 0:
        raise ValueError("samples_per_class must be positive.")
    for label, pool in (("answerable", answerable_pool), ("unanswerable", unanswerable_pool)):
        if len(pool) < samples_per_class:
            raise ValueError(
                f"Need {samples_per_class} {label} tickets, but only {len(pool)} are available."
            )
    sampled = pd.concat([
        answerable_pool.sample(n=samples_per_class, random_state=seed),
        unanswerable_pool.sample(n=samples_per_class, random_state=seed + 1),
    ]).sample(frac=1, random_state=seed)
    tenants = sampled["business"].unique()
    if len(tenants) != 1:
        raise ValueError("Benchmark pools must belong to exactly one held-out tenant.")
    if sampled["ticket_id"].isna().any() or sampled["ticket_id"].duplicated().any():
        raise ValueError("Benchmark ticket IDs must be present and unique.")

    questions = []
    # Convert pandas missing values to JSON null rather than emitting NaN.
    for row in sampled.astype(object).where(sampled.notna(), None).to_dict(orient="records"):
        evidence = json.loads(row["evidence_json"]) if row["evidence_json"] else []
        if not isinstance(evidence, list) or any(not isinstance(item, dict) for item in evidence):
            raise ValueError(f"Invalid evidence list for ticket {row['ticket_id']}")
        sources = list(dict.fromkeys(
            item["source"] for item in evidence if isinstance(item.get("source"), str) and item["source"]
        ))
        cited_sources = row.get("cited_sources")
        if isinstance(cited_sources, str):
            cited_sources = json.loads(cited_sources)
        if cited_sources is None:
            cited_sources = sources if row["action"] == "answer" else []
        questions.append({
            "ticket_id": row["ticket_id"],
            "tenant": row["business"],
            "category": row["category"],
            "customer_query": row["customer_query"],
            "ground_truth_action": row["action"],
            "is_answerable": normalize_answerable(row["is_answerable"]),
            "escalation_reason": row["escalation_reason"],
            "ground_truth_answer": row["answer"],
            "evidence_json": row["evidence_json"] or "[]",
            "cited_sources": cited_sources,
        })
    return {
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "held_out_tenant": tenants[0],
            "seed": seed,
            "total_questions": len(questions),
            "answer_present_count": samples_per_class,
            "provably_absent_count": samples_per_class,
        },
        "questions": questions,
    }


def save_artifacts(benchmark_payload: dict, remaining_df, output_benchmark_path: Path, output_train_path: Path):
    benchmark_path, train_path = Path(output_benchmark_path), Path(output_train_path)
    if benchmark_path.resolve() == train_path.resolve():
        raise ValueError("Benchmark and training outputs must use different paths.")
    tenant = benchmark_payload["metadata"]["held_out_tenant"]
    if remaining_df["business"].eq(tenant).any():
        raise ValueError(f"Training data still contains held-out tenant {tenant!r}.")
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    train_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_path.write_text(
        json.dumps(benchmark_payload, indent=4, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    remaining_df.to_csv(train_path, index=False)
    print(f"Saved {len(benchmark_payload['questions'])} benchmark questions to {benchmark_path}")
    print(f"Saved {len(remaining_df)} training tickets to {train_path}")
