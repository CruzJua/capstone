"""CLI runner for deterministic local demo seeding and vector index verification."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEMO_ROOT = PROJECT_ROOT / "examples" / "client-training"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.demo_setup.seeder import (
    DEFAULT_MANIFEST_PATH,
    DemoSeedError,
    execute_demo_seed,
    plan_demo_seed,
    redact_mongo_uri,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or execute deterministic local demo seeding into an isolated local MongoDB Atlas Local container."
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and fixture hashes without connecting to MongoDB or writing records.",
    )
    mode_group.add_argument(
        "--execute",
        action="store_true",
        help="Execute idempotent seeding, document embedding, vector index creation, and readiness polling.",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEMO_ROOT / ".env.local"),
        help="Path to the dedicated demo environment file (defaults to examples/client-training/.env.local; never loads root .env).",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST_PATH),
        help="Path to the canonical demo fixture manifest JSON.",
    )
    parser.add_argument(
        "--refresh-changed",
        action="store_true",
        help="Allow updating previously seeded records when canonical source fixture hashes have changed.",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=120.0,
        help="Maximum seconds to wait for vector_index to become READY (default: 120).",
    )
    parser.add_argument(
        "--summary-out",
        default=str(DEMO_ROOT / "logs" / "seed_summary.json"),
        help="Path to write the 4-space indented machine-readable seed summary JSON.",
    )
    return parser


def resolve_demo_config(env_file_path: Path, *, allow_example_fallback: bool = False) -> dict[str, str]:
    file_vars: dict[str, str] = {}
    target_path = env_file_path
    if not target_path.is_file() and allow_example_fallback:
        example_path = DEMO_ROOT / ".env.example"
        if example_path.is_file():
            target_path = example_path
    if target_path.is_file():
        loaded = dotenv_values(target_path)
        for key, value in loaded.items():
            if value is not None:
                file_vars[key] = str(value).strip()

    def get_val(key: str, default: str = "") -> str:
        if key in os.environ and os.environ[key].strip():
            return os.environ[key].strip()
        return file_vars.get(key, default).strip()

    return {
        "APP_MODE": get_val("APP_MODE", ""),
        "MONGODB_URI": get_val("MONGODB_URI", ""),
        "MONGODB_TRAINING_DB_NAME": get_val("MONGODB_TRAINING_DB_NAME", ""),
        "MONGODB_DB_NAME": get_val("MONGODB_DB_NAME", "rag_knowledge_base"),
        "MONGODB_COLLECTION_NAME": get_val("MONGODB_COLLECTION_NAME", "doc_vectors"),
        "MONGODB_VECTOR_INDEX_NAME": get_val("MONGODB_VECTOR_INDEX_NAME", "vector_index"),
        "EMBEDDING_MODEL_NAME": get_val("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    env_file_path = Path(args.env_file).resolve()
    cfg = resolve_demo_config(env_file_path, allow_example_fallback=bool(args.dry_run))

    # Propagate resolved demo collection/index/model to os.environ for downstream ingestor
    os.environ["MONGODB_COLLECTION_NAME"] = cfg["MONGODB_COLLECTION_NAME"]
    os.environ["MONGODB_VECTOR_INDEX_NAME"] = cfg["MONGODB_VECTOR_INDEX_NAME"]
    os.environ["EMBEDDING_MODEL_NAME"] = cfg["EMBEDDING_MODEL_NAME"]

    try:
        if args.dry_run:
            plan = plan_demo_seed(
                app_mode=cfg["APP_MODE"],
                mongo_uri=cfg["MONGODB_URI"],
                training_db_name=cfg["MONGODB_TRAINING_DB_NAME"],
                standard_db_name=cfg["MONGODB_DB_NAME"],
                manifest_path=Path(args.manifest),
                project_root=PROJECT_ROOT,
            )
            print(json.dumps(plan, indent=4, ensure_ascii=False))
            return 0

        summary = execute_demo_seed(
            app_mode=cfg["APP_MODE"],
            mongo_uri=cfg["MONGODB_URI"],
            training_db_name=cfg["MONGODB_TRAINING_DB_NAME"],
            standard_db_name=cfg["MONGODB_DB_NAME"],
            manifest_path=Path(args.manifest),
            project_root=PROJECT_ROOT,
            refresh_changed=args.refresh_changed,
            wait_timeout_seconds=args.wait_timeout,
            summary_output_path=Path(args.summary_out) if args.summary_out else None,
        )
        print(json.dumps(summary, indent=4, ensure_ascii=False))
        return 0
    except Exception as exc:
        failure_summary = {
            "mode": "dry_run" if args.dry_run else "execute",
            "status": "failed",
            "ready": False,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "target": {
                "app_mode": cfg.get("APP_MODE") or "<unset>",
                "redacted_target": redact_mongo_uri(cfg.get("MONGODB_URI", "")),
                "database_name": cfg.get("MONGODB_TRAINING_DB_NAME") or "<unset>",
            },
            "error_type": type(exc).__name__,
            "errors": [str(exc)],
        }
        if args.summary_out and not args.dry_run:
            try:
                out_path = Path(args.summary_out)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    json.dumps(failure_summary, indent=4, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
        print(json.dumps(failure_summary, indent=4, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
