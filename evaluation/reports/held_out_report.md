# Held-out evaluation report: hard-negative model (`llama32_3b_hardneg_full_01`)

Models: `llama3.2:3b-qlora-hardneg-full01-q4` and `-q8` (Ollama). Control: the sprint-3 `llama3.2:3b-qlora-kaggle-full01` q4/q8 ("old"). Untuned base: `llama3.2:3b`. Teacher: `gemini-3.8-flash`. Benchmark: `data/evaluation/held_out_benchmark.json` (frozen, 100 `harbor_view` questions, sha256 `656bd369b60b6db973078f2674f771ce75132d46a77938bcb5648ac7b1e9d261`, verified unchanged before and after every run).

**Revision 3.** This revision incorporates the completed 49-row response review (section 5d), corrects statistical and provenance wording, and verifies the saved generation/judgment logs without new inference or paid API calls. The earlier revision added three saved runs (marked **‡**: the untuned base model on ground truth and on live retrieval, and the teacher on live retrieval with the current retriever) and standard teacher-gap recovery (section 8). Section 1 provides the summary.

**How to read this report.** Ground-truth-context results and live-retrieval results are in separate tables and are never pooled. Judge-free numbers are the headline; judge-based numbers come from `gpt-5.4-mini` and are **not comparable** to the historical sprint-3 Gemma-judged numbers (live q4 18/100, q8 21/100; ground truth q4 82/100, q8 85/100). Near a 50% rate, the approximate 95% margin of error is +/-14 percentage points at n = 50 and +/-10 at n = 100; these are single-rate binomial approximations, not uncertainty estimates for paired model differences. Section 6c uses paired question-by-question tests. The benchmark has 50 unanswerable questions (expect escalate), 46 answerable questions (expect answer) and 4 answerable questions where the documents require a human (`docs_require_human`, expect escalate). "Answer present" means the 50 answerable questions (46 + 4); "answer absent" means the 50 unanswerable ones.

## 1. Summary

1. **The hard-negative training repaired the old fine-tune's escalation failure.** Live, the old models escalated 0 of 50 unanswerable questions and the new ones 21 (q4) and 30 (q8). Judged live passes went from 23 and 21 to 45 and 53 of 100. Question by question, the new q4 beats the old q4 on a net 22 questions and the new q8 beats the old q8 on a net 32 (sign test p < 0.001 for both).
2. **But the new model is not shown to beat the untuned base model.** **‡** The untuned `llama3.2:3b` is already a strong baseline in this harness: with ground truth it escalates 50 of 50 absent questions, and live it escalates 26 of 50 (new q4: 21, new q8: 30). Judged passes: base 63 (ground truth) and 47 (live) against new q4 67 and 45, new q8 71 and 53. The paired differences are +4 and +8 (ground truth) and -2 and +6 (live) questions, none distinguishable from zero (p between 0.30 and 0.87). The old fine-tune was clearly *worse* than the base (live, net -24 questions, p < 0.001).
3. **Standard recovery** **‡** = (student - base) / (teacher - base), strict passes: ground truth 19% (q4) and 38% (q8); live -5% (q4) and +15% (q8). The old models: -10% (ground truth) and -59% / -63% (live). With n = 100 none of the new-model values is distinguishable from 0%. The honest reading: hard-negative training restored roughly base-model quality; it has not been shown to add quality beyond the base.
4. **The behavior profile does differ from the base** (descriptive, small n). **‡** The base over-escalates answerable questions (7 of 46 with ground truth; the new models 0 of 46) and answers 16 of the 50 absent questions confidently by a text heuristic (new q4: 3, new q8: 4), but it escalates 3 of the 4 `docs_require_human` questions live where the new models escalate 1. So fine-tuning changed what kind of mistakes the model makes, without a measured net gain.
5. **Escalation is not solved live.** 29 (q4) and 20 (q8) of the 50 unanswerable questions are still labelled `action=answer`. The completed response review labels 9/29 (31.0%) q4 answers and 3/20 (15.0%) q8 answers as fabricated, including minor unsupported details; 18 q4 and 15 q8 answers acknowledge missing information or offer a human next step without fabricated facts. Another 2 answers per model are labelled neither fabricated nor handoff-only. These textual categories do not change the recorded actions or pass counts (section 5d).
6. **The teacher is far ahead live.** **‡** On live retrieval with the current retriever, `gemini-3.8-flash` passes 88 of 100 (strict) against 53 for the best student (net 35 questions, p < 0.001). It escalates 50 of 50 absent and 4 of 4 `docs_require_human`, but it also over-escalates 7 of 46 answerable questions.
7. **Held-out status** is verified to a stated extent in section 1a: no `harbor_view` data and no copied benchmark question or source passage in the local training CSV.
8. **Limits:** 27 records are unjudged (all `answer_present`, all `inconsistent_verdict`), one LLM judge with known strictness quirks, n = 100, a single base-model prompt/schema setup, and a response review restricted to the new models' 49 live answered-absent outputs. It is not an independent multi-reviewer validation.

## 1a. Held-out status (verified read-only)

**What was verified.** The local training file used for this model, `data/cleaned/hardneg_v1/train_tickets.csv` (3,947 rows), contains no `harbor_view` data and no copy of any benchmark question or `harbor_view` source passage. Its sha256 (`797653bb…09ef`) matches the one recorded in `logs/hardneg_v1_training_manifest.json`, and the manifest itself records `held_out_tenant_absent: true`. The two inputs it was built from (`data/cleaned/train_tickets.csv`, 3,995 rows, and `data/cleaned/hardneg_hardneg_v1.csv`, 1,199 rows) also match the manifest hashes and contain only the four non-held-out tenants.

