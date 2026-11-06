"""Idempotent creation and inspection of the Atlas Vector Search index on ``doc_vectors``.

This module is the single Python implementation: ``RAGDocumentIngestor.ensure_vector_search_index``
delegates to it, so the ingestion scripts never need the Atlas UI. It holds no tenant-specific logic;
the index is shared by every tenant and filtered by ``tenant_id`` at query time.

Creating an index only *submits* it. Atlas builds it asynchronously, so nothing here waits for the
build; callers read ``get_vector_index_status`` to see ``building`` become ``ready``.

States returned by ``get_vector_index_status`` / ``ensure_vector_index``:
    missing        no index with that name exists
    building       the index exists but is not yet queryable
    ready          the index is queryable
    failed         the server reports the index build failed
    misconfigured  the index exists with different dimensions than the embedding model produces
"""

import re
from typing import Any, Callable, Dict, Optional, Tuple

from pymongo.errors import CollectionInvalid, OperationFailure
from pymongo.operations import SearchIndexModel

DEFAULT_INDEX_NAME = "vector_index"

_NAMESPACE_NOT_FOUND = 26
_NAMESPACE_EXISTS = 48
_PERMISSION_CODES = {13, 8000}
_PERMISSION_PATTERN = re.compile(r"not authorized|unauthorized|not allowed to do action|requires authentication", re.I)
_EXISTS_PATTERN = re.compile(r"already exists|duplicate", re.I)


class VectorIndexPermissionError(RuntimeError):
    """The database user may not create collections or inspect/create Atlas Search indexes."""


def build_vector_index_definition(num_dimensions: int) -> Dict[str, Any]:
    """The shared vector index definition: cosine similarity, filterable by tenant_id and doc_id."""
    return {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": num_dimensions,
                "similarity": "cosine",
            },
            {"type": "filter", "path": "tenant_id"},
            {"type": "filter", "path": "doc_id"},
        ]
    }


def is_permission_error(exc: BaseException) -> bool:
    if not isinstance(exc, OperationFailure):
        return False
    return exc.code in _PERMISSION_CODES or bool(_PERMISSION_PATTERN.search(str(exc)))


def permission_message(collection_name: str, index_name: str) -> str:
    return (
        f"The database user is not permitted to create collections or to inspect/create Atlas Search "
        f"indexes, so the vector index '{index_name}' on collection '{collection_name}' could not be set up. "
        "Grant the user Atlas search-index privileges (the createSearchIndexes and listSearchIndexes "
        "actions, for example through a custom role or the built-in atlasAdmin role), or create the index "
        "once by hand in Atlas using the shared definition."
    )


def _indexed_dimensions(index: Dict[str, Any]) -> Optional[int]:
    definition = index.get("latestDefinition") or index.get("definition") or {}
    for field in definition.get("fields", []):
        if field.get("type") == "vector":
            return field.get("numDimensions")
    return None


def classify_index(index: Dict[str, Any], expected_dimensions: Optional[int] = None) -> Tuple[str, Optional[str]]:
    """Maps one ``listSearchIndexes`` entry to (state, message)."""
    status = str(index.get("status") or index.get("state") or "").upper()
    if status == "DOES_NOT_EXIST":
        return "missing", None
    indexed = _indexed_dimensions(index)
    if expected_dimensions is not None and indexed is not None and indexed != expected_dimensions:
        return "misconfigured", (
            f"The index was built for {indexed} dimensions but the embedding model produces "
            f"{expected_dimensions}. Drop and recreate the index (it is not changed automatically)."
        )
    if status == "FAILED":
        return "failed", "The server reports that the index build failed. Check the index in Atlas."
    if index.get("queryable") is True or status == "READY" or (status == "" and "queryable" not in index):
        return "ready", None
    return "building", None


def get_vector_index_status(
    collection: Any, index_name: str, expected_dimensions: Optional[int] = None
) -> Dict[str, Any]:
    """Reads the index state. Raises ``VectorIndexPermissionError`` when the user may not list indexes."""
    try:
        indexes = [idx for idx in collection.list_search_indexes(index_name) if idx.get("name") == index_name]
    except OperationFailure as exc:
        if exc.code == _NAMESPACE_NOT_FOUND:
            return {"name": index_name, "state": "missing"}
        if is_permission_error(exc):
            raise VectorIndexPermissionError(permission_message(collection.name, index_name)) from exc
        raise
    if not indexes:
        return {"name": index_name, "state": "missing"}
    state, message = classify_index(indexes[0], expected_dimensions)
    status: Dict[str, Any] = {"name": index_name, "state": state}
    if message:
        status["message"] = message
    return status


def ensure_vector_index(
    db: Any,
    collection_name: str,
    index_name: str,
    num_dimensions: int,
    log: Callable[[str], None] = print,
) -> Dict[str, Any]:
    """Creates the collection and the vector index if they are missing. Safe to run on every start.

    An existing index is never recreated or modified. Returns
    ``{"name", "state", "collection_created", "index_created"[, "message"]}``.
    """
    result: Dict[str, Any] = {"name": index_name, "collection_created": False, "index_created": False}
    try:
        if collection_name not in db.list_collection_names():
            log(f"Creating collection '{collection_name}'...")
            try:
                db.create_collection(collection_name)
                result["collection_created"] = True
            except CollectionInvalid:
                pass  # created concurrently by another process
            except OperationFailure as exc:
                if exc.code != _NAMESPACE_EXISTS:
                    raise
    except OperationFailure as exc:
        if is_permission_error(exc):
            raise VectorIndexPermissionError(permission_message(collection_name, index_name)) from exc
        raise

    collection = db[collection_name]
    status = get_vector_index_status(collection, index_name, num_dimensions)
    if status["state"] != "missing":
        log(f"Vector search index '{index_name}' already exists ({status['state']}).")
        result.update({key: value for key, value in status.items() if key != "name"})
        return result

    model = SearchIndexModel(
        definition=build_vector_index_definition(num_dimensions), name=index_name, type="vectorSearch"
    )
    try:
        collection.create_search_index(model=model)
        result["index_created"] = True
        log(f"Vector search index '{index_name}' submitted to Atlas; it builds in the background.")
    except OperationFailure as exc:
        if is_permission_error(exc):
            raise VectorIndexPermissionError(permission_message(collection_name, index_name)) from exc
        if not _EXISTS_PATTERN.search(str(exc)):
            raise
        log(f"Vector search index '{index_name}' is already being built.")
    result["state"] = "building"
    return result
