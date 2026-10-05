<div style="text-align: center; margin-top: 40%; font-family: sans-serif;">

# Temp README before working on project

**Project:** Local Customer Support Agent

**Author:** Juan Cruz

**Date:** August 9, 2026 (Revised: September 2, 2026)

</div>

<div style="page-break-after: always;"></div>

## Project Summary

My project is a self hosted AI customer support backend that can be reused for any website. The core AI task would be knowledge distillation, where a major teacher model (Claude or Gemini) generates thousands of synthetic support interactions. These interactions would range general Q&A, multi-turn conversations, escalations, and structured ticket summaries, and they would also span several business types each with its own cache of knowledge. The data would be cleaned to remove duplicates, validate support schema, and filter ungrounded claims. The cleaned dataset would be used to QLoRA fine tune a small open weight student model (Qwen2.5-1.5B/3B or Llama 3.2). The student model will have a support agent skill set consisting of answering strictly from retrieved context, citing sources, classify intent, and refusal or escalation when context does not contain an answer.

Specific knowledge on each business is handled by a RAG (retrieval augmented generation) pipeline where uploaded documents are placed into chunks, the chunks are embedded and stored in a MongoDB Atlas Vector Search, then they are retrieved using a tenant filter and injected into the prompt at the time of the query. This allows business logic to live with each caller rather than in the model's weights which is the heart of the reusability of the project. The application layer includes quantized local inference (llama.cpp/Ollama) with constrained decoding to enforce structured outputs, an Express gateway with per-tenant API keys and routing, an embeddable React chat widget, and a Next.js admin dashboard with a ticket queue.

The main technical challenge I'm expecting is how a distilled 1-3B model can handle grounded support from businesses it has yet to see from its training. To diagnose performance accurately, retrieval will be measured separately from generation using recall@k on the held-out tenant to verify whether the retrieved context actually contains the answer span. Generation will be evaluated directly against ground truth in two halves: questions whose answers are present in the documents, and questions whose answers are provably absent, making hallucinations directly countable, alongside precision/recall of escalations. For questions that need the model to stretch and sort of guess a little, responses will be evaluated using an independent LLM judge distinct from the teacher model (e.g., if Gemini is the teacher, Claude or ChatGPT will judge). Instead of framing the comparison as a head-to-head win rate against the teacher, the evaluation will measure recovery: what fraction of teacher-level groundedness and escalation accuracy the student achieves, at what latency, on what hardware, and at what cost per thousand queries. This highly differs from what has been done in prior classes where we used hosted AI APIs, and for this project I plan to build, train, evaluate, and serve the model myself.

---

## Personal Motivation

I feel like my coursework at Neumont splits into two halves, a few classes in Python, data collection, and data cleaning, followed by what felt like almost entirely full-stack web development with Node, React, Next.js, Express, and MongoDB. This project deliberately joins those two. It is a Python training pipeline on one side and a production web platform on the other. In previous projects, including a pantry inventory app, I added intelligence by calling hosted APIs but for my capstone I want to prove I can build the intelligence itself. This includes generating a dataset, fine tuning a model, evaluating it, and serving it in an application. Small, locally hosted models matter wherever cost and privacy rule out major companies APIs, and reusable AI infrastructure is exactly the kind of product I hope to build professionally as an AI engineer. The result is both a genuine technical challenge and a strong portfolio piece.

---

## Technologies and Research Requirements

- **Python + PyTorch (QLoRA via Unsloth)** – Used to fine-tune the student model. I have Python and data-handling experience from earlier coursework, but parameter efficient fine tuning is new and will require research through Unsloth/Hugging Face documentation and small scale training experiments. I have planned extra time for learning, getting the technology right, and doing preliminary research on unfamiliar tools. Rather than a single training run, I plan to run an iterative loop of 5 to 10 training runs across Weeks 4 and 5 to refine data quality and model performance.