| Check | Result |
| :--- | :--- |
| Tenants in the training CSV | `cinder_and_salt` 974, `iron_and_oak` 989, `kettle_and_loom` 992, `northstar_auto` 992; **`harbor_view` 0 rows** |
| Case-insensitive "harbor" anywhere in any column (training CSV, base CSV, hard-negative CSV, hard-negative plan) | **0 occurrences** in each |
| `scripts/audit_training_data.py` error `held_out_tenant_in_training` | **not raised** |
| The 100 benchmark questions as exact (normalized) substrings of the training text | **0 of 100** |
| The 101 benchmark evidence quotes as exact substrings | **0 of 101** |
| The 185 `harbor_view` source passages (8+ words) as exact substrings | **0 of 185** |
| Highest word-6-gram overlap: questions / quotes / passages | 0.40 / 0.10 / 0.40, i.e. short generic phrases ("how much do you charge for", "how much notice do you need to"), not copies |

**Earlier audit commands** (read source data and write audit outputs where specified; retained from the previous revision, not re-executed for revision 3):

    sha256sum data/cleaned/hardneg_v1/train_tickets.csv data/cleaned/train_tickets.csv
    uv run python scripts/audit_training_data.py --input data/cleaned/hardneg_v1/train_tickets.csv \
        --held-out-tenant harbor_view --output logs/hardneg_full01_eval/training_audit_hardneg_v1.json
    grep -c -i harbor data/cleaned/hardneg_v1/train_tickets.csv
    uv run python scripts/check_heldout_leakage.py --output /tmp/heldout_leakage_check.json

The leakage-check entry point is now `scripts/check_heldout_leakage.py`, with reusable logic in `src/evaluation/heldout_leakage.py`. The earlier audit was executed before this relocation; the command above shows the current equivalent with a new output path so the archived `evaluation/reports/heldout_leakage_check.json` is preserved. The regular training-data audit checks the tenant column and quote integrity; this additional check compares question and passage text.

**What remains unverified (so "held-out" is claimed only to this extent):**

1. Whether the Kaggle job read exactly this file. The training notebook auto-discovers a single attached `train_tickets.csv` (and sets `HELD_OUT_TENANT = "harbor_view"` as a guard), but what was attached on Kaggle cannot be checked from this machine; only the local file and its manifest hash are verified.
2. Matching is exact text and 6-grams: it would not catch a paraphrase of a benchmark question or passage, or topically similar content from other tenants.
3. Exposure of the base model (`Llama-3.2-3B-Instruct`) or the teacher to `harbor_view` text before this project is unknowable here and not claimed.
4. Evaluation-time retrieval does use `harbor_view` documents by design: the live runs query the `harbor_view` chunks in `capstone_dev`. That is retrieval at test time, not training exposure.

**Side observation, unrelated to held-out status and not investigated:** the same audit run reports 345 `action_reason_inconsistency` errors (its expected escalation reason differs from the recorded one for the 345 `escalate|docs_require_human` rows). It does not affect the findings above, but it is a data-quality flag for whoever owns the training data.

## 2. Live-run backend and settings

| Setting | Value |
| :--- | :--- |
| Backend | MongoDB Atlas `$vectorSearch`, tenant pre-filter `tenant_id = harbor_view` |
| Database | `capstone_dev` (the training database). The original four live runs were pointed at it through `MONGODB_DB_NAME=capstone_dev`; the **‡** base and teacher live runs resolved it through `MONGODB_TRAINING_DB_NAME`, which has the same value |
| Collection / index | `doc_vectors` / `vector_index` |
| Embedding model | `BAAI/bge-small-en-v1.5` |
| BGE query prefix | **on** (`Represent this sentence for searching relevant passages: `); the P3 control run had it off |
| Reranker | **off** |
| Relevance cutoff | none |
| top_k | **4** |
| max chunks per document | 2 |
| numCandidates | 100 |
| Chunks for `harbor_view` | 61 |

Context determinism: the four original live runs (new q4, new q8, old q4, old q8) saw identical retrieved contexts for all 100 questions. **‡** The new base-model live run and the new teacher live run also saw identical contexts on **100 of 100** questions, so every live comparison in this report is context-matched. The older saved teacher live log (old retriever, no prefix) matches on only 41 of 100 and is no longer used. The P3 prefix-off run also matches only 41 of 100, by design.

## 3. Retrieval quality (recall@k)

Current retriever, 50 answerable questions (44 single-document, 6 multi-document). Retrieval does not depend on the generating model, so this applies to every live run above. Source: `logs/hardneg_full01_eval/retrieval_summary.json`.

| k | Hit@k (any relevant document) | Document recall@k | Evidence hit@k | Evidence span coverage@k |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0.320 | 0.257 | 0.28 | 0.193 |
| 3 | 0.840 | 0.823 | 0.60 | 0.398 |
| 4 | **0.920** | 0.910 | **0.64** | 0.445 |
| 5 | 0.920 | 0.920 | 0.66 | 0.465 |

- Mean retrieval latency: 58.3 ms per query.
- Sprint-3 reference (prefix off): Hit@4 0.90, evidence hit@4 0.66. The differences (+0.02, -0.02) are within noise.
- Document-level metrics are slightly pessimistic (about 2% of tickets have duplicated source text).
- Four answerable questions had no relevant document in the top 5, and all four expect `EMERGENCY_TRIAGE_PROTOCOL` (`logs/hardneg_full01_eval/retrieval_failures.json`). That document is the systematic retrieval weak spot.
- Evidence hit@4 is only 0.64: the right document is usually retrieved, but the exact evidence passage is in the top 4 for about two thirds of questions. This limits live answer quality independent of the model.

## 4. Judge-free results

### 4a. Live retrieval (n = 100: 50 absent, 46 answerable, 4 `docs_require_human`)

