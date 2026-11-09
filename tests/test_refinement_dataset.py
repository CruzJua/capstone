"""Development fixture safety and deterministic split tests, without inference."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.evaluation.generation import load_benchmark
from src.evaluation.refinement_dataset import (
    QUOTAS, TENANTS, prepare_refinement_datasets, save_refinement_datasets,
)

ROOT = Path(__file__).resolve().parents[1]


class RefinementDatasetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "tickets.csv"
        self.rows = []
        for tenant in (*TENANTS, "harbor_view"):
            for stratum in QUOTAS:
                for index in range(14):
                    answerable = stratum != "absent_escalation"
                    self.rows.append({
                        "ticket_id": f"{tenant}-{stratum}-{index}",
                        "batch_key": f"{stratum}-{index}", "business": tenant,
                        "category": "policy", "customer_query": f"{tenant} {stratum} question {index}",
                        "action": "answer" if stratum == "supported_answer" else "escalate",
                        "is_answerable": str(answerable),
                        "escalation_reason": "docs_require_human" if stratum == "human_required"
                        else "none" if answerable else "not_in_docs",
                        "answer": "Original response",
                        "evidence_json": json.dumps([{"source": "POLICY.md", "quote": "Original quote"}]
                                                    if answerable else []),
                    })
        self.write_source()

    def write_source(self):
        with self.source.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(self.rows)

    def test_balance_exclusion_disjoint_groups_and_source_exactness(self):
        before = self.source.read_bytes()
        payloads = prepare_refinement_datasets(self.source)
        original = {r["ticket_id"]: r for r in self.rows}
        for payload in payloads.values():
            metadata = payload["metadata"]
            self.assertNotIn("held_out_tenant", metadata)
            self.assertEqual(metadata["total_questions"], 40)
            self.assertEqual(metadata["stratum_counts"],
                             {"supported_answer": 20, "absent_escalation": 12, "human_required": 8})
            self.assertEqual(metadata["answer_present_count"], 28)
            self.assertEqual(set(metadata["tenant_counts"].values()), {10})
            for question in payload["questions"]:
                self.assertIn(question["tenant"], TENANTS)
                row = original[question["ticket_id"]]
                self.assertEqual(question["customer_query"], row["customer_query"])
                self.assertEqual(question["ground_truth_answer"], row["answer"])
                self.assertEqual(question["evidence_json"], json.loads(row["evidence_json"]))
        for fields in (("ticket_id",), ("tenant", "batch_key"), ("customer_query",)):
            a, b = [{tuple(q[f] for f in fields) for q in payloads[s]["questions"]}
                    for s in ("dev", "validation")]
            self.assertFalse(a & b)
        self.assertEqual(before, self.source.read_bytes())

    def test_reproducible_and_seed_changes_selection(self):
        baseline = prepare_refinement_datasets(self.source)
        self.assertEqual(baseline, prepare_refinement_datasets(self.source))
        self.assertNotEqual(baseline["dev"]["questions"],
                            prepare_refinement_datasets(self.source, seed=391)["dev"]["questions"])

    def test_load_benchmark_compatibility(self):
        paths = [self.root / "dev.json", self.root / "validation.json"]
        payloads = prepare_refinement_datasets(self.source)
        save_refinement_datasets(payloads, *paths, self.source)
        for path in paths:
            metadata, questions = load_benchmark(path)
            self.assertEqual(metadata["total_questions"], len(questions))
            self.assertEqual(len(questions), 40)

    def test_refuses_overwrite_and_prechecks_both_paths(self):
        dev, validation = self.root / "dev.json", self.root / "validation.json"
        validation.write_text("existing")
        with self.assertRaises(FileExistsError):
            save_refinement_datasets(prepare_refinement_datasets(self.source), dev, validation, self.source)
        self.assertFalse(dev.exists())
        self.assertEqual(validation.read_text(), "existing")

    def test_refuses_protected_paths_and_collisions(self):
        payloads = prepare_refinement_datasets(self.source)
        for unsafe in (self.source, ROOT / "data/cleaned/unsafe.json",
                       self.root / "held_out_benchmark.json"):
            with self.subTest(path=unsafe), self.assertRaises(ValueError):
                save_refinement_datasets(payloads, unsafe, self.root / "val.json", self.source)
        with self.assertRaises(ValueError):
            save_refinement_datasets(payloads, self.root / "same.json", self.root / "same.json", self.source)

    def test_refuses_duplicate_ticket_ids(self):
        self.rows.append(dict(self.rows[0]))
        self.write_source()
        with self.assertRaisesRegex(ValueError, "Duplicate ticket"):
            prepare_refinement_datasets(self.source)

    def test_refuses_insufficient_groups(self):
        self.rows = [r for r in self.rows if not (r["business"] == TENANTS[0]
                     and r["ticket_id"].startswith(f"{TENANTS[0]}-supported_answer-"))]
        self.write_source()
        with self.assertRaisesRegex(ValueError, "Insufficient disjoint"):
            prepare_refinement_datasets(self.source)

    def test_refuses_malformed_evidence(self):
        for row in self.rows:
            if row["is_answerable"] == "True":
                row["evidence_json"] = '[{"source": "POLICY.md"}]'
        self.write_source()
        with self.assertRaisesRegex(ValueError, "Invalid evidence"):
            prepare_refinement_datasets(self.source)

    def test_real_fixtures_source_hash_and_disjointness(self):
        source = ROOT / "data/cleaned/train_tickets.csv"
        payloads = prepare_refinement_datasets(source)
        for split in ("dev", "validation"):
            path = ROOT / "data/evaluation" / f"refinement_{split}.json"
            if path.exists():
                self.assertEqual(json.loads(path.read_text()), payloads[split])


if __name__ == "__main__":
    unittest.main()
