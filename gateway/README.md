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

## 1B. Configuration Comes From `.env`

The gateway reads its settings from the repository-root `.env` (copy `.env.example` to get started), so `npm run dev` or `npm start` needs nothing passed on the command line. Order of precedence, highest first:

1. Variables already in the process environment (shell exports, inline `VAR=value npm run dev`, Docker `environment:`).
2. `<repo root>/.env`
3. `gateway/.env`

Existing variables are never overridden by a file, so a one-off override is still `VAR=value npm run dev`. Missing files are ignored. At startup the gateway logs which env files it loaded (file names only, never values). The same rule applies to the internal chat service (`scripts/run_chat_service.py`), which reads the same root `.env`. Restart the process after editing `.env`.

---

## 2. Running in `standard` Mode (Default)

In `standard` mode, administrators register their own business via `/signup` ("Get to Know You" onboarding) and sign in with email and password at `/login`.

```bash
# Terminal 1: Start the Orchestration Gateway (APP_MODE=standard and MONGODB_DB_NAME come from .env)
cd gateway
npm run dev

# Terminal 2: Start the Next.js Admin Dashboard
cd dashboard
npm run dev
```

Open `http://localhost:3000/signup` to create an administrator account and provision a tenant workspace, or `http://localhost:3000/login` to sign in.

---

## 3. Running in `preset_training` Mode (One-Click Demo Login)

To inspect the 5 synthetic training businesses (`iron_and_oak`, `cinder_and_salt`, `harbor_view`, `kettle_and_loom`, `northstar_auto`) using the existing `capstone_dev` development database without passwords:

Set `APP_MODE=preset_training` and `MONGODB_TRAINING_DB_NAME=capstone_dev` in `.env` (the training DB must differ from `MONGODB_DB_NAME`), or pass them for a single run:

```bash
# Terminal 1: Start the Gateway in preset_training mode with explicit training DB
cd gateway
APP_MODE=preset_training MONGODB_TRAINING_DB_NAME=capstone_dev npm run dev

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

The demo also starts `chat-service-demo` (the internal chat service described in section 5), reachable only from the gateway on the compose network. Its database is `MONGODB_TRAINING_DB_NAME` because the demo gateway runs in `preset_training` mode. The Docker image builds the widget bundle itself (multi-stage build), so `/widget.js` works without a local `npm run build`. The full image build, including the PyTorch layer, has not been exercised end to end; only the widget stage and `docker compose config` have.

---

## 4. Running Automated Security & Authorization Tests

```bash
cd gateway
npm test
```

The test suite runs entirely against an in-memory MongoDB mock and mocked Python ingestion runner (never mutating live Atlas databases). The public chat tests also use a scripted mock chat backend and a stub HTTP chat service, so no model, embedding download or network access is needed.

The Python side of the chat service has its own offline tests: `uv run python -m unittest tests.test_chat_service` from the repository root.

---

## 5. Public Chat Endpoint & Embeddable Widget

Third-party storefronts embed the chat widget with one tag:

```html
<script src="https://GATEWAY_HOST/widget.js"
        data-tenant-id="your_tenant_id"
        data-api-url="https://GATEWAY_HOST"
        defer></script>
```

| Route | Auth | Purpose |
| :--- | :--- | :--- |
| `GET /widget.js` | none | Serves `widget/dist/widget.js` (read from the build output on each request, with ETag). Override the location with `WIDGET_DIST_PATH`. |
| `POST /api/chat` | none (anonymous) | Streams a grounded reply as SSE, or returns one JSON body when `Accept` lacks `text/event-stream`. Contract: `widget/API_CONTRACT.md`. |

Both are mounted **before** the admin CORS policy, CSRF origin check and `requireAuth` (see `src/server.js`). `/api/chat` has its own CORS policy (`POST, OPTIONS`, `Content-Type` only, no credentials), per-tenant origin allowlist, per-IP and per-session rate limits, and a 16 KB body cap.

### How a message flows

```
widget -> POST /api/chat (gateway: validate, rate limit, load tenant, check origin)
       -> POST /v1/chat   (internal Python chat service, src/chat/server.py)
            -> RAGRetriever.retrieve()  ($vectorSearch pre-filtered by tenant_id, optional reranker)
            -> Ollama (llama.cpp GGUF) with the tenant's agent_config, streamed
       <- NDJSON events (sources, token, done / error) -> SSE to the visitor: token, done / error only
