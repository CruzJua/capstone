# Model-refinement development baseline

This work prepares and evaluates the current local model for a future runtime refinement. It does not change the system prompt, decoding policy, contact settings, or widget handoff flow. The project owner explicitly deferred those application changes. No additional training, teacher generation, or paid judging is part of this work.

## Evaluation fixtures

Both fixtures are sampled deterministically from the existing `data/cleaned/train_tickets.csv`, using seed 390. The source is read only. The preparation logic is `src/evaluation/refinement_dataset.py`; its CLI is `scripts/prepare_refinement_eval.py`.

| Fixture | Questions | Per tenant | Supported answer | Missing-information escalation | Human-required escalation |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `data/evaluation/refinement_dev.json` | 40 | 10 | 20 | 12 | 8 |
| `data/evaluation/refinement_validation.json` | 40 | 10 | 20 | 12 | 8 |

The four tenants are `cinder_and_salt`, `iron_and_oak`, `kettle_and_loom`, and `northstar_auto`. Each contributes five supported-answer questions, three missing-information questions, and two answer-present questions requiring human handling to each split. In each split, 28 questions are answer-present and 12 answer-absent; the expected actions are balanced at 20 answers and 20 escalations.

Ticket IDs, tenant/source-batch groups, and normalized exact question text are disjoint between splits. Questions, reference answers, evidence, and action labels are preserved from the source. This is a development check on training-exposed examples and tenants, not an unseen-training-example or unseen-tenant generalization claim. Exact-text and batch separation do not establish semantic paraphrase independence. Neither split contains `harbor_view`.

| Input or fixture | SHA256 |
| :--- | :--- |
| Source training CSV | `a025d7005aa4ec88f1a537f8e666ab6ac1a2c182d0f0db2e8faed1a3c992fe79` |
| Development fixture | `f38adfb221915558a6415892a95cf6aa7228a39ac8252e1fa537429131761522` |
| Validation fixture | `04e62aefd43a539a277e4a09947fe6a5fd08835900247f7052564e96f22ff430` |

The preparation CLI refuses existing outputs, output collisions, training-directory targets, and the frozen benchmark filename. Reproducing the files later requires new output paths; it does not require overwriting the current fixtures.

## Commands

Executed from the repository root:

```bash
.venv/bin/python scripts/prepare_refinement_eval.py
.venv/bin/python -m unittest tests.test_refinement_dataset -v
```

To reproduce the same fixtures at new paths:

```bash
.venv/bin/python scripts/prepare_refinement_eval.py \
    --source data/cleaned/train_tickets.csv \
    --seed 390 \
    --dev-output /tmp/refinement_dev_reproduced.json \
    --validation-output /tmp/refinement_validation_reproduced.json
```

The model runner uses local Ollama and read-only retrieval from the configured training database. Teacher requests are disabled explicitly. Offline embedding-cache flags prevent Hugging Face downloads. The default inference-client temperature is 0.2; neither prompt nor sampling settings were tuned in this work.

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
.venv/bin/python scripts/run_baselines.py \
    --finetuned-models llama3.2:3b-qlora-hardneg-full01-q4 \
    --teacher-provider none \
    --context-mode both \
    --benchmark-file data/evaluation/refinement_dev.json \
    --output-dir logs/refinement/baseline_dev

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
.venv/bin/python scripts/run_baselines.py \
    --finetuned-models llama3.2:3b-qlora-hardneg-full01-q4 \
    --teacher-provider none \
    --context-mode both \
    --benchmark-file data/evaluation/refinement_validation.json \
    --output-dir logs/refinement/baseline_validation