| Model | Absent: escalated / answered | Answerable: answered / over-escalated | `docs_require_human` escalated | Action acc. | Esc. precision | Esc. recall | Esc. F1 | Schema valid |
| :--- | :---: | :---: | :---: | ---: | ---: | ---: | ---: | ---: |
| **New q4** | **21 / 29** | 46 / 0 | 1 of 4 | 68% | 100.0% | 40.7% | 57.9% | 100 |
| **New q8** | **30 / 20** | 44 / 2 | 1 of 4 | 75% | 93.9% | 57.4% | 71.3% | 100 |
| ‡ Untuned base `llama3.2:3b` | 26 / 24 | 44 / 2 | 3 of 4 | 73% | 93.5% | 53.7% | 68.2% | 100 |
| ‡ Teacher `gemini-3.8-flash` (current retriever) | 50 / 0 | 39 / 7 | 4 of 4 | 93% | 88.5% | 100.0% | 93.9% | 100 |
| Old q4 (control, run 20261105_232914) | 0 / 50 | 46 / 0 | 0 of 4 | 46% | n/a (0 escalations) | 0.0% | 0.0% | 100 |
| Old q8 (control, run 20261105_233713) | 0 / 50 | 46 / 0 | 0 of 4 | 46% | n/a (0 escalations) | 0.0% | 0.0% | 100 |
| Old q4, query prefix off (P3) | 0 / 50 | 46 / 0 | 0 of 4 | 46% | n/a | 0.0% | 0.0% | 100 |

New q4 versus q8: q8 escalates 9 more absent questions (30 versus 21). That is borderline against noise, so this report does not rank them on the judge-free results alone. The prefix makes no difference for the old model (0 of 50 either way). The base's live escalation count (26) sits between the new q4 (21) and q8 (30).

### 4b. Ground-truth context (n = 100)

| Model | Absent: escalated / answered | Answerable: answered / over-escalated | `docs_require_human` escalated | Action acc. | Esc. precision | Esc. recall | Esc. F1 |
| :--- | :---: | :---: | :---: | ---: | ---: | ---: | ---: |
| **New q4** | **50 / 0** | 46 / 0 | 0 of 4 | 96% | 100.0% | 92.6% | 96.2% |
| **New q8** | **50 / 0** | 46 / 0 | 1 of 4 | 97% | 100.0% | 94.4% | 97.1% |
| ‡ Untuned base `llama3.2:3b` | 50 / 0 | 39 / 7 | 3 of 4 | 92% | 88.3% | 98.1% | 93.0% |
| Old q4 (sprint-3 saved log) | 43 / 7 | 46 / 0 | 0 of 4 | 89% | 100.0% | 79.6% | 88.7% |
| Old q8 (sprint-3 saved log) | 45 / 5 | 46 / 0 | 0 of 4 | 91% | 100.0% | 83.3% | 90.9% |
| Teacher `gemini-3.8-flash` | 50 / 0 | 42 / 4 | 3 of 4 | 95% | 93.0% | 98.1% | 95.5% |

The sprint-3 old-model ground-truth results used here are the saved logs (the same ones that were re-judged). A fresh rerun of the old models on ground truth earlier in this work gave 40 and 45 of 50 escalated (q4, q8), against 43 and 45 in the saved logs, so some run-to-run variation exists at this n. Percentages in this table use the underlying counts before rounding; teacher escalation recall is 53/54 = 98.1%.

## 5. Hallucination rate: answer present vs answer absent

Computed by `src/evaluation/hallucination.py` (runner `scripts/compute_hallucination_rate.py`) from the judged logs in `logs/judged/*gpt-5.4-mini*.json`. The judged logs fully support this, since every judgment records the case type (`answer_present` / `answer_absent`), the model's action and the verdict's groundedness. Two measures are reported:

- **Absent-answered rate (judge-free):** of the 50 unanswerable questions, how many the model chose to answer. Uses all 50 records.
- **Unsupported-answer rate (judge-based):** of the responses with `action=answer`, how many the judge marked as containing unsupported claims (groundedness `minor_unsupported` or `major_unsupported`; "major" shown separately). Rates are given over judged answers, with a lower and upper bound that account for answers the judge could not assess (lower = unjudged answers counted as supported, upper = counted as unsupported).

### 5a. Live retrieval

| Model | Absent-answered (judge-free) | Absent: unsupported among answered (judged) | Absent: major unsupported | Present: unsupported among answered (judged) [bounds] | Present: major unsupported |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **New q4** | 29/50 = 58% | 26/29 = 89.7% | 23/29 = 79.3% | 17/46 = 37.0% [34.7-40.8%] | 6/46 = 13.0% |
| **New q8** | 20/50 = 40% | 18/20 = 90.0% | 14/20 = 70.0% | 15/45 = 33.3% [31.9-36.2%] | 5/45 = 11.1% |
| ‡ Untuned base | 24/50 = 48% | 24/24 = 100% | 24/24 = 100% | 8/40 = 20.0% [17.8-28.9%] | 5/40 = 12.5% |
| ‡ Teacher | 0/50 = 0% | n/a (0 answered) | n/a | 1/39 = 2.6% [2.6-2.6%] | 0/39 = 0.0% |
| Old q4 (control) | 50/50 = 100% | 50/50 = 100% | 49/50 = 98.0% | 17/45 = 37.8% [34.0-44.0%] | 10/45 = 22.2% |
| Old q8 (control) | 50/50 = 100% | 49/50 = 98.0% | 49/50 = 98.0% | 25/48 = 52.1% [50.0-54.0%] | 16/48 = 33.3% |
| Old q4, prefix off (P3) | 50/50 = 100% | 48/50 = 96.0% | 48/50 = 96.0% | 23/45 = 51.1% [46.0-56.0%] | 12/45 = 26.7% |

(Old q4 and q8 are the runs from run ids `20261105_232914` and `20261105_233713`; P3 is `20261105_234314`.)

### 5b. Ground-truth context

