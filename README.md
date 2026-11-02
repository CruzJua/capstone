# Local Customer Support Agent

A Python prototype for tenant-filtered MongoDB Atlas retrieval and schema-constrained local support responses through Ollama. It includes a loopback chat demo, QLoRA training/export notebooks, and independent retrieval/generation/judge evaluation tools. The embeddable widget and administration/ticket interface are later application work.

The compact [experiment results](evaluation/results.json) retain source hashes, four short Kaggle screenings, two separate full runs, six Kaggle model/context evaluations, rubric assessments, and retrieval measurements. Training curves: [current Kaggle full run](evaluation/training/kaggle_full01_loss.png) and [historical Colab full run](evaluation/training/colab_full01_loss.png). Raw logs and downloaded models stay local and are not included in Git.

**Recorded limitations:** all three Kaggle quantizations returned valid JSON but answered all 100 live-RAG cases, including 50 absent-answer cases and four requiring a human. Escalation recall was zero; these are experimental integration candidates. Valid JSON, exact quotations, and passing software tests do not establish grounded answers. The teacher baseline is complete in both modes; measured comparisons and their limits are summarized below. Revised-data retraining is deferred until after Sprint 4.

## Setup and local demo

### Portable Self-Contained Docker Demo (No Atlas Account or Paid API Required)

For a reproducible, self-contained local demonstration of the Management Dashboard (`dashboard/`), Orchestration Gateway (`gateway/`), local MongoDB Vector Search (`mongodb/mongodb-atlas-local:8.0`), and the 5 preset businesses (`cinder_and_salt`, `harbor_view`, `iron_and_oak`, `kettle_and_loom`, `northstar_auto`) from [`data/fixtures/demo_manifest.json`](data/fixtures/demo_manifest.json):

```bash
# 1-command setup: generates .env.demo.local, starts local MongoDB + Vector Search,
# seeds 5 businesses, 12 sample tickets, 30 source docs (384-dim bge-small-en-v1.5),
# waits for vector_index READY + $vectorSearch smoke query, and launches Gateway + Dashboard:
bash scripts/setup_demo.sh

# Lifecycle commands:
bash scripts/setup_demo.sh status            # Inspect container health, seed counts, and Ollama readiness
bash scripts/setup_demo.sh restart           # Restart gateway/dashboard while preserving demo MongoDB volumes
bash scripts/setup_demo.sh stop              # Stop demo containers without deleting volumes
bash scripts/setup_demo.sh logs              # Inspect container logs
bash scripts/setup_demo.sh reset             # Tear down ONLY capstone_local_demo containers and demo volumes
bash scripts/setup_demo.sh reset --rebuild   # Wipe demo volumes and re-seed from scratch
```