```

Each command was planned with `--dry-run` before execution. Credentials and database connection strings are not included in this report.

## Ground-truth-context results

Both ground-truth runs completed all 40 requested responses, with no execution failures. No retrieved context was substituted for the reference evidence in this mode.

| Split | Correct actions | Valid schemas | Escalation precision | Escalation recall | Escalation F1 | Answer action on absent questions |
| :--- | :--- | :--- | ---: | ---: | ---: | :--- |
| Development | 32/40 = 80.0% | 40/40 | 100.0% | 60.0% | 75.0% | 0/12 |
| Validation | 33/40 = 82.5% | 40/40 | 100.0% | 65.0% | 78.8% | 0/12 |

| Split | Supported questions answered | Absent questions escalated | Human-required questions escalated | Generation p50 / p95 | Mean generation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Development | 20/20 | 12/12 | 0/8 | 1351 / 1955 ms | 1438 ms |
| Validation | 20/20 | 12/12 | 1/8 | 1369 / 1698 ms | 1419 ms |

These action counts do not establish factual correctness of the generated answer text. Ground-truth absence is straightforward in this harness because unanswerable questions receive no evidence; live retrieval can provide distracting or incomplete passages instead.

## Live-RAG results

Both live-RAG runs completed all 40 requested responses using MongoDB Atlas, `capstone_dev.doc_vectors`, index `vector_index`, BGE query prefix enabled, reranker off, top-k 4, maximum 2 chunks per document, and 100 vector candidates. Retrieval remained tenant-scoped. The evaluation runner applies no relevance cutoff; these are not measurements of the gateway's per-tenant similarity-threshold configuration.

| Split | Correct actions | Valid schemas | Escalation precision | Escalation recall | Escalation F1 | Answer action on absent questions |
| :--- | :--- | :--- | ---: | ---: | ---: | :--- |
| Development | 29/40 = 72.5% | 40/40 | 100.0% | 45.0% | 62.1% | 5/12 = 41.7% |
| Validation | 34/40 = 85.0% | 40/40 | 93.8% | 75.0% | 83.3% | 1/12 = 8.3% |

| Split | Supported questions answered | Absent questions escalated | Human-required questions escalated | Generation p50 / p95 | Mean generation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Development | 20/20 | 7/12 | 2/8 | 1670 / 2119 ms | 1717 ms |
| Validation | 19/20 | 11/12 | 4/8 | 1740 / 2198 ms | 1745 ms |

Human-required escalation remains a weakness in both modes. Differences between development and validation reflect different small samples under the same unchanged model, not a before/after improvement. The higher live validation score does not establish better factual quality or a generalization gain.

## Run artifacts and serving provenance

All four actual runs exited successfully, completing 160/160 requested responses. All 160 raw JSON responses passed the response schema. Independent checks matched every record to its fixture and recomputed action accuracy, escalation precision/recall/F1, schema validity and the absent-answer action proxy.

| Split | Context | Generation log |
| :--- | :--- | :--- |
| Development | Ground truth | `logs/refinement/baseline_dev/baseline_eval_llama3.2_3b-qlora-hardneg-full01-q4_ground_truth_20261109_053012.json` |
| Development | Live RAG | `logs/refinement/baseline_dev/baseline_eval_llama3.2_3b-qlora-hardneg-full01-q4_retriever_20261109_053132.json` |
| Validation | Ground truth | `logs/refinement/baseline_validation/baseline_eval_llama3.2_3b-qlora-hardneg-full01-q4_ground_truth_20261109_053243.json` |
| Validation | Live RAG | `logs/refinement/baseline_validation/baseline_eval_llama3.2_3b-qlora-hardneg-full01-q4_retriever_20261109_053406.json` |

The live logs have adjacent `.retriever_settings.json` sidecars. `evaluation/reports/refinement_baseline_results.json` records exact commands, execution exit codes, fixture/source/log/sidecar hashes, per-stratum action counts and latency distributions. The Ollama model identity remained `782d8b899e9170e1ff3715c58710cdfbefcf0fdbdcbb0c0efacecc067450511d`; request temperature was 0.2 and the observed runtime context window was 4096 tokens. Serving discovery recorded no errors. Hardware discovery did not identify a GPU through its command-line probe; Ollama's serving metadata separately records resident VRAM, which is not a peak-memory measurement.

Teacher provider was `none` throughout. No teacher or judge API requests were made. Local inference has zero API token cost; this does not include hardware, electricity, or existing database hosting costs. No new factual hallucination judgments were produced.

## Interpretation and scope

Ground-truth-context and live-RAG outcomes must remain separate. Action accuracy, escalation precision/recall, schema validity, and latency are measured by the existing runner. Its legacy `hallucination_rate` field is an absent-answer action proxy: choosing `answer` on an unanswerable question. It is not a factual-fabrication judgment. No new judge-based pass rate, fabrication-rate comparison, teacher-gap recovery, or improvement claim is supported by these baseline runs.

The runner exercises `SupportInferenceClient` and the retriever, rather than the public gateway/widget or tenant-specific production configuration. It does not test contact-form collection or guarantee successful human contact. Future runtime changes must be shared with the evaluated path or tested through the production path separately.

No candidate adjustment is selected here. The validation fixture is evaluated with the same unchanged baseline; future changes should be chosen using development evidence, without adapting rules to individual validation or held-out failures. No held-out confirmation is run because no model behavior changes in this scope.

The existing held-out report and the project owner's reported live outage checks are separate evidence. Completing this baseline/testing scope does not mean the model's known escalation, factuality, or handoff-language limitations are solved. Prompt changes, accurate async-follow-up wording, configured public contact methods, and the visitor contact form are deferred work.

## Automated verification

An independent verification agent ran the following checks after fixture creation:

| Check | Actual result |
| :--- | :--- |
| Python `unittest discover -s tests` | 391 passed, including 9 new fixture tests |
| Gateway `npm test` | 157 passed |
| Widget `npm test` | 40 passed |
| Dashboard `npm test` | 10 passed |
| Dashboard `npm run lint` | Clean, exit 0 |

The fixture audit checked source-exact fields, source hashes, balancing, tenant exclusion, loader compatibility and disjoint IDs/batches/normalized questions. It found no issue. Local mock HTTP tests required socket access outside the restricted sandbox; final results above are the successful reruns, not the restricted attempts.

Frozen benchmark, original training CSV, hard-negative training CSV, inference client, response schema and chat orchestrator hashes matched the pre-task snapshot after verification. No production service was restarted. Files remain uncommitted; unrelated pre-existing working-tree changes are retained.
