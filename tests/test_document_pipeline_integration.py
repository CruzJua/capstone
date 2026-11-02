"""Offline integration checks on independent, disposable document fixtures."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.documents.integration import document_chunks, render_generation_document
from src.documents.parser import parse_document
from src.documents.quality import screen_records
from scripts.business_data_generator import Business


ROOT = Path(__file__).resolve().parents[1]


class SharedPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tenant = self.root / "unseen_organization"
        self.tenant.mkdir()
        self.source = self.tenant / "procedures.md"
        self.text = ("# Handling\n\nApplies only to sealed items.\n\n"
                     "| Action | Do Not |\n| --- | --- |\n"
                     "| Wait 7 minutes | Remove the lid early |\n")
        self.source.write_text(self.text)

    def test_generation_and_retrieval_share_atomic_text_and_trace(self):
        document = parse_document(self.source)
        rendered = render_generation_document(document)
        chunks = document_chunks(document)
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertIn(chunk["text"], rendered)
            self.assertEqual(chunk["source_sha256"], document.sha256)
            self.assertEqual(chunk["source_id"], "procedures.md")
        table = next(chunk for chunk in chunks if "| Action |" in chunk["text"])
        self.assertIn("Do Not", table["text"])
        self.assertIn("7 minutes", table["text"])
        self.assertIn("only to sealed items", table["text"])

    def test_generator_default_preserves_legacy_but_structured_changes_fingerprint(self):
        legacy = Business("unseen_organization", self.tenant, False)
        shared = Business("unseen_organization", self.tenant, False, "structured")
        self.assertIn(self.text.strip(), legacy.corpus_text())
        self.assertNotIn("Document SHA256:", legacy.corpus_text())
        self.assertIn("Document SHA256:", shared.corpus_text())
        self.assertIn("Do Not", shared.corpus_text())
        self.assertNotEqual(legacy.fingerprint("same-model"), shared.fingerprint("same-model"))
        self.assertIn("Shared structured-document rules", shared.system_prompt())

    def test_ingestor_structured_parse_requires_no_network_or_model(self):
        from src.rag.ingestor import RAGDocumentIngestor
        ingestor = object.__new__(RAGDocumentIngestor)
        ingestor.document_parser, ingestor.chunk_size = "structured", 500
        chunks = ingestor._parse_file(self.source, "nested/procedures.md")
        self.assertTrue(all(c["doc_id"] == "nested/procedures.md" for c in chunks))
        self.assertTrue(all("source_locator" in c for c in chunks))
        ingestor.chunk_size = 1
        with self.assertRaisesRegex(ValueError, "rather than truncate|not truncated"):
            ingestor._parse_file(self.source)

    def test_structured_ingestion_stores_provenance_with_mocked_embedding_and_db(self):
        from src.rag.ingestor import RAGDocumentIngestor
        ingestor = object.__new__(RAGDocumentIngestor)
        ingestor.document_parser, ingestor.chunk_size = "structured", 500
        vector = Mock()
        vector.tolist.return_value = [0.1, 0.2]
        ingestor.model = Mock()
        ingestor.model.max_seq_length = 500
        ingestor.model.tokenizer = lambda text, **kw: {"input_ids": text.split()}
        ingestor.model.encode.side_effect = lambda texts, **kw: [vector] * len(texts)
        ingestor.collection = Mock()
        count = ingestor.ingest_tenant_directory("arbitrary_tenant", self.tenant)
        rows = ingestor.collection.insert_many.call_args.args[0]
        self.assertEqual(count, len(rows))
        self.assertTrue(all(row["tenant_id"] == "arbitrary_tenant" and row["source_sha256"] for row in rows))
        self.assertTrue(all(row["parser_version"] == "structured-v1" for row in rows))

    def test_report_and_quarantine_never_relabel_or_rewrite(self):
        valid = {"ticket_id": "not_a_benchmark_case", "business": self.tenant.name,
                 "action": "answer", "evidence_json": json.dumps([
                     {"source": self.source.name, "quote": "Applies only to sealed items."}])}
        invalid = {**valid, "ticket_id": "another_case", "evidence_json": json.dumps([
            {"source": "missing.md", "quote": "Applies only to sealed items."}])}
        original = json.dumps([valid, invalid], sort_keys=True)
        kept, report = screen_records([valid, invalid], self.root, "report")
        self.assertEqual(kept, [valid, invalid])
        self.assertEqual(report["rows_requiring_review"], 1)
        kept, report = screen_records([valid, invalid], self.root, "quarantine")
        self.assertEqual(kept, [valid])
        self.assertFalse(report["semantic_correctness_assessed"])
        self.assertEqual(json.dumps([valid, invalid], sort_keys=True), original)

    def test_structured_ingestion_relative_and_symlink_roots_share_source_policy(self):
        from src.rag.ingestor import RAGDocumentIngestor
        (self.tenant / "generation_reference_policy.md").write_text("# Policy\n\nKeep this eligible policy.")
        excluded = self.tenant / "generation_reference"
        excluded.mkdir()
        (excluded / "notes.md").write_text("Private generation notes")
        alias = self.root / "alias"
        alias.symlink_to(self.tenant, target_is_directory=True)
        for directory in (Path(os.path.relpath(self.tenant)), alias):
            with self.subTest(directory=directory):
                ingestor = object.__new__(RAGDocumentIngestor)
                ingestor.document_parser, ingestor.chunk_size = "structured", 500
                ingestor.model = Mock()
                ingestor.model.max_seq_length = 500
                ingestor.model.tokenizer = lambda text, **kw: {"input_ids": text.split()}
                vector = Mock()
                vector.tolist.return_value = [0.1]
                ingestor.model.encode.side_effect = lambda texts, **kw: [vector] * len(texts)
                ingestor.collection = Mock()
                ingestor.ingest_tenant_directory("fixture", directory)
                rows = ingestor.collection.insert_many.call_args.args[0]
                self.assertEqual({row["source_id"] for row in rows},
                                 {"procedures.md", "generation_reference_policy.md"})

    def test_answer_without_evidence_and_path_escape_are_quarantined(self):
        for row in ({"business": self.tenant.name, "action": "answer", "evidence_json": "[]"},
                    {"business": "../outside", "evidence_json": "[]"}):
            kept, report = screen_records([row], self.root, "quarantine")
            self.assertEqual(kept, [])
            self.assertEqual(report["rows_requiring_review"], 1)

    def test_inspection_cli_is_offline_and_execution_is_explicit(self):
        command = [sys.executable, str(ROOT / "scripts/ingest_rag_docs.py")]
        result = subprocess.run(command + ["--document-parser", "structured", "--inspect-only",
                                "--tenant-dir", f"unseen_organization={self.tenant}"],
                                capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(report["database_writes"], 0)
        self.assertEqual(report["embedding_jobs"], 0)
        self.assertTrue(report["tenants"]["unseen_organization"])
        denied = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("--execute", denied.stderr)

    def test_cleaner_audit_only_writes_report_and_never_dataset(self):
        import scripts.business_data_cleaner as cleaner
        import pandas as pd
        frame = pd.DataFrame([{"ticket_id": "fixture", "business": self.tenant.name,
                               "action": "escalate", "evidence_json": "[]"}])
        report = self.root / "report.json"
        output = self.root / "must_not_exist.csv"
        arguments = ["cleaner", "--provenance-mode", "report", "--provenance-audit-only",
                     "--data-root", str(self.tenant), "--provenance-report", str(report),
                     "--output-csv", str(output)]
        with patch.object(sys, "argv", arguments), patch.object(cleaner, "load_results_to_dataframe", return_value=frame), \
                patch.object(cleaner, "export_dataset") as export, contextlib.redirect_stdout(io.StringIO()):
            cleaner.main()
        export.assert_not_called()
        self.assertTrue(report.is_file())
        self.assertFalse(output.exists())

    def test_structured_corpus_rejects_escape_and_preserves_crlf_source_hash(self):
        from src.documents.integration import load_documents
        self.source.write_bytes(self.text.replace("\n", "\r\n").encode())
        business = Business("unseen_organization", self.tenant, False, "structured")
        self.assertEqual(business.parsed_docs[self.source.name].sha256,
                         parse_document(self.source).sha256)
        outside = self.root / "private.txt"
        outside.write_text("Must not enter the tenant corpus")
        (self.tenant / "escape.txt").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "outside"):
            load_documents(self.tenant)
        with self.assertRaisesRegex(ValueError, "outside"):
            Business("unseen_organization", self.tenant, False, "structured")

    def test_exact_source_ids_distinguish_extensions(self):
        other = self.tenant / "procedures.json"
        other.write_text('{"rule":"Keep the lid closed"}')
        chunks = document_chunks(parse_document(self.source)) + document_chunks(parse_document(other))
        self.assertEqual({c["doc_id"] for c in chunks}, {"procedures.md", "procedures.json"})

    def test_csv_false_label_does_not_bypass_target_schema(self):
        row = {"business": self.tenant.name, "action": "answer", "is_answerable": "False",
               "escalation_reason": "none", "evidence_json": json.dumps([
                   {"source": self.source.name, "quote": "Applies only to sealed items."}])}
        kept, report = screen_records([row], self.root, "quarantine")
        self.assertEqual(kept, [])
        self.assertIn("answer_target_conflicts_with_escalation_label",
                      report["rows"][0]["assessment"]["target_schema_findings"])

    def test_embedding_token_budget_refuses_before_encode_or_database_write(self):
        from src.rag.ingestor import RAGDocumentIngestor
        ingestor = object.__new__(RAGDocumentIngestor)
        ingestor.document_parser, ingestor.chunk_size = "structured", 500
        ingestor.model = Mock()
        ingestor.model.max_seq_length = 4
        ingestor.model.tokenizer = lambda text, **kw: {"input_ids": [0] * 20}
        ingestor.collection = Mock()
        with self.assertRaisesRegex(ValueError, "embedding token limit"):
            ingestor.ingest_tenant_directory("arbitrary", self.tenant)
        ingestor.model.encode.assert_not_called()
        ingestor.collection.delete_many.assert_not_called()
        ingestor.collection.insert_many.assert_not_called()


if __name__ == "__main__":
    unittest.main()
