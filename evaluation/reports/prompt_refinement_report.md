# Support policy refinement

The runtime system policy now distinguishes answering a documented question from handling a request that needs missing information, staff decisions, account access, dispute resolution, or urgent human help. Requests requiring that intervention should use `action=escalate`, including when the assistant provides a partial grounded answer. A documented instruction mentioning staff does not alone require escalation.

The canonical policy is `src/inference/system_policy.json`. Python evaluation and live orchestration import the same policy through `src/inference/policy.py`; dashboard visibility is provided through the gateway. Tenant instructions and tone remain subordinate customization. Prompt priority is an instruction to the model, not a formal guarantee against conflicting input.

Escalation offers optional asynchronous email follow-up through the application form. The assistant must not promise a live transfer, claim submission or notification, or promise response times. Urgent matters require appropriate direct business contact and a warning that email follow-up is not immediate. Contact details must come from supplied evidence or verified tenant metadata. The gateway supplies optional `business_contact.email` and `business_contact.phone`; the chat service places these in a distinct contact block. No phone is mandatory, and no emergency number is guessed.

No weights, decoding temperature, response schema, fixtures, training files, or frozen benchmark were changed. Raw evaluation records remain original model decisions. A separate live-only product-capability safeguard can replace unsupported transfer/submission promises and set the effective action to escalate; it is not applied by the evaluation runner. A valid JSON response can still violate the semantic policy. The application owns form rendering and successful-submission confirmation, rather than trusting generation to perform those operations.

## Evaluation protocol

One prompt candidate was selected from the requested product behavior before evaluating validation. The existing development and validation fixtures each contain 40 questions from four training-exposed tenants, including 20 supported answers, 12 missing-information escalations, and 8 human-required escalations. These fixtures are not held-out generalization tests. The frozen harbor_view benchmark was neither read for tuning nor executed.

Each command was first executed with `--dry-run`. Actual local q4 evaluations use these commands, changing only the split and output path:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OLLAMA_HOST=http://127.0.0.1:11434 \
.venv/bin/python scripts/run_baselines.py \
    --finetuned-models llama3.2:3b-qlora-hardneg-full01-q4 \
    --teacher-provider none \
    --context-mode both \
    --benchmark-file data/evaluation/refinement_dev.json \
    --output-dir logs/refinement/prompt_candidate_dev

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OLLAMA_HOST=http://127.0.0.1:11434 \
.venv/bin/python scripts/run_baselines.py \
    --finetuned-models llama3.2:3b-qlora-hardneg-full01-q4 \
    --teacher-provider none \
    --context-mode both \
    --benchmark-file data/evaluation/refinement_validation.json \
    --output-dir logs/refinement/prompt_candidate_validation
```

The comparison uses existing `logs/refinement/baseline_dev/` and `baseline_validation/` runs. Temperature remains 0.2. Live retrieval uses the configured training database, BGE query prefix, reranker disabled, and top-k 4. The evaluation path does not exercise gateway similarity thresholds, tenant customization, contact metadata, browser form behavior, or automatic email delivery. Those need application tests. No teacher, model judge, paid API, or training job is involved. Zero API token cost excludes hardware/electricity and database hosting.

## Verification and limitations

The focused policy/chat suite passed 38 tests, including actual loopback authentication and NDJSON streaming checks. Initial restricted-sandbox socket failures were rerun successfully with local socket access. Tests verify canonical policy wiring, subordinate customization, optional structured contact propagation, newline rejection, raw evaluation actions, and a separate live response safeguard; they do not prove model compliance.

Action metrics measure agreement with fixture labels, not factual grounding, contact accuracy, urgency suitability, or the absence of live-transfer promises. The runner's legacy hallucination field is only the rate of `answer` actions on missing-answer questions, not a factual hallucination judgment. No old judge decisions are reused for new responses. Small-sample changes should not be presented as statistically established gains.

## Live response safeguard

Development responses still contained learned statements such as “I am connecting you with a team member now” despite the new policy. The prompt alone therefore does not satisfy the product-honesty requirement. Live orchestration now buffers the answer until schema validation and a narrow capability check finish. Explicit affirmative connecting/transferring or submission/email/notification claims are replaced with a fixed truthful explanation offering the optional form, warning that email is not immediate, and recommending verified direct contact for time-sensitive help. The effective response is escalation with confidence 0.0 and no invented citations.

Ordinary “call us” policy answers, explicit “I cannot connect you” statements, and safe grounded partial escalations are preserved. Safeguard activations log a warning recording raw action, effective action, and safeguard reason without visitor text; unchanged responses use info logging. This is application enforcement for recognized wording, not a measured model gain or a comprehensive semantic detector. Unrecognized paraphrases, urgency classification, factual grounding and unsupported contact details still require broader evaluation. Because text is buffered, the first visitor answer now waits for full generation and validation; sources/loading events can still appear first. Content-free internal progress events during generation let the HTTP server detect disconnects and close the Ollama stream without exposing unvalidated text.

## Raw model results

Policy version `2026-11-09.1`; JSON SHA256 `021ef14ebba498248ae60ce4af8805ad8c0b29c0deea8c6e2fbefe7427f42843`. All four candidate runs exited 0, completed 160/160 responses, and passed schema validation. Policy wording was unchanged between development and validation.

### Ground-truth context

| Split | Correct actions baseline → candidate | Escalation precision | Escalation recall | Human-required correct | Supported correct | Mean generation ms |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| dev | 32/40 → 35/40 | 100.0% → 94.1% | 60.0% → 80.0% | 0/8 → 4/8 | 20/20 → 19/20 | 1438 → 1440 |
| validation | 33/40 → 34/40 | 100.0% → 85.0% | 65.0% → 85.0% | 1/8 → 5/8 | 20/20 → 17/20 | 1419 → 1409 |

### Live RAG

| Split | Correct actions baseline → candidate | Escalation precision | Escalation recall | Human-required correct | Supported correct | Mean generation ms |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| dev | 29/40 → 36/40 | 100.0% → 90.0% | 45.0% → 90.0% | 2/8 → 7/8 | 20/20 → 18/20 | 1717 → 1818 |
| validation | 34/40 → 37/40 | 93.8% → 94.7% | 75.0% → 90.0% | 4/8 → 7/8 | 19/20 → 19/20 | 1745 → 1868 |

Raw action accuracy improved on these samples in both modes, including human-required escalation, while unnecessary escalation increased on supported ground-truth questions. Validation ground-truth precision fell from 100% to 85%: the change trades some supported answers for better escalation recall. Validation live accuracy rose from 34/40 to 37/40. This is a small training-exposed development comparison, not proof of improved factual quality or unseen-tenant generalization.

The saved baseline and candidate contexts matched exactly for every pair in all four comparisons (40/40 per comparison), including live retrieval. Ground-truth missing-information escalations remained 12/12; live missing-information escalations changed from 7/12 to 11/12 on development and remained 11/12 on validation. Mean live generation time increased; longer prompts and different output lengths are possible contributors, rather than an isolated causal latency result.

The narrow live safeguard detector still recognizes unsupported capability promises in raw candidate outputs. Those diagnostic counts and offline effective-action replay are explicitly separate in `prompt_refinement_results.json`; they are not factual judgments or live end-to-end scores. No candidate output was rejudged. Source log hashes, full policy text/hash, settings and independently checked per-stratum counts are preserved in that file.