- **Knowledge distillation and synthetic data generation (Claude or Gemini API as teacher)** – The teacher generates the training corpus consisting of support conversations, escalations, and ticket summaries across several businesses, creating known ground truths for evaluation. I have called LLM APIs before, but designing generation prompts, quality filters, and deduplication is new research territory. I will research the strengths of candidate models to decide which makes the better teacher, while ensuring the model used to judge evaluation outcomes is a different model so the student isn't scored by the model it was trained to imitate.

- **Student model: Qwen2.5-1.5B/3B or Llama 3.2** – The small open-weight model being fine-tuned. New to me so it requires research into model selection, chat templates, and context-window management. From my small amounts of research so far these do seem to be the best options though.

- **Hugging Face ecosystem (Transformers, Datasets, Hub)** – Dataset management, training, and model versioning. I have very limited prior knowledge in this. I will learn through official documentation and tutorials.

- **Retrieval-Augmented Generation (RAG)** – Grounds the model in each tenant's uploaded documents. This is entirely new to me, and will require research into chunking strategies, embedding quality, hybrid search, and query rewriting for multi-turn chats. Retrieval quality will also be evaluated independently from generation using recall@k.

- **Embedding model (e.g., bge-small or all-MiniLM)** – Converts document chunks and user queries into vectors for semantic retrieval. I've used this before but I think I did so incorrectly so I will be doing some digging into them.

- **MongoDB Atlas Vector Search** – Stores tenants, conversations, tickets, document chunks, and embeddings, and performs tenant filtered vector retrieval. I am experienced with MongoDB, but the $vectorSearch aggregation stage and vector index tuning are new grounds to me.

- **llama.cpp / Ollama with GGUF quantization** – Serves the fine-tuned model locally and is completely new to me. It would require research into quantization levels and their quality/latency trade-offs as well as potential cloud hosting. It also provides constrained decoding (using GBNF grammars in llama.cpp or structured output formats in Ollama) to guarantee schema-valid JSON outputs at decode time without needing to train specifically toward JSON validity.

- **Node.js + Express** – API gateway handling authentication, per-tenant routing, retrieval, and prompt assembly. I feel really confident in this part so I'm not expecting much for research.

- **React (embeddable widget) and Next.js (admin dashboard)** – A chat widget any site can load via script tag, plus a dashboard for document upload, tenant configuration, and ticket review. Like node and express I feel good about this, although script tag embedding and style isolation will need light research.

- **Evaluation tooling (ground-truth benchmarks, recall@k, and LLM-as-judge)** – Evaluates retrieval separately from generation using recall@k on the held-out tenant to see if retrieved chunks contain the answer span. Evaluates hallucination directly against ground truth in two halves (questions whose answers are present in documents and questions whose answers are provably absent, making hallucinations countable) along with precision/recall of escalations. For answers that require the model to stretch or sort of guess a little, an independent LLM judge (separate from the teacher) will compare student and teacher responses. Rather than a head-to-head win rate, metrics will measure recovery (the fraction of teacher-level groundedness and escalation accuracy achieved by the student, at what latency, on what hardware, and at what cost per thousand queries). JSON validity is dropped as a headline metric since constrained decoding handles it. The harness will be built early (functional by Weeks 2–3, running well by Week 5) so early runs can be evaluated immediately. This is new to me and honestly the main section of research for me in this project.

- **GPU compute (Google Colab / Kaggle)** – Training environment for fine-tuning runs. I have used notebooks and such to train models, but managing longer training jobs, checkpoints, and experiment tracking is new to me. With QLoRA training on 1.5B/3B models taking hours rather than days, I will take advantage of weekly GPU allocations to run 5 to 10 iterative training cycles starting in Week 4 and leading into Week 5, budgeting buffer time to learn, fail, and iterate on data quality.

---

## Minimum Viable Product (MVP)

- A synthetic data pipeline generates, filters, and stores a validated distillation dataset (several thousand examples) from the teacher model across at least five fictional businesses.

