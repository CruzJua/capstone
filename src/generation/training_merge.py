"""Assemble a retrieved-context training CSV from the active one plus teacher-labelled hard negatives.

Nothing here edits a label or an answer. Rows are removed (uniform rules), replaced by their
re-labelled version, or extended with a `context_json` column: the passages the model is SHOWN,
while `evidence_json` keeps the passages the answer CITES. The result is checked with the v2
notebook's own validation functions and the model's real tokenizer, because the notebook stops the
whole run on a single bad or overlong example.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import random
from html import escape
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.documents.quality import screen_cited_quotes
from src.generation.hard_negatives import DISTRACTOR_TYPE, build_context, resolve_source_name, retrieval_query

NOTEBOOK_PROMPT_NAMES = {"SUPPORT_SYSTEM_PROMPT", "TASK_SYSTEM_PROMPT"}


def collapse(text: str) -> str:
    return " ".join(text.split()).casefold()


def load_notebook_helpers(notebook_path: Path) -> dict[str, Any]:
    """Read the notebook's pure helper functions (validation, prompt building) without running it."""
    notebook = json.loads(Path(notebook_path).read_text(encoding="utf-8"))
    namespace: dict[str, Any] = dict(json=json, math=math, random=random, escape=escape, Path=Path, pd=pd)
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        try:
            tree = ast.parse("".join(cell["source"]))
        except SyntaxError:  # cells that start with %pip or other magics
            continue
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) or (
            isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in NOTEBOOK_PROMPT_NAMES for t in node.targets))]
        exec(compile(tree, str(notebook_path), "exec"), namespace)
    return namespace


def token_lengths(examples: list[dict], tokenizer) -> list[tuple[str, str, int]]:
    """Length of every full conversation under the model's chat template."""
    lengths = []
    for example in examples:
        text = tokenizer.apply_chat_template(example["messages"], tokenize=False, add_generation_prompt=False)
        lengths.append((example["ticket_id"], example["task"],
                        len(tokenizer(text, add_special_tokens=False)["input_ids"])))
    return lengths


def build_catalog(documents: list[dict], data_root: Path) -> dict[str, list[dict]]:
    """Every indexed chunk per tenant, labelled with the file name that training evidence cites."""
    names: dict[tuple[str, str], str] = {}
    catalog: dict[str, list[dict]] = {}
    for doc in documents:
        tenant = doc["tenant_id"]
        if (tenant, doc["doc_id"]) not in names:
            names[(tenant, doc["doc_id"])] = resolve_source_name(Path(data_root) / tenant, doc["doc_id"])
        catalog.setdefault(tenant, []).append({
            "source": names[(tenant, doc["doc_id"])], "section": doc.get("section") or "",
            "quote": doc["text"].strip(), "key": collapse(doc["text"])})
    return catalog


def realistic_context(row: dict, retrieve: Callable[[str, str], list[dict]], catalog: dict, data_root: Path,
                      max_chars: int = 3000, max_chunks: int = 4) -> list[dict]:
    """What retrieval would show for this question, with the cited passage guaranteed to be present.

    The answer was written from the cited evidence, so showing context that lacks it would teach
    the model to answer without support. If retrieval missed the cited passage, it is inserted at a
    deterministic position (not always first) and the lowest-ranked other chunks are trimmed.
    """
    tenant = row["business"]
    context = build_context(retrieve(retrieval_query(json.loads(row["messages_json"])), tenant),
                            Path(data_root) / tenant, max_chars, max_chunks)
    protected: list[dict] = []
    for item in json.loads(row["evidence_json"]):
        need = collapse(item["quote"])
        hit = next((c for c in context if c["source"] == item["source"] and need in collapse(c["quote"])), None)
        if hit is None:
            chunk = next((c for c in catalog.get(tenant, [])
                          if c["source"] == item["source"] and need in c["key"] and len(c["quote"]) <= max_chars), None)
            hit = ({k: chunk[k] for k in ("source", "section", "quote")} if chunk is not None
                   else {"source": item["source"], "section": "", "quote": item["quote"].strip()})
            position = int(hashlib.sha256(row["ticket_id"].encode()).hexdigest(), 16) % (len(context) + 1)
            context.insert(position, hit)
        if not any(hit is p for p in protected):
            protected.append(hit)
    while len(context) > max_chunks or sum(len(c["quote"]) for c in context) > max_chars:
        removable = [i for i in range(len(context) - 1, -1, -1) if not any(context[i] is p for p in protected)]
        if not removable:
            break
        del context[removable[0]]
    return context


