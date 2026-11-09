"""Offline checks for automatic vector index setup (mocked MongoDB client, no real database)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import numpy as np
from pymongo.errors import CollectionInvalid, OperationFailure

from scripts.ingest_uploaded_document import ensure_vector_index_step, ingest_single_document
from src.rag.ingestor import RAGDocumentIngestor
from src.rag.vector_index import (
    VectorIndexPermissionError,
    build_vector_index_definition,
    classify_index,
    ensure_vector_index,
    get_vector_index_status,
)


def permission_failure():
    return OperationFailure("not authorized on example_db to execute command { createSearchIndexes }", code=13)


class FakeCollection:
    """Stateful stand-in for a pymongo collection with Atlas search index support."""

    def __init__(self, name="doc_vectors", indexes=None, list_error=None, create_error=None):
        self.name = name
        self.indexes = list(indexes or [])
        self.list_error = list_error
        self.create_error = create_error
        self.created_models = []

    def list_search_indexes(self, name=None):
        if self.list_error:
            raise self.list_error
        return [idx for idx in self.indexes if name is None or idx["name"] == name]

    def create_search_index(self, model):
        self.created_models.append(model)
        if self.create_error:
            raise self.create_error
        document = model.document
        self.indexes.append(
            {"name": document["name"], "status": "PENDING", "queryable": False, "latestDefinition": document["definition"]}
        )


class FakeDatabase:
    def __init__(self, collection, existing=True, list_error=None, create_error=None):
        self.collection = collection
        self.collections = {collection.name} if existing else set()
        self.list_error = list_error
        self.create_error = create_error
        self.created_collections = []

    def list_collection_names(self):
        if self.list_error:
            raise self.list_error
        return list(self.collections)

    def create_collection(self, name):
        self.created_collections.append(name)
        if self.create_error:
            raise self.create_error
        self.collections.add(name)

    def __getitem__(self, name):
        return self.collection


def ready_index(dimensions=384):
    return {
        "name": "vector_index",
        "status": "READY",
        "queryable": True,
        "latestDefinition": build_vector_index_definition(dimensions),
    }


class EnsureVectorIndexTests(unittest.TestCase):
    def ensure(self, db, **kwargs):
        return ensure_vector_index(db, "doc_vectors", "vector_index", 384, log=lambda message: None, **kwargs)

    def test_index_absent_is_created_exactly_once_across_repeated_runs(self):
        collection = FakeCollection()
        db = FakeDatabase(collection)
        first = self.ensure(db)
        second = self.ensure(db)
        third = self.ensure(db)
        self.assertEqual((first["state"], first["index_created"]), ("building", True))
        self.assertFalse(second["index_created"])
        self.assertFalse(third["index_created"])
        self.assertEqual(len(collection.created_models), 1)

    def test_created_index_uses_the_shared_definition_and_name(self):
        collection = FakeCollection()
        self.ensure(FakeDatabase(collection))
        document = collection.created_models[0].document
        self.assertEqual(document["name"], "vector_index")
        self.assertEqual(document["type"], "vectorSearch")
        self.assertEqual(
            document["definition"],
            {
                "fields": [
                    {"type": "vector", "path": "embedding", "numDimensions": 384, "similarity": "cosine"},
                    {"type": "filter", "path": "tenant_id"},
                    {"type": "filter", "path": "doc_id"},
                ]
            },
        )

    def test_present_index_is_not_recreated(self):
        for existing in (ready_index(), {"name": "vector_index", "status": "BUILDING", "queryable": False}):
            collection = FakeCollection(indexes=[existing])
            result = self.ensure(FakeDatabase(collection))
            self.assertEqual(collection.created_models, [])
            self.assertFalse(result["index_created"])
        self.assertEqual(self.ensure(FakeDatabase(FakeCollection(indexes=[ready_index()])))["state"], "ready")

    def test_failed_and_wrongly_sized_indexes_are_reported_not_replaced(self):
        collection = FakeCollection(indexes=[{"name": "vector_index", "status": "FAILED", "queryable": False}])
        self.assertEqual(self.ensure(FakeDatabase(collection))["state"], "failed")
        collection = FakeCollection(indexes=[ready_index(768)])
        result = self.ensure(FakeDatabase(collection))
        self.assertEqual(result["state"], "misconfigured")
        self.assertIn("768", result["message"])
        self.assertEqual(collection.created_models, [])

    def test_missing_collection_is_created_once_then_left_alone(self):
        collection = FakeCollection()
        db = FakeDatabase(collection, existing=False)
        first = self.ensure(db)
        self.ensure(db)
        self.assertTrue(first["collection_created"])
        self.assertEqual(db.created_collections, ["doc_vectors"])

    def test_concurrent_creators_are_tolerated(self):
        db = FakeDatabase(FakeCollection(), existing=False, create_error=CollectionInvalid("already exists"))
        self.assertFalse(self.ensure(db)["collection_created"])
        duplicate = FakeCollection(create_error=OperationFailure("Duplicate Index", code=68))
        result = self.ensure(FakeDatabase(duplicate))
        self.assertEqual((result["state"], result["index_created"]), ("building", False))

    def test_namespace_not_found_reads_as_missing(self):
        collection = FakeCollection(list_error=OperationFailure("ns not found", code=26))
        self.assertEqual(get_vector_index_status(collection, "vector_index")["state"], "missing")

    def test_environment_style_overrides_are_respected_through_arguments(self):
        collection = FakeCollection(name="custom_vectors")
        ensure_vector_index(FakeDatabase(collection), "custom_vectors", "custom_index", 768, log=lambda m: None)
        document = collection.created_models[0].document
        self.assertEqual(document["name"], "custom_index")
        self.assertEqual(document["definition"]["fields"][0]["numDimensions"], 768)


class PermissionErrorTests(unittest.TestCase):
    def assert_clear(self, error):
        message = str(error)
        self.assertIn("database user is not permitted", message)
        self.assertIn("createSearchIndexes", message)
        self.assertIn("listSearchIndexes", message)
        self.assertIn("vector_index", message)
        self.assertNotIn("example_db", message, "driver text and database names must not be echoed")

    def run_case(self, db):
        with self.assertRaises(VectorIndexPermissionError) as caught:
            ensure_vector_index(db, "doc_vectors", "vector_index", 384, log=lambda m: None)
        self.assert_clear(caught.exception)

    def test_listing_search_indexes_not_authorized(self):
        self.run_case(FakeDatabase(FakeCollection(list_error=permission_failure())))

    def test_creating_the_index_not_authorized(self):
        collection = FakeCollection(create_error=permission_failure())
        self.run_case(FakeDatabase(collection))
        self.assertEqual(len(collection.created_models), 1)

    def test_creating_the_collection_not_authorized(self):
        self.run_case(FakeDatabase(FakeCollection(), existing=False, create_error=permission_failure()))

    def test_listing_collections_not_authorized(self):
        self.run_case(FakeDatabase(FakeCollection(), list_error=permission_failure()))

    def test_atlas_style_not_allowed_message_is_recognised(self):
        error = OperationFailure("user is not allowed to do action [createSearchIndexes] on [db.doc_vectors]", code=8000)
        self.run_case(FakeDatabase(FakeCollection(create_error=error)))

    def test_other_errors_are_not_disguised_as_permission_problems(self):
        collection = FakeCollection(list_error=OperationFailure("something else broke", code=1))
        with self.assertRaises(OperationFailure):
            ensure_vector_index(FakeDatabase(collection), "doc_vectors", "vector_index", 384, log=lambda m: None)


class ClassificationTests(unittest.TestCase):
    def test_states(self):
        self.assertEqual(classify_index({"status": "READY", "queryable": True}, 384)[0], "ready")
        self.assertEqual(classify_index({"status": "STALE", "queryable": True}, 384)[0], "ready")
        self.assertEqual(classify_index({"status": "PENDING", "queryable": False}, 384)[0], "building")
        self.assertEqual(classify_index({"status": "FAILED"}, 384)[0], "failed")
        self.assertEqual(classify_index({"status": "DOES_NOT_EXIST"}, 384)[0], "missing")

    def test_source_names_no_specific_tenant(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "data" / "fixtures" / "demo_manifest.json").read_text())
        tenant_ids = [tenant["tenant_id"] for tenant in manifest["preset_tenants"]]
        self.assertTrue(tenant_ids, "the manifest should list tenants to check against")
        source = (root / "src" / "rag" / "vector_index.py").read_text()
        for tenant_id in tenant_ids:
            self.assertNotIn(tenant_id, source)


class IngestorDelegationTests(unittest.TestCase):
    def build_ingestor(self):
        ingestor = RAGDocumentIngestor.__new__(RAGDocumentIngestor)  # skip loading the embedding model
        ingestor.db = MagicMock()
        ingestor.collection = Mock()
        ingestor.collection.name = "doc_vectors"
        ingestor.num_dimensions = 384
        return ingestor

    def test_ensure_vector_search_index_reuses_the_shared_implementation(self):
        ingestor = self.build_ingestor()
        with patch("src.rag.ingestor.ensure_vector_index", return_value={"state": "building"}) as shared, patch.dict(
            os.environ, {"MONGODB_VECTOR_INDEX_NAME": "custom_index"}
        ):
            result = ingestor.ensure_vector_search_index()
        shared.assert_called_once_with(ingestor.db, "doc_vectors", "custom_index", 384)
        self.assertEqual(result, {"state": "building"})

    def test_explicit_index_name_wins(self):
        ingestor = self.build_ingestor()
        with patch("src.rag.ingestor.ensure_vector_index", return_value={}) as shared:
            ingestor.ensure_vector_search_index("explicit_name")
        self.assertEqual(shared.call_args.args[2], "explicit_name")


class IngestionScriptTests(unittest.TestCase):
    def run_ingest(self, ensure_behaviour):
        events = []

        class RecordingIngestor:
            def __init__(self, **kwargs):
                self.collection = Mock()
                self.collection.count_documents.side_effect = lambda *a, **k: events.append("count") or 0
                self.collection.insert_many.side_effect = lambda *a, **k: events.append("insert")
                self.model = Mock()
                self.model.encode.return_value = np.zeros((1, 384), dtype=np.float32)
                self.client = Mock()

            def ensure_vector_search_index(self):
                events.append("ensure")
                return ensure_behaviour()

            def _parse_file(self, path):
                return [{"doc_id": path.stem, "section": "Policy", "text": "Items may be returned within 30 days."}]

        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "RETURNS.md"
            doc.write_text("# Policy\nItems may be returned within 30 days.\n", encoding="utf-8")
            with patch.dict(os.environ, {"MONGODB_URI": "mongodb://u:p@host:27017/?x=1"}, clear=False), patch(
                "scripts.ingest_uploaded_document.DocumentIngestor", RecordingIngestor
            ):
                result = ingest_single_document(file_path=doc, tenant_id="example_tenant", doc_id_override="RETURNS")
        return result, events

    def test_the_ensure_step_runs_before_chunks_are_inserted(self):
        result, events = self.run_ingest(lambda: {"state": "building", "index_created": True})
        self.assertEqual(events, ["ensure", "count", "insert"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["vector_index"], {"state": "building", "index_created": True})

    def test_a_permission_problem_warns_but_does_not_block_the_upload(self):
        def deny():
            raise VectorIndexPermissionError("The database user is not permitted to create it.")

        result, events = self.run_ingest(deny)
        self.assertIn("insert", events)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["vector_index"]["state"], "permission_denied")
        self.assertIn("not permitted", result["vector_index"]["message"])

    def test_unexpected_errors_are_reported_generically_without_leaking_driver_text(self):
        def explode():
            raise RuntimeError("connect failed mongodb://admin:hunter2@cluster0.example.net")

        result, events = self.run_ingest(explode)
        self.assertIn("insert", events)
        self.assertEqual(result["vector_index"]["state"], "unknown")
        self.assertNotIn("hunter2", str(result))

    def test_step_helper_summarises_ready_without_a_message(self):
        ingestor = Mock()
        ingestor.ensure_vector_search_index.return_value = {"state": "ready", "index_created": False}
        self.assertEqual(ensure_vector_index_step(ingestor), {"state": "ready", "index_created": False})


if __name__ == "__main__":
    unittest.main()
