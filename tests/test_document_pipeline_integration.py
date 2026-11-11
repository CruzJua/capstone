"""Offline integration checks on independent, disposable document fixtures."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from src.documents.integration import document_chunks, render_generation_document
from src.documents.parser import parse_document


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

    def test_structured_corpus_rejects_escape_and_preserves_crlf_source_hash(self):
        from src.documents.integration import load_documents
        self.source.write_bytes(self.text.replace("\n", "\r\n").encode())
        documents = load_documents(self.tenant)
        self.assertEqual(documents[self.source.name].sha256,
                         parse_document(self.source).sha256)
        outside = self.root / "private.txt"
        outside.write_text("Must not enter the tenant corpus")
        (self.tenant / "escape.txt").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "outside"):
            load_documents(self.tenant)

    def test_exact_source_ids_distinguish_extensions(self):
        other = self.tenant / "procedures.json"
        other.write_text('{"rule":"Keep the lid closed"}')
        chunks = document_chunks(parse_document(self.source)) + document_chunks(parse_document(other))
        self.assertEqual({c["doc_id"] for c in chunks}, {"procedures.md", "procedures.json"})

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