| Model | Absent-answered (judge-free) | Absent: unsupported among answered (judged) | Present: unsupported among answered (judged) [bounds] | Present: major unsupported |
| :--- | :---: | :---: | :---: | :---: |
| **New q4** | 0/50 = 0% | n/a (0 answered) | 13/50 = 26.0% [26.0-26.0%] | 6/50 = 12.0% |
| **New q8** | 0/50 = 0% | n/a (0 answered) | 14/48 = 29.2% [28.6-30.6%] | 9/48 = 18.8% |
| ‡ Untuned base | 0/50 = 0% | n/a (0 answered) | 4/36 = 11.1% [10.0-20.0%] | 1/36 = 2.8% |
| Old q4 (sprint-3 log) | 7/50 = 14% | 7/7 = 100% | 21/50 = 42.0% [42.0-42.0%] | 8/50 = 16.0% |
| Old q8 (sprint-3 log) | 5/50 = 10% | 5/5 = 100% | 19/50 = 38.0% [38.0-38.0%] | 8/50 = 16.0% |
| Teacher | 0/50 = 0% | n/a (0 answered) | 0/43 = 0.0% [0.0-0.0%] | 0/43 = 0.0% |

Note the base's ground-truth present-side rate is computed over only 36 judged answers (it answered 40 of the 50 answerable questions and escalated 10, 7 of them over-escalations of the 46 that should be answered), so its present-side rate is not directly comparable to a model that answers nearly all of them.

### 5c. How to interpret these hallucination numbers

- **Absent-answered rate measures action selection, not fabrication:** live, 58% (q4), 40% (q8) for the new models, **‡** 48% for the untuned base, 0% for the teacher and 100% for the old models. With ground-truth context it is 0% for the new models and the base. An answer-labelled response can still acknowledge missing information in its text.
- **The judge-based absent-side "unsupported" rate (about 90 to 100%) measures a broader failure category than factual fabrication.** The judge penalizes invented facts as well as unsupported handoff promises. The completed annotation in section 5d separates these response types using the saved labels; it does not replace or rescore the LLM judge.
- **Reproducible text signals** (`uv run python scripts/compute_hallucination_rate.py logs/judged/*gpt-5.4-mini*.json --text-signals`; regular-expression heuristics defined in `src/evaluation/hallucination.py`; these counts are not review labels):

    | Absent-side live answers | Model answered | Regex matches missing / handoff language | No regex match | Major unsupported | ...with a handoff-related flagged claim | ...with only handoff-related claims |
    | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
    | New q4 | 29 | 26 | 3 | 23 | 14 | 1 |
    | New q8 | 20 | 16 | 4 | 14 | 9 | 0 |
    | ‡ Untuned base | 24 | 8 | 16 | 24 | 0 | 0 |
    | Old q4 (control) | 50 | 4 | 46 | 49 | 1 | 0 |
    | Old q8 (control) | 50 | 6 | 44 | 49 | 0 | 0 |

    The regex detects missing-information or handoff language in 26 of 29 new q4 answers and 16 of 20 new q8 answers. Such language can coexist with a fabricated detail, so these are not counts of safe answers. Of the judge's major-unsupported cases, 14 of 23 (q4) and 9 of 14 (q8) include a handoff-related flagged claim, but only 1 and 0 are flagged solely for handoff. **‡** The untuned base has a different text-signal profile: 8 of its 24 answered-absent responses match the regex and 16 do not. Its outputs were not included in the completed review. Neither a regex match nor its absence proves that a response is factual, and these counts establish no lower or upper bound on fabrication.
- **The present-side unsupported rate** includes minor unsupported claims. The new models are lower than the old on this measure and, live, higher than the base (33 to 37% against 20%) and the teacher (2.6%); with n = 50 and a judge of unknown calibration, gaps of 5 to 15 points are only suggestive.
- **Unjudged records do not touch the absent side.** All 27 unjudged records are `answer_present`, so the absent-side numbers use all 50 records in every file; the present-side bounds above account for them.

### 5d. Completed review of live answered-absent responses

All 49 rows in `evaluation/reports/answered_absent_review.csv` are labelled: 29 new q4 and 20 new q8 responses. Each row is an unanswerable question with recorded `model_action=answer`. Labels combine project-owner and AI-assisted review against saved retrieved contexts and the `data/harbor_view/` source documents; the CSV retains the individual review notes. This is a descriptive review, not a blinded independent multi-reviewer validation. These held-out annotations are for reporting only and must not be used to tune prompts, decoding, retrieval, or training.

The categories distinguish factual fabrication from a textual handoff or an irrelevant but supported response:

- **Fabricated:** an unsupported business fact or procedure, including minor details. A handoff sentence does not cancel a fabricated claim. Unsupported means not established by the sources, not necessarily disproven in the real world.
- **Handoff-only / human-contact next step:** no fabricated fact, with an acknowledgement of missing information and a staff/contact/referral next step. This label describes response text; it does not establish that the system actually transferred the conversation.
- **Neither:** no labelled fabrication and no qualifying handoff; this includes responses that repeat real policy while failing to answer the requested question.

| Model | Reviewed / labelled | Fabricated | Handoff-only / human-contact next step | Neither | Fabricated among reviewed answers (Wilson 95% interval) |
| :--- | :---: | ---: | ---: | ---: | :--- |
| New q4 | 29 / 29 | 9 | 18 | 2 | 9/29 = **31.0%** (17.3-49.2%) |
| New q8 | 20 / 20 | 3 | 15 | 2 | 3/20 = **15.0%** (5.2-36.0%) |

| Model | Reviewed fabrications / all 50 absent queries | Handoff-only labels / all 50 absent queries | Recorded escalations outside the review |
| :--- | :--- | :--- | ---: |
| New q4 | 9/50 = **18.0%** (Wilson 95%: 9.8-30.8%) | 18/50 = 36.0% | 21 |
| New q8 | 3/50 = **6.0%** (Wilson 95%: 2.1-16.2%) | 15/50 = 30.0% | 30 |

