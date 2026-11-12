# Admin Management Dashboard

An open-source, multi-tenant administrative dashboard for managing business knowledge bases, configuring fine-tuned local customer support agents, and reviewing grounded model interactions.

Part of the self-hosted customer support application, alongside the gateway, local inference service, and embeddable widget.

---

## Key Features

* **Tenant & Profile Configuration (`/profile`):**
  * Manage business identity, sector/industry, contact information, and team metadata.
  * View the application-managed core assistant policy, which administrators cannot edit.
  * Edit subordinate Business Instructions, agent tone, temperature, context chunk count, and vector similarity threshold.
  * Configure widget origins and validated public support email and phone details, with country selection and an optional phone extension.
  * Persisted directly to MongoDB Atlas (`businesses` collection).
* **Document Ingestion Hub (`/`):**
  * Drag-and-drop file uploader supporting Markdown (`.md`) and JSON (`.json`) knowledge documents.
  * Triggers backend chunking, section extraction, and 384-dimension vector embedding via `BAAI/bge-small-en-v1.5`.
  * Read-only raw document viewer, document replacement, and re-indexing.
* **Knowledge Base & Chunk Explorer:**
  * Interactive inspector for individual vector chunks stored in Atlas (`doc_vectors`).
  * Real-time token and character length validation bounded by the model's 512-token limit.
* **Ticket Review Queue (`/tickets`):**
  * Centralized queue to audit customer support interactions.
  * Inspect fine-tuned model answers (`[label]`), chain-of-thought explanations (`[rationale]`), and cited ground-truth context chunks.
  * Human-in-the-loop review actions: Approve answers or flag queries for policy updates.
  * Review visitor contact details submitted through the widget after an escalation and prepare an email response. Follow-up is asynchronous; the widget does not connect visitors to a live agent.
* **"Get to Know You" Onboarding Wizard (`/signup`):**
  * Automated tenant onboarding that converts business legal names into normalized `tenant_id` slugs.
  * Offers default business instructions tailored to the company's industry; these remain subordinate to the core assistant policy.

---

## Architecture Overview

The dashboard connects the frontend administrator to the local inference and retrieval stack:

```text
[Admin Browser]
       │
       ▼ (HTTP / Port 3000)
[Next.js App Router (dashboard/)]
       │
       ▼ (REST API / Port 4000)
[Express Orchestration Gateway (gateway/)]
       │
       ├─────────────────────────────────┐
       ▼                                 ▼
[MongoDB Atlas]               [Python Ingestion Engine]
  ├── businesses                ├── src/documents/parser.py
  ├── doc_vectors               └── src/rag/ingestor.py (bge-small-en-v1.5)
  └── ticket_logs
```

---

## Tech Stack

* **Framework:** [Next.js](https://nextjs.org/) (App Router, JavaScript/JSX)
* **Styling:** [Tailwind CSS](https://tailwindcss.com/)
* **Icons:** [Lucide React](https://lucide.dev/)
* **State Management:** React Context (`TenantContext`, `AuthContext`)
* **Backend Connection:** Express Orchestration Gateway (`http://localhost:4000`)

---

## Getting Started

### Prerequisites

* **Node.js:** v22 or later (the Docker image uses Node.js 22)
* **npm:** v9.0.0 or later
* Running **Express Gateway** on port `4000` (see `gateway/README.md`)
* Valid root `.env` configured using `.env.example` with `MONGODB_URI` and `MONGODB_DB_NAME`

### 1. Installation

Navigate to the `dashboard/` directory and install dependencies:

```bash
cd dashboard
npm install
```

### 2. Running the Development Server

Start the interactive Next.js development server with hot-reload:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser to access the dashboard.

### 3. Production Build & Verification

To verify that all pages compile cleanly with zero errors:

```bash
npm run build
```

Run the dashboard's validation and configuration tests and its lint checks with:

```bash
npm test
npm run lint
```

To run the optimized production server:

```bash
npm run start
```

### 4. Optional Client-Training Docker Sandbox

To launch the dashboard, gateway, and local MongoDB Atlas (`$vectorSearch`) together in isolated containers on `http://localhost:3001`:

```bash
# Run from the repository root:
bash examples/client-training/scripts/setup.sh
```

In `preset_training` mode (`http://localhost:3001/login`), the login screen displays one-click demo buttons for the 5 preset businesses (`cinder_and_salt`, `harbor_view`, `iron_and_oak`, `kettle_and_loom`, `northstar_auto`) and enables the sidebar workspace switcher, while `standard` mode hides preset controls and uses standard email/password authentication.

---

## Directory Structure

```text
dashboard/
├── public/                 # Static assets and icons
├── src/
│   ├── app/
│   │   ├── layout.js       # Global root layout, font, and theme wrapper
│   │   ├── globals.css     # Tailwind CSS base and theme definitions
│   │   ├── page.js         # Document Ingestion Hub & metric overview
│   │   ├── profile/
│   │   │   └── page.jsx    # Business Profile & LLM Runtime Configuration
│   │   └── tickets/
│   │       └── page.jsx    # Ticket Review Queue & Grounded Rationale
│   ├── components/         # Reusable UI components
│   │   ├── Sidebar.jsx     # Persistent navigation and tenant switcher
│   │   └── ConfigSlider.jsx# Reusable range slider for LLM parameters
│   ├── context/
│   │   └── TenantContext.jsx # Active tenant state and switcher
│   └── lib/
│       └── api.js          # Client for Express Gateway (http://localhost:4000)
├── next.config.mjs         # Next.js runtime configuration
├── package.json            # Dashboard dependencies and scripts
└── README.md               # This documentation
```

---

## Environment Configuration

The dashboard communicates with the backend Gateway via environment variables. Create a `.env.local` inside `dashboard/` if you need custom port overrides:

```bash
NEXT_PUBLIC_GATEWAY_URL="http://localhost:4000"
```

If omitted, the dashboard defaults to querying `http://localhost:4000/api`.

---

## Security & Tenant Isolation

* **No Direct DB Access:** In compliance with project architectural constraints, the dashboard never connects directly to MongoDB Atlas and holds zero database credentials. All requests route through the backend gateway.
* **Tenancy Scoping:** All API requests and file uploads carry the active `tenant_id` to guarantee strict multi-tenant isolation across MongoDB Atlas `$vectorSearch` indexes.
