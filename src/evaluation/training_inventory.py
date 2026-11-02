"""Read-only inventory of explicitly supplied training artifacts."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

def load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Safely loads a JSON file if it exists, returning None otherwise."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def inspect_single_run_directory(run_dir: Path) -> Dict[str, Any]:
    """Analyzes a single training run directory in read-only mode."""
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_dir():
        return {
            "run_dir": str(run_dir),
            "run_id": run_dir.name,
            "status": "directory_not_found",
            "exists": False,
        }

    run_config = load_json_safe(run_dir / "run_config.json") or {}
    run_summary = load_json_safe(run_dir / "run_summary.json") or {}
    split_manifest = load_json_safe(run_dir / "split_manifest.json") or {}
    baseline_val = load_json_safe(run_dir / "baseline_validation.json") or {}
    search_plan = load_json_safe(run_dir / "search_plan.json") or {}
    search_results = load_json_safe(run_dir / "search_results.json") or {}
    best_params = load_json_safe(run_dir / "best_hyperparameters.json") or {}
    interruption = load_json_safe(run_dir / "interruption.json") or {}
    checkpoint_audit = load_json_safe(run_dir / "checkpoint_audit.json") or []

    run_name = run_config.get("run_name") or run_dir.name
    raw_mode = run_config.get("run_mode", run_summary.get("run_mode", "unknown"))

    # 1. Classify Run Type
    is_smoke = (
        raw_mode == "smoke"
        or run_summary.get("smoke_test_only") is True
        or run_config.get("max_steps", -1) in (10, 20)
        or (raw_mode == "unknown" and "smoke" in run_name.lower())
    )
    is_search = (
        raw_mode == "search"
        or (run_dir / "trials").is_dir()
        or (run_dir / "search_results.csv").is_file()
        or bool(search_plan)
        or "search" in run_name.lower()
    )
    is_resumed = (
        run_config.get("resume") is True
        or (run_dir / "resume_environment.json").is_file()
        or (run_dir / "environment_migration.json").is_file()
    )

    if is_search:
        classification = "hyperparameter_search"
        classification_notes = "Search container; each trial is counted once, not the container."
    elif is_smoke and raw_mode != "full":
        classification = "smoke_test"
        classification_notes = "Plumbing check (short budget, 20 steps / 128 tickets); verifies gradients and mask formatting, not convergence."
    elif is_resumed:
        classification = "resumed_run"
        classification_notes = "Continuation of a prior run from saved checkpoints; not an independent experiment."
    elif raw_mode == "full" or "full" in run_name.lower():
        classification = "full_run"
        classification_notes = "Full QLoRA training run across complete training set (excluding held-out tenant)."
    else:
        classification = "single_run"
        classification_notes = "Single fine-tuning run."

    # 2. Determine Overall Status
    if run_summary:
        status = "completed" if run_summary.get("all_recorded_losses_finite") is not False else "failed"
    elif interruption or (run_dir / "interrupted.json").is_file():
        status = "interrupted"
    elif is_search:
        if search_results.get("search_complete"):
            status = "completed"
        elif (run_dir / "trials").is_dir():
            status = "in_progress"
        else:
            status = "configured_not_started"
    elif (run_dir / "run_config.json").is_file():
        status = "in_progress"
    else:
        status = "unrecognized_artifacts"

    # 3. Audit Checkpoints (Explicitly NOT separate experiments)
    checkpoint_dirs = sorted(
        [d for d in (run_dir / "checkpoints").glob("checkpoint-*") if d.is_dir()],
        key=lambda p: int(p.name.rsplit("-", 1)[-1]) if p.name.rsplit("-", 1)[-1].isdigit() else 0,
    )
    checkpoints_count = len(checkpoint_dirs)

    # 4. Audit GGUF Exports (Explicitly NOT separate experiments)
    gguf_files = []
    gguf_dir = run_dir / "gguf"
    if gguf_dir.is_dir():
        gguf_files = [str(f.relative_to(run_dir)) for f in gguf_dir.rglob("*.gguf") if f.is_file()]

    # 5. Audit Adapter
    adapter_dir = run_dir / "adapter"
    has_adapter = (
        (adapter_dir / "adapter_config.json").is_file()
        and any((adapter_dir / name).is_file() for name in ("adapter_model.safetensors", "adapter_model.bin"))
    )

    # 6. Audit Trials if Search Run
    trials_inventory = []
    if is_search:
        trials_dir = run_dir / "trials"
        if trials_dir.is_dir():
            for t_dir in sorted(trials_dir.iterdir()):
                if not t_dir.is_dir():
                    continue
                trial_id = t_dir.name
                t_result = load_json_safe(t_dir / "result.json") or {}
                t_attempts = sorted([a.name for a in t_dir.glob("attempt_*") if a.is_dir()])
                retry_count = max(0, len(t_attempts) - 1)

                if not t_result and t_attempts:
                    t_result = load_json_safe(t_dir / t_attempts[-1] / "result.json") or {}

                t_params = t_result.get("hyperparameters") or load_json_safe(
                    t_dir / (t_attempts[-1] if t_attempts else "") / "hyperparameters.json"
                ) or {}

                trials_inventory.append({
                    "trial_id": trial_id,
                    "classification": "hyperparameter_screening_trial",
                    "status": t_result.get("status", "unknown"),
                    "hyperparameters": t_params,
                    "validation_loss": t_result.get("validation_loss"),
                    "baseline_validation_loss": t_result.get("baseline_validation_loss"),
                    "optimizer_steps": t_result.get("optimizer_steps"),
                    "attempts": t_attempts,
                    "retry_count": retry_count,
                    "is_retry": retry_count > 0,
                    "best_checkpoint": t_result.get("best_checkpoint"),
                    "error": t_result.get("error"),
                })

    if is_search:
        known = {t["trial_id"] for t in trials_inventory}
        for result in search_results.get("results", []):
            if isinstance(result, dict) and result.get("trial_id") not in known:
                trials_inventory.append({**result, "classification": "hyperparameter_screening_trial", "artifact_status": "result_metadata_only"})
                known.add(result.get("trial_id"))

    # Metrics and Losses
    baseline_loss = run_summary.get("baseline_validation_loss", baseline_val.get("baseline_loss"))
    selected_loss = run_summary.get("selected_validation_loss", run_summary.get("validation_metrics", {}).get("selected_loss"))
    loss_delta = (selected_loss - baseline_loss) if (selected_loss is not None and baseline_loss is not None) else None

    # Hyperparameters
    hyperparams = {
        "learning_rate": run_config.get("learning_rate"),
        "optimizer": run_config.get("optimizer"),
        "lora_rank": run_config.get("lora_rank"),
        "lora_alpha": run_config.get("lora_alpha"),
        "weight_decay": run_config.get("weight_decay"),
        "warmup_ratio": run_config.get("warmup_ratio"),
        "batch_size_effective": (
            run_config.get("train_batch_size", 1) * run_config.get("gradient_accumulation_steps", 8)
            if "train_batch_size" in run_config
            else None
        ),
    }

    return {
        "run_id": run_name,
        "run_dir": str(run_dir),
        "exists": True,
        "classification": classification,
        "classification_notes": classification_notes,
        "status": status,
        "model_name": run_config.get("model_name", "unknown"),
        "held_out_tenant": run_config.get("held_out_tenant") or split_manifest.get("held_out_tenant"),
        "data_sha256": run_config.get("data_sha256") or split_manifest.get("data_sha256"),
        "hyperparameters": hyperparams,
        "dataset_sample": {
            "train_examples": run_config.get("train_examples"),
            "validation_examples": run_config.get("validation_examples"),
            "train_tickets": run_config.get("train_tickets"),
            "validation_tickets": run_config.get("validation_tickets"),
        },
        "metrics": {
            "baseline_validation_loss": baseline_loss,
            "selected_validation_loss": selected_loss,
            "validation_loss_delta": loss_delta,
            "all_recorded_losses_finite": run_summary.get("all_recorded_losses_finite"),
            "best_checkpoint": run_summary.get("best_checkpoint"),
            "optimizer_steps_completed": run_summary.get("optimizer_steps"),
        },
        "artifacts_inventory": {
            "adapter_present": has_adapter,
            "adapter_path": str((run_dir / "adapter").relative_to(run_dir)) if has_adapter else None,
            "checkpoints_count": checkpoints_count,
            "checkpoints_list": [str(d.name) for d in checkpoint_dirs],
            "checkpoint_audit_present": bool(checkpoint_audit),
            "gguf_exports": gguf_files,
            "loss_curves_present": (run_dir / "loss_curves.png").is_file(),
            "loss_history_csv_present": (run_dir / "loss_history.csv").is_file(),
        },
        "search_details": {
            "planned_trials": search_results.get("planned_trials", len(search_plan.get("search", {}).get("plan", search_plan.get("plan", [])))),
            "completed_trials_count": search_results.get("successful_trials", len([t for t in trials_inventory if t["status"] == "completed"])),
            "failed_trials_count": len([t for t in trials_inventory if t["status"] == "failed"]),
            "best_trial_id": best_params.get("best_trial_id"),
            "best_hyperparameters": best_params.get("hyperparameters"),
            "trials": trials_inventory,
        } if is_search else None,
    }


def get_pending_remote_inventory():
    """No remote runs are inferred from notebook defaults or conversation history."""
    return []


def summarize_runs(
    run_directories: Sequence[Union[str, Path]],
    include_pending: bool = True,
) -> Dict[str, Any]:
    """Generates an honest, read-only inventory across supplied and remote runs."""
    inspected_runs = []
    seen_ids = set()
    seen_paths = set()

    # 1. Inspect explicitly supplied local directories
    for path_str in run_directories:
        p = Path(path_str).resolve()
        if p in seen_paths:
            continue
        seen_paths.add(p)
        if not p.is_dir():
            inspected_runs.append({"run_id": p.name, "run_dir": str(p), "exists": False, "classification": "unknown", "status": "directory_not_found"})
            continue
        if p.is_dir():
            # Check if this directory itself is a run (has run_config.json or trials/)
            if any((p / marker).exists() for marker in ("run_config.json", "run_summary.json", "search_results.json", "trials", "checkpoints")):
                rep = inspect_single_run_directory(p)
                inspected_runs.append(rep)
                seen_ids.add(rep["run_id"])
            else:
                # Check subdirectories
                sub_runs = [d for d in p.iterdir() if d.is_dir()]
                for sub in sub_runs:
                    if any((sub / marker).exists() for marker in ("run_config.json", "run_summary.json", "search_results.json", "trials", "checkpoints")):
                        if sub.resolve() in seen_paths:
                            continue
                        seen_paths.add(sub.resolve())
                        rep = inspect_single_run_directory(sub)
                        inspected_runs.append(rep)
                        seen_ids.add(rep["run_id"])

    # 2. Include pending remote runs if requested
    pending_runs = []
    if include_pending:
        for pending in get_pending_remote_inventory():
            if pending["run_id"] not in seen_ids:
                pending_runs.append(pending)

    all_entries = inspected_runs + pending_runs

    # Counts
    completed_runs = [r for r in all_entries if r["status"] == "completed"]
    failed_runs = [r for r in all_entries if r["status"] == "failed"]
    interrupted_runs = [r for r in all_entries if r["status"] == "interrupted"]
    pending_count = len([r for r in all_entries if r["status"] == "pending_remote"])

    # Search containers are not additional experiments. Count each trial once.
    independent_experiments = []
    for run in inspected_runs:
        if run.get("classification") == "hyperparameter_search":
            independent_experiments.extend(run["search_details"]["trials"])
        elif run.get("exists"):
            independent_experiments.append(run)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary_counts": {
            "total_independent_experiments_inventoried": len(independent_experiments),
            "completed": sum(r.get("status") == "completed" for r in independent_experiments),
            "failed": sum(r.get("status") == "failed" for r in independent_experiments),
            "interrupted": len(interrupted_runs),
            "pending_remote": pending_count,
            "explicitly_supplied_directories_found": sum(r.get("exists", False) for r in inspected_runs),
        },
        "classification_rules_enforced": [
            "Checkpoints (checkpoint-*) are intermediate training snapshots, NOT independent experiments.",
            "Quantization formats (Q4_K_M GGUF) are export artifacts, NOT independent experiments.",
            "Retries and resume attempts (attempt_02) are continuations, NOT independent experiments.",
            "Code search space definitions do NOT infer completed runs without physical artifacts.",
            "Unavailable remote artifacts are not inferred; supply their directories to audit them.",
        ],
        "runs": all_entries,
    }


def format_markdown_report(inventory: Dict[str, Any]) -> str:
    """Formats the inventory as a clean, rigorous markdown document."""
    lines = [
        "# Training Artifact Inventory & Experiment Audit",
        "",
        f"**Audit Timestamp:** `{inventory['timestamp']}`  ",
        f"**Total Independent Experiments Tracked:** `{inventory['summary_counts']['total_independent_experiments_inventoried']}`  ",
        f"**Completed:** `{inventory['summary_counts']['completed']}` | **Failed:** `{inventory['summary_counts']['failed']}` | **Pending Remote:** `{inventory['summary_counts']['pending_remote']}`  ",
        "",
        "## Accounting & Disambiguation Standards",
        "> [!IMPORTANT]",
        "> 1. **Checkpoints Are Not Experiments:** Periodic saves (`checkpoint-200`, `checkpoint-400`) belong to a single training run.",
        "> 2. **Quantization Formats Are Not Experiments:** GGUF (`Q4_K_M`) and FP16 weights are post-training export artifacts.",
        "> 3. **Retries Are Not Experiments:** Resumed attempts (`attempt_02` after an interrupted `attempt_01`) continue the same trial.",
        "> 4. **No Code-Existence Inferences:** The presence of a 4-combination grid in `train_llama_qlora_kaggle.ipynb` does not count as 4 completed experiments unless output artifacts exist.",
        "> 5. **Remote Artifact Status:** No remote runs are inferred. Supply downloaded directories to inspect their evidence.",
        "",
        "## Experiment Inventory",
        "",
        "| Run ID | Classification | Status | Base Model | LR / Optim | Rank | Baseline Val | Selected Val | Checkpoints | Artifact Status |",
        "|:---|:---|:---|:---|:---|:---:|:---:|:---:|:---:|:---|",
    ]

    for run in inventory["runs"]:
        run_id = run["run_id"]
        cls_name = run["classification"]
        status = run["status"]
        model = run.get("model_name", "").split("/")[-1]
        hp = run.get("hyperparameters", {})
        lr = f"{hp.get('learning_rate', 'n/a')}" if isinstance(hp.get("learning_rate"), (int, float)) else "grid"
        optim = hp.get("optimizer", "n/a")
        rank = hp.get("lora_rank", "n/a")

        metrics = run.get("metrics", {})
        b_loss = f"{metrics.get('baseline_validation_loss', 'n/a'):.4f}" if isinstance(metrics.get("baseline_validation_loss"), (int, float)) else "n/a"
        s_loss = f"{metrics.get('selected_validation_loss', 'n/a'):.4f}" if isinstance(metrics.get("selected_validation_loss"), (int, float)) else "n/a"

        art = run.get("artifacts_inventory", {})
        chk_count = art.get("checkpoints_count", 0)

        if run.get("status") == "pending_remote":
            art_status = f"Pending on {run.get('storage_location', 'Remote')}"
        elif run.get("exists"):
            parts = []
            if art.get("adapter_present"):
                parts.append("Adapter")
            if chk_count > 0:
                parts.append(f"{chk_count} Chkpts")
            if art.get("gguf_exports"):
                parts.append("GGUF")
            art_status = ", ".join(parts) if parts else "Config only"
        else:
            art_status = "Not found locally"

        lines.append(
            f"| `{run_id}` | `{cls_name}` | **{status}** | `{model}` | {lr} / {optim} | {rank} | {b_loss} | {s_loss} | {chk_count} | {art_status} |"
        )

    lines.extend([
        "",
        "## Run Classification Taxonomy",
        "- **`smoke_test`**: Short pipeline and gradient sanity checks (e.g. 20 steps, 128 tickets). Not evaluated for convergence.",
        "- **`hyperparameter_screening_trial`**: Short bounded trial (e.g. 60 steps on 256 tickets) comparing learning rates or optimizers against validation completion loss.",
        "- **`full_run`**: Full fine-tuning run across complete training set for full epochs (excluding held-out tenant `harbor_view`).",
        "- **`resumed_run`**: Exact resumption from an audited checkpoint using saved optimizer and RNG states.",
        "- Dataset SHA-256 fingerprints are recorded; a changed hash alone does not prove a deliberate updated-dataset iteration.",
        "",
        "Only explicitly supplied training directories are audited. Generation evaluations must be reported from their own logs.",

    ])

    return "\n".join(lines)
