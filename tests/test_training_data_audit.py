"""Meaningful boundary tests for the offline audit, including false-positive traps."""

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.evaluation.training_data_audit import (
    audit_rows, audit_split, audit_training_data, inspect_screening_artifacts, load_documents,
    normalize_text,
)


def ticket(**overrides):
    result = {
        "ticket_id": "tenant-0000_t0", "batch_key": "tenant-0000", "business": "tenant",
        "customer_query": "When is pickup?", "answer": "Pickup is at 5 pm.", "rationale": "Policy states pickup time.",
        "action": "answer", "is_answerable": "True", "confidence": "0.9", "escalation_reason": "none",
        "messages_json": json.dumps([{"role": "customer", "content": "When is pickup?"}]),
        "evidence_json": json.dumps([{"source": "POLICY.md", "quote": "Pickup is at 5 pm."}]),
    }
    result.update(overrides)
    return result


class TrainingDataAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        tenant = self.root / "tenant"
        tenant.mkdir()
        (tenant / "POLICY.md").write_text("# Policy\n\n**Pickup** is at 5 pm.\nWe do not deliver.")
        (tenant / "OTHER.md").write_text("Deposit is $50.")
        (tenant / "faq_support_knowledgebase.json").write_text(json.dumps({
            "faqs": [{"id": "FAQ-1", "answer": "Call the owner.", "escalate_to_human": True}]}))
        # Content in this subdirectory must not be accepted as authoritative source evidence.
        (tenant / "generation_reference").mkdir()
        (tenant / "generation_reference" / "EXCLUDED.md").write_text("Pickup at midnight.")
        self.catalog, _ = load_documents(self.root, {"tenant"})

    def tearDown(self):
        self.temp.cleanup()

    def test_normalization_does_not_erase_numbers_or_negation(self):
        result = audit_rows([ticket()], self.catalog)
        self.assertEqual(result["evidence_quote_counts"], {"presentation_normalized": 1})
        self.assertEqual(result["confirmed_structural_errors"], [])
        self.assertNotEqual(normalize_text("We do not deliver."), normalize_text("We do deliver."))
        self.assertNotEqual(normalize_text("5 pm"), normalize_text("6 pm"))

    def test_wrong_source_match_is_signal_not_semantic_verdict(self):
        row = ticket(evidence_json=json.dumps([{"source": "POLICY.md", "quote": "Deposit is $50."}]))
        result = audit_rows([row], self.catalog)
        self.assertFalse(result["confirmed_structural_errors"])
        self.assertEqual(result["review_signals"][0]["other_documents_with_normalized_quote"], ["OTHER.md"])

    def test_faq_alias_resolves_but_is_disclosed(self):
        row = ticket(evidence_json=json.dumps([{"source": "FAQ-1", "quote": "Call the owner."}]))
        result = audit_rows([row], self.catalog)
        self.assertFalse(result["confirmed_structural_errors"])
        self.assertEqual(result["review_signal_counts"], {"source_id_alias": 1})

    def test_json_object_quote_matches_despite_pretty_printing(self):
        path = self.root / "tenant" / "matrix.json"
        path.write_text(json.dumps({"services": [{"name": "Oven", "minutes": 30}]}, indent=4))
        catalog, _ = load_documents(self.root, {"tenant"})
        row = ticket(evidence_json=json.dumps([{"source": "matrix.json", "quote": '{"name": "Oven", "minutes": 30}'}]))
        self.assertEqual(audit_rows([row], catalog)["review_signals"], [])

    def test_unknown_source_and_excluded_subdirectory_are_errors(self):
        row = ticket(evidence_json=json.dumps([{"source": "EXCLUDED.md", "quote": "Pickup at midnight."}]))
        self.assertEqual(audit_rows([row], self.catalog)["error_counts"], {"unknown_evidence_source": 1})

    def test_human_escalation_with_evidence_is_valid(self):
        row = ticket(action="escalate", escalation_reason="docs_require_human", confidence="0.3")
        self.assertFalse(audit_rows([row], self.catalog)["confirmed_structural_errors"])

    def test_absent_answer_and_invalid_schema_are_errors(self):
        row = ticket(is_answerable="False", confidence="nan", messages_json="{}", evidence_json="{}")
        counts = audit_rows([row], self.catalog)["error_counts"]
        for code in ("unanswerable_answer_target", "invalid_confidence", "invalid_messages_schema", "invalid_evidence_schema"):
            self.assertEqual(counts[code], 1)

    def test_held_out_duplicates_and_batch_leak_are_detected(self):
        first = ticket(business="harbor_view")
        second = ticket(ticket_id="tenant-0000_t1")
        result = audit_rows([first, second], self.catalog)
        self.assertIn("held_out_tenant_in_training", result["error_counts"])
        self.assertTrue(result["duplicate_groups"])
        rows = [ticket(), second]
        manifest = {"train_ticket_ids": [rows[0]["ticket_id"]], "validation_ticket_ids": [rows[1]["ticket_id"]], "data_sha256": "expected"}
        result = audit_split(rows, manifest, "expected")
        self.assertEqual(result["errors"][0]["code"], "batch_overlap")

    def test_actual_manifest_requires_complete_coverage_and_matching_hash(self):
        row = ticket()
        result = audit_split([row], {"train_ticket_ids": [], "validation_ticket_ids": []}, "expected")
        self.assertEqual({x["code"] for x in result["errors"]}, {"tickets_not_in_manifest", "data_hash_mismatch"})

    def test_nonmutating_end_to_end_and_no_inferred_trials(self):
        csv_path = self.root / "input.csv"
        row = ticket()
        with csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=row.keys())
            writer.writeheader()
            writer.writerow(row)
        result = audit_training_data(csv_path, self.root)
        self.assertTrue(result["input_preservation"]["all_unchanged"])
        self.assertEqual(result["audit"]["rows"], 1)
        selection = self.root / "promoted_search_selection.json"
        selection.write_text(json.dumps({"successful_trials": 4, "best_trial_id": "trial_003"}))
        inventory = inspect_screening_artifacts(self.root)
        self.assertEqual(len(inventory["promoted_selections"]), 1)
        self.assertEqual(inventory["individual_search_artifacts"], [])

    def test_cli_rejects_output_inside_input_document_tree(self):
        script = Path(__file__).resolve().parents[1] / "scripts/audit_training_data.py"
        target = self.root / "tenant" / "POLICY.md"
        before = target.read_bytes()
        result = subprocess.run([sys.executable, str(script), "--data-root", str(self.root),
                                 "--output", str(target)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside source", result.stderr)
        self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
