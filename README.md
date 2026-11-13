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

## Standard Docker stack (Sprint 6)

`compose.yaml` runs a separate standard-mode installation with MongoDB Vector Search,
Ollama, model initialization, the internal chat service, gateway, and dashboard.
It does not seed the preset businesses. The default browser ports are 3002 and 4002;
database, inference, and internal chat ports are not published.

Generate private installation settings once, using your external GGUF directory and
its verified checksum. This helper uses only Python's standard library and refuses to
overwrite an existing configuration:

```bash
python3 scripts/setup_stack.py \
  --model-dir /absolute/path/to/external/hardneg_full01 \
  --model-sha256 YOUR_VERIFIED_64_CHARACTER_SHA256
docker compose --env-file .env.compose.local -f compose.yaml config --quiet
docker compose --env-file .env.compose.local -f compose.yaml build gateway dashboard
docker compose --env-file .env.compose.local -f compose.yaml up -d --wait --wait-timeout 900
```

Alternatively, copy `.env.compose.example` to `.env.compose.local` and replace every
placeholder with installation-specific values. Keep that private file across restarts:
it holds database credentials and the stable contact-form secret. Do not use rendered
Compose configuration as a shareable log because it contains those values.

The first image build downloads public dependencies; first chat startup may download
the BGE embedding model. The standard image uses Python 3.14 and CPU Torch for
embeddings. Ollama requires NVIDIA GPU access through NVIDIA Container Toolkit; it does
not silently start without the requested device reservation. The initializer checks the supplied GGUF checksum and
recipe, imports the exact selected model, and checks installed identity before reusing
its saved state. It does not silently fall back to the base model. Mounts read only the
external GGUF and the checked-in import recipe; model files are not baked into images.

Open [the dashboard](http://localhost:3002/signup) to create a business. Configure the
exact widget origin before embedding `http://localhost:4002/widget.js`. The dashboard
API URL is embedded at build time; changing `NEXT_PUBLIC_GATEWAY_URL` requires rebuilding
the dashboard. Use the same hostname for its API and dashboard during local testing.

```bash
docker compose --env-file .env.compose.local -f compose.yaml ps
docker compose --env-file .env.compose.local -f compose.yaml logs --tail=100 gateway chat-service dashboard
docker compose --env-file .env.compose.local -f compose.yaml down
```

Named volumes retain the database, the database's replica-set keyfile, vector-search
state, imported model, and embedding cache during ordinary recreation. `down --volumes`
deletes that installation's stored data and is not a restart command. Use a different
Compose project name and ports for independent installations. Atlas Local is the
local-development database target; client production database suitability remains a
separate deployment decision.

Atlas Local names its replica set after the container hostname and generates its keyfile
under `/data/configdb`. `compose.yaml` therefore pins `hostname: mongodb` and names the
`mongodb_config` volume. Removing either lets `down` followed by `up` leave the database
permanently unhealthy even though the data volume survived. A database volume created by an
earlier revision without these settings cannot be reattached; use a new Compose project name
(or export and re-import the data) instead of deleting it blindly.

Operating notes from the tested single-machine setup (Ubuntu, RTX 4060 with 8 GB VRAM):

- The first reply after the stack starts or the model has been idle took about 40 seconds in
  testing; later replies took 2 to 5 seconds. This is cold-start cost from loading the model
  onto the GPU and from the first embedding use; the split between them was not measured.
  Ollama's default 5-minute keep-alive is not overridden in `compose.yaml`, so an idle model
  unloads and the next visitor pays the cold start again.
- The gateway keeps conversation history and rate limits in memory, so they reset when it is
  recreated. Business records, documents, vectors, tickets, saved contact details, and the
  imported model persist. A follow-up form opened before a recreation still works afterward
  because `CHAT_FOLLOW_UP_SECRET` is stable.
- A missing GGUF directory or a checksum mismatch stops `model-init` with a nonzero exit; the
  stack never falls back to the base model.
- Browser chat is rejected from any origin not listed for the business. The check applies to
  browsers; requests without an `Origin` header (curl, server-side clients) are not blocked by it.

If Docker Engine still references an unavailable `docker-credential-desktop` helper,
public pulls can use an isolated client configuration without editing your saved one:

```bash
export DOCKER_CONFIG="$(mktemp -d /tmp/support-docker-client.XXXXXX)"
printf '{"auths": {}}\n' > "$DOCKER_CONFIG/config.json"
```

This temporary configuration has no registry login; use it only for the public images
in this setup.

Verified on the development machine (NVIDIA GPU, standard mode, Compose project `capstone_verify`):
image builds from the hashed CPU lock; model import and exact-tag selection; 100% GPU inference
(`ollama ps`, 29 of 29 layers offloaded); signup, saved settings, Markdown upload, grounded answer,
safe escalation, contact capture, ticket review and New chat in a real browser on a separate
storefront origin; tenant isolation in both directions; recreation with persisted data; and
single-service outages with recovery. Not yet verified: a different machine or a cold Docker
cache, GPUs other than the RTX 4060, other browsers, and sustained or concurrent load.

### NVIDIA prerequisite on Ubuntu

Host `nvidia-smi` must work, then install and configure NVIDIA Container Toolkit using
[NVIDIA's installation guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
These commands require your terminal's interactive sudo authentication. Finish any
active image builds before restarting Docker; restarting its daemon interrupts them.

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends ca-certificates curl gnupg2
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

After the image is pulled and Docker is configured, verify container access before
starting the whole stack:

```bash
docker compose --env-file .env.compose.local -f compose.yaml run --rm --no-deps --entrypoint nvidia-smi ollama
```

Then verify an actual response uses the GPU with Ollama's `ps` output and GPU monitoring.
A successful `nvidia-smi` test alone does not prove model layers are running on the GPU.

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
