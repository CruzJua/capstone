# Client training demo

An optional, self-contained sandbox for learning document upload, tenant configuration,
tickets, and widget behavior with five synthetic preset businesses (`cinder_and_salt`,
`harbor_view`, `iron_and_oak`, `kettle_and_loom`, `northstar_auto`). The standard
application never starts it.

## What runs

Everything lives in the Compose project `capstone_client_training`:

| Service | Purpose | Host port |
| --- | --- | --- |
| `mongodb-demo` | Local MongoDB Atlas (`$vectorSearch`), no Atlas account needed | `127.0.0.1:27018` |
| `demo-seed` | One-shot, idempotent seeding of the presets, sample tickets, documents, and vectors | none |
| `gateway-demo` | Orchestration gateway in `preset_training` mode | `127.0.0.1:4001` |
| `chat-service-demo` | Internal retrieval/generation service, reachable only from the gateway | none |
| `dashboard-demo` | Management dashboard with one-click preset login | `127.0.0.1:3001` |
| `ollama-demo` | Optional bundled Ollama (`--with-ollama`) | `127.0.0.1:11435` |

Images (`capstone-client-training-*`), volumes, network, session cookie
(`capstone_demo_session`), database (`capstone_demo`), and configuration are all separate
from the standard installation, so both can run side by side.

## Run

Run everything from the repository root.

```bash
# Build, start, seed, and wait until healthy (uses host Ollama for chat)
bash examples/client-training/scripts/setup.sh

# Fully self-contained: also run Ollama inside the project, then download a model into it
bash examples/client-training/scripts/setup.sh --with-ollama
bash examples/client-training/scripts/setup.sh pull-model --with-ollama
```

Open the dashboard at <http://localhost:3001/login>. Gateway health is at
<http://localhost:4001/api/health>.

| Command | Effect |
| --- | --- |
| `setup.sh` / `setup` | Build images, start the stack, run the seeder, wait for readiness |
| `setup.sh start` | Start without rebuilding |
| `setup.sh stop` | Stop containers; data volumes are kept |
| `setup.sh restart` | Restart gateway and dashboard; data is kept |
| `setup.sh status` | Show containers, seed summary, and gateway health |
| `setup.sh logs [service]` | Show this project's logs |
| `setup.sh pull-model` | Pull `OLLAMA_MODEL` into the bundled Ollama container |
| `setup.sh reset [--rebuild]` | **Deletes this project's volumes** and training records |

Never use `reset` as a routine restart.

## Configuration

The launcher creates `examples/client-training/.env.local` (ignored by git) with a random
local database password on first run. See `.env.example` for every setting. Local Docker
client settings (`.docker-client/`) and logs (`logs/`) are also ignored.

Inference: by default the containers call Ollama on the host
(`OLLAMA_HOST=http://host.docker.internal:11434`), which can use the host GPU. With
`--with-ollama` they call the bundled `ollama-demo` container instead; that container is
CPU-only unless you add GPU access yourself. Set `OLLAMA_MODEL` in `.env.local` to choose
the model. The dashboard, authentication, tickets, chunk explorer, uploads, and
`$vectorSearch` all work without any model; only live answer generation needs one.

## Dependencies on the rest of the repository

The sandbox is isolated at runtime but is not a standalone copy of the code. Its images are
built from the repository root and reuse `gateway/`, `dashboard/`, `widget/`, `src/`, and
`scripts/`. Preset metadata and documents stay under `data/` (`data/fixtures/demo_manifest.json`
and the five tenant folders) because the gateway's `preset_training` mode also reads them.
Seeding logic is in `src/demo_setup/` with tests in `tests/test_demo_setup.py`.

## Verify without databases or models

```bash
.venv/bin/python examples/client-training/scripts/seed.py --dry-run
```

This validates configuration and fixture hashes only. The full image build, startup, and
`--with-ollama` path have not been verified end to end after the move to this folder.

This is a training sandbox, not the standard Docker deployment or a production install.
Legacy demo containers and volumes from before the move are not migrated or deleted.
