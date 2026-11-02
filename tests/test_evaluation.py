"""Offline regression checks for held-out preparation and generation scoring."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from src.evaluation.dataset import (
    load_and_filter_data, sample_balanced_benchmark, save_artifacts,
)
from src.evaluation.generation import (
    build_ground_truth_context, calculate_metrics, load_benchmark,
    run_evaluation_loop, save_evaluation_log,
)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = [
            {
                "ticket_id": f"{tenant}-{index}", "business": tenant,
                "category": "policy", "customer_query": f"Question {index}?",
                "action": "answer" if index == 0 else "escalate",
                "is_answerable": index < 2,
                "escalation_reason": "none" if index == 0 else "docs_require_human" if index == 1 else "not_in_docs",
                "answer": "Reference answer",
                "evidence_json": json.dumps([{"source": "policy.md", "quote": "Ask a human."}]) if index < 2 else "[]",
            }
            for tenant in ("held_out", "training") for index in range(4)
        ]
        self.dataset = self.root / "tickets.csv"
        pd.DataFrame(self.rows).to_csv(self.dataset, index=False)

    def prepare(self):
        pools = load_and_filter_data(self.dataset, "held_out")
        return sample_balanced_benchmark(*pools[:2], 2, 42), pools[2]

    def test_balanced_reproducible_split_preserves_human_escalations(self):
        payload, training = self.prepare()
        repeated, _ = self.prepare()
        self.assertEqual(payload["questions"], repeated["questions"])
        self.assertEqual(payload["metadata"]["total_questions"], 4)
        self.assertEqual(sum(q["is_answerable"] for q in payload["questions"]), 2)
        self.assertEqual(set(training.business), {"training"})
        by_id = {q["ticket_id"]: q for q in payload["questions"]}
        self.assertEqual(by_id["held_out-1"]["ground_truth_action"], "escalate")
        self.assertEqual(by_id["held_out-0"]["cited_sources"], ["policy.md"])
        self.assertEqual(by_id["held_out-1"]["cited_sources"], [])

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            load_and_filter_data(self.dataset, "missing")
        pools = load_and_filter_data(self.dataset, "held_out")
        for size in (0, -1, 3):
            with self.assertRaises(ValueError):
                sample_balanced_benchmark(*pools[:2], size, 42)
        frame = pd.DataFrame(self.rows).astype({"is_answerable": object})
        frame.loc[0, "is_answerable"] = "unknown"
        frame.to_csv(self.dataset, index=False)
        with self.assertRaisesRegex(ValueError, "Invalid is_answerable"):
            load_and_filter_data(self.dataset, "held_out")

    def test_artifact_round_trip_and_leakage_guard(self):
        payload, training = self.prepare()
        benchmark_path, train_path = self.root / "eval/benchmark.json", self.root / "train/tickets.csv"
        with contextlib.redirect_stdout(io.StringIO()):
            save_artifacts(payload, training, benchmark_path, train_path)
        metadata, questions = load_benchmark(benchmark_path, limit=2)
        self.assertEqual(metadata, payload["metadata"])
        self.assertEqual(len(questions), 2)
        self.assertEqual(len(pd.read_csv(train_path)), 4)
        with self.assertRaises(ValueError):
            save_artifacts(payload, pd.DataFrame(self.rows), benchmark_path, train_path)
        with self.assertRaises(ValueError):
            load_benchmark(benchmark_path, limit=-1)
        payload["questions"][0]["is_answerable"] = "False"
        benchmark_path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "boolean"):
            load_benchmark(benchmark_path)

    def test_context_groups_quotes_and_handles_bad_evidence(self):
        evidence = [
            {"source": "policy.md", "quote": "One"},
            {"source": "faq.json", "quote": "Two"},
            {"source": "policy.md", "quote": "Three"},
            None, {"source": "bad", "quote": None},
        ]
        context = build_ground_truth_context(json.dumps(evidence))
        self.assertEqual(context.count('<context source="policy.md">'), 1)
        self.assertIn("One\nThree\n</context>", context)
        self.assertEqual(context, build_ground_truth_context(evidence))
        for invalid in (None, "", "invalid json", "null", "{}", 12):
            self.assertEqual(build_ground_truth_context(invalid), "")

    def test_confusion_matrix_and_metrics(self):
        def question(index, expected, present):
            return {
                "ticket_id": str(index), "tenant": "held_out", "customer_query": "Question?",
                "ground_truth_action": expected, "is_answerable": present, "evidence_json": "[]",
            }

        questions = [question(0, "answer", True), question(1, "answer", True),
                     question(2, "escalate", False), question(3, "escalate", False)]
        client = Mock()
        timing = {"latency_ms": 20, "tokens_per_second": 5, "eval_tokens": 10}
        client.generate_raw.side_effect = [
            (json.dumps({"action": action, "answer": "Text", "confidence": 0.8, "cited_sources": []}), timing)
            for action in ("answer", "escalate", "escalate", "answer")
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            counts, records, latencies, speeds = run_evaluation_loop(client, None, questions)
        self.assertEqual([counts[key] for key in ("TP", "FP", "FN", "TN")], [1, 1, 1, 1])
        metrics = calculate_metrics(counts, latencies, speeds)
        for key in ("hallucination_rate", "escalation_precision", "escalation_recall", "escalation_f1", "action_accuracy"):
            self.assertEqual(metrics[key], 0.5)
        self.assertEqual(metrics["schema_validity_rate"], 1)
        self.assertEqual(metrics["avg_latency_ms"], 20)
        self.assertEqual(metrics["avg_tokens_per_second"], 5)
        with contextlib.redirect_stdout(io.StringIO()):
            path = save_evaluation_log(metrics, records, "org/model:tag", str(self.root / "logs/run.json"))
        self.assertEqual(json.loads(path.read_text())["records"], records)

    def test_invalid_responses_do_not_earn_decision_credit(self):
        questions = [{"ticket_id": str(i), "tenant": "held_out", "customer_query": "?",
                      "ground_truth_action": "escalate", "is_answerable": False} for i in range(3)]
        client = Mock()
        client.generate_raw.side_effect = [(raw, {}) for raw in (
            "not JSON", '{"action":"escalate","confidence":2,"answer":"No"}',
            '{"action":"answer","confidence":2,"answer":"Invented"}',
        )]
        with contextlib.redirect_stdout(io.StringIO()):
            counts, records, latencies, speeds = run_evaluation_loop(client, None, questions)
        self.assertEqual(counts["schema_invalid"], 3)
        self.assertEqual(counts["TP"], 0)
        self.assertEqual(counts["FN"], 3)
        self.assertEqual(counts["absent_hallucinated"], 1)
        self.assertTrue(all(record["error"] for record in records))
        self.assertEqual(calculate_metrics(counts, latencies, speeds)["action_accuracy"], 0)

    def test_retrieval_uses_tenant_and_rejects_leakage(self):
        question = {"ticket_id": "test", "tenant": "held_out", "customer_query": "?",
                    "ground_truth_action": "escalate", "is_answerable": False}
        client, retriever = Mock(), Mock()
        retriever.retrieve.return_value = [{"tenant_id": "held_out", "text": "context"}]
        retriever.format_context.return_value = "formatted context"
        client.generate_raw.return_value = ('{"action":"escalate","answer":"No","confidence":0.2}', {})
        with contextlib.redirect_stdout(io.StringIO()):
            run_evaluation_loop(client, retriever, [question], use_retriever=True)
        retriever.retrieve.assert_called_once_with(query="?", tenant_id="held_out")
        client.generate_raw.assert_called_once_with("?", "formatted context")
        retriever.retrieve.return_value = [{"tenant_id": "training"}]
        with self.assertRaisesRegex(RuntimeError, "Cross-tenant"):
            run_evaluation_loop(client, retriever, [question], use_retriever=True)

    def test_empty_metrics_and_service_failure(self):
        metrics = calculate_metrics({}, [], [])
        self.assertEqual(metrics["action_accuracy"], 0)
        self.assertEqual(metrics["avg_latency_ms"], 0)
        client = Mock()
        client.generate_raw.side_effect = ConnectionError("Ollama unavailable")
        question = {"customer_query": "?", "ground_truth_action": "answer"}
        with self.assertRaises(ConnectionError):
            run_evaluation_loop(client, None, [question])

    def test_cli_orchestration_saves_mode_and_metadata(self):
        from scripts import evaluate_generation

        payload, _ = self.prepare()
        benchmark_path, log_path = self.root / "benchmark.json", self.root / "run.json"
        benchmark_path.write_text(json.dumps(payload))
        client = Mock(model="test-model")
        client.generate_raw.return_value = ('{"action":"escalate","answer":"No","confidence":0.2}', {})
        with patch("sys.argv", ["evaluate_generation.py", "--benchmark-file", str(benchmark_path),
                                "--limit", "2", "--output-log", str(log_path)]), \
                patch.object(evaluate_generation, "initialize_services", return_value=(client, None)), \
                contextlib.redirect_stdout(io.StringIO()):
            evaluate_generation.main()
        log = json.loads(log_path.read_text())
        self.assertEqual(log["model"], "test-model")
        self.assertEqual(log["metrics"]["context_mode"], "ground_truth")
        self.assertEqual(log["metrics"]["benchmark_metadata"], payload["metadata"])
        self.assertEqual(len(log["records"]), 2)


if __name__ == "__main__":
    unittest.main()