- A single 1–3B parameter student model is fine-tuned on this dataset and produces structured outputs (answer, cited sources, confidence, action) guaranteed via constrained decoding (GBNF grammars / structured outputs in llama.cpp/Ollama).

- A RAG pipeline ingests tenant documents end-to-end (chunking, embedding, storage in Atlas Vector Search) and retrieves tenant-filtered context at query time.

- The same trained model serves at least two demo tenants with different knowledge bases, demonstrating reusability through configuration rather than retraining.

- The model runs locally via llama.cpp/Ollama behind an Express gateway with per-tenant API keys.

- An embeddable React chat widget completes the full loop: customer question → retrieval → grounded answer or escalation → ticket visible in the Next.js admin dashboard.

- An evaluation report on a held-out (never-trained-on) tenant that measures retrieval separately via recall@k, evaluates hallucination rate on countable ground-truth splits (present vs. provably absent answers) and escalation precision/recall, and compares the student against the teacher on recovery (fraction of teacher-level groundedness and escalation accuracy achieved, latency, and cost per thousand queries) using an independent LLM judge for questions requiring extrapolation.

---

## Milestones and Timeline

The following timeline reflects my current expectations for completing the project within the 10-week term. The first half of the schedule is dedicated to the AI work (dataset construction, fine-tuning, and evaluation design) and the second half to the application platform, with refinement spanning both.

| Phase | Timeframe | Key Activities and Deliverables |
|---|---|---|
| Research, Planning, and Documentation | Week 1 (1 week) | Review distillation and RAG literature (Self-Instruct, QLoRA), select student model and chat template, design system architecture and data schemas, set up training environment (Colab/Kaggle) and experiment tracking. |
| Data Collection and Preparation | Weeks 2–3 (2 weeks) | Design 5–6 fictional businesses and their knowledge bases. Build the teacher-model generation pipeline, generate grounded Q&A, multi-turn conversations, escalations, and ticket summaries. Filter via deduplication, schema validation, and groundedness checks, and reserve one full business as the held-out evaluation tenant. Build RAG ingestion (chunking, embedding, Atlas Vector Search index). Build an initial functional evaluation harness (ground-truth dataset, retrieval recall@k, and two-half hallucination tests) by the end of Week 3 to evaluate data and retrieval early. |
| Prototyping (Model and Architecture) | Week 4 (1 week) | Start first QLoRA fine-tuning runs (beginning an iterative cycle of 5–10 runs), quantize to GGUF, and verify local inference with constrained decoding via llama.cpp/Ollama. Assemble end-to-end RAG retrieval prototype and evaluate retrieval recall@k. Iterate on training data quality based on early outputs and evaluation. |
| Core Development — AI | Week 5 (1 week) | Execute subsequent fine-tuning runs across the dataset based on data-iteration feedback. Finalize the evaluation harness so it is running well (held-out tenant benchmark, ground-truth present/absent hallucination testing, separate retrieval recall@k, escalation precision/recall, and independent LLM judge rubric). Run zero-shot student and teacher baselines to measure recovery rate, latency, and cost. |
| Core Development — Application | Weeks 6–7 (2 weeks) | Express gateway with per-tenant API keys, routing, retrieval, and prompt assembly. Embeddable React chat widget with script-tag loading and style isolation. Next.js admin dashboard with document upload, tenant configuration, and ticket queue. |
| MVP Complete | Week 8 (1 week) | Integrate all components; stand up two demo tenants with different knowledge bases running the same model. Verify the full loop (question → retrieval → grounded answer or escalation → ticket in dashboard). |
| Testing, Evaluation, and Refinement | Week 9 (1 week) | Produce the full evaluation report on the held-out tenant (reporting retrieval recall@k separately, ground-truth hallucination rate, escalation metrics, recovery rate vs teacher, latency, and serving cost). Conduct additional fine-tuning runs if metrics warrant. Bug fixes and UX polish. |
| Final Presentation and Submission | Week 10 (1 week) | Final documentation and README. Prepare and rehearse the demo. Complete the written report. If time warrants finish up some stretch goals. |