def merge_training_data(base: pd.DataFrame, hardneg: pd.DataFrame, plan: dict, data_root: Path) -> tuple[pd.DataFrame, dict]:
    """Quarantine unverifiable base rows, replace re-labelled originals, append the new rows."""
    if list(base.columns) != list(hardneg.columns):
        raise ValueError("base and hard-negative CSVs must have identical columns")

    kept_records, _ = screen_cited_quotes(base.to_dict(orient="records"), data_root)
    kept = pd.DataFrame(kept_records, columns=base.columns)
    quarantined = sorted(set(base["ticket_id"]) - set(kept["ticket_id"]))

    source_by_new = {f"{key}_t0": entry["source_ticket_id"] for key, entry in plan.items()}
    missing = [t for t in hardneg["ticket_id"] if t not in source_by_new]
    if missing:
        raise ValueError(f"hard-negative rows missing from plan.json: {missing[:3]}")
    originals = {source_by_new[t] for t in hardneg["ticket_id"]}
    unknown = originals - set(base["ticket_id"])
    if unknown:
        raise ValueError(f"replaced tickets are not in the base CSV: {sorted(unknown)[:3]}")

    # A re-labelled ticket must ask the very same question, or it is not a replacement.
    base_query = dict(zip(base["ticket_id"], base["customer_query"].str.strip()))
    for new_id, query in zip(hardneg["ticket_id"], hardneg["customer_query"].str.strip()):
        if base_query[source_by_new[new_id]] != query:
            raise ValueError(f"{new_id} does not carry the original question of {source_by_new[new_id]}")

    # Sibling tickets must stay in one train/validation group: reuse the original batch key.
    base_batch = dict(zip(base["ticket_id"], base["batch_key"]))
    hardneg = hardneg.copy()
    hardneg["batch_key"] = [base_batch[source_by_new[t]] for t in hardneg["ticket_id"]]

    survivors = kept[~kept["ticket_id"].isin(originals)]
    merged = pd.concat([survivors, hardneg], ignore_index=True)
    report = {
        "base_rows": len(base), "quarantined_by_quote_rule": len(quarantined),
        "quarantined_ticket_ids": quarantined, "replaced_originals": len(originals & set(kept["ticket_id"])),
        "replaced_but_already_quarantined": len(originals & set(quarantined)),
        "hardneg_rows_added": len(hardneg), "rows_after_merge": len(merged),
    }
    return merged, report


def attach_contexts(merged: pd.DataFrame, plan: dict, retrieve: Callable[[str, str], list[dict]],
                    catalog: dict, data_root: Path, max_chars: int = 3000, max_chunks: int = 4) -> tuple[pd.DataFrame, dict]:
    """Add `context_json` to every row and restore honest answerability on escalations."""
    plan_by_ticket = {f"{key}_t0": entry for key, entry in plan.items()}
    contexts, evidence_json, answerable, dropped = [], [], [], []
    for row in merged.to_dict(orient="records"):
        entry = plan_by_ticket.get(row["ticket_id"])
        if entry is not None:
            context = list(entry["context"])  # exactly what the teacher judged
            if row["interaction_type"] == DISTRACTOR_TYPE:
                evidence, is_answerable = "[]", False  # retrieved passages are context, not support
            else:
                evidence, is_answerable = row["evidence_json"], True
                # Teacher quotes are verbatim up to markup; make sure the cited text itself is shown.
                for item in json.loads(evidence):
                    if not any(collapse(item["quote"]) in collapse(c["quote"]) for c in context):
                        context.append({"source": item["source"], "section": "", "quote": item["quote"].strip()})
        elif json.loads(row["evidence_json"]):
            context = realistic_context(row, retrieve, catalog, data_root, max_chars, max_chunks)
            evidence, is_answerable = row["evidence_json"], row["is_answerable"]
        else:
            dropped.append(row["ticket_id"])  # an unverified "not in docs" label with no teacher check
            contexts.append(None)
            evidence_json.append(row["evidence_json"])
            answerable.append(row["is_answerable"])
            continue
        contexts.append(json.dumps([{k: c[k] for k in ("source", "section", "quote")} for c in context],
                                   ensure_ascii=False))
        evidence_json.append(evidence)
        answerable.append(is_answerable)
    out = merged.copy()
    out["context_json"], out["evidence_json"], out["is_answerable"] = contexts, evidence_json, answerable
    out = out[out["context_json"].notna()].reset_index(drop=True)
    return out, {"dropped_without_verified_context": dropped, "final_rows": len(out)}


def audit_training_frame(frame: pd.DataFrame, helpers: dict[str, Any], tokenizer, held_out_tenant: str,
                         max_tokens: int, task_mode: str = "label_and_rationale",
                         include_serving_labels: bool = True) -> dict:
    """Run the notebook's validation, then measure real token lengths of every example."""
    validated = helpers["validate_tickets"](frame, held_out_tenant, task_mode)
    examples = helpers["build_task_examples"](validated, task_mode, include_serving_labels)
    lengths = token_lengths(examples, tokenizer)
    values = sorted(length for _, _, length in lengths)
    overlong = [(t, task, n) for t, task, n in lengths if n > max_tokens]
    train, validation = helpers["split_tickets"](validated, 0.10, 42)
    return {
        "notebook_validation": "passed", "examples": len(examples),
        "tokens_median": values[len(values) // 2], "tokens_p99": values[int(len(values) * 0.99)],
        "tokens_max": values[-1], "max_tokens_allowed": max_tokens,
        "overlong_examples": len(overlong), "overlong_ticket_ids": sorted({t for t, _, _ in overlong}),
        "split_check": {"train_tickets": len(train), "validation_tickets": len(validation),
                        "validation_distractor_rows": int((validation["interaction_type"] == DISTRACTOR_TYPE).sum())},
    }
