"""Offline repair must preserve provenance and never invent semantic verdicts."""

import json
import tempfile
import unittest
from pathlib import Path

from src.evaluation.adjudication import (
    prepare_retry_plan, repair_judgments, sha256_file, write_new_json, write_repair_bundle,
)
from src.evaluation.judge import (
    JudgeIdentity, JudgeOutputError, JudgeResumeError, build_initial_state,
    check_resume_compatible, load_generation_log, load_rubric, save_state,
)


def verdict(decision="appropriate", evidence=True):
    return {
        "evidence_sufficient": evidence, "decision": decision,
        "correctness": "correct", "groundedness": "fully_grounded",
        "unsupported_claims": [], "citation_support": "supported",
        "invalid_citations": [], "explanation": "The supplied policy states the fee.",
    }


class OfflineRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.generation = self.root / "generation.json"
        records = []
        for ticket, answerable, action in (("a", False, "escalate"), ("b", True, "answer"), ("c", False, "escalate")):
            records.append({
                "ticket_id": ticket, "tenant": "tenant", "category": "policy",
                "is_answerable": answerable, "ground_truth_action": action,
                "customer_query": "What is the fee?", "schema_valid": True,
                "model_action": "answer", "model_answer": "The fee is $5.",
                "model_sources": ["POLICY"], "context": "[Source: POLICY]\nThe fee is $5.",
            })
        self.generation.write_text(json.dumps({
            "model": "llama3.2:3b", "metrics": {"context_mode": "retriever"}, "records": records,
        }))
        self.identity = JudgeIdentity("ollama", "gemma4:latest", "localhost:11434", 0.0, False, 8192, 512)
        self.log = load_generation_log(self.generation)
        self.original = self.root / "original.json"
        state = build_initial_state(self.log, self.identity, load_rubric())
        for entry in state["judgments"][:2]:
            entry.update(status="judged", verdict=verdict(), passed=True, attempts=1)
        state["judgments"][2].update(status="failed", error={"type": "invalid_verdict", "message": "invalid"})
        save_state(self.original, state)

    def test_decision_only_correction_preserves_original_and_exposes_uncertainty(self):
        before = self.original.read_bytes(), self.generation.read_bytes()
        result = repair_judgments([self.original])[0][1]
        changed, unchanged, failed = result["judgments"]
        self.assertEqual(changed["verdict"]["decision"], "inappropriate")
        self.assertFalse(changed["passed"])
        self.assertEqual(changed["repair"]["original_verdict"]["decision"], "appropriate")
        self.assertTrue(changed["repair"]["original_passed"])
        self.assertEqual(changed["verdict"]["evidence_sufficient"], True)
        self.assertIn("not_semantically_revalidated", changed["repair"]["evidence_sufficient_source"])
        self.assertEqual(unchanged["verdict"], verdict())
        self.assertIsNone(failed["verdict"])
        self.assertIsNone(failed["passed"])
        self.assertEqual(result["repair"]["mechanically_corrected_decisions"], 1)
        self.assertEqual(before, (self.original.read_bytes(), self.generation.read_bytes()))
        check_resume_compatible(result, self.log, self.identity, load_rubric())

    def test_unresolved_denominators_and_present_absent_dimensions(self):
        result = repair_judgments([self.original])[0][1]
        overall = result["summary"]["overall"]
        self.assertEqual((overall["records"], overall["judged"], overall["unresolved_records"]), (3, 2, 1))
        self.assertEqual(overall["strict_pass_rate_lower_bound"], 1 / 3)
        self.assertEqual(overall["strict_pass_rate_upper_bound"], 2 / 3)
        absent = result["summary"]["per_split"]["answer_presence"]["answer_absent"]
        self.assertEqual((absent["all_record_denominator"], absent["dimension_denominator"]), (2, 1))
        self.assertEqual(absent["dimensions"]["decision"]["inappropriate"], 1)

    def test_generation_tampering_is_rejected(self):
        payload = json.loads(self.generation.read_text())
        payload["records"][0]["model_answer"] = "tampered"
        self.generation.write_text(json.dumps(payload))
        with self.assertRaises(JudgeResumeError):
            repair_judgments([self.original])

    def test_payload_fingerprint_tampering_is_rejected(self):
        state = json.loads(self.original.read_text())
        state["judgments"][2]["input_fingerprint"] = "0" * 64
        self.original.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            repair_judgments([self.original])

    def test_pass_flag_tampering_is_not_silently_repaired(self):
        state = json.loads(self.original.read_text())
        state["judgments"][1]["passed"] = False
        self.original.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, "pass flag"):
            repair_judgments([self.original])

    def _retry(self):
        plan = prepare_retry_plan([self.original], self.root / "prepared")["plans"][0]
        log = load_generation_log(plan["input_path"])
        self.assertEqual([r["ticket_id"] for r in log.records], ["c"])
        state = build_initial_state(log, self.identity, load_rubric())
        entry = state["judgments"][0]
        entry.update(status="judged", verdict=verdict("inappropriate"), passed=False, attempts=1)
        path = Path(plan["output_path"])
        save_state(path, state)
        return path

    def test_fresh_targeted_retry_merges_only_exact_original_response(self):
        retry = self._retry()
        result = repair_judgments([self.original], [retry])[0][1]
        entry = result["judgments"][2]
        self.assertEqual(entry["status"], "judged")
        self.assertEqual(entry["repair"]["method"], "fresh_independent_judge_retry")
        self.assertEqual(entry["repair"]["original_judgment"]["status"], "failed")
        self.assertEqual(result["repair"]["fresh_semantic_judgments"], 1)
        self.assertEqual(result["summary"]["overall"]["unresolved_records"], 0)

    def test_retry_cannot_change_model_response_even_with_updated_subset_hash(self):
        retry = self._retry()
        state = json.loads(retry.read_text())
        subset_path = Path(state["source"]["path"])
        subset = json.loads(subset_path.read_text())
        subset["records"][0]["model_answer"] = "Changed answer"
        subset_path.write_text(json.dumps(subset))
        # Rebuild a self-consistent subset judgment; ancestry still must fail.
        updated = build_initial_state(load_generation_log(subset_path), self.identity, load_rubric())
        updated["judgments"][0].update(status="judged", verdict=verdict("inappropriate"), passed=False)
        save_state(retry, updated)
        with self.assertRaisesRegex(ValueError, "differs from original"):
            repair_judgments([self.original], [retry])

    def test_retry_identity_change_is_rejected(self):
        retry = self._retry()
        state = json.loads(retry.read_text())
        state["judge"]["num_ctx"] = 16384
        retry.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, "identity differs"):
            repair_judgments([self.original], [retry])

    def test_retry_cannot_add_already_judged_cases(self):
        retry = self._retry()
        state = json.loads(retry.read_text())
        subset_path = Path(state["source"]["path"])
        subset = json.loads(subset_path.read_text())
        subset["records"].append(json.loads(self.generation.read_text())["records"][1])
        subset_path.write_text(json.dumps(subset))
        updated = build_initial_state(load_generation_log(subset_path), self.identity, load_rubric())
        save_state(retry, updated)
        with self.assertRaisesRegex(ValueError, "already judged"):
            repair_judgments([self.original], [retry])

    def test_retry_cannot_claim_a_different_original_judge_artifact(self):
        retry = self._retry()
        state = json.loads(retry.read_text())
        subset_path = Path(state["source"]["path"])
        subset = json.loads(subset_path.read_text())
        subset["retry_provenance"]["original_judged_sha256"] = "0" * 64
        subset_path.write_text(json.dumps(subset))
        updated = build_initial_state(load_generation_log(subset_path), self.identity, load_rubric())
        save_state(retry, updated)
        with self.assertRaisesRegex(ValueError, "does not belong"):
            repair_judgments([self.original], [retry])

    def test_retry_contradiction_is_rejected_not_mechanically_certified(self):
        retry = self._retry()
        state = json.loads(retry.read_text())
        state["judgments"][0].update(verdict=verdict(), passed=True)
        retry.write_text(json.dumps(state))
        with self.assertRaises(JudgeOutputError) as caught:
            repair_judgments([self.original], [retry])
        self.assertIn("decision", str(caught.exception))

    def test_output_is_idempotent_and_originals_are_protected(self):
        output = self.root / "repair"
        first = write_repair_bundle([self.original], output)
        second = write_repair_bundle([self.original], output)
        self.assertEqual(first, second)
        self.assertEqual(first["files"][0]["original_judged_sha256"], sha256_file(self.original))
        with self.assertRaisesRegex(ValueError, "overwrite an input"):
            write_new_json(self.original, {}, {self.original.resolve()})
        with self.assertRaisesRegex(ValueError, "overwrite different"):
            write_new_json(output / "repair_manifest.json", {})

    def test_duplicate_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            repair_judgments([self.original, self.original])


if __name__ == "__main__":
    unittest.main()
