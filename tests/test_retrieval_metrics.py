"""Unit tests for retrieval evaluation metrics, tenant isolation, and benchmark auditing."""

import json
import tempfile
import unittest
from pathlib import Path

from src.evaluation.retrieval_metrics import (
    aggregate_retrieval_metrics,
    compare_sample_to_benchmark,
    compute_doc_recall,
    compute_evidence_coverage,
    compute_hit_rate,
    compute_mrr,
    evaluate_query_retrieval,
    normalize_text_span,
    parse_ground_truth_docs,
    parse_ground_truth_evidence,
    verify_tenant_isolation,
)


class TestRetrievalMetrics(unittest.TestCase):
    def test_text_normalization(self):
        self.assertEqual(normalize_text_span("  Hello \t\n World!  "), "hello world!")
        self.assertEqual(normalize_text_span(""), "")
        self.assertEqual(normalize_text_span(None), "")

    def test_parse_ground_truth_docs_and_evidence(self):
        row = {
            "evidence_json": json.dumps([
                {"source": "CATERING_AND_CUSTOM_CAKES.md", "quote": "Outdoor displays are limited to 2 hours."},
                {"source": "faq_support_knowledgebase.json", "quote": "Deposit is $45 nonrefundable."},
            ]),
            "cited_sources": '["CATERING_AND_CUSTOM_CAKES.md"]',
        }
        docs = parse_ground_truth_docs(row)
        self.assertEqual(docs, {"CATERING_AND_CUSTOM_CAKES", "faq_support_knowledgebase"})

        evidence = parse_ground_truth_evidence(row)
        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]["doc_id"], "CATERING_AND_CUSTOM_CAKES")
        self.assertEqual(evidence[0]["quote"], "Outdoor displays are limited to 2 hours.")
        self.assertEqual(evidence[1]["doc_id"], "faq_support_knowledgebase")

    def test_single_doc_hit_rate_equals_recall(self):
        truth = {"POST_OP_CARE_GUIDE"}
        retrieved = ["POST_OP_CARE_GUIDE", "faq_support_knowledgebase"]

        # For k=1, hit rate and doc recall are both 1.0
        self.assertEqual(compute_hit_rate(truth, retrieved, k=1), 1.0)
        self.assertEqual(compute_doc_recall(truth, retrieved, k=1), 1.0)

        # For irrelevant first chunk
        retrieved_bad = ["OTHER_DOC", "POST_OP_CARE_GUIDE"]
        self.assertEqual(compute_hit_rate(truth, retrieved_bad, k=1), 0.0)
        self.assertEqual(compute_doc_recall(truth, retrieved_bad, k=1), 0.0)
        self.assertEqual(compute_hit_rate(truth, retrieved_bad, k=2), 1.0)
        self.assertEqual(compute_doc_recall(truth, retrieved_bad, k=2), 1.0)

    def test_multi_doc_distinguishes_hit_rate_and_recall(self):
        """CRITICAL: Verifies distinction when a query requires multiple documents."""
        truth = {"CATERING_AND_CUSTOM_CAKES", "faq_support_knowledgebase"}

        # Only one of two documents retrieved at k=1
        retrieved = ["CATERING_AND_CUSTOM_CAKES", "UNRELATED_DOC"]
        hit_k1 = compute_hit_rate(truth, retrieved, k=1)
        recall_k1 = compute_doc_recall(truth, retrieved, k=1)
        self.assertEqual(hit_k1, 1.0)
        self.assertEqual(recall_k1, 0.5)  # Hit rate is 1.0, but Recall is only 0.5!

        # Both documents retrieved in top-2
        retrieved_both = ["CATERING_AND_CUSTOM_CAKES", "faq_support_knowledgebase"]
        self.assertEqual(compute_hit_rate(truth, retrieved_both, k=2), 1.0)
        self.assertEqual(compute_doc_recall(truth, retrieved_both, k=2), 1.0)

        # 3 documents required, only 1 retrieved
        truth_3 = {"DOC_A", "DOC_B", "DOC_C"}
        retrieved_3 = ["DOC_A", "DOC_X", "DOC_Y"]
        self.assertEqual(compute_hit_rate(truth_3, retrieved_3, k=3), 1.0)
        self.assertAlmostEqual(compute_doc_recall(truth_3, retrieved_3, k=3), 1.0 / 3.0)

    def test_mrr_calculation(self):
        truth = {"TARGET_DOC"}
        self.assertEqual(compute_mrr(truth, ["TARGET_DOC", "OTHER"], k=3), 1.0)
        self.assertEqual(compute_mrr(truth, ["OTHER", "TARGET_DOC"], k=3), 0.5)
        self.assertEqual(compute_mrr(truth, ["A", "B", "TARGET_DOC"], k=3), 1.0 / 3.0)
        self.assertEqual(compute_mrr(truth, ["A", "B", "C", "TARGET_DOC"], k=3), 0.0)

    def test_evidence_span_coverage(self):
        evidence = [
            {"doc_id": "POLICY", "quote": "Refunds within 30 days are fully honored."},
            {"doc_id": "POLICY", "quote": "Restocking fee is 15%."},
        ]

        chunks_full = [
            {
                "doc_id": "POLICY",
                "text": "General overview. Refunds within 30 days are fully honored for all items.",
            },
            {
                "doc_id": "POLICY",
                "text": "For electronics, a restocking fee is 15% upon inspection.",
            },
        ]

        cov_full = compute_evidence_coverage(evidence, chunks_full, k=2)
        self.assertTrue(cov_full["measurable"])
        self.assertEqual(cov_full["covered_quotes"], 2)
        self.assertEqual(cov_full["evidence_hit_rate"], 1.0)
        self.assertEqual(cov_full["evidence_span_coverage"], 1.0)

        # Partial coverage (only 1 chunk retrieved at k=1)
        cov_part = compute_evidence_coverage(evidence, chunks_full, k=1)
        self.assertEqual(cov_part["covered_quotes"], 1)
        self.assertEqual(cov_part["evidence_hit_rate"], 1.0)
        self.assertEqual(cov_part["evidence_span_coverage"], 0.5)

        # Matching text in a WRONG doc_id does not count
        chunks_wrong_doc = [
            {
                "doc_id": "WRONG_MANUAL",
                "text": "Refunds within 30 days are fully honored.",
            }
        ]
        cov_wrong = compute_evidence_coverage(evidence, chunks_wrong_doc, k=1)
        self.assertEqual(cov_wrong["covered_quotes"], 0)
        self.assertEqual(cov_wrong["evidence_hit_rate"], 0.0)
        self.assertEqual(cov_wrong["evidence_span_coverage"], 0.0)

        # Unmeasurable evidence
        cov_empty = compute_evidence_coverage([], chunks_full, k=2)
        self.assertFalse(cov_empty["measurable"])
        self.assertEqual(cov_empty["evidence_span_coverage"], 0.0)

    def test_strict_tenant_isolation(self):
        good_chunks = [
            {"tenant_id": "harbor_view", "doc_id": "DOC1", "text": "..."},
            {"tenant_id": "harbor_view", "doc_id": "DOC2", "text": "..."},
        ]
        # Should pass with no exception
        verify_tenant_isolation(good_chunks, expected_tenant="harbor_view")

        bad_chunks = [
            {"tenant_id": "harbor_view", "doc_id": "DOC1", "text": "..."},
            {"tenant_id": "iron_and_oak", "doc_id": "LEAKED_DOC", "text": "..."},
        ]
        with self.assertRaises(RuntimeError) as ctx:
            verify_tenant_isolation(bad_chunks, expected_tenant="harbor_view")
        self.assertIn("Tenant isolation breach", str(ctx.exception))
        self.assertIn("iron_and_oak", str(ctx.exception))

    def test_evaluate_query_retrieval(self):
        ground_truth = {"DOC_A", "DOC_B"}
        evidence = [{"doc_id": "DOC_A", "quote": "Valid quote span."}]
        chunks = [
            {"tenant_id": "tenant1", "doc_id": "DOC_A", "text": "Here is a Valid quote span. Enjoy."},
            {"tenant_id": "tenant1", "doc_id": "DOC_C", "text": "Unrelated."},
        ]

        res = evaluate_query_retrieval(
            ground_truth_docs=ground_truth,
            retrieved_chunks=chunks,
            k_values=[1, 2],
            ground_truth_evidence=evidence,
            expected_tenant="tenant1",
        )

        self.assertTrue(res["is_multi_doc"])
        self.assertEqual(res["ground_truth_doc_count"], 2)
        self.assertEqual(res["hit_rate"][1], 1.0)
        self.assertEqual(res["doc_recall"][1], 0.5)
        self.assertEqual(res["hit_rate"][2], 1.0)
        self.assertEqual(res["doc_recall"][2], 0.5)  # DOC_B was not retrieved
        self.assertEqual(res["evidence_hit_rate"][1], 1.0)
        self.assertEqual(res["evidence_span_coverage"][1], 1.0)

    def test_aggregate_retrieval_metrics(self):
        queries = [
            {
                "is_multi_doc": False,
                "hit_rate": {1: 1.0, 3: 1.0},
                "doc_recall": {1: 1.0, 3: 1.0},
                "mrr": {1: 1.0, 3: 1.0},
                "evidence_measurable": True,
                "evidence_hit_rate": {1: 1.0, 3: 1.0},
                "evidence_span_coverage": {1: 1.0, 3: 1.0},
            },
            {
                "is_multi_doc": True,
                "hit_rate": {1: 1.0, 3: 1.0},
                "doc_recall": {1: 0.5, 3: 1.0},
                "mrr": {1: 1.0, 3: 1.0},
                "evidence_measurable": True,
                "evidence_hit_rate": {1: 0.0, 3: 1.0},
                "evidence_span_coverage": {1: 0.0, 3: 1.0},
            },
        ]
        agg = aggregate_retrieval_metrics(queries, k_values=[1, 3])
        self.assertEqual(agg["n"], 2)
        self.assertEqual(agg["single_doc_count"], 1)
        self.assertEqual(agg["multi_doc_count"], 1)
        self.assertEqual(agg["hit_rate"][1], 1.0)
        self.assertEqual(agg["doc_recall"][1], 0.75)  # (1.0 + 0.5) / 2
        self.assertEqual(agg["doc_recall"][3], 1.0)
        self.assertEqual(agg["multi_doc_metrics"]["doc_recall"][1], 0.5)
        self.assertEqual(agg["evidence_span_coverage"][1], 0.5)

    def test_compare_sample_to_benchmark(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bench_file = Path(tmpdir) / "held_out_benchmark.json"
            payload = {
                "metadata": {"held_out_tenant": "harbor_view", "seed": 42},
                "questions": [
                    {"ticket_id": f"harbor_view-ans-{i}", "is_answerable": True} for i in range(50)
                ] + [
                    {"ticket_id": f"harbor_view-unans-{i}", "is_answerable": False} for i in range(50)
                ],
            }
            bench_file.write_text(json.dumps(payload), encoding="utf-8")

            # 1. Matching answerable subset
            sample_ans = [f"harbor_view-ans-{i}" for i in range(50)]
            res = compare_sample_to_benchmark(sample_ans, bench_file, tenant="harbor_view")
            self.assertTrue(res["is_identical_to_benchmark_answerable_subset"])
            self.assertFalse(res["is_identical_to_full_benchmark"])
            self.assertEqual(res["overlap_with_benchmark_answerable"], 50)
            self.assertEqual(res["relationship"], "identical_to_benchmark_answerable_subset")

            # 2. Different tenant
            res_diff = compare_sample_to_benchmark(["iron-01", "iron-02"], bench_file, tenant="iron_and_oak")
            self.assertEqual(res_diff["relationship"], "disjoint_tenant")
            self.assertFalse(res_diff["is_identical_to_full_benchmark"])

            # 3. Partial overlap
            sample_part = [f"harbor_view-ans-{i}" for i in range(25)] + ["other-ticket-1"]
            res_part = compare_sample_to_benchmark(sample_part, bench_file, tenant="harbor_view")
            self.assertEqual(res_part["relationship"], "partial_overlap")
            self.assertEqual(res_part["overlap_with_benchmark_answerable"], 25)

    def test_run_benchmark_end_to_end_with_mock_retriever(self):
        from unittest.mock import MagicMock
        from scripts.benchmark_retrieval import run_benchmark
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            dataset_file = tmp_path / "mock_tickets.csv"
            bench_file = tmp_path / "mock_benchmark.json"
            summary_out = tmp_path / "summary.json"
            failures_out = tmp_path / "failures.json"

            # Create a mock CSV with both single and multi-doc tickets
            df = pd.DataFrame([
                {
                    "ticket_id": "tenantA-001",
                    "business": "tenantA",
                    "customer_query": "How do I return?",
                    "is_answerable": True,
                    "evidence_json": json.dumps([{"source": "RETURNS.md", "quote": "30 days window."}]),
                    "cited_sources": "RETURNS.md",
                },
                {
                    "ticket_id": "tenantA-002",
                    "business": "tenantA",
                    "customer_query": "Multi doc question",
                    "is_answerable": True,
                    "evidence_json": json.dumps([
                        {"source": "DOC1.md", "quote": "Quote one."},
                        {"source": "DOC2.md", "quote": "Quote two."},
                    ]),
                    "cited_sources": '["DOC1.md", "DOC2.md"]',
                },
            ])
            df.to_csv(dataset_file, index=False)

            bench_file.write_text(json.dumps({
                "metadata": {"held_out_tenant": "tenantA", "seed": 42},
                "questions": [
                    {"ticket_id": "tenantA-001", "is_answerable": True},
                ],
            }), encoding="utf-8")

            mock_retriever = MagicMock()
            mock_retriever.index_name = "test_index"
            # Mock retrieve return: for ticket 1, return RETURNS; for ticket 2, return only DOC1
            def mock_retrieve(query, tenant_id, top_k, max_per_doc):
                if "return" in query.lower():
                    return [{"tenant_id": tenant_id, "doc_id": "RETURNS", "text": "30 days window for all."}]
                else:
                    return [{"tenant_id": tenant_id, "doc_id": "DOC1", "text": "Quote one here."}]

            mock_retriever.retrieve.side_effect = mock_retrieve

            args = MagicMock()
            args.tenant = "tenantA"
            args.dataset = str(dataset_file)
            args.sample_size = 10
            args.k_values = [1, 2]
            args.seed = 42
            args.max_per_doc = 2
            args.benchmark_file = str(bench_file)
            args.summary_out = str(summary_out)
            args.failures_out = str(failures_out)

            summary = run_benchmark(mock_retriever, args)
            self.assertTrue(summary_out.is_file())
            self.assertIn("tenantA", summary["tenant_metrics"])
            metrics = summary["tenant_metrics"]["tenantA"]
            # 2 tickets total:
            # ticket 1: hit=1, recall=1
            # ticket 2: hit=1, recall=0.5 (only DOC1 retrieved out of DOC1, DOC2)
            # overall hit@1: 1.0, recall@1: 0.75
            self.assertEqual(metrics["hit_rate"][1], 1.0)
            self.assertEqual(metrics["doc_recall"][1], 0.75)
            self.assertEqual(metrics["multi_doc_count"], 1)
            self.assertEqual(metrics["multi_doc_metrics"]["doc_recall"][1], 0.5)

    def test_summarize_training_runs_classification_and_accounting(self):
        from scripts.summarize_training_runs import inspect_single_run_directory, summarize_runs

        with tempfile.TemporaryDirectory() as tmpdir:
            run_root = Path(tmpdir) / "test_smoke_run"
            run_root.mkdir()

            # 1. Setup mock run directory
            (run_root / "run_config.json").write_text(json.dumps({
                "run_name": "test_smoke_run",
                "run_mode": "smoke",
                "model_name": "unsloth/Llama-3.2-3B-Instruct-bnb-4bit",
                "learning_rate": 2e-4,
                "optimizer": "adamw_8bit",
                "lora_rank": 16,
                "max_steps": 20,
            }))
            (run_root / "run_summary.json").write_text(json.dumps({
                "run_mode": "smoke",
                "smoke_test_only": True,
                "baseline_validation_loss": 1.45,
                "selected_validation_loss": 1.20,
                "optimizer_steps": 20,
            }))

            # Mock checkpoints
            (run_root / "checkpoints" / "checkpoint-10").mkdir(parents=True)
            (run_root / "checkpoints" / "checkpoint-20").mkdir(parents=True)

            # Mock adapter
            (run_root / "adapter").mkdir()
            (run_root / "adapter" / "adapter_config.json").write_text("{}")
            (run_root / "adapter" / "adapter_model.safetensors").write_text("dummy")

            # Mock gguf
            (run_root / "gguf").mkdir()
            (run_root / "gguf" / "model.Q4_K_M.gguf").write_text("GGUF_dummy")

            report = inspect_single_run_directory(run_root)

            # Assert classification and accounting rules
            self.assertEqual(report["classification"], "smoke_test")
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["artifacts_inventory"]["checkpoints_count"], 2)
            self.assertTrue(report["artifacts_inventory"]["adapter_present"])
            self.assertEqual(len(report["artifacts_inventory"]["gguf_exports"]), 1)
            self.assertEqual(report["metrics"]["baseline_validation_loss"], 1.45)
            self.assertEqual(report["metrics"]["selected_validation_loss"], 1.20)

            # Summarize via summarize_runs
            inventory = summarize_runs([run_root], include_pending=True)
            # The 2 checkpoints must NOT increase independent experiment count
            # Only supplied physical artifacts count; no remote runs are invented.
            self.assertEqual(inventory["summary_counts"]["explicitly_supplied_directories_found"], 1)
            self.assertEqual(inventory["summary_counts"]["completed"], 1)
            self.assertEqual(inventory["summary_counts"]["pending_remote"], 0)


if __name__ == "__main__":
    unittest.main()
