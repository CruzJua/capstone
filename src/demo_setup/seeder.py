"""Deterministic, safe local demo seeder and vector index initializer."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "data" / "fixtures" / "demo_manifest.json"

ALLOWED_DEMO_HOSTS = frozenset({"127.0.0.1", "localhost", "mongodb-demo"})
ALLOWED_DEMO_DB_NAMES = frozenset({"capstone_demo", "capstone_local_demo"})
FORBIDDEN_DB_NAMES = frozenset(
    {
        "rag_knowledge_base",
        "capstone_dev",
        "admin",
        "local",
        "config",
    }
)
SEED_STATE_COLLECTION = "demo_seed_state"
SEED_STATE_ID = "demo_fixture_manifest_v1"


class DemoSeedError(RuntimeError):
    """Base error for demo seed/setup failures."""


class DemoTargetRefusedError(DemoSeedError):
    """Raised when the configured mode, URI, or database is not a safe local demo target."""


class DemoSourceDriftError(DemoSeedError):
    """Raised when source fixtures changed relative to an already-seeded demo database without --refresh-changed."""


class DemoReadinessTimeoutError(DemoSeedError):
    """Raised when the local vector search index does not become READY within the bounded timeout."""


def compute_file_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def compute_json_sha256(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def redact_mongo_uri(uri: str) -> str:
    """Return a safe, credential-free representation of the MongoDB target."""
    if not uri:
        return "<empty>"
    try:
        parsed = urlsplit(uri)
        scheme = parsed.scheme or "mongodb"
        host = parsed.hostname or "unknown-host"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{scheme}://{host}{port}"
    except Exception:
        return "<redacted-uri>"


def load_demo_manifest(
    manifest_path: Optional[Path | str] = None,
    project_root: Optional[Path | str] = None,
) -> Dict[str, Any]:
    root = Path(project_root) if project_root else PROJECT_ROOT
    resolved_path = Path(manifest_path) if manifest_path else (root / "data" / "fixtures" / "demo_manifest.json")
    if not resolved_path.is_file():
        raise DemoSeedError(f"Demo fixture manifest not found at {resolved_path}")

    raw_bytes = resolved_path.read_bytes()
    manifest_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    data = json.loads(raw_bytes.decode("utf-8"))

    if not isinstance(data, dict):
        raise DemoSeedError("Demo fixture manifest must be a JSON object.")

    required_keys = {
        "seed_version",
        "embedding_model",
        "embedding_dimensions",
        "vector_index_name",
        "vector_collection_name",
        "preset_tenants",
        "sample_tickets",
    }
    missing = required_keys - set(data.keys())
    if missing:
        raise DemoSeedError(f"Demo fixture manifest is missing required keys: {sorted(missing)}")

    preset_tenants = data.get("preset_tenants")
    sample_tickets = data.get("sample_tickets")
    if not isinstance(preset_tenants, list) or not preset_tenants:
        raise DemoSeedError("preset_tenants must be a non-empty list.")
    if not isinstance(sample_tickets, list) or not sample_tickets:
        raise DemoSeedError("sample_tickets must be a non-empty list.")

    seen_tenant_ids = set()
    tenant_hashes: Dict[str, str] = {}
    document_hashes: Dict[str, Dict[str, str]] = {}

    for tenant in preset_tenants:
        tid = str(tenant.get("tenant_id") or "").strip()
        if not tid or tid in seen_tenant_ids:
            raise DemoSeedError(f"Invalid or duplicate preset tenant_id in manifest: '{tid}'")
        seen_tenant_ids.add(tid)

        business_core = {
            "tenant_id": tid,
            "name": tenant["name"],
            "industry": tenant["industry"],
            "contact_email": tenant["contact_email"],
            "team_name": tenant["team_name"],
            "agent_config": tenant["agent_config"],
        }
        tenant_hashes[tid] = compute_json_sha256(business_core)

        doc_list = tenant.get("source_documents") or []
        if not isinstance(doc_list, list) or not doc_list:
            raise DemoSeedError(f"Tenant '{tid}' has no source_documents in manifest.")

        doc_map: Dict[str, str] = {}
        for rel_doc in doc_list:
            rel_str = str(rel_doc).strip()
            if "held_out_benchmark" in rel_str or "evaluation/" in rel_str:
                raise DemoSeedError(
                    f"Forbidden benchmark path '{rel_str}' referenced in demo manifest."
                )
            doc_path = (root / rel_str).resolve()
            if not doc_path.is_file():
                raise DemoSeedError(f"Missing source document for tenant '{tid}': {doc_path}")
            doc_map[rel_str] = compute_file_sha256(doc_path)
        document_hashes[tid] = doc_map

    seen_ticket_ids = set()
    ticket_hashes: Dict[str, str] = {}
    for ticket in sample_tickets:
        tkt_id = str(ticket.get("ticket_id") or "").strip()
        tkt_tenant = str(ticket.get("tenant_id") or "").strip()
        if not tkt_id or tkt_id in seen_ticket_ids:
            raise DemoSeedError(f"Invalid or duplicate ticket_id in manifest: '{tkt_id}'")
        if tkt_tenant not in seen_tenant_ids:
            raise DemoSeedError(
                f"Sample ticket '{tkt_id}' references unknown preset tenant '{tkt_tenant}'."
            )
        seen_ticket_ids.add(tkt_id)
        ticket_hashes[tkt_id] = compute_json_sha256(ticket)

    return {
        "manifest_path": str(resolved_path),
        "manifest_sha256": manifest_sha256,
        "seed_version": str(data["seed_version"]),
        "embedding_model": str(data["embedding_model"]),
        "embedding_dimensions": int(data["embedding_dimensions"]),
        "vector_index_name": str(data["vector_index_name"]),
        "vector_collection_name": str(data["vector_collection_name"]),
        "document_parser": str(data.get("document_parser", "legacy")),
        "chunk_size": int(data.get("chunk_size", 500)),
        "chunk_overlap": int(data.get("chunk_overlap", 75)),
        "preset_tenants": preset_tenants,
        "sample_tickets": sample_tickets,
        "tenant_hashes": tenant_hashes,
        "ticket_hashes": ticket_hashes,
        "document_hashes": document_hashes,
    }


def validate_demo_environment_and_target(
    *,
    app_mode: Optional[str],
    mongo_uri: Optional[str],
    training_db_name: Optional[str],
    standard_db_name: Optional[str] = None,
    allowed_hosts: Optional[frozenset[str]] = None,
    allowed_db_names: Optional[frozenset[str]] = None,
) -> Dict[str, str]:
    """Validate that the seed target is strictly an isolated local demo instance.

    Refuses:
    - Any APP_MODE other than 'preset_training'
    - Missing or placeholder MONGODB_URI
    - Cloud/SRV URIs (mongodb+srv://) or *.mongodb.net hosts
    - Non-allowlisted hostnames (only 127.0.0.1, localhost, or mongodb-demo are permitted)
    - Missing MONGODB_TRAINING_DB_NAME, standard DB collisions, or non-allowlisted DB names
    """
    mode = (app_mode or "").strip()
    if mode != "preset_training":
        raise DemoTargetRefusedError(
            f"Refusing demo seed: APP_MODE must be 'preset_training' (got '{mode or 'standard'}')."
        )

    uri = (mongo_uri or "").strip()
    if not uri or "<username>" in uri or "<password>" in uri:
        raise DemoTargetRefusedError(
            "Refusing demo seed: MONGODB_URI is missing or contains placeholder credentials."
        )

    lower_uri = uri.lower()
    if lower_uri.startswith("mongodb+srv://"):
        raise DemoTargetRefusedError(
            "Refusing demo seed: 'mongodb+srv://' cloud Atlas URIs are strictly forbidden for local demo seeding."
        )
    if not lower_uri.startswith("mongodb://"):
        raise DemoTargetRefusedError(
            "Refusing demo seed: MONGODB_URI must use the 'mongodb://' scheme pointing to the local demo container."
        )
    if "mongodb.net" in lower_uri or "atlas" in lower_uri.split("@")[-1]:
        raise DemoTargetRefusedError(
            "Refusing demo seed: remote Atlas hostnames are forbidden for local demo seeding."
        )

    parsed = urlsplit(uri)
    # Extract all host entries in case of comma-separated host list
    netloc_without_auth = parsed.netloc.rsplit("@", 1)[-1]
    host_entries = [h.strip() for h in netloc_without_auth.split(",") if h.strip()]
    if not host_entries:
        raise DemoTargetRefusedError("Refusing demo seed: no hostname found in MONGODB_URI.")

    permitted_hosts = allowed_hosts if allowed_hosts is not None else ALLOWED_DEMO_HOSTS
    resolved_hosts = []
    for entry in host_entries:
        host_only = entry.split(":", 1)[0].strip().lower()
        if host_only not in permitted_hosts:
            raise DemoTargetRefusedError(
                f"Refusing demo seed: target host '{host_only}' is not in the allowed local demo targets {sorted(permitted_hosts)}."
            )
        resolved_hosts.append(host_only)

    db_name = (training_db_name or "").strip()
    std_db = (standard_db_name or "rag_knowledge_base").strip()
    if not db_name:
        raise DemoTargetRefusedError(
            "Refusing demo seed: MONGODB_TRAINING_DB_NAME is required."
        )
    if db_name == std_db:
        raise DemoTargetRefusedError(
            f"Refusing demo seed: MONGODB_TRAINING_DB_NAME ('{db_name}') must be distinct from standard MONGODB_DB_NAME ('{std_db}')."
        )
    if db_name in FORBIDDEN_DB_NAMES:
        raise DemoTargetRefusedError(
            f"Refusing demo seed: database '{db_name}' is reserved for standard/development Atlas usage and cannot be used by the automated local demo seeder."
        )

    permitted_dbs = allowed_db_names if allowed_db_names is not None else ALLOWED_DEMO_DB_NAMES
    if db_name not in permitted_dbs:
        raise DemoTargetRefusedError(
            f"Refusing demo seed: database '{db_name}' is not in the allowed local demo database names {sorted(permitted_dbs)}."
        )

    return {
        "app_mode": mode,
        "redacted_target": redact_mongo_uri(uri),
        "host": resolved_hosts[0],
        "database_name": db_name,
        "standard_database_name": std_db,
    }


def plan_demo_seed(
    *,
    app_mode: Optional[str],
    mongo_uri: Optional[str],
    training_db_name: Optional[str],
    standard_db_name: Optional[str] = None,
    manifest_path: Optional[Path | str] = None,
    project_root: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Build a read-only dry-run seed plan without connecting to MongoDB or loading models."""
    target_info = validate_demo_environment_and_target(
        app_mode=app_mode,
        mongo_uri=mongo_uri,
        training_db_name=training_db_name,
        standard_db_name=standard_db_name,
    )
    manifest = load_demo_manifest(manifest_path=manifest_path, project_root=project_root)

    total_docs = sum(len(docs) for docs in manifest["document_hashes"].values())
    return {
        "mode": "dry_run",
        "status": "planned",
        "seed_version": manifest["seed_version"],
        "manifest_sha256": manifest["manifest_sha256"],
        "target": target_info,
        "embedding_model": manifest["embedding_model"],
        "embedding_dimensions": manifest["embedding_dimensions"],
        "vector_collection_name": manifest["vector_collection_name"],
        "vector_index_name": manifest["vector_index_name"],
        "document_parser": manifest["document_parser"],
        "counts": {
            "preset_businesses": len(manifest["preset_tenants"]),
            "sample_tickets": len(manifest["sample_tickets"]),
            "source_documents": total_docs,
        },
        "tenant_hashes": manifest["tenant_hashes"],
        "ticket_hashes": manifest["ticket_hashes"],
        "document_hashes": manifest["document_hashes"],
    }


def _strip_business_for_comparison(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tenant_id": doc.get("tenant_id"),
        "name": doc.get("name"),
        "industry": doc.get("industry"),
        "contact_email": doc.get("contact_email"),
        "team_name": doc.get("team_name"),
        "agent_config": doc.get("agent_config"),
    }


def _strip_ticket_for_comparison(doc: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "ticket_id",
        "tenant_id",
        "customer_contact",
        "escalation_reason",
        "ticket_summary",
        "question",
        "answer",
        "messages",
        "rationale",
        "similarity_score",
        "retrieved_chunks",
        "status",
        "admin_notes",
        "admin_reply",
        "created_at",
    )
    return {k: doc[k] for k in keys if k in doc}


def ensure_local_vector_search_index(
    collection: Any,
    *,
    index_name: str,
    num_dimensions: int,
) -> Dict[str, Any]:
    """Ensure the collection and vectorSearch index with tenant_id and doc_id filters exist."""
    db = collection.database
    if collection.name not in db.list_collection_names():
        db.create_collection(collection.name)

    definition = {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": int(num_dimensions),
                "similarity": "cosine",
            },
            {
                "type": "filter",
                "path": "tenant_id",
            },
            {
                "type": "filter",
                "path": "doc_id",
            },
        ]
    }

    try:
        existing_indexes = list(collection.list_search_indexes())
        for idx in existing_indexes:
            if idx.get("name") == index_name:
                return {
                    "index_name": index_name,
                    "action": "already_exists",
                    "definition": definition,
                }
    except Exception:
        pass

    model = SearchIndexModel(
        definition=definition,
        name=index_name,
        type="vectorSearch",
    )
    try:
        collection.create_search_index(model=model)
        action = "created"
    except Exception as exc:
        msg = str(exc).lower()
        if "already exists" in msg or "duplicate" in msg:
            action = "already_exists"
        else:
            raise DemoSeedError(
                f"Failed to create vector search index '{index_name}': {type(exc).__name__}: {exc}"
            ) from exc

    return {
        "index_name": index_name,
        "action": action,
        "definition": definition,
    }


