"""Build the v2 training CSV: active training data + teacher-labelled hard negatives + retrieved context.

Reads the active train_tickets.csv and the cleaned hard-negative CSV (both unchanged), applies the
narrow quote rule to the old rows, swaps each re-labelled ticket for its new version, adds a
`context_json` column (what the model is shown), validates the result with the v2 training
notebook's own functions and the model's tokenizer, then writes a NEW directory containing
train_tickets.csv (the file name the Kaggle notebook searches for) plus a manifest.

Offline and free: no API calls. Needs the cached embedding model, so set HF_HUB_OFFLINE=1.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.generation.training_merge import (attach_contexts, audit_training_frame, build_catalog,
                                           load_notebook_helpers, merge_training_data)
from src.rag.offline import build_offline_retriever


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-csv", type=Path, default=ROOT / "data/cleaned/train_tickets.csv")
    parser.add_argument("--hardneg-csv", type=Path, default=ROOT / "data/cleaned/hardneg_hardneg_v1.csv")
    parser.add_argument("--plan", type=Path, default=ROOT / "data/generated/hardneg_v1/plan.json")
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--notebook", type=Path, default=ROOT / "notebooks/train_llama_qlora_kaggle_v2.ipynb")
    parser.add_argument("--tokenizer-dir", type=Path, required=True,
                        help="folder holding the model's tokenizer files (e.g. a trained adapter folder)")
    parser.add_argument("--held-out-tenant", default="harbor_view")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--max-context-chars", type=int, default=3000)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--drop-overlong", action="store_true",
                        help="remove every ticket with an example over the limit (uniform rule), then re-audit")
    parser.add_argument("--out-dir", type=Path, required=True, help="new directory; must not exist yet")
    parser.add_argument("--manifest", type=Path, required=True, help="new JSON path for the build manifest")
    return parser.parse_args()


def main():
    args = parse_args()
    for path in (args.out_dir, args.manifest):
        if path.exists():
            sys.exit(f"error: refusing to overwrite existing path: {path}")
    from transformers import AutoTokenizer

    base = pd.read_csv(args.base_csv, keep_default_na=False)
    hardneg = pd.read_csv(args.hardneg_csv, keep_default_na=False)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    helpers = load_notebook_helpers(args.notebook)
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer_dir), local_files_only=True)

    merged, report = merge_training_data(base, hardneg, plan, args.data_root)
    tenants = sorted(set(merged["business"]))
    print(f"Indexing {len(tenants)} tenants locally to build realistic retrieved context...")
    retriever = build_offline_retriever(args.data_root, tenants)
    catalog = build_catalog(retriever.collection.documents, args.data_root)
    framed, context_report = attach_contexts(
        merged, plan, lambda query, tenant: retriever.retrieve(query, tenant, top_k=args.top_k),
        catalog, args.data_root, args.max_context_chars, args.top_k)
    report.update(context_report)

    audit = audit_training_frame(framed, helpers, tokenizer, args.held_out_tenant, args.max_tokens)
    if audit["overlong_examples"] and args.drop_overlong:
        report["dropped_overlong_ticket_ids"] = audit["overlong_ticket_ids"]
        framed = framed[~framed["ticket_id"].isin(audit["overlong_ticket_ids"])].reset_index(drop=True)
        report["final_rows"] = len(framed)
        audit = audit_training_frame(framed, helpers, tokenizer, args.held_out_tenant, args.max_tokens)
    if audit["overlong_examples"]:
        sys.exit(f"error: {audit['overlong_examples']} examples exceed {args.max_tokens} tokens; "
                 f"the notebook would stop. Re-run with --drop-overlong. Tickets: {audit['overlong_ticket_ids'][:5]}")

    args.out_dir.mkdir(parents=True)
    out_csv = args.out_dir / "train_tickets.csv"
    framed.to_csv(out_csv, index=False)
    context_chars = framed["context_json"].map(lambda value: sum(len(c["quote"]) for c in json.loads(value)))
    manifest = {
        "inputs": {"base_csv": {"path": str(args.base_csv), "sha256": sha256(args.base_csv)},
                   "hardneg_csv": {"path": str(args.hardneg_csv), "sha256": sha256(args.hardneg_csv)},
                   "plan": {"path": str(args.plan), "sha256": sha256(args.plan)},
                   "notebook": {"path": str(args.notebook), "sha256": sha256(args.notebook)}},
        "output": {"path": str(out_csv), "sha256": sha256(out_csv), "rows": len(framed)},
        "merge": report, "notebook_audit": audit,
        "composition": {
            "by_tenant": framed["business"].value_counts().to_dict(),
            "by_action_and_reason": {f"{a}|{r}": int(n) for (a, r), n in
                                     framed.groupby(["action", "escalation_reason"]).size().items()},
            "context_chars_by_action": {action: {"mean": round(float(group.mean())), "median": int(group.median())}
                                        for action, group in context_chars.groupby(framed["action"])},
        },
        "held_out_tenant_absent": args.held_out_tenant not in set(framed["business"]),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=4) + "\n", encoding="utf-8")
    printable = {k: manifest[k] for k in ("output", "notebook_audit", "composition")}
    printable["merge"] = {k: v for k, v in report.items() if not k.endswith("_ids")}
    print(json.dumps(printable, indent=4))


if __name__ == "__main__":
    main()