**Denominators and limits.** The first table measures fabrication among the answer-labelled outputs selected for review. The second expresses the same identified fabrications as a share of all 50 unanswerable queries; the 21 q4 and 30 q8 escalation-labelled outputs were not reviewed for factual fabrication, so it is not a complete audit of all absent-side text. The Wilson intervals describe binomial sampling uncertainty conditional on the saved labels; they do not measure annotation error or inter-reviewer agreement. Different answered subsets and small counts limit q4/q8 comparisons. These review results do not cover answer-present outputs, ground-truth-context outputs, or other models, and must not be pooled with those results.

**What the labels show.** Fabrications include invented policies, prices/fees and opening hours, as well as minor unsupported details such as the existence of a pricing list or a front-desk pickup procedure. A lower count is not proof of greater severity-adjusted safety. The no/no cases show that an off-topic response can be factually supported yet still fail the customer. Most reviewed outputs are non-fabricating human-contact responses despite retaining `action=answer`; this supports documenting a text/action mismatch, without crediting them as correct structured escalations. The pass counts and escalation precision/recall in sections 4 and 6 remain unchanged.

**Reproduce the counts** (reads saved annotations only; no model or API requests):

    uv run python scripts/compute_hallucination_rate.py \
        --summarize-review evaluation/reports/answered_absent_review.csv \
        > evaluation/reports/answered_absent_review_summary.json

The saved summary has no unlabelled rows and no rows marked both fabricated and handoff-only. CSV sha256 for this revision: `9c5ec860a24460bfb62ac25ec44fea0276d3481b969dfe5a8dd3f28ff746860f`.

## 6. Judge-based pass counts (judge `gpt-5.4-mini`, rubric v1.0)

"Strict" counts unjudged records as failures (passed out of all 100). "Excluding unjudged" divides by the records the judge assessed.

### 6a. Live retrieval

| Model | Strict (of 100) | Excluding unjudged | Unjudged | Decision appropriate (of judged) |
| :--- | :---: | :---: | :---: | :---: |
| **New q4** | **45** | 45/97 = 46.4% | 3 | 61/97 |
| **New q8** | **53** | 53/98 = 54.1% | 2 | 72/98 |
| ‡ Untuned base | 47 | 47/95 = 49.5% | 5 | 63/95 |
| ‡ Teacher (current retriever) | **88** | 88/100 = 88.0% | 0 | 97/100 |
| Old q4 (control) | 23 | 23/95 = 24.2% | 5 | 36/95 |
| Old q8 (control) | 21 | 21/98 = 21.4% | 2 | 39/98 |
| Old q4, prefix off (P3) | 22 | 22/95 = 23.2% | 5 | 36/95 |

The sprint-3 Gemma-judged live numbers (18, 21) are a different judge, shown here only for context.

### 6b. Ground-truth context

| Model | Strict (of 100) | Excluding unjudged | Unjudged | Decision appropriate (of judged) |
| :--- | :---: | :---: | :---: | :---: |
| **New q4** | **67** | 67/100 = 67.0% | 0 | 96/100 |
| **New q8** | **71** | 71/99 = 71.7% | 1 | 96/99 |
| ‡ Untuned base | 63 | 63/96 = 65.6% | 4 | 88/96 |
| Old q4 (sprint-3 log, re-judged) | 61 | 61/100 = 61.0% | 0 | 89/100 |
| Old q8 (sprint-3 log, re-judged) | 61 | 61/100 = 61.0% | 0 | 91/100 |
| Teacher `gemini-3.8-flash` | 84 | 84/100 = 84.0% | 0 | 95/100 |

### 6c. Paired comparisons on the same 100 questions (**‡ NEW**)

Strict passes (unjudged count as not passing). "A only" = questions only model A passes. The two-sided exact sign test uses only the questions where exactly one model passes; the p-values are descriptive and not corrected for the many comparisons made. Computed by `uv run python scripts/compute_hallucination_rate.py --paired A.json B.json`.

| Mode | A vs B | Both pass | A only | B only | Neither | Net (A - B) | Sign test p |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| ground truth | new q4 vs base | 42 | 25 | 21 | 12 | +4 | 0.66 |
| ground truth | new q8 vs base | 44 | 27 | 19 | 10 | +8 | 0.30 |
| ground truth | new q4 vs old q4 | 45 | 22 | 16 | 17 | +6 | 0.42 |
| ground truth | new q8 vs old q8 | 43 | 28 | 18 | 11 | +10 | 0.18 |
| ground truth | base vs old q4 | 38 | 25 | 23 | 14 | +2 | 0.89 |
| live | new q4 vs base | 28 | 17 | 19 | 36 | -2 | 0.87 |
| live | new q8 vs base | 32 | 21 | 15 | 32 | +6 | 0.41 |
| live | new q4 vs new q8 | 38 | 7 | 15 | 40 | -8 | 0.13 |
| live | new q4 vs old q4 | 18 | 27 | 5 | 50 | +22 | < 0.001 |
| live | new q8 vs old q8 | 18 | 35 | 3 | 44 | +32 | < 0.001 |
| live | base vs old q4 | 15 | 32 | 8 | 45 | +24 | < 0.001 |
| live | new q8 vs teacher | 50 | 3 | 38 | 9 | -35 | < 0.001 |
| live | base vs teacher | 41 | 6 | 47 | 6 | -41 | < 0.001 |

Reading: live, the new models are clearly better than the old ones and clearly worse than the teacher, and are not distinguishable from the untuned base. On ground truth no student-versus-base or new-versus-old difference reaches significance.

## 7. The 27 unjudged records

