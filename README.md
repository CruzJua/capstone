# Local Customer Support Agent

A self-hosted, multi-tenant customer support system with a management dashboard, an embeddable chat widget, tenant-filtered MongoDB vector retrieval, and local Ollama inference. The gateway connects the public widget to an internal Python chat service; database credentials stay on the server.

## Application layout

| Path | Purpose |
| :--- | :--- |
| `gateway/` | Express API, authentication, tenant configuration, document uploads, tickets, and public chat endpoints |
| `dashboard/` | Next.js administration interface |
| `widget/` | Embeddable script and React chat component |
| `src/chat/` | Internal chat service and retrieval/generation orchestration |
| `src/inference/` | Local inference client, structured response schema, and shared support policy |
| `src/rag/`, `src/documents/` | Tenant-filtered retrieval, parsing, document ingestion, and index support |
| `examples/client-training/` | Optional, separately launched client-training Docker sandbox |
| `src/demo_setup/`, `data/fixtures/` | Shared training-sandbox seeding logic and preset metadata |
| `scripts/` | CLI entry points for application services, document ingestion, and demo setup |
| `deployment/ollama/` | Current fine-tuned model import recipe |

Historical research, evaluation, notebooks, datasets, local documents, raw logs, and downloaded model exports have been moved outside the application. The original tracked project is preserved on the `backup-post-project-cleanup` branch. The local sibling `PRO390-archive/` contains the research workspace and a relocation manifest; ignored artifacts in that archive are not backed up by Git. Installed dependencies, current application build output, runtime settings, and active demo fixtures remain in the application.

## Local development

Install Python 3.14+, uv, Node.js/npm, and Ollama. From the repository root:

```bash
uv sync
cp .env.example .env
npm install --prefix gateway
npm install --prefix dashboard
npm install --prefix widget
npm run build --prefix widget
```

Set database, embedding, and inference settings in `.env`. The embedding model and vector index must agree; the current embedding model is `BAAI/bge-small-en-v1.5` with 384 dimensions. Keep credentials local. Use `APP_MODE=standard` for business onboarding. Preset development mode requires an explicit, separate `MONGODB_TRAINING_DB_NAME`; see [gateway configuration](gateway/README.md).

Start these processes in separate terminals, each from the repository root:

```bash
ollama serve
```

```bash
.venv/bin/python scripts/run_chat_service.py --port 8100
```

```bash
npm run dev --prefix gateway
```

```bash
npm run dev --prefix dashboard
```

The dashboard runs at [localhost:3000](http://localhost:3000); the gateway defaults to port 4000. The gateway's `CHAT_BACKEND_URL` must address the Python service, and both processes must share `CHAT_BACKEND_TOKEN` when that service is reachable from another host. Restart processes after changing their environment.

The dashboard exposes a read-only core support policy and editable business instructions. Escalation can save a ticket and offer a visitor contact form for asynchronous follow-up. Saving contact details does not send an email or connect a live agent. Configure public business contact information and allowed widget origins in the dashboard. See the [dashboard guide](dashboard/README.md), [gateway guide](gateway/README.md), and [widget guide](widget/README.md) for details.

## Import a local model

Ollama serves an imported model from its own storage. Fine-tuned GGUF exports are downloaded separately; the project does not download them. Keep the weights outside the application checkout. The retained [Q4 import recipe](deployment/ollama/Modelfile) expects the weight file alongside the recipe. For a new import, place `Llama-3.2-3B-Instruct.Q4_K_M.gguf` in your chosen model directory, then run:

```bash
# Set MODEL_DIRECTORY to your external directory containing the GGUF.
: "${MODEL_DIRECTORY:?Set MODEL_DIRECTORY to your external model directory}"
cp deployment/ollama/Modelfile "$MODEL_DIRECTORY/Modelfile"
ollama create llama3.2:3b-qlora-hardneg-full01-q4 \
  -f "$MODEL_DIRECTORY/Modelfile"
ollama list
```

Set `OLLAMA_MODEL=llama3.2:3b-qlora-hardneg-full01-q4` in `.env`. Existing imported Ollama tags do not need re-importing just because the source GGUF was relocated. The archived model recipes and weights retain their original relative layout for historical imports. `ollama pull llama3.2:3b` separately installs the untuned base.

Embedding libraries may download their model when it is not cached. When cached, `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` prevents Hugging Face downloads.

## Optional client-training demo

The optional [client-training example](examples/client-training/README.md) is a self-contained Docker sandbox with the dashboard, gateway, internal chat service, local MongoDB vector search, and five seeded preset businesses. It is for training and demonstrations, not the standard or production deployment, and the standard application never starts it. Run all commands from the repository root:

```bash
# Build, seed, and start (chat uses Ollama running on the host)
bash examples/client-training/scripts/setup.sh

# Fully self-contained: bundled Ollama container plus a model download into it
bash examples/client-training/scripts/setup.sh --with-ollama
bash examples/client-training/scripts/setup.sh pull-model --with-ollama

bash examples/client-training/scripts/setup.sh status
bash examples/client-training/scripts/setup.sh stop
bash examples/client-training/scripts/setup.sh logs
```

Endpoints: [dashboard:3001](http://localhost:3001/login), [gateway:4001](http://localhost:4001/api/health), MongoDB on `127.0.0.1:27018`. Configuration, logs, images, volumes, database, and session cookie are isolated under the `capstone_client_training` Compose project, so it can run beside the standard stack. Setup downloads container images and may download embeddings. `setup.sh reset` deletes the demo's database volumes; use it only when those records are disposable. The full image build and startup have not been verified end to end. See the [example README](examples/client-training/README.md) for the service list, commands, and configuration.

## Document ingestion

Dashboard uploads use `scripts/ingest_uploaded_document.py`. The bulk-ingestion CLI is retained for explicit administration and inspection:

```bash
.venv/bin/python scripts/ingest_rag_docs.py \
  --document-parser structured --inspect-only
```

Inspection performs no database writes or embedding jobs. Actual bulk ingestion requires `--execute` and can replace tenant vectors. The structured parser retains source identity and table structure; embedding-token limits are checked before writes. Review inspection output before ingestion. Preset tenant source documents remain because demo seeding and document viewing use them.

## Research and evaluation archive

Research is separated from this application checkout. On the current workstation it is under the sibling `PRO390-archive/research/`, including its own original dependency manifest, source snapshot, evaluation tools and reports, notebooks, datasets, logs, and model exports. `PRO390-archive/relocation-manifest.json` records the original and new location of each moved artifact. Research commands must run from that workspace with a separate Python environment; the application dependency manifest now contains runtime dependencies only. Credentials were not copied into the source snapshot.

The frozen 100-question `harbor_view` benchmark moved intact to `research/data/evaluation/held_out_benchmark.json` within the archive. It must remain unchanged and excluded from training or hyperparameter selection. Ground-truth-context and live-RAG evaluations remain separate. This cleanup does not run or replace final model-quality evaluation.

The local archive is outside this Git repository. The backup branch preserves tracked research, while ignored weights, logs, and documents need their own backup if desired.

## Software checks

With dependencies already installed, run the offline/mocked suites:

```bash
.venv/bin/python -m unittest discover -s tests
npm test --prefix gateway
npm test --prefix dashboard
npm run lint --prefix dashboard
npm test --prefix widget
```

Tests using local stub HTTP servers require permission to bind loopback sockets. These software checks do not replace final model evaluation or a full Docker integration test. Application builds are separate checks and write ignored build output.
