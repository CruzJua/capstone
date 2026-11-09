"""Synthetic leakage-audit checks; no models, external services or frozen data."""

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.evaluation.heldout_leakage import (
    check_heldout_leakage, flatten_json_strings, normalize, overlap, shingles,
)

ROOT = Path(__file__).resolve().parents[1]


class HeldoutLeakageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.train = self.root / "train.csv"
        self.benchmark = self.root / "benchmark.json"
        self.tenant = self.root / "unseen_shop"
        self.tenant.mkdir()
        self.phrase = "Pickup reservations are accepted every weekday until five in the afternoon"
        with self.train.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["business", "question", "answer"])
            writer.writeheader()
            writer.writerow({"business": "other_shop", "question": self.phrase, "answer": "No deliveries"})
        self.benchmark.write_text(json.dumps({
            "metadata": {"held_out_tenant": "unseen_shop"},
            "questions": [{"customer_query": self.phrase,
                           "evidence_json": json.dumps([{"quote": self.phrase}])},
                          {"customer_query": "Completely different inquiry",
                           "evidence_json": [{"quote": "No matching passage"}]}],
        }))
        (self.tenant / "POLICY.md").write_text(self.phrase)

    def test_exact_copies_and_tenant_keys_with_inputs_unchanged(self):
        before = {p: p.read_bytes() for p in (self.train, self.benchmark, self.tenant / "POLICY.md")}
        report = check_heldout_leakage(self.train, self.benchmark, self.tenant)
        self.assertEqual(report["benchmark_questions"]["exact_substring_matches"], 1)
        self.assertEqual(report["benchmark_evidence_quotes"]["exact_substring_matches"], 1)
        self.assertEqual(report["unseen_shop_source_passages"]["exact_substring_matches"], 1)
        self.assertEqual(report["tenant_check"]["rows_with_business_unseen_shop"], 0)
        self.assertEqual(report["tenant_check"]["case_insensitive_unseen_occurrences_in_all_columns"], 0)
        self.assertEqual(report["inputs"]["train_csv"], str(self.train.resolve()))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_ngram_overlap_and_normalization(self):
        grams = shingles("one two three four five six".split())
        result = overlap("ONE two three four five six seven", grams, "not an exact copy")
        self.assertFalse(result["exact_substring"])
        self.assertEqual(result["ngram_overlap"], 0.5)
        self.assertEqual(normalize("Three, DAYS!"), "three days")
        self.assertIsNone(overlap("short", set(), " unrelated ")["ngram_overlap"])

    def test_nested_json_strings(self):
        self.assertEqual(flatten_json_strings({"a": ["first", {"b": "second"}], "n": 1}),
                         ["first", "second"])

    def test_cli_writes_four_space_json_and_refuses_overwrite(self):
        output = self.root / "result.json"
        command = [sys.executable, str(ROOT / "scripts/check_heldout_leakage.py"),
                   "--train-csv", str(self.train), "--benchmark", str(self.benchmark),
                   "--tenant-dir", str(self.tenant), "--output", str(output)]
        subprocess.run(command, check=True, capture_output=True, text=True)
        raw = output.read_text()
        self.assertEqual(raw, json.dumps(json.loads(raw), indent=4, ensure_ascii=False) + "\n")
        retry = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(retry.returncode, 0)
        self.assertIn("Refusing to overwrite", retry.stderr)
        self.assertEqual(output.read_text(), raw)

    def test_cli_refuses_dangling_symlink(self):
        output = self.root / "result.json"
        output.symlink_to(self.root / "missing.json")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/check_heldout_leakage.py"),
                                 "--output", str(output)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to overwrite", result.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
