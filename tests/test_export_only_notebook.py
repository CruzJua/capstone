"""Exercise fresh-session export with synthetic files and a fake model loader."""

import ast
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks/export_gguf_kaggle.ipynb"


class ExportOnlyNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notebook = json.loads(NOTEBOOK.read_text())
        cls.code = {cell['id']: ''.join(cell['source']) for cell in cls.notebook['cells']
                    if cell['cell_type'] == 'code'}

    def fixture(self, root, name='full-run', mode='full'):
        run = root / name
        adapter = run / 'adapter'
        adapter.mkdir(parents=True)
        (run / 'run_config.json').write_text(json.dumps({
            'run_name': name, 'run_mode': mode, 'max_seq_length': 2048,
        }))
        (run / 'run_summary.json').write_text(json.dumps({
            'run_mode': mode, 'optimizer_steps': 100, 'all_recorded_losses_finite': True,
            'smoke_test_only': mode == 'smoke',
        }))
        (adapter / 'adapter_config.json').write_text('{"base_model_name_or_path":"test-base"}')
        (adapter / 'adapter_model.safetensors').write_bytes(b'synthetic adapter fixture')
        (adapter / 'tokenizer_config.json').write_text('{"chat_template":"saved-template"}')
        (adapter / 'tokenizer.json').write_text('{}')
        return run

    def helpers(self):
        # Execute the real configuration and helper cells, without installation,
        # Unsloth imports, model loading, or global changes to GPU visibility.
        namespace = {}
        with patch.dict(os.environ):
            exec(compile(self.code['configuration'], str(NOTEBOOK), 'exec'), namespace)
            exec(compile(self.code['export-helpers'], str(NOTEBOOK), 'exec'), namespace)
        return namespace

    def fingerprints(self, root):
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob('*') if path.is_file()}

    def test_notebook_code_compiles_without_training_or_generation_calls(self):
        self.assertEqual(self.notebook['metadata']['accelerator'], 'GPU')
        ids = [cell['id'] for cell in self.notebook['cells']]
        self.assertEqual(len(ids), len(set(ids)))
        for cell in self.notebook['cells']:
            if cell['cell_type'] != 'code':
                continue
            self.assertEqual(cell['outputs'], [])
            self.assertIsNone(cell['execution_count'])
            source = ''.join(cell['source'])
            if cell['id'] == 'install':
                self.assertTrue(source.startswith('%pip install'))
                continue
            tree = ast.parse(source)
            compile(tree, f"{NOTEBOOK}:{cell['id']}", 'exec')
            calls = [node.func.attr for node in ast.walk(tree)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
            self.assertFalse(set(calls) & {'train', 'fit', 'generate', 'get_peft_model'})
            self.assertNotIn('google.colab', source)

    def test_fresh_kernel_runs_all_noninstall_cells_in_order_and_reuses_exports(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ):
            os.environ.pop('HF_TOKEN', None)
            root = Path(directory)
            run = self.fixture(root / 'inputs')
            before = self.fingerprints(run)
            model = Mock()

            def save_gguf(path, tokenizer, quantization_method):
                self.assertEqual(tokenizer.chat_template, 'saved-template')
                path = Path(str(path) + '_gguf')
                path.mkdir(parents=True, exist_ok=True)
                (path / f'model.{quantization_method.upper()}.gguf').write_bytes(b'GGUF' + b'\x00' * 100)

            model.save_pretrained_gguf.side_effect = save_gguf
            loader = Mock(return_value=(model, SimpleNamespace(chat_template='loader-default')))
            fake_unsloth = SimpleNamespace(FastLanguageModel=SimpleNamespace(from_pretrained=loader))
            fake_secrets = SimpleNamespace(UserSecretsClient=lambda: SimpleNamespace(get_secret=lambda name: None))
            namespace = {}
            with patch.dict('sys.modules', {'unsloth': fake_unsloth, 'kaggle_secrets': fake_secrets}):
                for cell in self.notebook['cells']:
                    if cell['cell_type'] != 'code' or cell['id'] == 'install':
                        continue
                    exec(compile(''.join(cell['source']), str(NOTEBOOK), 'exec'), namespace)
                    if cell['id'] == 'configuration':
                        # The only user-selected inputs in a new Kaggle session.
                        namespace['SOURCE_RUN_DIR'] = str(run)
                        namespace['OUTPUT_ROOT'] = root / 'output'
                loader.assert_called_once_with(model_name=str(run / 'adapter'), max_seq_length=2048,
                                               dtype=None, load_in_4bit=True, token=None)
                self.assertEqual(model.save_pretrained_gguf.call_count, 3)
                output = root / 'output/full-run'
                manifest = json.loads((output / 'gguf_export.json').read_text())
                self.assertTrue(manifest['exports_complete'])
                self.assertEqual(manifest['completed_quantizations'], ['q4_k_m', 'q5_k_m', 'q8_0'])
                self.assertEqual(len(list((output / 'gguf').glob('*.gguf'))), 3)
                self.assertTrue((output / 'source_provenance.json').is_file())
                exec(compile(self.code['reload-and-export'], str(NOTEBOOK), 'exec'), namespace)
                self.assertEqual(loader.call_count, 1)
                self.assertEqual(model.save_pretrained_gguf.call_count, 3)
                self.assertEqual(self.fingerprints(run), before)

    def test_search_smoke_missing_adapter_and_missing_tokenizer_rejected_before_load(self):
        helpers = self.helpers()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mode in ('search', 'smoke'):
                run = self.fixture(root, mode, mode)
                with self.assertRaisesRegex(ValueError, 'FULL'):
                    helpers['inspect_full_run'](run)
            full = self.fixture(root)
            (full / 'adapter/adapter_model.safetensors').unlink()
            with self.assertRaisesRegex(FileNotFoundError, 'weights'):
                helpers['inspect_full_run'](full)
            (full / 'adapter/adapter_model.safetensors').write_bytes(b'fixture')
            (full / 'adapter/tokenizer.json').unlink()
            with self.assertRaisesRegex(FileNotFoundError, 'tokenizer'):
                helpers['inspect_full_run'](full)

    def test_auto_discovery_avoids_arbitrary_model_selection(self):
        helpers = self.helpers()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.fixture(root, 'first-full')
            self.fixture(root, 'screening', 'search')
            self.assertEqual(helpers['find_full_run']('', root)['source_run_dir'], str(first))
            self.fixture(root, 'second-full')
            with self.assertRaisesRegex(ValueError, 'found 2'):
                helpers['find_full_run']('', root)
            self.assertEqual(helpers['find_full_run'](str(first), root)['source_run_dir'], str(first))

    def test_changed_source_cannot_reuse_old_outputs_and_source_cannot_be_output(self):
        helpers = self.helpers()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.fixture(root / 'input')
            with self.assertRaisesRegex(ValueError, 'separate'):
                helpers['prepare_export'](str(run), run)
            context = helpers['prepare_export'](str(run), root / 'output')
            self.assertEqual(helpers['prepare_export'](str(run), root / 'output'), context)
            (run / 'adapter/adapter_model.safetensors').write_bytes(b'different model')
            with self.assertRaisesRegex(ValueError, 'different source'):
                helpers['prepare_export'](str(run), root / 'output')

    def test_shared_export_helpers_match_training_notebooks(self):
        helpers = ast.parse(self.code['export-helpers'])
        names = {'validate_gguf_quantizations', 'collect_gguf_export', 'export_gguf_variants'}
        selected = lambda tree: [ast.dump(node, include_attributes=False) for node in tree.body
                                 if isinstance(node, ast.FunctionDef) and node.name in names]
        for name in ('train_llama_qlora.ipynb', 'train_llama_qlora_kaggle.ipynb'):
            training = json.loads((ROOT / 'notebooks' / name).read_text())
            source = ''.join(next(cell['source'] for cell in training['cells'] if cell['id'] == 'optional-gguf'))
            self.assertEqual(selected(helpers), selected(ast.parse(source)))


if __name__ == '__main__':
    unittest.main()
