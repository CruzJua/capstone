# Express Orchestration Gateway

A lightweight Node.js / Express backend service connecting the vector store (MongoDB Atlas), the local inference engine (`llama.cpp` / Ollama), and client applications (the Admin Dashboard and Storefront Chat Widget).

---

## Key Responsibilities

* **Multi-Tenant Administration:** Exposes REST endpoints to query and update tenant profiles, contact metadata, and AI runtime parameters (`agent_config`).
* **Tenancy Enforcement & Seeding:** Connects to MongoDB Atlas (`businesses` collection) and automatically seeds default mock tenants (`cinder_and_salt`, `harbor_view`, `iron_and_oak`, `kettle_and_loom`, `northstar_auto`) on first boot.
* **CORS & Gateway Security:** Configured to accept authorized cross-origin requests from the Admin Dashboard (`http://localhost:3000`).

---

## Getting Started

### Prerequisites

* **Node.js:** v18.0.0 or later (v20+ recommended)
* **npm:** v9.0.0 or later
* **MongoDB Atlas Connection:** A valid root `.env` configured from `.env.example` with:
  * `MONGODB_URI`: MongoDB connection string.
  * `MONGODB_DB_NAME`: Database name (defaults to `capstone_dev` for development or `rag_knowledge_base` for production demo).

### 1. Installation

Navigate to the `gateway/` directory and install dependencies:

```bash
cd gateway
npm install
```

### 2. Running the Gateway

Start the development server with automatic file watching:

```bash
npm run dev
```

Or start the production server:

```bash
npm start
```

The gateway listens by default on `http://localhost:4000`.

---

## API Endpoints

### Health Check

* **`GET /api/health`**
  * Returns gateway status, connected MongoDB database name, and current server timestamp.

### Tenant Configuration

* **`GET /api/tenants`**
  * Returns an array of all tenant documents stored in the `businesses` collection, sorted alphabetically by name.

* **`GET /api/tenants/:tenantId/config`**
  * Returns the full tenant document for the specified `tenantId`.
  * Returns `404 Not Found` if the tenant does not exist.

* **`PUT /api/tenants/:tenantId/config`**
  * Validates and updates mutable tenant configuration fields (`name`, `contact_email`, `industry`, `team_name`, and `agent_config`).
  * Updates `updated_at` to the current ISO timestamp.
  * Returns the updated tenant document or `400 Bad Request` if field validation fails.

---

## Tenant Document Schema (`businesses` Collection)

Each tenant configuration in MongoDB Atlas follows this document schema:

```json
{
    "_id": "ObjectId(...)",
    "tenant_id": "iron_and_oak",
    "name": "Iron & Oak Provision Co.",
    "industry": "Outdoor Apparel & Heritage Gear",
    "contact_email": "support@ironandoak.com",
    "team_name": "Outfitter Support Team",
    "agent_config": {
        "system_prompt": "You are a customer support agent for Iron & Oak Provision Co. Answer questions strictly using the provided context chunks.",
        "agent_tone": "Warm & Professional",
        "temperature": 0.2,
        "max_context_chunks": 4,
        "similarity_threshold": 0.70
    },
    "updated_at": "2026-10-18T00:00:00Z"
}
```

### Field Definitions & Constraints

| Field | Type | Description / Validation |
| :--- | :--- | :--- |
| `tenant_id` | String | Unique slug identifier for the business tenant (e.g. `iron_and_oak`). |
| `name` | String | Display name of the business (non-empty string). |
| `industry` | String | Business sector / industry classification. |
| `contact_email` | String | Support contact email address. |
| `team_name` | String | Internal team or department label. |
| `agent_config.system_prompt` | String | Grounding instructions, persona, and boundary constraints for local LLM inference. |
| `agent_config.agent_tone` | String | Expected agent communication style (e.g. `Warm & Professional`, `Rugged & Direct`). |
| `agent_config.temperature` | Number | Sampling temperature between `0.00` and `1.00`. |
| `agent_config.max_context_chunks` | Integer | Maximum number of retrieved RAG context chunks (`1` to `8`). |
| `agent_config.similarity_threshold` | Number | Minimum cosine similarity cutoff for vector retrieval (`0.50` to `0.95`). |
| `updated_at` | String | ISO 8601 timestamp of the last configuration change. |
