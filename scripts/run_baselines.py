"""Run baseline evaluations across base student, fine-tuned student, and teacher models.

Supports:
- Local student models via Ollama (SupportInferenceClient).
- Configurable teacher models (GeminiTeacherAdapter or MockTeacherAdapter).
- Context modes: ground-truth evidence quotes, live-RAG retrieval, or both.
- Safe collision-free logging that never overwrites existing evaluation files.
- Planning and dry-run mode (--dry-run / --plan) that verifies configurations,
  computes benchmark hashes, and logs planned steps without GPU/network calls.

Usage Examples:
    # Dry-run plan (no GPU or API calls):
    python scripts/run_baselines.py --dry-run

    # Run local base student on ground-truth context with limit for smoke test:
    python scripts/run_baselines.py --models llama3.2:3b --limit 5

    # Run explicitly identified students, or just --finetuned-models for an FT-only run:
    python scripts/run_baselines.py --base-model llama3.2:3b --finetuned-models llama3.2:3b-qlora

    # Run with mock teacher for end-to-end integration test without paid API spend:
    python scripts/run_baselines.py --models llama3.2:3b --teacher-provider mock --limit 3 --compare
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv

from src.evaluation.comparison import (
    GeminiTeacherAdapter,
    BaselineExecutionError,
    MockTeacherAdapter,
    compare_evaluations,
    compute_file_sha256,
    format_comparison_text,
    get_hardware_metadata,
    get_model_pricing,
    ModelPricing,
    resolve_gemini_api_key,
    run_baseline_evaluation,
    validate_teacher_runtime,
)
from src.rag.db_config import resolve_training_db_name
from src.evaluation.generation import (
    load_benchmark,
    initialize_services,
    print_scorecard,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=None,
        help="Legacy model selection: known Llama base and qlora/finetuned names only; roles never depend on order. Prefer explicit role flags; empty/none skips students.",
    )
    parser.add_argument("--base-model", help="Exact Ollama model to evaluate as the base student.")
    parser.add_argument("--finetuned-models", nargs="+", default=[],
                        help="Exact Ollama model(s) to evaluate as fine-tuned students, including FT-only runs.")
    parser.add_argument(
        "--teacher-model",
        default=os.getenv("TEACHER_MODEL"),
        help="Teacher model identifier (e.g. gemini-2.5-flash or gemini-1.5-flash). Default: $TEACHER_MODEL",
    )
    parser.add_argument(
        "--teacher-provider",
        choices=["gemini", "mock", "none"],
        default="none",
        help="Teacher model provider: 'gemini', 'mock' (offline test), or 'none' (skip teacher)",
    )
    parser.add_argument(
        "--context-mode",
        choices=["ground_truth", "retriever", "both"],
        default="ground_truth",
        help="Context mode: 'ground_truth' (evidence quotes), 'retriever' (live-RAG), or 'both'",
    )
    parser.add_argument(
        "--benchmark-file",
        default=str(PROJECT_ROOT / "data/evaluation/held_out_benchmark.json"),
        help="Path to frozen benchmark JSON file",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit questions for smoke testing (e.g. --limit 5)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "logs" / "baselines"),
        help="Directory to save baseline evaluation logs",
    )
    parser.add_argument(
        "--dry-run",
        "--plan",
        action="store_true",
        help="Plan and print execution matrix without calling models or using GPU/API",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Automatically generate a comparison table across evaluated runs upon completion",
    )
    parser.add_argument("--no-query-prefix", action="store_true",
                        help="Retriever mode only: disable the BGE query prefix to reproduce pre-prefix (sprint-3) "
                             "runs. The default stays prefix-on.")
    parser.add_argument("--allow-paid-api", action="store_true", help="Explicitly authorize teacher API requests and sending benchmark data.")
    parser.add_argument("--pricing-file", help="Verified pricing catalog JSON with source/date; optional, otherwise paid cost is unmeasured.")
    parser.add_argument("--teacher-timeout", type=float, default=60.0,
                        help="Interactions client transport timeout in seconds; no server deadline header (default: 60).")
    parser.add_argument("--teacher-max-attempts", type=int, default=1,
                        help="Maximum Gemini attempts including the initial request (default: 1; no retries).")
    args = parser.parse_args()
    try:
        resolve_student_models(args)
        validate_teacher_runtime(args.teacher_timeout, args.teacher_max_attempts)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def resolve_student_models(args) -> Dict[str, str]:
    """Resolve identities before any service calls; never assign roles by position."""
    explicit = args.base_model is not None or bool(args.finetuned_models)
    if explicit and args.models is not None:
        raise ValueError("Use --base-model/--finetuned-models or legacy --models, not both.")
    selected = []
    if explicit:
        if args.base_model is not None:
            selected.append((args.base_model, "base_student"))
        selected.extend((name, "finetuned_student") for name in args.finetuned_models)
    else:
        for name in args.models if args.models is not None else ["llama3.2:3b"]:
            key = name.strip().lower()
            if key in {"none", "false", "0", ""}:
                continue
            if key in {"llama3.2:3b", "llama3.2:3b-instruct"}:
                role = "base_student"
            elif any(marker in key for marker in ("qlora", "finetuned", "student-ft")):
                role = "finetuned_student"
            else:
                raise ValueError(f"Role is unknown for {name!r}; use --base-model or --finetuned-models.")
            selected.append((name, role))
    roles = {}
    for name, role in selected:
        name = name.strip()
        if not name or name.lower() in {"none", "false", "0"}:
            raise ValueError("Explicit model names must be nonempty model identifiers.")
        if name in roles:
            raise ValueError(f"Duplicate student model {name!r}; select each identity only once.")
        roles[name] = role
    if list(roles.values()).count("base_student") > 1:
        raise ValueError("Select only one base student per comparison matrix.")
    return roles


def display_dry_run_plan(
    benchmark_path: Path,
    metadata: Dict[str, Any],
    questions: List[Dict[str, Any]],
    modes: List[str],
    student_models: Dict[str, str],
    teacher_provider: str,
    teacher_model: Optional[str],
    output_dir: Path,
    hw_meta: Dict[str, Any],
    pricing_catalog: Optional[Dict[str, ModelPricing]] = None,
):
    """Prints a clear execution plan during dry-run."""
    benchmark_sha = compute_file_sha256(benchmark_path) if benchmark_path.exists() else "missing"
    print("\n" + "=" * 80)
    print("BASELINE ORCHESTRATION EXECUTION PLAN (DRY-RUN)")
    print("=" * 80)
    print(f"Benchmark File:       {benchmark_path}")
    print(f"Benchmark SHA256:     {benchmark_sha}")
    print(f"Held-Out Tenant:      {metadata.get('held_out_tenant', 'unknown')}")
    print(f"Available Questions:  {len(questions)} (limit applied: {len(questions) != metadata.get('total_questions')})")
    print(f"Context Modes:        {', '.join(modes)}")
    print(f"Output Directory:     {output_dir}")
    print("-" * 80)
    print("HARDWARE SPECIFICATIONS:")
    print(f"  OS / Platform:      {hw_meta.get('platform')}")
    print(f"  CPU Model:          {hw_meta.get('cpu_model', 'Unknown')} ({hw_meta.get('cpu_count_logical')} cores)")
    print(f"  System RAM:         {hw_meta.get('ram_total_human', 'Unknown')}")
    gpu_desc = ", ".join(hw_meta.get("gpu_info") or []) if hw_meta.get("gpu_info") else "None detected"
    print(f"  GPU Info:           {gpu_desc}")
    print("-" * 80)
    print("PLANNED EVALUATION RUNS:")

    run_index = 1
    # Students
    for model, role in student_models.items():
        pricing = get_model_pricing(model, pricing_catalog)
        for mode in modes:
            print(f"  [{run_index}] Model: {model} (Local Ollama {role})")
            print(f"      Context: {mode} | Est. Queries: {len(questions)}")
            print(f"      Pricing: {pricing.pricing_source} (Cost: $0.00 API spend)")
            run_index += 1

    # Teacher
    if teacher_provider != "none":
        t_name = teacher_model or ("mock-teacher" if teacher_provider == "mock" else "UNSET (set --teacher-model)")
        pricing = get_model_pricing(t_name.removeprefix("models/"), pricing_catalog)
        for mode in modes:
            print(f"  [{run_index}] Teacher: {t_name} (Provider: {teacher_provider})")
            print(f"      Context: {mode} | Est. Queries: {len(questions)}")
            print(f"      Pricing: {pricing.pricing_source}")
            if teacher_provider == "gemini":
                key, source = resolve_gemini_api_key()
                has_key = bool(key and "<" not in key and "your_" not in key)
                status = f"Present via {source}" if has_key else "MISSING (required for live execution)"
                print(f"      Credentials: GEMINI_API_KEY ({status})")
            run_index += 1

    print("-" * 80)
    print("Dry-run complete. No GPU inference was started and no paid API calls were made.")
    print("To execute for real, run again without the --dry-run flag.\n")


def describe_retriever_settings(retriever: Any) -> Dict[str, Any]:
    """Effective retriever settings that the evaluation log itself does not capture."""
    return {
        "backend": "offline in-memory index, not Atlas" if getattr(retriever, "client", True) is None else "MongoDB Atlas",
        "database": getattr(getattr(retriever, "db", None), "name", None),
        "collection": getattr(getattr(retriever, "collection", None), "name", None),
        "index_name": getattr(retriever, "index_name", None),
        "query_prefix": getattr(retriever, "query_prefix", None),
        "query_prefix_enabled": bool(getattr(retriever, "query_prefix", "")),
        "reranker": getattr(retriever, "reranker_model_name", None) or "off",
        "min_rerank_score": getattr(retriever, "min_rerank_score", None),
        "relevance_cutoff": "none",
        "top_k": 4,
        "max_per_doc": 2,
        "num_candidates": 100,
    }


def write_retriever_settings_sidecar(log_path: Path, retriever: Any, model_name: str) -> Path:
    """Write settings next to a finished log; exclusive mode so nothing is ever overwritten."""
    sidecar = log_path.with_name(f"{log_path.stem}.retriever_settings.json")
    payload = {"log_file": log_path.name, "model": model_name, **describe_retriever_settings(retriever)}
    with sidecar.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=4) + "\n")
    return sidecar


def build_teacher_adapter(provider: str, model_name: Optional[str], *,
                          timeout_seconds: float = 60.0, max_attempts: int = 1):
    if provider == "mock":
        return MockTeacherAdapter(model=model_name or "mock-teacher")
    elif provider == "gemini":
        return GeminiTeacherAdapter(model=model_name, timeout_seconds=timeout_seconds, max_attempts=max_attempts)
    return None


def main():
    load_dotenv(find_dotenv(usecwd=True), override=False)
    args = parse_args()

    benchmark_path = Path(args.benchmark_file).resolve()
    if not benchmark_path.exists():
        raise FileNotFoundError(f"Frozen benchmark not found: {benchmark_path}")

    metadata, questions = load_benchmark(benchmark_path, args.limit)
    output_dir = Path(args.output_dir).resolve()
    hw_meta = get_hardware_metadata()

    modes = ["ground_truth", "retriever"] if args.context_mode == "both" else [args.context_mode]
    student_models = resolve_student_models(args)
    teacher_provider = args.teacher_provider

    if teacher_provider == "gemini" and not args.teacher_model:
        raise SystemExit("Set --teacher-model or TEACHER_MODEL to the actual dataset teacher.")
    from scripts.compare_evaluations import load_pricing_catalog
    pricing_catalog = load_pricing_catalog(args.pricing_file)

    if args.dry_run:
        if teacher_provider == "gemini":
            print(f"Teacher API: interactions; client transport timeout={args.teacher_timeout}s; "
                  f"max attempts={args.teacher_max_attempts}; no server deadline header; "
                  f"generation config={GeminiTeacherAdapter.GENERATION_CONFIG}.", flush=True)
        display_dry_run_plan(
            benchmark_path=benchmark_path,
            metadata=metadata,
            questions=questions,
            modes=modes,
            student_models=student_models,
            teacher_provider=teacher_provider,
            teacher_model=args.teacher_model,
            output_dir=output_dir,
            hw_meta=hw_meta,
            pricing_catalog=pricing_catalog,
        )
        return 0

    if teacher_provider == "gemini" and not args.allow_paid_api:
        raise SystemExit("Teacher requests require --allow-paid-api. Use --dry-run to inspect the plan first.")

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    completed_log_paths: List[Path] = []
    completed_log_payloads: List[Dict[str, Any]] = []

    # 1. Run Student Models
    for model_name, model_role in student_models.items():
        for mode in modes:
            use_retriever = (mode == "retriever")
            print(f"\n>>> Running Evaluation: Model={model_name} | Mode={mode} | Questions={len(questions)}")
            client, retriever = initialize_services(
                model_name=model_name, use_retriever=use_retriever,
                query_prefix="" if (use_retriever and args.no_query_prefix) else None,
                # Dev/eval scripts use the training DB; MONGODB_DB_NAME is the production database.
                db_name=resolve_training_db_name() if use_retriever else None,
            )
            try:
                pricing = (pricing_catalog or {}).get(model_name) or ModelPricing(model_name=model_name)
                metrics, records, log_path = run_baseline_evaluation(
                    client=client,
                    retriever=retriever,
                    questions=questions,
                    use_retriever=use_retriever,
                    benchmark_file=benchmark_path,
                    benchmark_metadata=metadata,
                    output_dir=output_dir,
                    pricing=pricing,
                    model_role=model_role,
                )
                print_scorecard(metrics, model_name, len(records))
                print(f"Log written safely to: {log_path}")
                if retriever is not None:
                    print(f"Retriever settings: {write_retriever_settings_sidecar(log_path, retriever, model_name)}")
                completed_log_paths.append(log_path)
                completed_log_payloads.append(json.loads(log_path.read_text(encoding="utf-8")))
            finally:
                if retriever is not None and getattr(retriever, "client", None) is not None:
                    retriever.client.close()

    # 2. Run Teacher Model (if enabled)
    if teacher_provider != "none":
        print(f"Initializing teacher adapter: provider={teacher_provider}; "
              f"API={'interactions' if teacher_provider == 'gemini' else 'mock'}; "
              f"client transport timeout={args.teacher_timeout}s; max attempts={args.teacher_max_attempts} "
              "(including initial request).", flush=True)
        try:
            adapter = build_teacher_adapter(teacher_provider, args.teacher_model,
                                            timeout_seconds=args.teacher_timeout,
                                            max_attempts=args.teacher_max_attempts)
        except Exception as exc:
            print(f"Teacher initialization failed ({type(exc).__name__}); no evaluation completed.", file=sys.stderr, flush=True)
            return 2
        for mode in modes:
            use_retriever = (mode == "retriever")
            print(f"\n>>> Running Teacher Evaluation: Model={adapter.model} | Mode={mode} | Questions={len(questions)}")
            retriever = None
            if use_retriever:
                from src.rag.retriever import RAGRetriever
                retriever = RAGRetriever(db_name=resolve_training_db_name())

            try:
                pricing = get_model_pricing(adapter.model, pricing_catalog)
                metrics, records, log_path = run_baseline_evaluation(
                    client=adapter,
                    retriever=retriever,
                    questions=questions,
                    use_retriever=use_retriever,
                    benchmark_file=benchmark_path,
                    benchmark_metadata=metadata,
                    output_dir=output_dir,
                    pricing=pricing,
                    model_role="teacher",
                )
                print_scorecard(metrics, adapter.model, len(records))
                print(f"Teacher log written safely to: {log_path}")
                completed_log_paths.append(log_path)
                completed_log_payloads.append(json.loads(log_path.read_text(encoding="utf-8")))
            finally:
                if retriever is not None and hasattr(retriever, "client"):
                    retriever.client.close()

    # 3. Automatic Comparison Table Generation (if requested)
    if args.compare and completed_log_payloads:
        print("\n" + "=" * 80)
        print("GENERATING AUTOMATIC COMPARISON TABLE")
        print("=" * 80)
        for mode in modes:
            selected = [(log, path) for log, path in zip(completed_log_payloads, completed_log_paths)
                        if log["metrics"]["context_mode"] == mode]
            report = compare_evaluations(
                logs=[log for log, _ in selected], log_paths=[path for _, path in selected],
                pricing_catalog=pricing_catalog,
                base_model_name=next((name for name, role in student_models.items() if role == "base_student"), None),
                teacher_model_name=adapter.model if teacher_provider != "none" else None,
            )
            print(format_comparison_text(report))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaselineExecutionError as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        sys.exit(2)