- **Endpoints (bound to loopback `127.0.0.1`):**
  - **Admin Dashboard (One-Click Demo Login):** [http://localhost:3001/login](http://localhost:3001/login)
  - **Orchestration Gateway API & Health:** [http://localhost:4001/api/health](http://localhost:4001/api/health)
  - **Local MongoDB Atlas (Vector Search):** `127.0.0.1:27018` (database `capstone_demo`, isolated from standard `rag_knowledge_base` and `capstone_dev`)
- **Prerequisites & Disk Expectations:** Docker Engine / Desktop with `docker compose` (~2.5 GB disk for container images and the cached `BAAI/bge-small-en-v1.5` embedding model). If `~/.cache/huggingface` already contains `BAAI/bge-small-en-v1.5`, the seed job copies it into the `demo_hf_cache` volume automatically.
- **What Works Without vs. With Ollama:** One-click demo authentication, tenant switching, runtime configuration updates, document inventory, raw document viewing, chunk inspection, `.md`/`.json` document uploads with 384-dim vector indexing, ticket review queue actions, and `$vectorSearch` retrieval all work immediately without Ollama. For live LLM generation, start `ollama serve` on the host (and `ollama pull llama3.2:3b` or import your fine-tuned GGUF); `/api/health` and the dashboard sidebar report `ollama_reachable` and `ollama_ready` dynamically.
- **Dry-Run & Host Seeding CLI:** You can inspect the deterministic fixture manifest and hashes without connecting to any database via `.venv/bin/python scripts/seed_demo.py --dry-run`.

### Python Loopback Chat Demo & Manual Setup

From the repository root, install Python 3.14+ and `uv`, then initialize a fresh checkout:

```bash
uv sync
cp .env.example .env
```

Configure `.env` with `MONGODB_URI`, `MONGODB_DB_NAME`, `MONGODB_COLLECTION_NAME`, `MONGODB_VECTOR_INDEX_NAME`, `EMBEDDING_MODEL_NAME`, `OLLAMA_HOST`, and `OLLAMA_MODEL`. Keep credentials local. Recorded retrieval used `capstone_dev.doc_vectors`, index `vector_index`, and `BAAI/bge-small-en-v1.5`; the embedding model must match the existing index. Optional `HF_TOKEN` supplies Hugging Face authentication. When embeddings are cached, `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` prevents downloads.

Ollama must be running (`ollama serve` if needed). The repo does not contain or download model weights. To import your downloaded Kaggle GGUF, copy the portable template, edit its `FROM` path to the actual file, then create the local tag:

```bash
cp evaluation/Modelfile.example Modelfile.local
# Edit FROM in Modelfile.local before running ollama create.
ollama create llama3.2:3b-qlora-kaggle-full01-q4 -f Modelfile.local
ollama list
OLLAMA_MODEL=llama3.2:3b-qlora-kaggle-full01-q4 \
  .venv/bin/python scripts/run_chat_demo.py --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Select a business and ask a question; the page displays retrieved evidence, context, answer, citations, action, confidence and timing. **Check connections** refreshes readiness. This is an unauthenticated loopback development demo. Run model and embedding jobs sequentially when compute is available. Repeat the import with the correct Q5/Q8 files and matching `...-q5` / `...-q8` tags before evaluating all three formats. Base-model comparisons also require `llama3.2:3b` installed separately.

## Data, parser and index checks

The versioned `data/cleaned/cleaned_tickets.csv` is the original cleaned synthetic corpus. The frozen [benchmark](data/evaluation/held_out_benchmark.json) contains 100 `harbor_view` cases: 50 answer-present, 50 absent; four present cases require escalation. Keep it unchanged and exclude this tenant from training and development tuning.

A fresh checkout lacks the ignored derived training CSV. If needed, this preparation command recreates that local copy and writes its accompanying sample benchmark under ignored `logs/`, preserving the versioned frozen benchmark. It is unnecessary on the existing workspace when the training CSV is already present:

```bash
.venv/bin/python scripts/prepare_evaluation_dataset.py \
  --dataset data/cleaned/cleaned_tickets.csv --tenant harbor_view \
  --samples-per-class 50 --seed 42 \
  --output-train data/cleaned/train_tickets.csv \
  --output-benchmark logs/prepared_benchmark.json
```

Read-only corpus/evidence inspections require no model or database:

```bash
.venv/bin/python scripts/audit_document_provenance.py \
  --csv data/cleaned/train_tickets.csv
.venv/bin/python scripts/ingest_rag_docs.py \
  --document-parser structured --inspect-only
```

The shared Markdown/JSON/TXT parser retains source identity, byte hashes, locators, table headers, negation and conditions. Provenance checks flag ambiguity, missing context and attribution problems; they do not rewrite citations or certify target correctness. Generator and ingestor default to `legacy`; structured mode is opt-in. Cleaner screening defaults to `off`; `--provenance-mode report --provenance-audit-only --provenance-report logs/NEW_REPORT.json` reports without exporting a dataset (supply raw inputs via `--files`; see `--help`).

The current data and vector index were not migrated. Eighteen JSON blocks exceed the default 500-word structured-ingestion budget; increasing a word budget does not prove tokenizer fit. Structured ingestion separately refuses embedding-token overflow. Actual ingestion requires explicit `--execute` and replaces tenant vectors; inspection does neither. Preserve the current index while collecting matched comparisons.

## Training and GGUF export

Retraining is deferred until after Sprint 4. For a future authorized run, [train_llama_qlora_kaggle.ipynb](notebooks/train_llama_qlora_kaggle.ipynb) supports `smoke`, `search`, and `full` modes. Default search is four 60-update trials on 256 training / 64 validation tickets. A full run uses a new `RUN_NAME`, `RUN_MODE="full"`, `RESUME=False`, and `BEST_PARAMS_FILE="auto"` with exactly one matching attached search output. Set `DATA_CSV` explicitly for a new dataset version: an old search artifact can otherwise supply its cached original CSV. Keep the data-hash guards; never relabel an old selection file with a new data hash. [The Colab notebook](notebooks/train_llama_qlora.ipynb) supports smoke/full training. Checkpoints, retries and quantization formats are not extra full training runs.

To export an **existing** full-run adapter in a fresh Kaggle session, use [export_gguf_kaggle.ipynb](notebooks/export_gguf_kaggle.ipynb). Attach the full-run reports and complete `adapter/` directory, including tokenizer/template and weights. Select one GPU, enable Internet, set `SOURCE_RUN_DIR` to the attached run or leave it blank to discover exactly one valid run, then run this export-only notebook top to bottom. It exports Q4_K_M, Q5_K_M and Q8_0 sequentially without a trainer; a training CSV is unnecessary. Download the GGUF files, `gguf_export.json`, and `source_provenance.json`. Valid existing exports resume; a fresh background session may repeat conversion. Running only a training notebook's last cell in an empty session is insufficient.

Read-only tools accept the actual downloaded paths:

```bash
# Set GGUF_FILE to a downloaded .gguf and RUN_DIR to a downloaded report directory.
: "${GGUF_FILE:?Set GGUF_FILE}" "${RUN_DIR:?Set RUN_DIR}"
.venv/bin/python scripts/inspect_gguf.py "$GGUF_FILE"
.venv/bin/python scripts/summarize_training_runs.py "$RUN_DIR"
```

## Evaluation, judging and comparison

The six original Kaggle generation runs are complete; rerun deliberately after relevant model/index changes. Ground-truth context and live retrieval are separate evaluation modes. This command **plans only**; remove `--dry-run` to execute the selected local matrix after all three tags are installed:

```bash
.venv/bin/python scripts/run_baselines.py \
  --finetuned-models llama3.2:3b-qlora-kaggle-full01-q4 \
    llama3.2:3b-qlora-kaggle-full01-q5 \
    llama3.2:3b-qlora-kaggle-full01-q8 \
  --teacher-provider none --context-mode both \
  --output-dir logs/baselines --dry-run
```

For one model, supply one tag. Add `--base-model llama3.2:3b` only when evaluating the base too. `--limit 5` is a smoke test, not full coverage. Retrieval alone can be measured on all 50 frozen answer-present cases:

```bash
.venv/bin/python scripts/benchmark_retrieval.py \
  --tenant harbor_view --dataset data/evaluation/held_out_benchmark.json \
  --sample-size 50 --k-values 1 3 4 5 --max-per-doc 2 \
  --summary-out logs/retrieval_summary.json --failures-out logs/retrieval_failures.json
```

Use exact generation paths printed by the runner. With `GEN_LOG` set to one completed generation JSON, plan independent local Gemma judging with the retained [versioned rubric](evaluation/judge_rubric.md):

```bash
: "${GEN_LOG:?Set GEN_LOG to a completed generation JSON}"
JUDGE_LOG="${GEN_LOG%.json}.judged.json"
.venv/bin/python scripts/judge_generation.py \
  --input "$GEN_LOG" --provider ollama --model gemma4:latest \
  --think false --num-ctx 8192 --num-predict 512 --output "$JUDGE_LOG"
```

Without `--execute`, judging makes no calls or writes. When compute is free, append `--execute --max-calls 200` for a 100-response log. Matching settings resume unfinished records; changed controls require a separate output. Contradictory decision-table scores are rejected, and failed/pending assessments remain visible. Summarize without calls using `scripts/judge_generation.py --summarize "$JUDGE_LOG"`.

Compare two completed logs from the same benchmark, coverage and context mode without inference:

```bash
: "${GEN_LOG_B:?Set GEN_LOG_B to the other matching generation JSON}"
.venv/bin/python scripts/compare_evaluations.py \
  --logs "$GEN_LOG" "$GEN_LOG_B" --require-compatible \
  --format json --output logs/comparison.json
```

Add `--judged-logs "$JUDGE_LOG" "$OTHER_JUDGE_LOG"` when both matching assessments exist. Source hashes attach judgments to their generation runs. Do not mix smoke/full coverage or ground-truth/retriever modes. Legacy serving settings can be incomplete; preserve compatibility warnings. Absent-answer action rate is not a content-hallucination rate, and resident VRAM snapshots are not peak memory. Kaggle and older Colab results remain separate in `evaluation/results.json`.

## Teacher baseline and measured comparison

The `gemini-3.8-flash` baseline completed with 100 ground-truth-context and 100 retrieval-context responses, all valid JSON. Gemini credentials are resolved from the project `.env` before inherited shell variables; logs record only the credential source.

The adapter uses synchronous `client.interactions.create` with canonical `models/gemini-3.8-flash`, `thinking_level="medium"`, `max_output_tokens=65536`, no temperature override, and stateless requests (`store=false`). The output limit is a ceiling, not a fixed token charge. The local transport timeout does not send `X-Server-Timeout`; the bounded retry budget is tested. Evaluation logs preserve responses, synchronous latency and output plus thinking tokens, so another teacher run is not needed solely for latency.

The compact [measured results](evaluation/results.json) include action accuracy of **95% / 92%** for ground truth / retrieval, mean generation latency of **4.26 / 5.34 seconds**, and catalog estimates of **$1.52 / $2.87 per 1,000 requests**. The 200-response generation run totals an estimated **$0.44**, not a verified provider invoice. Rubric coverage is **198 valid local Gemma judgments plus two separate secondary AI assessments**: 95 ground-truth strict passes and 87 retrieval strict passes. The raw retrieval Gemma file has 86 strict passes and two unscored records; secondary assessments stay in a separate artifact. Prior Kaggle coverage remains 599 Gemma judgments plus one separate assessment and 57 documented decision-table corrections.

Questions, targets and supplied contexts match the teacher and students within each mode. Gemini and Ollama generation settings differ, so the harness retains its compatibility error and withholds formal controlled recovery/gap-closed metrics. Historical base numerical results have missing serving identity; their older/incomplete rubric assessments are excluded. Targeted spot checks flagged suspected judge citation/reference-answer errors without changing valid Gemma verdicts. These are model assessments, not a human agreement study. Raw comparison and assessment artifacts remain local under `logs/teacher_comparison_20261027/`; revised-dataset retraining remains deferred until after Sprint 4.

For a new access check after configuration changes, use the two-question structured baseline before committing to a full run. The completed baseline above does not need repeating. This example is **plan-only**:

```bash
.venv/bin/python scripts/run_baselines.py --models none \
  --teacher-provider gemini --teacher-model gemini-3.8-flash \
  --teacher-timeout 180 --teacher-max-attempts 1 --limit 2 \
  --context-mode ground_truth --pricing-file evaluation/pricing_gemini_20261027.json \
  --output-dir logs/teacher_interactions_access_check --dry-run
```

For an authorized full run after both access-check responses complete with valid JSON, omit `--limit 2`, use `--context-mode both`, and choose `--output-dir logs/teacher_interactions_baselines`; actual paid execution additionally requires `--allow-paid-api` and removal of `--dry-run`. An action `MISS` is a quality finding, not an access failure. Both modes total 200 questions, and this same synchronous run records latency. The [dated pricing file](evaluation/pricing_gemini_20261027.json) is a historical estimate configuration; verify it before future billing estimates. Thinking and visible output are both billed at the output rate. Unknown usage remains unmeasured, and provider billing is authoritative. API/thinking/temperature settings differ from the local students; retain comparison warnings rather than claiming identical serving conditions. Local $0 API token cost excludes hardware, energy and hosting.

## Software checks and repository artifacts

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 CUDA_VISIBLE_DEVICES='' \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -m unittest discover -s tests -v
```

These checks cover software and mocked services, not new training or live quality experiments. Two full-dataset checks skip when the local derived training CSV is absent; the optional fresh-checkout preparation above enables them. Keep source, tests, notebooks, tenant source documents, the canonical cleaned CSV, frozen benchmark, rubric and compact evidence in Git. `.gitignore` excludes credentials, raw generation/state files, local logs, derived training copies, model weights, adapters, checkpoints and `Modelfile.local`.