```

The gateway talks to the Python service over HTTP so the embedding model and reranker load once instead of per request, and so the existing `RAGRetriever` and Ollama client are reused as they are. The model's schema-constrained JSON output is streamed and only the `answer` field is forwarded to the visitor, as `token` events.

### What the visitor sees, and human escalation

The visitor receives **only the model's reply**: no document sources, scores, chunk text, confidence, or any hint that the question was escalated. The `sources` event the chat service sends to the gateway is used server-side only.

When the model decides a question needs a person (`action: "escalate"`), the gateway saves the conversation as a ticket in `ticket_logs`, in the schema the dashboard's review queue already reads, so it shows up there with no dashboard changes:

| Ticket field | Value |
| :--- | :--- |
| `status` | `pending_review` (a new escalation re-opens a resolved ticket) |
| `escalation_reason` | `not_in_docs` when no relevant document was found, otherwise `docs_require_human` |
| `messages[]` | the whole retained conversation (`customer` / `agent`, with timestamps), including turns answered normally (up to the last 40 messages) |
| `retrieved_chunks`, `similarity_score`, `confidence`, `cited_sources` | for the reviewer only; chunks are `doc_id`, `section`, `score` and never include text |
| `ticket_summary`, `channel` | a short digest; `widget` |

There is one ticket per conversation, so a visitor who escalates twice updates the same ticket and keeps any admin notes and contact details. The ticket id is a hash of tenant and session; the visitor's raw session id is never stored. Ordinary answered conversations are not written to the database. Saving happens after the visitor has the full reply, and a failure to save is logged without affecting them. The widget collects no name or email, so `customer_contact` starts empty for an admin to fill in.

### Running it locally

```bash
# 1. Build the widget bundle (once, and after widget changes)
cd widget && npm install && npm run build:embed

# 2. Start the internal chat service (needs Atlas/local Mongo with a vector_index, and Ollama with the model)
uv run python scripts/run_chat_service.py --port 8100

# 3. Start the gateway
#    (PORT, CHAT_BACKEND_URL, WIDGET_DEFAULT_ALLOWED_ORIGINS, ... are read from .env; see section 1B)
cd gateway && npm run dev

# 4. Serve any page that embeds the widget from an origin allowed for your tenant
#    (see "Allowed origins" below; for local development set WIDGET_DEFAULT_ALLOWED_ORIGINS in .env)
```

### Allowed origins (per tenant)

Each tenant's allowed storefront origins live on its `businesses` document at `widget_config.allowed_origins` (array of exact origins, e.g. `["https://shop.example.com"]`; no wildcards, paths or credentials). Set it with the authenticated admin API:

```bash
curl -X PUT http://localhost:4000/api/tenants/<tenant_id>/config \
    -H "Content-Type: application/json" -b "capstone_session=<session cookie>" -H "Origin: http://localhost:3000" \
    -d '{"widget_config": {"allowed_origins": ["https://shop.example.com"]}}'
```

A tenant with no `widget_config.allowed_origins` falls back to `WIDGET_DEFAULT_ALLOWED_ORIGINS`, which has **no built-in value**: when it is unset or empty, every browser origin is rejected with `403 origin_not_allowed`. A sample development value is in `.env.example`. A tenant's own list always takes precedence over the env fallback, and an explicitly empty array allows no browser origin even when the fallback is set. Requests with no `Origin` header (curl, server-side callers) are not subject to the list. The dashboard does not expose this field yet.

### Environment variables

| Variable | Default | Meaning |
| :--- | :--- | :--- |
| `CHAT_BACKEND_URL` | `http://127.0.0.1:8100` | Internal chat service. |
| `CHAT_BACKEND_TOKEN` | *(empty)* | Shared secret sent as `X-Chat-Backend-Token`; set the same value on the chat service. Required whenever the service is reachable from another host. |
| `WIDGET_DEFAULT_ALLOWED_ORIGINS` | *(unset: reject)* | Comma-separated origins for tenants without their own list. |
| `WIDGET_DIST_PATH` | `widget/dist/widget.js` | Bundle served at `/widget.js`. |
| `CHAT_RATE_LIMIT_PER_IP` / `CHAT_RATE_LIMIT_PER_SESSION` | `30` / `10` | Requests per window. |
| `CHAT_RATE_LIMIT_WINDOW_MS` | `60000` | Sliding window. |
| `CHAT_MAX_DURATION_MS` | `120000` | Hard cap on one reply; ends with a `timeout` error event. |
| `CHAT_HEARTBEAT_MS` | `10000` | SSE `: ping` interval while a slow model reads the prompt. |
| `CHAT_PRE_STREAM_WAIT_MS` | `3000` | How long to wait for the first token before committing to a `200` stream. A backend that fails inside this window (model server down, retrieval failed) gets a real `503`; a slower model just starts streaming. `0` commits immediately. |
| `MONGODB_SERVER_SELECTION_TIMEOUT_MS` | `5000` | Read by the chat service (`scripts/run_chat_service.py`): how long retrieval waits for MongoDB before the request fails. |
| `CHAT_HISTORY_MAX_MESSAGES` | `8` | In-memory turns kept per `(tenant, session)`. |
| `TRUST_PROXY` | *(unset)* | Express `trust proxy` (for example `1`) so `req.ip` is the real client behind a reverse proxy. |

### Notes and limits

- Rate limits and conversation history are in memory and per process. Run a shared store before scaling to several gateway replicas.
- `session_id` must be 16 to 128 characters of letters, digits, `_`, `-`, `.`, `:`. The widget's ids satisfy this; short ids are rejected because history is keyed by them.
- Behind nginx or another proxy, disable buffering for `/api/chat` (the route sends `X-Accel-Buffering: no`) and do not compress it.
- Tenant `agent_config.system_prompt` and `agent_tone` are appended after the base support prompt the model was trained on. That combination has not been evaluated on the held-out benchmark.
