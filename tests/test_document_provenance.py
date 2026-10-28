"""Provenance tests use unseen source names and no tenant-specific rules."""

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.documents.parser import parse_document_text
from src.documents.integration import context_blocks
from src.documents.provenance import (
    EvidenceProvenanceValidator, audit_evidence_csv, load_tenant_corpus,
    normalize_structural, validate_evidence,
)


def document(source, text):
    return parse_document_text(source, text, Path(source).suffix)


class EvidenceProvenanceTests(unittest.TestCase):
    def test_exact_match_proves_source_only_and_retains_locator(self):
        text = "# Unseen telescope policy\n\nThe deposit is $73.25 and is not refundable after 8 hours.\n"
        corpus = {"mars-policy.md": document("mars-policy.md", text)}
        report = validate_evidence([{"source": "mars-policy.md", "quote": "not refundable after 8 hours"}], corpus)
        item = report["items"][0]
        self.assertTrue(report["accepted"])
        self.assertFalse(report["semantic_correctness_assessed"])
        self.assertEqual(item["status"], "verified_exact")
        match = item["matches"][0]
        self.assertEqual(match["source_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(text[match["locator"]["start"]:match["locator"]["end"]], item["quote"])

    def test_conservative_formatting_normalization_records_trace(self):
        doc = document("orbit.md", "The pressure must **not** exceed\n  19 kPa.")
        item = validate_evidence([{"source": "orbit.md", "quote": "The pressure must not exceed 19 kPa."}], {"orbit.md": doc})["items"][0]
        self.assertEqual(item["status"], "verified_structural")
        self.assertTrue(item["matches"][0]["transform_trace"])
        self.assertEqual(normalize_structural("**not** 19 kPa, only if dry").text, "not 19 kPa, only if dry")

    def test_negation_numbers_units_and_qualifiers_are_not_normalized_away(self):
        doc = document("orbital.md", "Do not exceed 19 kPa, only if dry.")
        validator = EvidenceProvenanceValidator({"orbital.md": doc})
        for quote in ("Do exceed 19 kPa, only if dry.", "Do not exceed 18 kPa, only if dry.",
                      "Do not exceed 19 Pa, only if dry.", "Do not exceed 19 kPa, if dry."):
            with self.subTest(quote=quote):
                report = validator.validate_evidence([{"source": "orbital.md", "quote": quote}])
                self.assertEqual(report["items"][0]["status"], "unmatched")
                self.assertFalse(report["accepted"])
                self.assertEqual(report["summary"]["confirmed_provenance_failures"], 0)

    def test_wrong_claimed_source_is_not_automatically_relabelled(self):
        corpus = {"manual.md": document("manual.md", "The limit is 19 kPa."),
                  "questions.md": document("questions.md", "Appointments start at noon.")}
        evidence = [{"source": "questions.md", "quote": "The limit is 19 kPa."}]
        before = json.dumps(evidence)
        report = validate_evidence(evidence, corpus)
        item = report["items"][0]
        self.assertEqual(item["status"], "source_mismatch")
        self.assertEqual(report["summary"]["confirmed_provenance_failures"], 1)
        self.assertEqual(item["claimed_source"], "questions.md")
        self.assertEqual(item["matches"][0]["source"], "manual.md")
        self.assertEqual(before, json.dumps(evidence))
        self.assertTrue(report["quarantine_recommended"])

    def test_unknown_source_and_no_filename_aliases(self):
        doc = document("nested/policy.md", "The deposit is $73.")
        item = validate_evidence([{"source": "policy.md", "quote": "The deposit is $73."}], {doc.source_id: doc})["items"][0]
        self.assertEqual(item["status"], "unknown_source")
        self.assertFalse(item["provenance_verified"])

    def test_duplicate_passages_are_ambiguous_not_semantically_wrong(self):
        text = "The limit is 19 kPa.\n\nThe limit is 19 kPa."
        doc = document("two.md", text)
        report = validate_evidence([{"source": "two.md", "quote": "The limit is 19 kPa."}], {"two.md": doc})
        item = report["items"][0]
        self.assertEqual(item["status"], "ambiguous_match")
        self.assertTrue(item["provenance_verified"])
        self.assertEqual(len(item["matches"]), 2)
        self.assertEqual(report["summary"]["confirmed_provenance_failures"], 0)

    def test_table_fragment_missing_negative_header_is_flagged(self):
        text = "# Spacecraft\n\n## Do Not Apply\n\n| Surface | Do Not Use |\n| --- | --- |\n| Lens | ammonia |\n"
        doc = document("unseen-safety.md", text)
        report = validate_evidence([{"source": doc.source_id, "quote": "Lens | ammonia"}], {doc.source_id: doc})
        item = report["items"][0]
        codes = {finding["code"] for finding in item["findings"]}
        self.assertTrue(item["provenance_verified"])
        self.assertEqual(codes, {"table_header_missing", "negative_context_missing"})
        self.assertFalse(report["accepted"])
        suggestion = item["suggested_blocks"][0]
        self.assertIn("Do Not Apply", suggestion["text"])
        self.assertIn("Do Not Use", suggestion["text"])
        self.assertIn("start", suggestion["locator"])
        self.assertEqual(report["summary"]["confirmed_provenance_failures"], 0)

    def test_complete_table_with_negative_context_is_accepted(self):
        text = "## Do Not Apply\n\n| Surface | Do Not Use |\n| --- | --- |\n| Lens | ammonia |\n"
        doc = document("complete.md", text)
        self.assertTrue(validate_evidence([{"source": doc.source_id, "quote": text}], {doc.source_id: doc})["accepted"])

    def test_pretable_paragraph_does_not_inherit_negative_column_header(self):
        text = "# Handling\n\nApplies only to sealed items.\n\n| Action | Do Not |\n| --- | --- |\n| Store | heat |\n"
        doc = document("handling.md", text)
        report = validate_evidence([{"source": doc.source_id, "quote": "Applies only to sealed items."}], {doc.source_id: doc})
        self.assertTrue(report["accepted"])
        self.assertFalse(report["requires_review"])
        self.assertEqual(report["items"][0]["findings"], [])

    def test_contextual_row_projection_has_explicit_trace_and_original_fragments(self):
        rows = "".join(f"| Part {index} | liquid solvent number {index} |\n" for index in range(100))
        text = "## Do Not Apply\n\n| Part | Do Not Use |\n| --- | --- |\n" + rows
        doc = document("large-table.md", text)
        row = next(block for block in context_blocks(doc, 500)
                   if block.kind == "table_row" and block.metadata["row_index"] == 4)
        report = validate_evidence([{"source": doc.source_id, "quote": row.text}], {doc.source_id: doc})
        item = report["items"][0]
        self.assertTrue(report["accepted"])
        self.assertEqual(len(item["matches"]), 1)
        match = item["matches"][0]
        self.assertEqual(match["match_kind"], "parsed_block_span")
        self.assertIn("contextual_table_row_projection_500_word_budget", match["transform_trace"])
        self.assertEqual(match["blocks"][0]["source_fragments"], row.metadata["source_fragments"])
        self.assertEqual(match["locator"], row.locator)

    def test_unavailable_oversized_row_projection_does_not_disable_raw_matching(self):
        text = "## Details\n\n" + "word " * 550 + "\n\n| Part | Rule |\n| --- | --- |\n| item | dry |\n"
        doc = document("oversize.md", text)
        report = validate_evidence([{"source": doc.source_id, "quote": "word word word word"}], {doc.source_id: doc})
        self.assertTrue(report["items"][0]["provenance_verified"])
        self.assertTrue(report["projection_diagnostics"])
        self.assertTrue(report["projection_diagnostics"][0]["raw_and_full_block_validation_available"])

    def test_decoded_json_string_provenance_preserves_pointer_and_quotes(self):
        raw = json.dumps({"a/b~c": [{"answer": 'Say "no" to 19 kPa.'}]})
        doc = document("answer.json", raw)
        item = validate_evidence([{"source": doc.source_id, "quote": 'Say "no" to 19 kPa.'}], {doc.source_id: doc})["items"][0]
        match = item["matches"][0]
        self.assertEqual(match["match_kind"], "decoded_json_value")
        self.assertEqual(match["locator"]["pointer"], "/a~1b~0c/0/answer")
        self.assertEqual(len(item["matches"]), 1)

    def test_canonical_block_span_is_explicitly_distinguished_from_raw_quote(self):
        doc = document("records.json", '{"global_rule":"No fees","items":[{"id":"x","amount":2}]}')
        block = doc.blocks[0]
        self.assertNotIn(block.text, doc.raw_text)
        item = validate_evidence([{"source": doc.source_id, "quote": block.text}], {doc.source_id: doc})["items"][0]
        self.assertEqual(item["matches"][0]["match_kind"], "parsed_block_span")
        self.assertEqual(item["matches"][0]["locator"], block.locator)
        self.assertIn("shared_document_parser_canonical_block_projection", item["matches"][0]["transform_trace"])

    def test_evidence_schema_errors_are_explicit(self):
        for bad in (None, {}, [None], [{"source": "x"}], [{"source": "x", "quote": " "}],
                    [{"source": 2, "quote": "hello"}], [{"source": "x", "quote": "hello", "extra": 3}]):
            with self.subTest(bad=bad):
                report = validate_evidence(bad, {})
                self.assertFalse(report["accepted"])
                self.assertEqual(report["summary"]["schema_errors"], 1)
        self.assertTrue(validate_evidence([], {})["accepted"])


class ReadOnlyCorpusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_recursive_exact_source_ids_exclude_references_and_hidden_files(self):
        for relative in ("a/policy.md", "b/policy.md", "generation_reference/notes.md", ".hidden/secret.md"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Any tenant's independent policy.")
        corpus = load_tenant_corpus(self.root)
        self.assertEqual(set(corpus), {"a/policy.md", "b/policy.md"})

    def test_symlink_escape_is_rejected(self):
        corpus_dir = self.root / "tenant"
        corpus_dir.mkdir()
        outside = self.root / "other.md"
        outside.write_text("Private other tenant.")
        (corpus_dir / "escape.md").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "outside its source"):
            load_tenant_corpus(corpus_dir)

    def test_shared_loader_preserves_crlf_bytes_and_source_hash(self):
        raw = b"# Safety\r\n\r\nDo not heat above 29 C.\r\n"
        (self.root / "windows.md").write_bytes(raw)
        doc = load_tenant_corpus(self.root)["windows.md"]
        self.assertEqual(doc.raw_text.encode(), raw)
        self.assertEqual(doc.sha256, hashlib.sha256(raw).hexdigest())

    def test_csv_audit_is_read_only_and_separates_flags_from_failures(self):
        data = self.root / "data"
        tenant = data / "unseen_tenant"
        tenant.mkdir(parents=True)
        (tenant / "rules.md").write_text("The allowed window is 3 hours.")
        (tenant / "other.md").write_text("The deposit is $16.")
        path = self.root / "original.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["ticket_id", "business", "evidence_json"])
            writer.writeheader()
            for index, source, quote in ((0, "rules.md", "The allowed window is 3 hours."),
                                         (1, "other.md", "The allowed window is 3 hours."),
                                         (2, "rules.md", "It takes approximately three hours.")):
                writer.writerow({"ticket_id": str(index), "business": "unseen_tenant",
                                 "evidence_json": json.dumps([{"source": source, "quote": quote}])})
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        report = audit_evidence_csv(path, data)
        self.assertEqual(report["summary"]["rows"], 3)
        self.assertEqual(report["summary"]["confirmed_provenance_failures"], 1)
        self.assertEqual(report["summary"]["review_flags"], 1)
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual(report["dataset_writes"], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_rejects_wrong_csv_schema_and_benchmark_input(self):
        path = self.root / "bad.csv"
        path.write_text("answer\nno\n")
        with self.assertRaisesRegex(ValueError, "CSV must contain"):
            audit_evidence_csv(path, self.root)
        with self.assertRaisesRegex(ValueError, "not a benchmark"):
            audit_evidence_csv(self.root / "benchmark.json", self.root)

    def test_duplicate_evidence_json_keys_are_schema_errors(self):
        tenant = self.root / "unseen"
        tenant.mkdir()
        (tenant / "rules.md").write_text("The limit is 7.")
        path = self.root / "source.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["ticket_id", "business", "evidence_json"])
            writer.writeheader()
            writer.writerow({"ticket_id": "x", "business": "unseen", "evidence_json":
                             '[{"source":"wrong.md","source":"rules.md","quote":"The limit is 7."}]'})
        report = audit_evidence_csv(path, self.root)
        self.assertEqual(report["summary"]["schema_errors"], 1)
        self.assertEqual(report["summary"]["provenance_verified_items"], 0)


if __name__ == "__main__":
    unittest.main()
