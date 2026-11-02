# Orchestration Gateway (`gateway/`)

Express backend connecting the Next.js Support Admin Console (`dashboard/`), MongoDB Atlas (`businesses`, `doc_vectors`, `ticket_logs`, `admin_users`, `admin_sessions`), and the Python ingestion workers (`scripts/ingest_uploaded_document.py`).

---

## 1. Server Modes & Database Isolation

The Gateway enforces two mutually exclusive server-controlled modes via `APP_MODE`:

| `APP_MODE` | Purpose | Database Used | Seeding & Preset Access | Authentication |
| :--- | :--- | :--- | :--- | :--- |
| `standard` *(default)* | Real business deployment & onboarding | `MONGODB_DB_NAME` *(defaults to `rag_knowledge_base`)* | Seeds **nothing**. Reserved preset tenants (`iron_and_oak`, `cinder_and_salt`, `harbor_view`, `kettle_and_loom`, `northstar_auto`) and `data/<preset_tenant>/` disk fallbacks are strictly blocked and hidden, even if old seeded records exist in the database. | Standard Admin Signup (`POST /api/auth/signup`) & Email/Password Login (`POST /api/auth/login`). `POST /api/auth/demo-login` is disabled (`403`). |
| `preset_training` | Synthetic development & preset evaluation | `MONGODB_TRAINING_DB_NAME` *(must be explicitly set and distinct from `MONGODB_DB_NAME`)* | Idempotently seeds the 5 preset businesses and 12 sample multi-turn tickets into `MONGODB_TRAINING_DB_NAME`. | One-click passwordless Demo Login (`POST /api/auth/demo-login`) issuing `demo_preset` sessions scoped to a single preset tenant. |

> **Fail-Closed Startup:** Any invalid `APP_MODE` value, or starting with `APP_MODE=preset_training` without an explicit `MONGODB_TRAINING_DB_NAME` distinct from `MONGODB_DB_NAME`, terminates startup immediately.

---

## 2. Running in `standard` Mode (Default)

In `standard` mode, administrators register their own business via `/signup` ("Get to Know You" onboarding) and sign in with email and password at `/login`.

```bash
# Terminal 1: Start the Orchestration Gateway in standard mode
cd gateway
APP_MODE=standard MONGODB_DB_NAME=rag_knowledge_base npm run dev

# Terminal 2: Start the Next.js Admin Dashboard
cd dashboard
npm run dev
```

Open `http://localhost:3000/signup` to create an administrator account and provision a tenant workspace, or `http://localhost:3000/login` to sign in.

---

## 3. Running in `preset_training` Mode (One-Click Demo Login)

To inspect the 5 synthetic training businesses (`iron_and_oak`, `cinder_and_salt`, `harbor_view`, `kettle_and_loom`, `northstar_auto`) using the existing `capstone_dev` development database without passwords:

```bash
# Terminal 1: Start the Gateway in preset_training mode with explicit training DB
cd gateway
APP_MODE=preset_training \
MONGODB_DB_NAME=rag_knowledge_base \
MONGODB_TRAINING_DB_NAME=capstone_dev \
npm run dev

# Terminal 2: Start the Next.js Admin Dashboard
cd dashboard
npm run dev
```

1. Open `http://localhost:3000/login`.
2. The dashboard queries `GET /api/auth/config`, detects `app_mode: "preset_training"`, and renders **Quick Demo Login (No Password)** buttons for the 5 preset tenants.
3. Clicking any preset calls `POST /api/auth/demo-login` with `{ "tenant_id": "<preset_id>" }`, which issues an `HttpOnly` session cookie scoped to that single preset tenant. Switching presets in the sidebar revokes the prior preset session and issues a new one.

---

## 3B. Self-Contained Docker Local Demo (No Atlas Account Required)

To run the complete local demo stack (`mongodb/mongodb-atlas-local:8.0` with local `$vectorSearch`, deterministic fixture seeding from `data/fixtures/demo_manifest.json`, `gateway-demo`, and `dashboard-demo`) isolated from any standard instance on ports `3001` / `4001` / `27018`:

```bash
# From the repository root:
bash scripts/setup_demo.sh

# Check health, vector index readiness, and Ollama reachability:
curl -s http://localhost:4001/api/health | python3 -m json.tool

# Reset only the local demo containers and volumes (never touches standard/Atlas data):
bash scripts/setup_demo.sh reset
```

The containerized demo uses `SESSION_COOKIE_NAME=capstone_demo_session` and `UPLOAD_STAGING_DIR=/tmp/capstone_demo_uploads` so it can run side-by-side with a standard instance on `:3000` / `:4000` without session or file staging collisions.

---

## 4. Running Automated Security & Authorization Tests

```bash
cd gateway
npm test
```

The test suite runs entirely against an in-memory MongoDB mock and mocked Python ingestion runner (never mutating live Atlas databases).
