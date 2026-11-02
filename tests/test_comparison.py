"""Comprehensive offline tests for model comparison, teacher recovery, and baseline orchestration."""

import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.evaluation.comparison import (
    ComparisonReport,
    GeminiTeacherAdapter,
    LatencyDistribution,
    MockTeacherAdapter,
    ModelEvaluationSummary,
    ModelPricing,
    TeacherRecoveryResult,
    calculate_teacher_recovery,
    calculate_token_metrics,
    check_comparison_compatibility,
    compare_evaluations,
    compute_file_sha256,
    compute_percentiles,
    compute_questions_sha256,
    extract_judged_metrics,
    format_comparison_markdown,
    format_comparison_text,
    generate_safe_log_path,
    get_hardware_metadata,
    get_model_pricing,
    run_baseline_evaluation,
    summarize_evaluation_log,
)
from src.evaluation.judge import (
    JudgeIdentity, JudgeResumeError, build_initial_state, load_generation_log, load_rubric,
)


class TestComparisonModule(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

        # Mock question set
        self.mock_questions = [
            {
                "ticket_id": "tenant-001",
                "tenant": "harbor_view",
                "category": "pricing",
                "customer_query": "What is the exam fee?",
                "ground_truth_action": "answer",
                "is_answerable": True,
                "evidence_json": json.dumps([{"source": "fees.md", "quote": "Exam fee is $50."}]),
            },
            {
                "ticket_id": "tenant-002",
                "tenant": "harbor_view",
                "category": "policy",
                "customer_query": "Can I get an unlisted refund?",
                "ground_truth_action": "escalate",
                "is_answerable": False,
                "evidence_json": "[]",
            },
            {
                "ticket_id": "tenant-003",
                "tenant": "harbor_view",
                "category": "disputes",
                "customer_query": "I want to dispute a charge.",
                "ground_truth_action": "escalate",
                "is_answerable": True,
                "evidence_json": json.dumps([{"source": "disputes.md", "quote": "All billing disputes must be escalated."}]),
            },
        ]

    # -----------------------------------------------------------------------
    # 1. Benchmark Integrity & Hashing
    # -----------------------------------------------------------------------

    def test_compute_file_sha256(self):
        sample_file = self.root / "benchmark.json"
        sample_file.write_text('{"test": 123}', encoding="utf-8")
        h1 = compute_file_sha256(sample_file)
        self.assertEqual(len(h1), 64)

        # Re-hashing the same content produces exact identical hash
        h2 = compute_file_sha256(sample_file)
        self.assertEqual(h1, h2)

        # Content modification changes hash
        sample_file.write_text('{"test": 124}', encoding="utf-8")
        h3 = compute_file_sha256(sample_file)
        self.assertNotEqual(h1, h3)

    def test_compute_questions_sha256(self):
        ids = ["q1", "q2", "q3"]
        h1 = compute_questions_sha256(ids)
        self.assertEqual(len(h1), 64)
        # Order matters
        h2 = compute_questions_sha256(["q3", "q2", "q1"])
        self.assertNotEqual(h1, h2)

    # -----------------------------------------------------------------------
    # 2. Compatibility Checking
    # -----------------------------------------------------------------------

    def test_compatibility_identical_runs(self):
        log_a = {
            "model": "model_a",
            "metrics": {"context_mode": "ground_truth", "benchmark_sha256": "abc"},
            "records": [{"ticket_id": "q1"}, {"ticket_id": "q2"}],
        }
        log_b = {
            "model": "model_b",
            "metrics": {"context_mode": "ground_truth", "benchmark_sha256": "abc"},
            "records": [{"ticket_id": "q1"}, {"ticket_id": "q2"}],
        }
        report = check_comparison_compatibility([log_a, log_b])
        self.assertTrue(report.is_compatible)
        self.assertFalse(report.has_errors)
        self.assertTrue(report.has_warnings)  # Legacy logs omit generation/retrieval settings.

    def test_compatibility_detects_context_mode_mismatch(self):
        log_gt = {
            "model": "student",
            "metrics": {"context_mode": "ground_truth", "benchmark_sha256": "abc"},
            "records": [{"ticket_id": "q1"}],
        }
        log_rag = {
            "model": "student_rag",
            "metrics": {"context_mode": "retriever", "benchmark_sha256": "abc"},
            "records": [{"ticket_id": "q1"}],
        }
        report = check_comparison_compatibility([log_gt, log_rag])
        self.assertTrue(report.has_warnings)
        self.assertTrue(any(i.category == "context_mode_mismatch" for i in report.issues))

    def test_compatibility_detects_coverage_mismatch(self):
        log_full = {
            "model": "model_full",
            "metrics": {"context_mode": "ground_truth"},
            "records": [{"ticket_id": "q1"}, {"ticket_id": "q2"}, {"ticket_id": "q3"}],
        }
        log_sample = {
            "model": "model_sample",
            "metrics": {"context_mode": "ground_truth"},
            "records": [{"ticket_id": "q1"}],
        }
        report = check_comparison_compatibility([log_full, log_sample])
        self.assertFalse(report.is_compatible)
        self.assertTrue(report.has_errors)
        self.assertTrue(any(i.category == "question_count_mismatch" for i in report.issues))

    # -----------------------------------------------------------------------
    # 3. Latency Distribution and Statistics
    # -----------------------------------------------------------------------

    def test_percentile_calculation(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        pcts = compute_percentiles(values, [50, 90, 95])
        self.assertEqual(pcts["p50"], 55.0)
        self.assertEqual(pcts["p90"], 91.0)
        self.assertEqual(pcts["p95"], 95.5)

    def test_latency_distribution_from_values(self):
        latencies = [100.0, 200.0, 300.0, 400.0]
        dist = LatencyDistribution.from_latencies(latencies)
        self.assertIsNotNone(dist)
        self.assertEqual(dist.min_ms, 100.0)
        self.assertEqual(dist.max_ms, 400.0)
        self.assertEqual(dist.mean_ms, 250.0)
        self.assertEqual(dist.sample_count, 4)

    def test_latency_distribution_empty(self):
        dist = LatencyDistribution.from_latencies([])
        self.assertIsNone(dist)

    # -----------------------------------------------------------------------
    # 4. Token Accounting and Cost Projections
    # -----------------------------------------------------------------------

    def test_local_model_token_cost(self):
        pricing = ModelPricing(
            model_name="llama3.2:3b",
            prompt_cost_per_million=0.0,
            completion_cost_per_million=0.0,
            is_local=True,
        )
        records = [
            {"prompt_tokens": 500, "eval_tokens": 50},
            {"prompt_tokens": 600, "eval_tokens": 60},
        ]
        metrics = calculate_token_metrics(records, pricing)
        self.assertEqual(metrics.total_prompt_tokens, 1100)
        self.assertEqual(metrics.total_completion_tokens, 110)
        self.assertEqual(metrics.avg_prompt_tokens, 550.0)
        self.assertEqual(metrics.avg_completion_tokens, 55.0)
        self.assertEqual(metrics.cost_per_1k_queries, 0.0)
        self.assertTrue(metrics.is_local)

    def test_paid_teacher_token_cost(self):
        pricing = ModelPricing(
            model_name="gemini-2.5-flash",
            prompt_cost_per_million=0.10,  # $0.10 per 1M prompt
            completion_cost_per_million=0.40,  # $0.40 per 1M completion
            is_local=False,
        )
        records = [
            {"prompt_tokens": 1000, "eval_tokens": 100},
            {"prompt_tokens": 1000, "eval_tokens": 100},
        ]
        metrics = calculate_token_metrics(records, pricing)
        # Cost per query = (1000 * 0.10 / 1M) + (100 * 0.40 / 1M) = 0.00010 + 0.00004 = 0.00014 USD
        # Cost per 1k queries = 0.14 USD
        self.assertAlmostEqual(metrics.cost_per_1k_queries, 0.14, places=4)
        self.assertFalse(metrics.is_local)

    def test_missing_prompt_tokens_for_paid_api_does_not_fabricate_zero(self):
        pricing = ModelPricing(
            model_name="paid-api",
            prompt_cost_per_million=0.10,
            completion_cost_per_million=0.40,
            is_local=False,
        )
        records = [
            {"eval_tokens": 100},  # Prompt tokens missing
        ]
        metrics = calculate_token_metrics(records, pricing)
        self.assertIsNone(metrics.avg_prompt_tokens)
        self.assertIsNone(metrics.cost_per_1k_queries)

    # -----------------------------------------------------------------------
    # 5. Teacher Recovery Calculations
    # -----------------------------------------------------------------------

    def test_standard_recovery_and_gap_closed(self):
        # Base accuracy = 0.40, Student = 0.85, Teacher = 0.90
        rec = calculate_teacher_recovery(
            metric_name="action_accuracy",
            student_value=0.85,
            teacher_value=0.90,
            base_value=0.40,
            is_inverse=False,
        )
        self.assertEqual(rec.status, "valid")
        # Ratio = 0.85 / 0.90 = 0.9444
        self.assertAlmostEqual(rec.recovery_ratio, 0.9444, places=3)
        # Gap closed = (0.85 - 0.40) / (0.90 - 0.40) = 0.45 / 0.50 = 0.90
        self.assertAlmostEqual(rec.gap_closed, 0.90, places=3)

    def test_inverse_recovery_for_absent_proxy(self):
        # Base proxy = 0.60, Student = 0.10, Teacher = 0.05 (lower is better)
        rec = calculate_teacher_recovery(
            metric_name="absent_answer_action_proxy",
            student_value=0.10,
            teacher_value=0.05,
            base_value=0.60,
            is_inverse=True,
        )
        self.assertEqual(rec.status, "valid")
        # Ratio = teacher / student = 0.05 / 0.10 = 0.50
        self.assertEqual(rec.recovery_ratio, 0.50)
        # Gap closed = (0.60 - 0.10) / (0.60 - 0.05) = 0.50 / 0.55 = 0.9091
        self.assertAlmostEqual(rec.gap_closed, 0.9091, places=3)

    def test_zero_denominator_when_teacher_equals_base(self):
        rec = calculate_teacher_recovery(
            metric_name="schema_validity",
            student_value=1.0,
            teacher_value=1.0,
            base_value=1.0,  # Base and teacher both 1.0 -> denominator 0
            is_inverse=False,
        )
        self.assertEqual(rec.status, "zero_denominator")
        self.assertIsNone(rec.gap_closed)
        self.assertEqual(rec.recovery_ratio, 1.0)

    def test_zero_teacher_denominator_for_ratio(self):
        rec = calculate_teacher_recovery(
            metric_name="metric_x",
            student_value=0.5,
            teacher_value=0.0,
            base_value=0.0,
            is_inverse=False,
        )
        self.assertIsNone(rec.recovery_ratio)
        self.assertIsNone(rec.gap_closed)

    def test_missing_measurement_preserved_as_none(self):
        rec = calculate_teacher_recovery(
            metric_name="unmeasured_metric",
            student_value=None,
            teacher_value=0.90,
            base_value=0.50,
        )
        self.assertEqual(rec.status, "missing_data")
        self.assertIsNone(rec.recovery_ratio)
        self.assertIsNone(rec.gap_closed)

    # -----------------------------------------------------------------------
    # 6. Independent Judged Log Integration
    # -----------------------------------------------------------------------

    def test_extract_judged_metrics_valid(self):
        judged_payload = {
            "judge": {"model": "gpt-4o-mini"},
            "rubric": {"version": "v1.0"},
            "source": {"sha256": "fake_sha_123"},
            "summary": {
                "overall": {
                    "total": 50,
                    "judged": 50,
                    "failed": 0,
                    "rates": {
                        "passed": 0.92,
                        "correctness": 0.96,
                        "groundedness": 0.94,
                        "citation_support": 0.90,
                        "escalation_validity": 0.98,
                    },
                }
            },
        }
        with patch("src.evaluation.comparison.warnings.warn") as warn:
            metrics = extract_judged_metrics(judged_payload, expected_log_sha256="fake_sha_123")
        warn.assert_called_once()
        self.assertIn("Legacy summary-only", warn.call_args.args[0])
        self.assertIs(warn.call_args.args[1], RuntimeWarning)
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.judge_model, "gpt-4o-mini")
        self.assertEqual(metrics.overall_pass_rate, 0.92)
        self.assertEqual(metrics.coverage_rate, 1.0)

    def modern_judged_payload(self):
        record = {
            "ticket_id": "case-1", "customer_query": "What is the fee?",
            "is_answerable": True, "ground_truth_action": "answer", "schema_valid": True,
            "model_action": "answer", "model_answer": "$50.", "model_sources": ["fees.md"],
            "context": "[Source: fees.md]\nThe fee is $50.",
        }
        path = self.root / "generation.json"
        path.write_text(json.dumps({"model": "llama3.2:3b", "records": [record]}))
        log = load_generation_log(path)
        state = build_initial_state(log, JudgeIdentity("ollama", "gemma4:latest"), load_rubric())
        state["judgments"][0].update(status="judged", passed=False, verdict={
            "evidence_sufficient": True, "decision": "appropriate", "correctness": "incorrect",
            "groundedness": "major_unsupported", "unsupported_claims": ["Invented fee"],
            "citation_support": "supported", "invalid_citations": [], "explanation": "Invented fee.",
        })
        return state

    def test_modern_judged_metrics_recompute_inflated_cached_summary(self):
        state = self.modern_judged_payload()
        state["summary"] = {"overall": {"records": 100, "judged": 100, "strict_pass_rate": 1.0}}
        before = json.dumps(state, sort_keys=True)
        metrics = extract_judged_metrics(state)
        self.assertEqual(metrics.total_records, 1)
        self.assertEqual(metrics.judged_records, 1)
        self.assertEqual(metrics.overall_pass_rate, 0)
        self.assertEqual(metrics.correctness_rate, 0)
        self.assertEqual(json.dumps(state, sort_keys=True), before)

    def test_modern_judged_metrics_reject_contradictory_verdict_and_missing_source(self):
        state = self.modern_judged_payload()
        state["judgments"][0]["verdict"]["evidence_sufficient"] = False
        with self.assertRaisesRegex(JudgeResumeError, "fails current validation"):
            extract_judged_metrics(state)
        Path(state["source"]["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "restore its source log"):
            extract_judged_metrics(state)

    def test_modern_summary_without_judgments_is_rejected(self):
        state = self.modern_judged_payload()
        del state["judgments"]
        with self.assertRaisesRegex(ValueError, "cached summary is not sufficient"):
            extract_judged_metrics(state)

    def test_moved_judged_file_uses_explicit_source_path_with_hash_validation(self):
        state = self.modern_judged_payload()
        actual_source = Path(state["source"]["path"])
        state["source"]["path"] = "/another/machine/generation.json"
        self.assertEqual(extract_judged_metrics(state, source_log_path=actual_source).total_records, 1)
        actual_source.write_text(actual_source.read_text() + "\n")
        with self.assertRaisesRegex(JudgeResumeError, "input log hash differs"):
            extract_judged_metrics(state, source_log_path=actual_source)

    def test_extract_judged_metrics_rejects_mismatched_sha(self):
        judged_payload = {
            "source": {"sha256": "actual_sha_456"},
            "summary": {"overall": {"total": 10, "judged": 10, "rates": {"passed": 0.8}}},
        }
        metrics = extract_judged_metrics(judged_payload, expected_log_sha256="different_sha_789")
        self.assertIsNone(metrics)

    # -----------------------------------------------------------------------
    # 7. Safe Output Path Generation
    # -----------------------------------------------------------------------

    def test_generate_safe_log_path(self):
        path1 = generate_safe_log_path(self.root, "eval", "llama3.2:3b", "ground_truth")
        path1.write_text("dummy", encoding="utf-8")

        # Second call in same directory produces distinct non-conflicting path
        path2 = generate_safe_log_path(self.root, "eval", "llama3.2:3b", "ground_truth")
        self.assertNotEqual(path1, path2)
        self.assertFalse(path2.exists())

    # -----------------------------------------------------------------------
    # 8. Teacher Adapter Implementations & Safety
    # -----------------------------------------------------------------------

    def test_mock_teacher_adapter(self):
        adapter = MockTeacherAdapter(model="mock-teacher-v1", action="answer")
        raw, timing = adapter.generate_raw("Hello", "Context document text")
        data = json.loads(raw)
        self.assertEqual(data["action"], "answer")
        self.assertEqual(adapter.model, "mock-teacher-v1")
        self.assertIn("latency_ms", timing)
        self.assertIn("eval_tokens", timing)

    def test_gemini_adapter_refuses_missing_credentials(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}, clear=True), \
                patch("dotenv.find_dotenv", return_value=""):
            with self.assertRaises(ValueError) as ctx:
                GeminiTeacherAdapter(model="test-teacher", api_key=None)
            self.assertIn("GEMINI_API_KEY", str(ctx.exception))

    def test_gemini_adapter_prefers_dotenv_key_over_shell_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            dotenv_file = Path(tmp) / ".env"
            dotenv_file.write_text('GEMINI_API_KEY="billed-project-key"\n')
            with patch.dict("os.environ", {"GEMINI_API_KEY": "unbilled-shell-key"}, clear=True), \
                    patch("dotenv.find_dotenv", return_value=str(dotenv_file)):
                adapter = GeminiTeacherAdapter(model="test-teacher")
                self.assertEqual(adapter.client._api_client.api_key, "billed-project-key")
                self.assertEqual(adapter.request_settings["api_key_source"], ".env")
            with patch.dict("os.environ", {"GEMINI_API_KEY": "unbilled-shell-key"}, clear=True), \
                    patch("dotenv.find_dotenv", return_value=""):
                adapter = GeminiTeacherAdapter(model="test-teacher")
                self.assertEqual(adapter.client._api_client.api_key, "unbilled-shell-key")
                self.assertEqual(adapter.request_settings["api_key_source"], "environment")

    # -----------------------------------------------------------------------
    # 9. Baseline Orchestration Integration Test (Offline Mock)
    # -----------------------------------------------------------------------

    def test_run_baseline_evaluation_offline(self):
        mock_client = Mock()
        mock_client.model = "test-mock-model"
        # Return valid answer on question 1, valid escalate on question 2, valid escalate on question 3
        mock_client.generate_raw.side_effect = [
            (
                json.dumps({"answer": "Answer 1", "cited_sources": ["fees.md"], "confidence": 0.9, "action": "answer"}),
                {"latency_ms": 150.0, "tokens_per_second": 60.0, "eval_tokens": 25, "prompt_tokens": 200},
            ),
            (
                json.dumps({"answer": "Escalate 2", "cited_sources": [], "confidence": 0.8, "action": "escalate"}),
                {"latency_ms": 120.0, "tokens_per_second": 65.0, "eval_tokens": 20, "prompt_tokens": 180},
            ),
            (
                json.dumps({"answer": "Escalate 3", "cited_sources": [], "confidence": 0.85, "action": "escalate"}),
                {"latency_ms": 130.0, "tokens_per_second": 62.0, "eval_tokens": 22, "prompt_tokens": 190},
            ),
        ]

        metrics, records, log_path = run_baseline_evaluation(
            client=mock_client,
            retriever=None,
            questions=self.mock_questions,
            use_retriever=False,
            output_dir=self.root / "logs",
        )

        self.assertTrue(log_path.exists())
        self.assertEqual(len(records), 3)
        self.assertEqual(metrics["action_accuracy"], 1.0)
        self.assertEqual(metrics["schema_validity_rate"], 1.0)
        self.assertIn("generation_latency_distribution", metrics)
        self.assertIn("e2e_latency_distribution", metrics)
        self.assertIn("token_cost_metrics", metrics)

        # Verify recorded fields
        self.assertIn("generation_latency_ms", records[0])
        self.assertIn("e2e_latency_ms", records[0])

    # -----------------------------------------------------------------------
    # 10. Multi-Model Comparison & Formatting
    # -----------------------------------------------------------------------

    def test_compare_evaluations_and_report_formatting(self):
        log_base = {
            "model": "llama3.2:3b",
            "metrics": {
                "context_mode": "ground_truth",
                "action_accuracy": 0.40,
                "escalation_precision": 0.50,
                "escalation_recall": 0.40,
                "escalation_f1": 0.4444,
                "schema_validity_rate": 1.0,
                "hallucination_rate": 0.50,
                "avg_tokens_per_second": 55.0,
                "total_eval": 2,
                "counts": {"absent_total": 2, "absent_hallucinated": 1},
            },
            "records": [
                {"ticket_id": "q1", "latency_ms": 1000.0, "eval_tokens": 40, "prompt_tokens": 300},
                {"ticket_id": "q2", "latency_ms": 1200.0, "eval_tokens": 50, "prompt_tokens": 320},
            ],
        }

        log_student = {
            "model": "llama3.2:3b-qlora",
            "metrics": {
                "context_mode": "ground_truth",
                "action_accuracy": 0.85,
                "escalation_precision": 0.90,
                "escalation_recall": 0.80,
                "escalation_f1": 0.8471,
                "schema_validity_rate": 1.0,
                "hallucination_rate": 0.10,
                "avg_tokens_per_second": 56.0,
                "total_eval": 2,
                "counts": {"absent_total": 2, "absent_hallucinated": 0},
            },
            "records": [
                {"ticket_id": "q1", "latency_ms": 950.0, "eval_tokens": 42, "prompt_tokens": 300},
                {"ticket_id": "q2", "latency_ms": 980.0, "eval_tokens": 45, "prompt_tokens": 320},
            ],
        }

        log_teacher = {
            "model": "gemini-2.5-flash",
            "metrics": {
                "context_mode": "ground_truth",
                "action_accuracy": 0.90,
                "escalation_precision": 0.95,
                "escalation_recall": 0.90,
                "escalation_f1": 0.9243,
                "schema_validity_rate": 1.0,
                "hallucination_rate": 0.05,
                "avg_tokens_per_second": 80.0,
                "total_eval": 2,
                "counts": {"absent_total": 2, "absent_hallucinated": 0},
            },
            "records": [
                {"ticket_id": "q1", "latency_ms": 300.0, "eval_tokens": 35, "prompt_tokens": 280},
                {"ticket_id": "q2", "latency_ms": 350.0, "eval_tokens": 38, "prompt_tokens": 290},
            ],
        }

        for log in (log_base, log_student, log_teacher):
            log["metrics"]["benchmark_sha256"] = "same-benchmark"
        report = compare_evaluations(
            logs=[log_base, log_student, log_teacher],
            base_model_name="llama3.2:3b",
            teacher_model_name="gemini-2.5-flash",
        )

        self.assertEqual(len(report.summaries), 3)
        self.assertTrue(len(report.teacher_recoveries) > 0)

        # Check Markdown format
        md = format_comparison_markdown(report)
        self.assertIn("Model Baseline & Comparison Report", md)
        self.assertIn("llama3.2:3b-qlora", md)
        self.assertIn("Absent-Answer Action Proxy*", md)
        self.assertIn("Teacher Recovery & Gap Analysis", md)

        # Check Text format
        text = format_comparison_text(report)
        self.assertIn("MODEL BASELINE COMPARISON & BENCHMARK SCORECARD", text)
        self.assertIn("COST PROJECTIONS PER 1,000 QUERIES", text)


if __name__ == "__main__":
    unittest.main()