def wait_for_vector_index_ready(
    collection: Any,
    *,
    index_name: str,
    timeout_seconds: float = 120.0,
    poll_interval_seconds: float = 2.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock_fn: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Poll list_search_indexes until the target vector index reports READY or queryable."""
    deadline = clock_fn() + max(0.1, float(timeout_seconds))
    last_status = "MISSING"

    while True:
        try:
            indexes = list(collection.list_search_indexes())
            matched = next((idx for idx in indexes if idx.get("name") == index_name), None)
            if matched is not None:
                status = str(matched.get("status") or matched.get("state") or "").upper()
                queryable = matched.get("queryable")
                last_status = status or ("READY" if queryable else "BUILDING")
                if status == "READY" or queryable is True:
                    return {
                        "index_name": index_name,
                        "ready": True,
                        "status": "READY",
                    }
                if status in {"FAILED", "DOES_NOT_EXIST"}:
                    raise DemoReadinessTimeoutError(
                        f"Vector search index '{index_name}' entered terminal status '{status}'."
                    )
        except DemoReadinessTimeoutError:
            raise
        except Exception as exc:
            last_status = f"ERROR:{type(exc).__name__}"

        if clock_fn() >= deadline:
            raise DemoReadinessTimeoutError(
                f"Timed out after {timeout_seconds:.1f}s waiting for vector search index '{index_name}' "
                f"to become READY (last observed status: {last_status}). "
                "Verify that the local database uses 'mongodb/mongodb-atlas-local' with an active mongot search process."
            )

        sleep_fn(poll_interval_seconds)


def verify_vector_search_smoke_query(
    collection: Any,
    *,
    index_name: str,
    query_vector: List[float],
    tenant_id: str = "iron_and_oak",
    timeout_seconds: float = 60.0,
    poll_interval_seconds: float = 2.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock_fn: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Execute a real tenant-prefiltered $vectorSearch query and confirm non-empty tenant-scoped results."""
    pipeline = [
        {
            "$vectorSearch": {
                "index": index_name,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 50,
                "limit": 4,
                "filter": {
                    "tenant_id": {"$eq": tenant_id},
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "tenant_id": 1,
                "doc_id": 1,
                "section": 1,
                "text": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]

    deadline = clock_fn() + max(0.1, float(timeout_seconds))
    last_error = None

    while True:
        try:
            results = list(collection.aggregate(pipeline))
            if results:
                if any(r.get("tenant_id") != tenant_id for r in results):
                    raise DemoSeedError(
                        f"Cross-tenant leakage detected during $vectorSearch smoke check for '{tenant_id}'."
                    )
                return {
                    "verified": True,
                    "tenant_id": tenant_id,
                    "result_count": len(results),
                    "top_doc_id": results[0].get("doc_id"),
                    "top_score": results[0].get("score"),
                }
        except DemoSeedError:
            raise
        except Exception as exc:
            last_error = f"{type(exc).__name__}"

        if clock_fn() >= deadline:
            detail = f" (last error: {last_error})" if last_error else " (0 documents returned by $vectorSearch)"
            raise DemoReadinessTimeoutError(
                f"Vector search index '{index_name}' reported READY but $vectorSearch returned no documents for "
                f"tenant '{tenant_id}' within {timeout_seconds:.1f}s{detail}."
            )

        sleep_fn(poll_interval_seconds)


def execute_demo_seed(
    *,
    app_mode: Optional[str],
    mongo_uri: Optional[str],
    training_db_name: Optional[str],
    standard_db_name: Optional[str] = None,
    manifest_path: Optional[Path | str] = None,
    project_root: Optional[Path | str] = None,
    refresh_changed: bool = False,
    wait_timeout_seconds: float = 120.0,
    summary_output_path: Optional[Path | str] = None,
    db_override: Optional[Any] = None,
    ingestor_factory: Optional[Callable[..., Any]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock_fn: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Execute idempotent demo seeding, local document embedding, index creation, and readiness verification."""
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    start_perf = time.perf_counter()

    target_info = validate_demo_environment_and_target(
        app_mode=app_mode,
        mongo_uri=mongo_uri,
        training_db_name=training_db_name,
        standard_db_name=standard_db_name,
    )
    root = Path(project_root) if project_root else PROJECT_ROOT
    manifest = load_demo_manifest(manifest_path=manifest_path, project_root=root)

    collection_name = (
        os.environ.get("MONGODB_COLLECTION_NAME") or manifest["vector_collection_name"]
    ).strip()
    index_name = (
        os.environ.get("MONGODB_VECTOR_INDEX_NAME") or manifest["vector_index_name"]
    ).strip()
    model_name = (
        os.environ.get("EMBEDDING_MODEL_NAME") or manifest["embedding_model"]
    ).strip()

    if model_name != manifest["embedding_model"]:
        raise DemoSeedError(
            f"Embedding model mismatch: environment requested '{model_name}', "
            f"but demo manifest requires '{manifest['embedding_model']}'."
        )

    client: Optional[MongoClient] = None
    if db_override is not None:
        db = db_override
    else:
        client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
        )
        db = client[target_info["database_name"]]

    try:
        businesses_col = db["businesses"]
        tickets_col = db["ticket_logs"]
        vectors_col = db[collection_name]
        state_col = db[SEED_STATE_COLLECTION]

        # Ensure standard collection indexes match gateway/src/db/mongo.js
        businesses_col.create_index([("tenant_id", 1)], unique=True)
        tickets_col.create_index([("ticket_id", 1)], unique=True)
        tickets_col.create_index([("tenant_id", 1), ("status", 1), ("created_at", -1)])
        db["admin_users"].create_index([("email", 1)], unique=True)
        db["admin_users"].create_index([("user_id", 1)], unique=True)
        db["admin_users"].create_index([("tenant_id", 1)])
        db["admin_sessions"].create_index([("session_id_hash", 1)], unique=True)
        db["admin_sessions"].create_index([("expires_at", 1)])

        prior_state = state_col.find_one({"_id": SEED_STATE_ID}) or {}
        prior_tenant_hashes = prior_state.get("tenant_hashes") or {}
        prior_ticket_hashes = prior_state.get("ticket_hashes") or {}
        prior_doc_hashes = prior_state.get("document_hashes") or {}

        # Detect source fixture drift against previously recorded seed state
        drifted_items: List[str] = []
        for tid, current_hash in manifest["tenant_hashes"].items():
            old_hash = prior_tenant_hashes.get(tid)
            if old_hash and old_hash != current_hash:
                drifted_items.append(f"business:{tid}")
        for tkt_id, current_hash in manifest["ticket_hashes"].items():
            old_hash = prior_ticket_hashes.get(tkt_id)
            if old_hash and old_hash != current_hash:
                drifted_items.append(f"ticket:{tkt_id}")
        for tid, doc_map in manifest["document_hashes"].items():
            old_doc_map = prior_doc_hashes.get(tid) or {}
            if old_doc_map and old_doc_map != doc_map:
                drifted_items.append(f"documents:{tid}")

        if drifted_items and not refresh_changed:
            raise DemoSourceDriftError(
                f"Source fixtures have changed since the last seed ({', '.join(drifted_items)}). "
                "Re-run with --refresh-changed or run a demo reset to apply updated source fixtures."
            )

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        business_counts = {"inserted": 0, "unchanged": 0, "changed": 0, "skipped_user_modified": 0}
        for tenant in manifest["preset_tenants"]:
            tid = tenant["tenant_id"]
            business_record = {
                "tenant_id": tid,
                "name": tenant["name"],
                "industry": tenant["industry"],
                "contact_email": tenant["contact_email"],
                "team_name": tenant["team_name"],
                "agent_config": dict(tenant["agent_config"]),
            }
            existing = businesses_col.find_one({"tenant_id": tid})
            if existing is None:
                businesses_col.insert_one(
                    {
                        **business_record,
                        "seed_source_sha256": manifest["tenant_hashes"][tid],
                        "updated_at": now_iso,
                    }
                )
                business_counts["inserted"] += 1
            else:
                existing_hash = compute_json_sha256(_strip_business_for_comparison(existing))
                target_hash = manifest["tenant_hashes"][tid]
                recorded_seed_hash = existing.get("seed_source_sha256") or prior_tenant_hashes.get(tid)

                if existing_hash == target_hash:
                    business_counts["unchanged"] += 1
                elif refresh_changed and recorded_seed_hash and recorded_seed_hash != target_hash:
                    businesses_col.update_one(
                        {"tenant_id": tid},
                        {
                            "$set": {
                                **business_record,
                                "seed_source_sha256": target_hash,
                                "updated_at": now_iso,
                            }
                        },
                    )
                    business_counts["changed"] += 1
                else:
                    # Preserve user-edited runtime config in the demo database
                    business_counts["skipped_user_modified"] += 1

        ticket_counts = {"inserted": 0, "unchanged": 0, "changed": 0, "skipped_user_modified": 0}
        for ticket in manifest["sample_tickets"]:
            tkt_id = ticket["ticket_id"]
            existing = tickets_col.find_one({"ticket_id": tkt_id})
            target_hash = manifest["ticket_hashes"][tkt_id]

            if existing is None:
                tickets_col.insert_one(
                    {
                        **ticket,
                        "seed_source_sha256": target_hash,
                        "updated_at": now_iso,
                    }
                )
                ticket_counts["inserted"] += 1
            else:
                existing_hash = compute_json_sha256(_strip_ticket_for_comparison(existing))
                recorded_seed_hash = existing.get("seed_source_sha256") or prior_ticket_hashes.get(tkt_id)

                if existing_hash == target_hash:
                    ticket_counts["unchanged"] += 1
                elif refresh_changed and recorded_seed_hash and recorded_seed_hash != target_hash:
                    tickets_col.update_one(
                        {"ticket_id": tkt_id},
                        {
                            "$set": {
                                **ticket,
                                "seed_source_sha256": target_hash,
                                "updated_at": now_iso,
                            }
                        },
                    )
                    ticket_counts["changed"] += 1
                else:
                    # Preserve user-edited ticket status / admin notes
                    ticket_counts["skipped_user_modified"] += 1

        # Determine which tenants require document parsing + embedding
        if ingestor_factory is not None:
            ingestor = ingestor_factory(
                mongo_uri=mongo_uri,
                db_name=target_info["database_name"],
                collection_name=collection_name,
                model_name=model_name,
                chunk_size=manifest["chunk_size"],
                chunk_overlap=manifest["chunk_overlap"],
                document_parser=manifest["document_parser"],
            )
        else:
            from src.rag.ingestor import RAGDocumentIngestor

            ingestor = RAGDocumentIngestor(
                mongo_uri=mongo_uri,
                db_name=target_info["database_name"],
                collection_name=collection_name,
                model_name=model_name,
                chunk_size=manifest["chunk_size"],
                chunk_overlap=manifest["chunk_overlap"],
                document_parser=manifest["document_parser"],
            )

        observed_dims = int(getattr(ingestor, "num_dimensions", 0))
        if observed_dims != manifest["embedding_dimensions"]:
            raise DemoSeedError(
                f"Embedding dimension mismatch: model '{model_name}' reported {observed_dims} dimensions, "
                f"expected {manifest['embedding_dimensions']}."
            )

        doc_counts = {
            "tenants_ingested": 0,
            "tenants_unchanged": 0,
            "documents_indexed": 0,
            "chunks_inserted": 0,
            "chunks_existing": 0,
            "by_tenant": {},
        }

        for tenant in manifest["preset_tenants"]:
            tid = tenant["tenant_id"]
            doc_hashes_for_tenant = manifest["document_hashes"][tid]
            expected_doc_ids = {
                Path(rel_path).stem for rel_path in doc_hashes_for_tenant.keys()
            }

            existing_chunk_count = vectors_col.count_documents({"tenant_id": tid})
            existing_doc_ids = set(vectors_col.distinct("doc_id", {"tenant_id": tid}))
            prior_hashes_for_tenant = prior_doc_hashes.get(tid)

            needs_ingest = (
                existing_chunk_count == 0
                or not expected_doc_ids.issubset(existing_doc_ids)
                or (
                    refresh_changed
                    and prior_hashes_for_tenant is not None
                    and prior_hashes_for_tenant != doc_hashes_for_tenant
                )
            )

            if not needs_ingest:
                doc_counts["tenants_unchanged"] += 1
                doc_counts["chunks_existing"] += existing_chunk_count
                doc_counts["by_tenant"][tid] = {
                    "action": "unchanged",
                    "documents": len(expected_doc_ids),
                    "chunks": existing_chunk_count,
                }
                continue

            # Parse and embed only the manifest source documents for this preset tenant,
            # preserving any custom user-uploaded documents whose doc_id is not in expected_doc_ids.
            tenant_chunks: List[Dict[str, Any]] = []
            doc_format_by_id: Dict[str, str] = {}
            for rel_path in sorted(doc_hashes_for_tenant.keys()):
                abs_path = (root / rel_path).resolve()
                parsed_chunks = ingestor._parse_file(abs_path)
                if not parsed_chunks:
                    raise DemoSeedError(
                        f"Source document '{rel_path}' produced 0 chunks during demo seed."
                    )
                doc_format_by_id[abs_path.stem] = abs_path.suffix.lstrip(".").lower()
                tenant_chunks.extend(parsed_chunks)

            texts = [c["text"] for c in tenant_chunks]
            encoded = ingestor.model.encode(texts, batch_size=32, show_progress_bar=False)
            vectors_list = (
                encoded.tolist() if hasattr(encoded, "tolist") else list(encoded)
            )

            # Build per-document chunk_index ordering so DocumentViewerModal reconstructs cleanly
            per_doc_counter: Dict[str, int] = {}
            docs_to_insert: List[Dict[str, Any]] = []
            for idx, chunk in enumerate(tenant_chunks):
                d_id = chunk["doc_id"]
                c_idx = per_doc_counter.get(d_id, 0)
                per_doc_counter[d_id] = c_idx + 1
                docs_to_insert.append(
                    {
                        "tenant_id": tid,
                        "doc_id": d_id,
                        "format": doc_format_by_id.get(d_id, "md"),
                        "section": chunk.get("section") or "Overview",
                        "chunk_index": c_idx,
                        "text": chunk["text"],
                        "embedding": list(vectors_list[idx]),
                        "source_sha256": doc_hashes_for_tenant.get(
                            f"{tenant['source_dir']}/{d_id}.{doc_format_by_id.get(d_id, 'md')}"
                        ),
                        "created_at": now_iso,
                    }
                )

            vectors_col.delete_many(
                {"tenant_id": tid, "doc_id": {"$in": sorted(expected_doc_ids)}}
            )
            vectors_col.insert_many(docs_to_insert)

            doc_counts["tenants_ingested"] += 1
            doc_counts["documents_indexed"] += len(expected_doc_ids)
            doc_counts["chunks_inserted"] += len(docs_to_insert)
            doc_counts["by_tenant"][tid] = {
                "action": "seeded",
                "documents": len(expected_doc_ids),
                "chunks": len(docs_to_insert),
            }

        # Ensure and wait for vector_index readiness
        index_result = ensure_local_vector_search_index(
            vectors_col,
            index_name=index_name,
            num_dimensions=observed_dims,
        )
        readiness_result = wait_for_vector_index_ready(
            vectors_col,
            index_name=index_name,
            timeout_seconds=wait_timeout_seconds,
            sleep_fn=sleep_fn,
            clock_fn=clock_fn,
        )

        # Verify actual tenant-filtered $vectorSearch query using a local query embedding
        smoke_query_vec_raw = ingestor.model.encode(
            "How often should I condition vegetable-tanned leather boots in dry climates?"
        )
        smoke_query_vec = (
            smoke_query_vec_raw.tolist()
            if hasattr(smoke_query_vec_raw, "tolist")
            else list(smoke_query_vec_raw)
        )
        smoke_result = verify_vector_search_smoke_query(
            vectors_col,
            index_name=index_name,
            query_vector=smoke_query_vec,
            tenant_id="iron_and_oak",
            timeout_seconds=min(60.0, wait_timeout_seconds),
            sleep_fn=sleep_fn,
            clock_fn=clock_fn,
        )

        completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        duration_seconds = round(time.perf_counter() - start_perf, 3)

        state_record = {
            "_id": SEED_STATE_ID,
            "seed_version": manifest["seed_version"],
            "manifest_sha256": manifest["manifest_sha256"],
            "embedding_model": model_name,
            "embedding_dimensions": observed_dims,
            "vector_collection_name": collection_name,
            "vector_index_name": index_name,
            "tenant_hashes": manifest["tenant_hashes"],
            "ticket_hashes": manifest["ticket_hashes"],
            "document_hashes": manifest["document_hashes"],
            "updated_at": completed_at,
        }
        state_col.replace_one({"_id": SEED_STATE_ID}, state_record, upsert=True)

        summary = {
            "mode": "execute",
            "status": "ready",
            "ready": True,
            "seed_version": manifest["seed_version"],
            "manifest_sha256": manifest["manifest_sha256"],
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": duration_seconds,
            "target": target_info,
            "model_and_index": {
                "embedding_model": model_name,
                "embedding_dimensions": observed_dims,
                "vector_collection": collection_name,
                "vector_index_name": index_name,
                "index_action": index_result["action"],
                "index_ready": readiness_result["ready"],
                "vector_search_smoke_query": smoke_result,
            },
            "counts": {
                "businesses": business_counts,
                "tickets": ticket_counts,
                "documents_and_vectors": doc_counts,
            },
            "errors": [],
        }

        if summary_output_path:
            out_path = Path(summary_output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(summary, indent=4, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        if hasattr(ingestor, "client") and getattr(ingestor, "client", None) is not None:
            try:
                ingestor.client.close()
            except Exception:
                pass

        return summary
    finally:
        if client is not None:
            client.close()

