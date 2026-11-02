"""Regression checks at the boundaries between the three evaluation workstreams."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.evaluation.comparison import (
    ModelPricing, calculate_token_metrics, check_comparison_compatibility,
    compare_evaluations, extract_judged_metrics, get_model_pricing,
    run_baseline_evaluation, summarize_evaluation_log,
)
from src.evaluation.judge import (
    BackendReply, JudgeIdentity, JudgeOptions, JudgeResumeError,
    check_resume_compatible, load_generation_log, load_rubric, run_judging,
)
from src.evaluation.retrieval_metrics import verify_tenant_isolation
from src.evaluation.training_inventory import inspect_single_run_directory, summarize_runs

ROOT = Path(__file__).resolve().parents[1]


class EvaluationIntegrationTests(unittest.TestCase):
    def test_judge_output_roundtrips_through_comparison_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'generation.json'
            log.write_text(json.dumps({
                'model': 'llama3.2:3b',
                'metrics': {'context_mode': 'ground_truth', 'benchmark_sha256': 'same'},
                'records': [{
                    'ticket_id': 'q1', 'customer_query': 'How much?', 'is_answerable': True,
                    'ground_truth_action': 'answer', 'schema_valid': True,
                    'context': '[Source: PRICE]\nIt costs $5.', 'model_action': 'answer',
                    'model_answer': '$5.', 'model_sources': ['PRICE'], 'action_correct': True,
                }],
            }))
            verdict = {
                'evidence_sufficient': True, 'decision': 'appropriate', 'correctness': 'correct',
                'groundedness': 'fully_grounded', 'unsupported_claims': [],
                'citation_support': 'supported', 'invalid_citations': [], 'explanation': 'The price matches.',
            }
            backend = SimpleNamespace(identity=JudgeIdentity('ollama', 'different-family', 'localhost', 0.0),
                                      complete=lambda *args: BackendReply(json.dumps(verdict), 10, 10))
            judged = root / 'judged.json'
            result = run_judging(load_generation_log(log), backend, load_rubric(), judged, JudgeOptions())
            metrics = extract_judged_metrics(result.state, hashlib.sha256(log.read_bytes()).hexdigest())
            self.assertEqual(metrics.total_records, 1)
            self.assertEqual(metrics.overall_pass_rate, 1.0)
            self.assertEqual(metrics.correctness_rate, 1.0)
            self.assertEqual(metrics.groundedness_rate, 1.0)
            self.assertIsNone(extract_judged_metrics({**result.state, 'source': {}}, 'expected'))
            with self.assertRaises(JudgeResumeError):
                check_resume_compatible(result.state, load_generation_log(log),
                                        JudgeIdentity('ollama', 'different-family', 'localhost', 0.9), load_rubric())
            # Matching is by content hash, not the old machine's absolute path.
            moved = json.loads(judged.read_text())
            moved['source']['path'] = '/another/machine/old.json'
            judged.write_text(json.dumps(moved))
            output = root / 'report.json'
            subprocess.run([sys.executable, str(ROOT / 'scripts/compare_evaluations.py'),
                            str(log), '--judged-logs', str(judged), '--format', 'json',
                            '--output', str(output)], check=True, capture_output=True, text=True)
            report = json.loads(output.read_text())
            self.assertIsInstance(report['summaries'][0]['tokens_and_cost'], dict)
            self.assertEqual(report['summaries'][0]['judged_metrics']['overall_pass_rate'], 1.0)

    def test_comparison_refuses_hash_context_settings_and_duplicate_mismatches(self):
        def log(model, digest='same', mode='ground_truth'):
            return {'model': model, 'metrics': {'benchmark_sha256': digest, 'context_mode': mode},
                    'records': [{'ticket_id': 'q1', 'context': 'same'}]}
        a, b = log('student'), log('teacher')
        self.assertTrue(check_comparison_compatibility([a, b]).is_compatible)
        b['metrics']['benchmark_sha256'] = 'different'
        self.assertFalse(check_comparison_compatibility([a, b]).is_compatible)
        self.assertEqual(compare_evaluations([a, b]).teacher_recoveries, [])
        b = log('teacher', mode='retriever')
        self.assertFalse(check_comparison_compatibility([a, b]).is_compatible)
        b = log('teacher')
        b['records'][0]['context'] = 'changed'
        self.assertFalse(check_comparison_compatibility([a, b]).is_compatible)
        b = log('teacher')
        b['records'].append(dict(b['records'][0]))
        self.assertFalse(check_comparison_compatibility([a, b]).is_compatible)
        b = log('teacher')
        a['generation_settings'], b['generation_settings'] = {'temperature': .2}, {'temperature': .8}
        self.assertFalse(check_comparison_compatibility([a, b]).is_compatible)

    def test_costs_and_missing_measurements_are_not_fabricated(self):
        unknown = get_model_pricing('gemini-unspecified-model')
        records = [{'prompt_tokens': 10, 'eval_tokens': 5}]
        self.assertIsNone(calculate_token_metrics(records, unknown).cost_per_1k_queries)
        paid = ModelPricing('paid', 1, 2, 'verified-source', 'verified-date', False)
        partial = calculate_token_metrics(records + [{'eval_tokens': 5}], paid)
        self.assertIsNone(partial.cost_per_1k_queries)
        self.assertIsNone(partial.total_tokens)
        empty = summarize_evaluation_log({'model': 'unknown', 'metrics': {}, 'records': []})
        self.assertIsNone(empty.action_accuracy)
        self.assertIsNone(empty.generation_latency)
        self.assertIsNone(summarize_evaluation_log({
            'metrics': {'counts': {'absent_total': 0}, 'hallucination_rate': 0}, 'records': []
        }).absent_answer_action_proxy)

    def test_inventory_counts_trials_once_and_never_invents_pending_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            full = root / 'full'
            full.mkdir()
            (full / 'run_config.json').write_text(json.dumps({'run_mode': 'full'}))
            (full / 'run_summary.json').write_text(json.dumps({'selected_validation_loss': 0.0}))
            report = inspect_single_run_directory(full)
            self.assertEqual(report['classification'], 'full_run')
            self.assertEqual(report['metrics']['selected_validation_loss'], 0.0)
            search = root / 'search'
            search.mkdir()
            (search / 'run_config.json').write_text(json.dumps({'run_mode': 'search'}))
            (search / 'search_results.json').write_text(json.dumps({
                'search_complete': True, 'planned_trials': 2, 'results': [
                    {'trial_id': 'trial_001', 'status': 'completed'},
                    {'trial_id': 'trial_002', 'status': 'failed'},
                ],
            }))
            inventory = summarize_runs([root, full])
            self.assertEqual(inventory['summary_counts']['total_independent_experiments_inventoried'], 3)
            self.assertEqual(inventory['summary_counts']['completed'], 2)
            self.assertEqual(inventory['summary_counts']['failed'], 1)
            self.assertEqual(inventory['summary_counts']['pending_remote'], 0)

    def test_teacher_execution_requires_explicit_authorization(self):
        result = subprocess.run([
            sys.executable, str(ROOT / 'scripts/run_baselines.py'), '--models', 'none',
            '--teacher-provider', 'gemini', '--teacher-model', 'test-teacher', '--limit', '1',
        ], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--allow-paid-api', result.stderr)

    def test_retrieval_fails_closed_and_can_use_exact_frozen_questions(self):
        from scripts.benchmark_retrieval import load_answerable
        with self.assertRaises(RuntimeError):
            verify_tenant_isolation([{'doc_id': 'UNKNOWN_TENANT'}], 'harbor_view')
        frame = load_answerable(ROOT / 'data/evaluation/held_out_benchmark.json')
        self.assertEqual(len(frame), 50)
        self.assertEqual(set(frame['business']), {'harbor_view'})


if __name__ == '__main__':
    unittest.main()