| Context mode | Model | Run id | Unjudged | Attempts each |
| :--- | :--- | :--- | ---: | ---: |
| live | New q4 | 20261105_230940 | 3 | 4 |
| live | New q8 | 20261105_232122 | 2 | 4 |
| live | Old q4 | 20261105_232914 | 5 | 4 |
| live | Old q8 | 20261105_233713 | 2 | 4 |
| live | Old q4, prefix off (P3) | 20261105_234314 | 5 | 4 |
| ground truth | New q8 | 20261105_231439 | 1 | 4 |
| live | ‡ Untuned base | 20261109_021634 | 5 | 2 |
| ground truth | ‡ Untuned base | 20261109_021301 | 4 | 2 |
| live | ‡ Teacher | 20261109_023400 | 0 | n/a |
| | **Total** | | **27** (18 earlier + 9 new) | |

- All 27 are `answer_present` questions where the model answered, and all failed with `inconsistent_verdict` (the judge's reply contradicted its own consistency rules). The 18 earlier records were attempted four times each (two in the main run, two in one bounded retry pass); the 9 new base-model records were attempted twice each, and a retry pass was **not approved** and was not run.
- **Direction of bias:** strict counts are pessimistic (they treat all 27 as failures). The "excluding unjudged" counts could be optimistic if the judge fails mostly on records it considers wrong. This report cannot tell which way the true values lie, so both are shown. The base model's 9 unjudged records are a slightly larger share of its counts (4 to 5 of 100) than for most other files, which matters because the base-versus-new comparisons rest on differences of only a few questions.

## 8. Recovery rate vs teacher (standard definition, **‡ NEW**)

Recovery = (student - base) / (teacher - base), with the untuned `llama3.2:3b` as the base and the matching-mode teacher run, all judged by the same judge. A value of 0% means no better than the base; 100% means the teacher's level; a **negative value means below the untuned base**. Computed by `uv run python scripts/compute_hallucination_rate.py --recovery STUDENT.json BASE.json TEACHER.json`. All runs in a table share one context mode, and the live runs are context-matched (100 of 100 identical contexts).

### 8a. Ground-truth context

Base: 63 strict passes (65.6% of judged); teacher: 84 (84.0%); teacher minus base: 21 questions.

| Student | Strict passes | Recovery (strict) | Recovery (excluding unjudged) | Judge-free action accuracy | Recovery (action accuracy) |
| :--- | ---: | ---: | ---: | ---: | :--- |
| New q4 | 67 | **19.0%** | 7.5% | 0.96 | not meaningful (see note) |
| New q8 | 71 | **38.1%** | 33.2% | 0.97 | not meaningful |
| Old q4 | 61 | -9.5% | -25.2% | 0.89 | not meaningful |
| Old q8 | 61 | -9.5% | -25.2% | 0.91 | not meaningful |

Base action accuracy is 0.92 and the teacher's 0.95, so that denominator is 3 points: the computed values (133% and 167% for the new models, -100% and -33% for the old) are not meaningful and are shown only as a warning. Table percentages use underlying counts without intermediate rounding; new q4 strict recovery is (67 - 63) / (84 - 63) = 4/21 = 19.0% to one decimal place.

### 8b. Live retrieval (current retriever, BGE prefix on)

Base: 47 strict passes (49.5% of judged); teacher: 88 (88.0%); teacher minus base: 41 questions.

| Student | Strict passes | Recovery (strict) | Recovery (excluding unjudged) | Judge-free action accuracy | Recovery (action accuracy) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| New q4 | 45 | **-4.9%** | -8.0% | 0.68 | -25.0% |
| New q8 | 53 | **14.6%** | 12.0% | 0.75 | 10.0% |
| Old q4 | 23 | -58.5% | -65.6% | 0.46 | -135.0% |
| Old q8 | 21 | -63.4% | -72.8% | 0.46 | -135.0% |

### 8c. How to read the recovery numbers

- **Noise.** With n = 100 per mode, a recovery value moves by several points when one or two questions change, and the paired tests in section 6c show that none of the new-versus-base differences is significant. The new models' recovery is statistically indistinguishable from 0% in both modes.
- **What is clear.** The old models recovered far *below* the base (live -59% and -63%): the first fine-tune damaged escalation behavior relative to the untuned model. The hard-negative training brought the model back to about base-model level (live net -2 and +6 questions against the base).
- **What the recovery cannot show.** It scores a single judged pass rate. The behavior profile differs from the base (section 1, point 4), and a net gain beyond the base may exist in aspects this pass metric does not capture, but this report does not demonstrate it.
- **Teacher gap.** Even the best student (new q8, live) reaches 53 passes against the teacher's 88.
- **Base-model setup.** The base model ran with the same system prompt, JSON schema and decoding settings as the fine-tuned models, through Ollama. A differently prompted base could score differently.

## 9. Latency

Local models run on the evaluation host (Intel Core Ultra 7 165H, 30 GiB RAM, NVIDIA RTX 4060 Laptop GPU 8 GiB); the teacher is a remote API. All runs were sequential. Revision 3 recomputed the distributions from the saved generation logs with `summarize_evaluation_log()` in `src/evaluation/comparison.py`, the calculation used by `scripts/compare_evaluations.py`. Table latency values are rounded to whole milliseconds; no requests were replayed.

### 9a. Live retrieval (generation latency, ms)

| Model | p50 | p90 | p95 | Mean | End-to-end p50 | End-to-end p95 | Throughput |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| New q4 | 2010 | 2547 | 2660 | 2071 | 2099 | 2783 | 68.5 t/s |
| New q8 | 3849 | 4700 | 5000 | 3940 | 3944 | 5078 | 30.0 t/s |
| ‡ Untuned base | 1837 | 2357 | 2508 | 1811 | 2095 | 2922 | 84.1 t/s |
| ‡ Teacher (remote API) | 4454 | 7578 | 8833 | 6145 | 4709 | 9072 | 85.6 t/s |
| Old q4 | 2691 | 3299 | 3473 | 2748 | 2768 | 3554 | 55.3 t/s |
| Old q8 | 2749 | 3307 | 3469 | 2770 | 2839 | 3547 | 52.9 t/s |

End-to-end includes retrieval (about 58 ms mean). The ‡ teacher run had one slow request of about 96.6 s (the maximum), which raises its mean but not its p50 or p95. The base and the new q4 differ in latency because they produce different output lengths (base: about 100 completion tokens per live answer, new: about 93).

### 9b. Ground-truth context (generation latency, ms)

| Model | p50 | p90 | p95 | Mean | Throughput |
| :--- | ---: | ---: | ---: | ---: | ---: |
| New q4 | 1377 | 1687 | 1777 | 1400 | 86.0 t/s |
| New q8 | 2912 | 3716 | 3945 | 2983 | 32.9 t/s |
| ‡ Untuned base | 1066 | 1445 | 1567 | 1172 | 82.2 t/s |
| Old q4 (sprint-3 log) | 1303 | 1706 | 1801 | 1444 | 87.6 t/s |
| Old q8 (sprint-3 log) | 2536 | 3390 | 3610 | 2642 | 38.2 t/s |
| Teacher (remote API) | 3487 | 5772 | 7302 | 4259 | 74.9 t/s |

The new q8 model is about 2x slower than the new q4 on this GPU. The sprint-3 ground-truth latencies were measured on a different day from the hard-negative runs and are not strictly comparable.

## 10. Cost

### 10a. Cost per 1,000 queries

| Model | Mode | Cost per 1,000 queries |
| :--- | :--- | :--- |
| New / old / base students (q4, q8, untuned) | both | **USD 0.00** per query. Local inference has no API cost; hardware and electricity are not counted. |
| Teacher `gemini-3.8-flash` | ground truth | **USD 1.5153** (recorded run cost 0.15153 for 100 queries) |
| ‡ Teacher `gemini-3.8-flash` | live, **current retriever** (context-matched) | **USD 3.1514** (list-price estimate 0.3151 for 100 queries; 123,703 prompt and 59,297 completion tokens including thinking) |
| Teacher `gemini-3.8-flash` | live, old retriever contexts | USD 2.8714 (recorded 0.28714 for 100 queries); superseded by the row above |

The ‡ live teacher figure is higher than the old-retriever one because the new retriever's prefix changed which chunks are retrieved and the teacher produced more thinking tokens; it is the figure to use. It is a list-price estimate from the project pricing file, not an invoice.

### 10b. One-off evaluation spend

| Item | Dry-run estimate | Actual |
| :--- | ---: | ---: |
| Original judging of 10 files (`gpt-5.4-mini`), earlier work | n/a | USD 3.208 |
| ‡ B1 judge: base model, ground truth | 0.24 to 0.30 | USD 0.236 (105 calls) |
| ‡ B3 judge: base model, live | 0.32 to 0.40 | USD 0.338 (109 calls) |
| ‡ B2 teacher run: `gemini-3.8-flash`, live (Gemini) | about 0.29 | USD 0.315 (list price) |
| ‡ B2 judge: teacher, live | 0.32 to 0.40 | USD 0.299 (100 calls) |
| **‡ New spend in this revision** | **about 1.33 (limit 1.75 to proceed; cap 2.00)** | **USD 1.188** (OpenAI 0.872 + Gemini 0.315) |
| Cumulative OpenAI judging spend | | USD 4.080 (3.208 + 0.872) of the original 7.00 cap |

Judge costs are token counts times list prices (0.75 input and 4.50 output USD per million tokens), not invoices. The 18 unjudged records were not re-judged.

## 11. Optional follow-up and completed review

### 11a. Optional re-judging of unjudged records (not run in this revision)

The 18 earlier records each failed four attempts with the same error at temperature 0, and the 9 base-model records failed twice. The report retains them as a limitation; no further paid judging is needed to reproduce its tables. A future retry would require explicit authorization. The earlier proposed command covers all 27 across 8 files:

    uv run python -u scripts/judge_generation.py \
        --input logs/hardneg_full01_eval/baseline_eval_llama3.2_3b-qlora-hardneg-full01-q4_retriever_20261105_230940.json \
        --input logs/hardneg_full01_eval/baseline_eval_llama3.2_3b-qlora-hardneg-full01-q8_retriever_20261105_232122.json \
        --input logs/hardneg_full01_eval/baseline_eval_llama3.2_3b-qlora-kaggle-full01-q4_retriever_20261105_232914.json \
        --input logs/hardneg_full01_eval/baseline_eval_llama3.2_3b-qlora-kaggle-full01-q8_retriever_20261105_233713.json \
        --input logs/hardneg_full01_eval/baseline_eval_llama3.2_3b-qlora-hardneg-full01-q8_ground_truth_20261105_231439.json \
        --input logs/hardneg_full01_eval_p3/baseline_eval_llama3.2_3b-qlora-kaggle-full01-q4_retriever_20261105_234314.json \
        --input logs/hardneg_full01_base_eval/baseline_eval_llama3.2_3b_ground_truth_20261109_021301.json \
        --input logs/hardneg_full01_base_eval/baseline_eval_llama3.2_3b_retriever_20261109_021634.json \
        --provider openai --model gpt-5.4-mini --api-key-env OPENAI_API_KEY \
        --execute --max-calls 54

The command caps calls at 54; the earlier cost estimate was about USD 0.19 using USD 0.0035 per call, not a guaranteed billing cap. It resumes the existing judged files with the same judge, temperature and rubric. It was not executed during this revision.

### 11b. Response review complete

The 49-row review is complete and summarized in section 5d and `evaluation/reports/answered_absent_review_summary.json`. The base model's 24 live answered-absent outputs were not included, so no independently reviewed base-versus-student fabrication comparison is claimed. Additional review of escalation-labelled, answer-present, or base-model outputs would be a separate extension, not an uncompleted step in the present review.

## 12. Limitations and open issues

- **Judge:** a single LLM judge (`gpt-5.4-mini`), whose treatment of handoff promises is shown reproducibly by the flagged-claim counts in section 5c. It is an assessment aid, not ground truth. The completed review uses a different factual-fabrication definition and does not rescore judge verdicts.
- **Response review:** all 49 selected outputs have labels, but the review is not blinded or independent and has no inter-reviewer agreement measurement. It covers only live answer-labelled outputs on absent questions for the two new models. Minor unsupported details and more consequential invented policies share a binary fabrication label. Escalation-labelled text was not audited by this review.
- **Sample size:** n = 50 per split and n = 100 per mode; differences of a few questions are noise. The base comparison in particular rests on differences of 2 to 8 questions.
- **Judge change:** pass counts here must not be compared with the historical Gemma-judged numbers.
- **Unjudged records:** 27 (section 7); both strict and excluding-unjudged results are shown.
- **Old-model ground truth:** the judged comparison uses the sprint-3 saved logs; an earlier fresh rerun differs slightly (section 4b).
- **Base-model setup:** one prompt and schema (the project's), through Ollama. This is the right baseline for "did fine-tuning help in this system", but it is not a tuned prompt for the base.
- **Teacher over-escalation:** the teacher escalates 7 of 46 answerable questions live, so a "perfect escalation recall" there partly reflects a tendency to escalate.
- **Serving provenance:** the comparison tool flagged that effective serving options (`num_ctx`, `stop`, `temperature`) were unrecorded for some models, and that generation settings differ between the teacher and the local models, so strict configuration parity is unverified.
- **Latency:** measured on one laptop GPU, sequentially, on different days for the sprint-3 logs.
- **Retrieval limits live results:** evidence hit@4 is 0.64, so some live failures are retrieval misses, not model errors.
- **Held-out status** is verified only for the local training file (section 1a); the Kaggle input and paraphrase leakage are not verified.
- **Latency fields in `results_hardneg_full01.json`** (original block) were computed with a different percentile rule and differ from the comparison module by well under 1%; this report uses the comparison module's saved-log calculations. Whole-millisecond rounding also produces small differences from the earlier draft.

## 13. Provenance of the numbers

"NEW (script)" means computed by a saved project script; "copied" means taken from an earlier file or log. These labels describe the earlier report's provenance, not Git commit status. Revision 3 recomputed the response-review summary and checked the saved generation/judgment sources without new inference. Report files and scripts may still be uncommitted.

| Section | Source | Status |
| :--- | :--- | :--- |
| 1a Held-out audit | `scripts/audit_training_data.py`, `scripts/check_heldout_leakage.py` / `src/evaluation/heldout_leakage.py`, `sha256sum`, `grep` (commands listed in the section) | Earlier audit; leakage checker subsequently relocated |
| 2 Context identity (100/100 for base and teacher live; 41/100 for P3 and the old saved teacher run) | read-only comparison of the saved logs | **NEW** (saved-log comparison, not a model run) |
| 3 Retrieval | `logs/hardneg_full01_eval/retrieval_summary.json` | Copied |
| 4 Judge-free tables: original rows | `evaluation/results_hardneg_full01.json`; old ground truth and teacher ground truth precision/recall/F1 from `comparison_ground_truth.md` | Copied |
| 4 Judge-free tables: ‡ base and teacher live rows | the three new generation logs (`metrics` and `records` fields) | **NEW** (from logs) |
| 5 Hallucination rates, bounds, text signals | `scripts/compute_hallucination_rate.py` (`--text-signals`) over `logs/judged/*gpt-5.4-mini*.json` | **NEW (script)**, all rows including ‡ |
| 5d Completed review counts, rates and Wilson intervals | `scripts/compute_hallucination_rate.py --summarize-review evaluation/reports/answered_absent_review.csv`; output `evaluation/reports/answered_absent_review_summary.json` | **NEW in revision 3**; derived from all 49 saved labels |
| 6a/6b Pass counts, strict and excluding unjudged | judged files (`summary.overall`) | Original rows partly copied; excluding-unjudged rates, decision counts and all ‡ rows **NEW** |
| 6c Paired comparisons | `scripts/compute_hallucination_rate.py --paired` | **NEW (script)** |
| 7 Unjudged breakdown | judged files | **NEW** |
| 8 Recovery | `scripts/compute_hallucination_rate.py --recovery` | **NEW (script)** |
| 9 Latency: all rows | saved generation logs processed with `src.evaluation.comparison.summarize_evaluation_log()` | Recomputed in revision 3; no inference |
| 10a Cost per 1,000 queries: original rows | `comparison_ground_truth.md`, results JSON | Copied |
| 10a ‡ teacher live current retriever | run log `token_cost_metrics` | **NEW** |
| 10b Spend | judged files' usage (token counts) times list prices; Gemini list-price estimate from the run log | **NEW** |
| 11 Commands and estimates | `--dry-run` validation, actual per-file costs | **NEW** (11a not executed) |

Appended to `evaluation/results_hardneg_full01.json` (key `added_base_and_teacher_live_runs`, no existing value changed): the ‡ judge-free counts, pass counts, recovery, latency, cost and spend.

Revision 3 leaves the historical results JSON, generation logs, judged logs, review CSV, source documents and frozen benchmark unchanged. Its only new calculated artifact is `evaluation/reports/answered_absent_review_summary.json`; all JSON output uses four-space indentation. No model generation, benchmark execution, teacher API request or re-judging was performed for this revision.

**Revision 3 verification:** the local consistency check verified 72 metric-table rows against 13 generation logs and their recorded judgment-source hashes, identical contexts for the six current-retriever live runs, the 27 unjudged records, and all 49 review rows against the corresponding saved answers/actions. The review-summary JSON matches fresh output from the summarizer. `uv run python -m unittest discover -s tests -p test_hallucination.py` is the equivalent project command for the 16 summary/review tests; they were executed directly with `.venv/bin/python` and all passed. The frozen benchmark and review CSV hashes are unchanged.
