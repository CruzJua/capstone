"""Unit tests for Sprint 4 Slice 5 deterministic local demo setup and seeding."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from scripts.ingest_uploaded_document import ingest_single_document
from src.demo_setup.seeder import (
    DEFAULT_MANIFEST_PATH,
    DemoReadinessTimeoutError,
    DemoSeedError,
    DemoSourceDriftError,
    DemoTargetRefusedError,
    execute_demo_seed,
    load_demo_manifest,
    plan_demo_seed,
    redact_mongo_uri,
    validate_demo_environment_and_target,
    wait_for_vector_index_ready,
)


class FakeCollection:
    def __init__(self, name: str, db: FakeDatabase):
        self.name = name
        self.database = db
        self.docs: list[dict] = []
        self.indexes: list[tuple] = []
        self.search_indexes: list[dict] = []
        self.fail_on_create_search_index = False

    def create_index(self, keys, **kwargs):
        self.indexes.append((keys, kwargs))
        return "ok"

    def find_one(self, query: dict):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def insert_one(self, doc: dict):
        copy = dict(doc)
        self.docs.append(copy)
        return Mock(inserted_id=copy.get("_id", "id"))

    def update_one(self, query: dict, update: dict, upsert: bool = False):
        for idx, doc in enumerate(self.docs):
            if all(doc.get(k) == v for k, v in query.items()):
                if "$set" in update:
                    self.docs[idx].update(update["$set"])
                return Mock(modified_count=1)
        if upsert:
            new_doc = dict(query)
            if "$setOnInsert" in update:
                new_doc.update(update["$setOnInsert"])
            if "$set" in update:
                new_doc.update(update["$set"])
            self.docs.append(new_doc)
            return Mock(modified_count=0, upserted_id="upserted")
        return Mock(modified_count=0)

    def replace_one(self, query: dict, replacement: dict, upsert: bool = False):
        for idx, doc in enumerate(self.docs):
            if all(doc.get(k) == v for k, v in query.items()):
                self.docs[idx] = dict(replacement)
                return Mock(modified_count=1)
        if upsert:
            self.docs.append(dict(replacement))
            return Mock(modified_count=0, upserted_id="upserted")
        return Mock(modified_count=0)

    def count_documents(self, query: dict, limit: int | None = None):
        matches = [
            doc
            for doc in self.docs
            if all(doc.get(k) == v for k, v in query.items())
        ]
        if limit is not None:
            matches = matches[:limit]
        return len(matches)

    def distinct(self, field: str, query: dict | None = None):
        query = query or {}
        values = set()
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                if field in doc:
                    values.add(doc[field])
        return sorted(values)

    def delete_many(self, query: dict):
        kept = []
        deleted = 0
        for doc in self.docs:
            match = True
            for k, v in query.items():
                if isinstance(v, dict) and "$in" in v:
                    if doc.get(k) not in v["$in"]:
                        match = False
                elif doc.get(k) != v:
                    match = False
            if match:
                deleted += 1
            else:
                kept.append(doc)
        self.docs = kept
        return Mock(deleted_count=deleted)

    def insert_many(self, docs: list[dict]):
        for d in docs:
            self.docs.append(dict(d))
        return Mock(inserted_ids=[i for i in range(len(docs))])

    def list_search_indexes(self):
        return list(self.search_indexes)

    def create_search_index(self, model):
        if self.fail_on_create_search_index:
            raise RuntimeError("Simulated search index creation failure")
        doc = model.document if hasattr(model, "document") else {
            "name": "vector_index",
            "type": "vectorSearch",
            "definition": {},
        }
        self.search_indexes.append(
            {
                "name": doc.get("name", "vector_index"),
                "type": doc.get("type", "vectorSearch"),
                "definition": doc.get("definition", {}),
                "status": "READY",
                "queryable": True,
            }
        )
        return doc.get("name", "vector_index")

    def aggregate(self, pipeline: list[dict]):
        vec_stage = next((s["$vectorSearch"] for s in pipeline if "$vectorSearch" in s), None)
        if not vec_stage:
            return []
        target_tenant = vec_stage.get("filter", {}).get("tenant_id", {}).get("$eq")
        limit = vec_stage.get("limit", 4)
        matched = [
            {
                "tenant_id": d["tenant_id"],
                "doc_id": d["doc_id"],
                "section": d.get("section", "Overview"),
                "text": d["text"],
                "score": 0.91,
            }
            for d in self.docs
            if d.get("tenant_id") == target_tenant
        ]
        return matched[:limit]


class FakeDatabase:
    def __init__(self, name: str = "capstone_demo"):
        self.name = name
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.collections:
            self.collections[name] = FakeCollection(name, self)
        return self.collections[name]

    def list_collection_names(self) -> list[str]:
        return list(self.collections.keys())

    def create_collection(self, name: str) -> FakeCollection:
        return self[name]


class FakeIngestor:
    def __init__(self, num_dimensions: int = 384):
        self.num_dimensions = num_dimensions
        self.model = Mock()
        self.model.encode.side_effect = self._encode
        self.client = None

    def _encode(self, texts, **kwargs):
        if isinstance(texts, str):
            return np.full((self.num_dimensions,), 0.05, dtype=np.float32)
        return np.full((len(texts), self.num_dimensions), 0.05, dtype=np.float32)

    def _parse_file(self, file_path: Path):
        return [
            {
                "doc_id": file_path.stem,
                "section": "Overview",
                "text": f"Synthetic chunk from {file_path.name}",
            }
        ]


class DemoSetupTests(unittest.TestCase):
    def test_load_demo_manifest_validates_all_5_presets_and_excludes_held_out_benchmark(self):
        manifest = load_demo_manifest(DEFAULT_MANIFEST_PATH)
        self.assertEqual(manifest["embedding_model"], "BAAI/bge-small-en-v1.5")
        self.assertEqual(manifest["embedding_dimensions"], 384)
        self.assertEqual(manifest["vector_index_name"], "vector_index")
        self.assertEqual(len(manifest["preset_tenants"]), 5)
        self.assertEqual(len(manifest["sample_tickets"]), 12)
        for tid, docs in manifest["document_hashes"].items():
            self.assertEqual(len(docs), 6, f"Expected 6 source docs for {tid}")
            for rel_path in docs:
                self.assertNotIn("held_out_benchmark", rel_path)
                self.assertNotIn("evaluation/", rel_path)

    def test_validate_demo_target_refuses_standard_mode_cloud_uris_and_normal_databases(self):
        # 1. Refuses standard mode
        with self.assertRaises(DemoTargetRefusedError):
            validate_demo_environment_and_target(
                app_mode="standard",
                mongo_uri="mongodb://127.0.0.1:27018/?directConnection=true",
                training_db_name="capstone_demo",
            )

        # 2. Refuses mongodb+srv:// cloud Atlas URIs
        with self.assertRaises(DemoTargetRefusedError):
            validate_demo_environment_and_target(
                app_mode="preset_training",
                mongo_uri="mongodb+srv://user:secret@cluster0.example.mongodb.net/?retryWrites=true",
                training_db_name="capstone_demo",
            )

        # 3. Refuses remote hostnames even with mongodb:// scheme
        with self.assertRaises(DemoTargetRefusedError):
            validate_demo_environment_and_target(
                app_mode="preset_training",
                mongo_uri="mongodb://user:secret@prod-db.internal.company.com:27017/",
                training_db_name="capstone_demo",
            )

        # 4. Refuses standard or existing development databases (rag_knowledge_base, capstone_dev)
        for forbidden_db in ("rag_knowledge_base", "capstone_dev", "capstone_demo_extra"):
            with self.subTest(db=forbidden_db), self.assertRaises(DemoTargetRefusedError):
                validate_demo_environment_and_target(
                    app_mode="preset_training",
                    mongo_uri="mongodb://127.0.0.1:27018/?directConnection=true",
                    training_db_name=forbidden_db,
                )

        # 5. Accepts valid local demo target and redacts credentials
        valid = validate_demo_environment_and_target(
            app_mode="preset_training",
            mongo_uri="mongodb://demo_admin:super_secret_pw@mongodb-demo:27017/?directConnection=true",
            training_db_name="capstone_demo",
            standard_db_name="rag_knowledge_base",
        )
        self.assertEqual(valid["host"], "mongodb-demo")
        self.assertEqual(valid["database_name"], "capstone_demo")
        self.assertNotIn("super_secret_pw", json.dumps(valid))
        self.assertEqual(redact_mongo_uri("mongodb://admin:secret@127.0.0.1:27018/"), "mongodb://127.0.0.1:27018")

    def test_plan_demo_seed_dry_run_makes_zero_connections_and_returns_deterministic_hashes(self):
        plan1 = plan_demo_seed(
            app_mode="preset_training",
            mongo_uri="mongodb://demo:pass@127.0.0.1:27018/?directConnection=true",
            training_db_name="capstone_demo",
        )
        plan2 = plan_demo_seed(
            app_mode="preset_training",
            mongo_uri="mongodb://demo:pass@127.0.0.1:27018/?directConnection=true",
            training_db_name="capstone_demo",
        )
        self.assertEqual(plan1["manifest_sha256"], plan2["manifest_sha256"])
        self.assertEqual(plan1["tenant_hashes"], plan2["tenant_hashes"])
        self.assertEqual(plan1["ticket_hashes"], plan2["ticket_hashes"])
        self.assertEqual(plan1["document_hashes"], plan2["document_hashes"])
        self.assertEqual(plan1["counts"]["preset_businesses"], 5)
        self.assertEqual(plan1["counts"]["sample_tickets"], 12)
        self.assertEqual(plan1["counts"]["source_documents"], 30)
        self.assertNotIn("pass", json.dumps(plan1))

    def test_execute_demo_seed_idempotence_and_preserves_user_edits(self):
        fake_db = FakeDatabase("capstone_demo")
        fake_ingestor = FakeIngestor(num_dimensions=384)

        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "seed_summary.json"
            first = execute_demo_seed(
                app_mode="preset_training",
                mongo_uri="mongodb://demo:secret@127.0.0.1:27018/?directConnection=true",
                training_db_name="capstone_demo",
                summary_output_path=summary_path,
                db_override=fake_db,
                ingestor_factory=lambda **kwargs: fake_ingestor,
            )
            self.assertTrue(first["ready"])
            self.assertEqual(first["counts"]["businesses"]["inserted"], 5)
            self.assertEqual(first["counts"]["tickets"]["inserted"], 12)
            self.assertEqual(first["counts"]["documents_and_vectors"]["tenants_ingested"], 5)
            self.assertEqual(first["counts"]["documents_and_vectors"]["chunks_inserted"], 30)
            self.assertTrue(summary_path.is_file())
            self.assertNotIn("secret", summary_path.read_text(encoding="utf-8"))

            # Verify vector index definition has 384 dims, cosine similarity, and tenant_id + doc_id filters
            created_idx = fake_db["doc_vectors"].search_indexes[0]
            self.assertEqual(created_idx["name"], "vector_index")
            fields = created_idx["definition"]["fields"]
            self.assertEqual(fields[0]["type"], "vector")
            self.assertEqual(fields[0]["numDimensions"], 384)
            self.assertEqual(fields[0]["similarity"], "cosine")
            filter_paths = [f["path"] for f in fields if f["type"] == "filter"]
            self.assertEqual(filter_paths, ["tenant_id", "doc_id"])

            # Simulate an admin editing iron_and_oak's temperature and resolving TKT-IO-1042
            fake_db["businesses"].update_one(
                {"tenant_id": "iron_and_oak"},
                {"$set": {"agent_config": {"temperature": 0.45}}},
            )
            fake_db["ticket_logs"].update_one(
                {"ticket_id": "TKT-IO-1042"},
                {"$set": {"status": "resolved", "admin_notes": "Approved by demo user"}},
            )

            # Repeat seed: must not duplicate records or overwrite the user-edited business/ticket
            second = execute_demo_seed(
                app_mode="preset_training",
                mongo_uri="mongodb://demo:secret@127.0.0.1:27018/?directConnection=true",
                training_db_name="capstone_demo",
                db_override=fake_db,
                ingestor_factory=lambda **kwargs: fake_ingestor,
            )
            self.assertEqual(second["counts"]["businesses"]["inserted"], 0)
            self.assertEqual(second["counts"]["businesses"]["unchanged"], 4)
            self.assertEqual(second["counts"]["businesses"]["skipped_user_modified"], 1)
            self.assertEqual(second["counts"]["tickets"]["inserted"], 0)
            self.assertEqual(second["counts"]["tickets"]["unchanged"], 11)
            self.assertEqual(second["counts"]["tickets"]["skipped_user_modified"], 1)
            self.assertEqual(second["counts"]["documents_and_vectors"]["tenants_unchanged"], 5)
            self.assertEqual(len(fake_db["businesses"].docs), 5)
            self.assertEqual(len(fake_db["ticket_logs"].docs), 12)
            self.assertEqual(len(fake_db["doc_vectors"].docs), 30)

            io_doc = fake_db["businesses"].find_one({"tenant_id": "iron_and_oak"})
            self.assertEqual(io_doc["agent_config"]["temperature"], 0.45)
            tkt_doc = fake_db["ticket_logs"].find_one({"ticket_id": "TKT-IO-1042"})
            self.assertEqual(tkt_doc["status"], "resolved")

    def test_changed_fixture_detection_and_controlled_refresh(self):
        fake_db = FakeDatabase("capstone_demo")
        fake_ingestor = FakeIngestor(num_dimensions=384)

        execute_demo_seed(
            app_mode="preset_training",
            mongo_uri="mongodb://127.0.0.1:27018/?directConnection=true",
            training_db_name="capstone_demo",
            db_override=fake_db,
            ingestor_factory=lambda **kwargs: fake_ingestor,
        )

        # Simulate prior seed state having an older source hash for iron_and_oak
        state_doc = fake_db["demo_seed_state"].find_one({"_id": "demo_fixture_manifest_v1"})
        state_doc["tenant_hashes"]["iron_and_oak"] = "0" * 64
        fake_db["demo_seed_state"].replace_one({"_id": "demo_fixture_manifest_v1"}, state_doc)
        fake_db["businesses"].update_one(
            {"tenant_id": "iron_and_oak"},
            {"$set": {"seed_source_sha256": "0" * 64, "name": "Old Iron & Oak"}},
        )

        # Without refresh_changed=True, seeding refuses with DemoSourceDriftError
        with self.assertRaises(DemoSourceDriftError):
            execute_demo_seed(
                app_mode="preset_training",
                mongo_uri="mongodb://127.0.0.1:27018/?directConnection=true",
                training_db_name="capstone_demo",
                refresh_changed=False,
                db_override=fake_db,
                ingestor_factory=lambda **kwargs: fake_ingestor,
            )

        # With refresh_changed=True, seeding updates the drifted fixture cleanly
        refreshed = execute_demo_seed(
            app_mode="preset_training",
            mongo_uri="mongodb://127.0.0.1:27018/?directConnection=true",
            training_db_name="capstone_demo",
            refresh_changed=True,
            db_override=fake_db,
            ingestor_factory=lambda **kwargs: fake_ingestor,
        )
        self.assertEqual(refreshed["counts"]["businesses"]["changed"], 1)
        io_doc = fake_db["businesses"].find_one({"tenant_id": "iron_and_oak"})
        self.assertEqual(io_doc["name"], "Iron & Oak Provision Co.")

    def test_partial_failure_does_not_report_ready_and_supports_safe_retry(self):
        fake_db = FakeDatabase("capstone_demo")
        fake_db["doc_vectors"].fail_on_create_search_index = True
        fake_ingestor = FakeIngestor(num_dimensions=384)

        with self.assertRaises(DemoSeedError):
            execute_demo_seed(
                app_mode="preset_training",
                mongo_uri="mongodb://127.0.0.1:27018/?directConnection=true",
                training_db_name="capstone_demo",
                db_override=fake_db,
                ingestor_factory=lambda **kwargs: fake_ingestor,
            )

        # State record must not have been written on partial failure
        self.assertIsNone(fake_db["demo_seed_state"].find_one({"_id": "demo_fixture_manifest_v1"}))

        # Clear failure and retry: succeeds without duplicating businesses or tickets
        fake_db["doc_vectors"].fail_on_create_search_index = False
        recovered = execute_demo_seed(
            app_mode="preset_training",
            mongo_uri="mongodb://127.0.0.1:27018/?directConnection=true",
            training_db_name="capstone_demo",
            db_override=fake_db,
            ingestor_factory=lambda **kwargs: fake_ingestor,
        )
        self.assertTrue(recovered["ready"])
        self.assertEqual(len(fake_db["businesses"].docs), 5)
        self.assertEqual(len(fake_db["ticket_logs"].docs), 12)

    def test_readiness_timeout_raises_actionable_error(self):
        fake_db = FakeDatabase("capstone_demo")
        col = fake_db["doc_vectors"]
        col.search_indexes.append(
            {
                "name": "vector_index",
                "status": "BUILDING",
                "queryable": False,
            }
        )
        clock_ticks = iter([0.0, 1.0, 2.5, 5.0])
        with self.assertRaises(DemoReadinessTimeoutError) as ctx:
            wait_for_vector_index_ready(
                col,
                index_name="vector_index",
                timeout_seconds=3.0,
                poll_interval_seconds=0.01,
                sleep_fn=lambda _: None,
                clock_fn=lambda: next(clock_ticks),
            )
        self.assertIn("BUILDING", str(ctx.exception))
        self.assertIn("mongodb/mongodb-atlas-local", str(ctx.exception))

    def test_worker_database_and_uri_propagation_survives_root_dotenv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = Path(tmpdir) / "TEST_DOC.md"
            md_file.write_text("# Policy\nItems may be returned within 30 days.\n", encoding="utf-8")

            captured_init = {}

            class CapturingIngestor:
                def __init__(self, **kwargs):
                    captured_init.update(kwargs)
                    self.collection = Mock()
                    self.collection.count_documents.return_value = 0
                    self.model = Mock()
                    self.model.encode.return_value = np.zeros((1, 384), dtype=np.float32)
                    self.client = Mock()

                def _parse_file(self, path):
                    return [{"doc_id": path.stem, "section": "Policy", "text": "Items may be returned within 30 days."}]

            with patch.dict(
                os.environ,
                {
                    "MONGODB_URI": "mongodb://demo_user:demo_pass@mongodb-demo:27017/?directConnection=true",
                    "MONGODB_DB_NAME": "capstone_demo",
                    "MONGODB_COLLECTION_NAME": "doc_vectors",
                },
                clear=False,
            ), patch("scripts.ingest_uploaded_document.DocumentIngestor", CapturingIngestor):
                result = ingest_single_document(
                    file_path=md_file,
                    tenant_id="iron_and_oak",
                    overwrite=True,
                    doc_id_override="TEST_DOC",
                    db_name_override="capstone_demo",
                )

            self.assertEqual(result["status"], "success")
            self.assertEqual(captured_init["db_name"], "capstone_demo")
            self.assertEqual(
                captured_init["mongo_uri"],
                "mongodb://demo_user:demo_pass@mongodb-demo:27017/?directConnection=true",
            )


if __name__ == "__main__":
    unittest.main()

