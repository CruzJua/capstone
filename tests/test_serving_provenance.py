"""Offline regression coverage for role selection and serving provenance."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.run_baselines import resolve_student_models
from src.evaluation.comparison import check_comparison_compatibility, run_baseline_evaluation
from src.inference.client import SupportInferenceClient
from src.inference.serving_metadata import capture_ollama_settings

ROOT = Path(__file__).resolve().parents[1]


class ModelRoleTests(unittest.TestCase):
    def roles(self, models=None, base=None, finetuned=()):
        return resolve_student_models(SimpleNamespace(models=models, base_model=base, finetuned_models=finetuned))

    def test_single_finetuned_and_reversed_legacy_order_keep_correct_roles(self):
        self.assertEqual(self.roles(finetuned=['my-custom-adapter']), {'my-custom-adapter': 'finetuned_student'})
        self.assertEqual(self.roles(models=['llama3.2:3b-qlora']), {'llama3.2:3b-qlora': 'finetuned_student'})
        self.assertEqual(self.roles(models=['llama3.2:3b-qlora', 'llama3.2:3b']),
                         {'llama3.2:3b-qlora': 'finetuned_student', 'llama3.2:3b': 'base_student'})
        self.assertEqual(self.roles(), {'llama3.2:3b': 'base_student'})
        self.assertEqual(self.roles(models=['none']), {})

    def test_ambiguous_duplicate_and_conflicting_selection_rejected(self):
        for kwargs in ({'models': ['unknown-model']}, {'models': ['none'], 'base': 'base'},
                       {'base': 'same', 'finetuned': ['same']}, {'base': ' '},
                       {'models': ['llama3.2:3b', 'llama3.2:3b-instruct']}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.roles(**kwargs)

    def test_cli_finetuned_only_dry_run_records_role_without_generation(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_baselines.py'),
                                 '--finetuned-models', 'custom-weights', '--dry-run'],
                                capture_output=True, text=True, check=True)
        self.assertIn('custom-weights (Local Ollama finetuned_student)', result.stdout)
        self.assertNotIn('(Local Ollama base_student)', result.stdout)


class ServingProvenanceTests(unittest.TestCase):
    def ollama(self):
        client = Mock()
        client.show.return_value = {
            'template': '{{ .Prompt }}',
            'parameters': 'stop "<|eot_id|>"\nstop "<|end_of_text|>"\ntemperature 0.6\n',
            'modelinfo': {'llama.context_length': 131072}, 'details': {'quantization_level': 'Q4_K_M'},
        }
        client.list.return_value = {'models': [{'model': 'student:latest', 'digest': 'sha256:one'}]}
        client.ps.return_value = {'models': [{'model': 'student:latest', 'digest': 'sha256:one',
                                             'context_length': 4096, 'size_vram': 1234}]}
        return client

    def metadata(self):
        return capture_ollama_settings(self.ollama(), 'student', {'temperature': 0.2})

    def test_observed_window_overrides_capacity_and_request_overrides_model_default(self):
        client = self.ollama()
        data = capture_ollama_settings(client, 'student', {'temperature': 0.2})
        self.assertEqual(data['capture_status'], 'recorded')
        self.assertEqual(data['context_length'], 4096)
        self.assertEqual(data['model_capacity_context_length'], 131072)
        self.assertEqual(data['context_length_source'], 'observed_runtime')
        self.assertEqual(data['effective_options']['temperature'], 0.2)
        self.assertEqual(data['effective_options']['stop'], ['<|eot_id|>', '<|end_of_text|>'])
        self.assertEqual(data['model_digest'], 'sha256:one')
        self.assertEqual(len(data['template_sha256']), 64)
        client.chat.assert_not_called()
        client.generate.assert_not_called()

    def test_unknown_defaults_stay_unknown_and_errors_do_not_leak_endpoint(self):
        client = self.ollama()
        client.ps.return_value = {'models': []}
        data = capture_ollama_settings(client, 'student', {'temperature': 0.2})
        self.assertIsNone(data['context_length'])
        self.assertEqual(data['capture_status'], 'incomplete')
        client.show.side_effect = RuntimeError('secret connection details')
        client.list.side_effect = RuntimeError('secret connection details')
        data = capture_ollama_settings(client, 'student', {'temperature': 0.2})
        self.assertNotIn('secret', json.dumps(data))
        self.assertEqual(data['capture_errors']['show'], 'RuntimeError')

    def log(self, model='base'):
        return {'model': model, 'metrics': {'context_mode': 'ground_truth', 'benchmark_sha256': 'frozen'},
                'records': [{'ticket_id': 'q1', 'context': 'same'}],
                'generation_settings': {'temperature': .2}, 'retrieval_settings': {},
                'serving_settings': self.metadata()}

    def test_different_weight_digests_allowed_but_serving_differences_rejected(self):
        base, ft = self.log(), self.log('finetuned')
        ft['serving_settings']['model_digest'] = 'sha256:other-weights'
        self.assertTrue(check_comparison_compatibility([base, ft]).is_compatible)
        mutations = [('template_sha256', 'different-template'), ('context_length', 2048)]
        for field, value in mutations:
            changed = copy.deepcopy(ft)
            changed['serving_settings'][field] = value
            self.assertFalse(check_comparison_compatibility([base, changed]).is_compatible)
        changed = copy.deepcopy(ft)
        changed['serving_settings']['effective_options']['stop'] = ['different-stop']
        self.assertFalse(check_comparison_compatibility([base, changed]).is_compatible)
        ft['model'] = base['model']
        self.assertFalse(check_comparison_compatibility([base, ft]).is_compatible)

    def test_legacy_provenance_warns_and_runtime_identity_mismatch_fails(self):
        base, other = self.log(), self.log('other')
        del other['serving_settings']
        report = check_comparison_compatibility([base, other])
        self.assertTrue(report.is_compatible)
        self.assertTrue(any(issue.category == 'serving_provenance_missing' for issue in report.issues))
        other = self.log('other')
        other['serving_settings']['runtime_identity_mismatch'] = True
        self.assertFalse(check_comparison_compatibility([base, other]).is_compatible)

    def test_baseline_persists_provenance_and_detects_tag_change_without_touching_input(self):
        client = SupportInferenceClient.__new__(SupportInferenceClient)
        client.model, client.temperature = 'student', .2
        client.generate_raw = Mock(return_value=(json.dumps({
            'answer': 'Contact support.', 'action': 'escalate', 'confidence': .1, 'cited_sources': []
        }), {'latency_ms': 1, 'prompt_tokens': 2, 'eval_tokens': 3, 'tokens_per_second': 4}))
        before = self.metadata()
        after = {**before, 'model_digest': 'sha256:changed'}
        client.get_serving_metadata = Mock(side_effect=[before, after])
        questions = [{'ticket_id': 'q1', 'tenant': 'heldout', 'customer_query': 'Unknown?',
                      'ground_truth_action': 'escalate', 'is_answerable': False, 'evidence_json': '[]'}]
        with tempfile.TemporaryDirectory() as directory, patch('src.evaluation.comparison.get_hardware_metadata', return_value={}):
            root = Path(directory)
            benchmark = root / 'benchmark.json'
            benchmark.write_text(json.dumps({'questions': questions}))
            original = benchmark.read_bytes()
            _, _, path = run_baseline_evaluation(client, None, questions, benchmark_file=benchmark,
                                                 output_dir=root, model_role='finetuned_student')
            saved = json.loads(path.read_text())
            self.assertEqual(saved['model_role'], 'finetuned_student')
            self.assertEqual(saved['serving_settings']['initial_model_digest'], 'sha256:one')
            self.assertTrue(saved['serving_settings']['identity_changed_during_run'])
            self.assertFalse(check_comparison_compatibility([saved]).is_compatible)
            self.assertEqual(benchmark.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
