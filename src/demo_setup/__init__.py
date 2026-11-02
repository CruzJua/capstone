"""Demo setup, deterministic fixture seeding, target validation, and local vector index verification."""

from .seeder import (
    ALLOWED_DEMO_HOSTS,
    ALLOWED_DEMO_DB_NAMES,
    DEFAULT_MANIFEST_PATH,
    DemoSeedError,
    DemoTargetRefusedError,
    DemoSourceDriftError,
    DemoReadinessTimeoutError,
    compute_file_sha256,
    compute_json_sha256,
    load_demo_manifest,
    redact_mongo_uri,
    validate_demo_environment_and_target,
    plan_demo_seed,
    execute_demo_seed,
    wait_for_vector_index_ready,
    verify_vector_search_smoke_query,
)

__all__ = [
    "ALLOWED_DEMO_HOSTS",
    "ALLOWED_DEMO_DB_NAMES",
    "DEFAULT_MANIFEST_PATH",
    "DemoSeedError",
    "DemoTargetRefusedError",
    "DemoSourceDriftError",
    "DemoReadinessTimeoutError",
    "compute_file_sha256",
    "compute_json_sha256",
    "load_demo_manifest",
    "redact_mongo_uri",
    "validate_demo_environment_and_target",
    "plan_demo_seed",
    "execute_demo_seed",
    "wait_for_vector_index_ready",
    "verify_vector_search_smoke_query",
]

