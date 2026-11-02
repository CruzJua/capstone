"""Exercise export recovery without loading a GPU model or mounting Drive."""
import ast
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GGUFExportTests(unittest.TestCase):
    def helpers(self, name):
        notebook = json.loads((ROOT / 'notebooks' / name).read_text())
        source = next(''.join(c['source']) for c in notebook['cells'] if c['id'] == 'optional-gguf')
        tree = ast.parse(source)
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        namespace = {'Path': Path}
        exec(compile(tree, name, 'exec'), namespace)
        return namespace

    def test_all_formats_resume_after_partial_conversion_without_repeating_completed_export(self):
        for name in ('train_llama_qlora.ipynb', 'train_llama_qlora_kaggle.ipynb'):
            helpers = self.helpers(name)
            with self.subTest(notebook=name), tempfile.TemporaryDirectory() as directory:
                run = Path(directory)
                calls = []

                def export(method):
                    calls.append(method)
                    if method == 'q5_k_m' and calls.count(method) == 1:
                        raise RuntimeError('interrupted conversion')
                    output = run / 'gguf_gguf'
                    output.mkdir(exist_ok=True)
                    (output / f'model.{method.upper()}.gguf').write_bytes(b'GGUF' + b'\x00' * 100)

                def save(path, payload):
                    path.write_text(json.dumps(payload))

                methods = ['q4_k_m', 'q5_k_m', 'q8_0']
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    helpers['export_gguf_variants'](run, methods, export, save)
                partial = json.loads((run / 'gguf_export.json').read_text())
                self.assertFalse(partial['exports_complete'])
                self.assertEqual(partial['completed_quantizations'], ['q4_k_m'])
                result = helpers['export_gguf_variants'](run, methods, export, save)
                self.assertEqual(calls, ['q4_k_m', 'q5_k_m', 'q5_k_m', 'q8_0'])
                self.assertEqual(set(result), set(methods))
                final = json.loads((run / 'gguf_export.json').read_text())
                self.assertTrue(final['exports_complete'])
                self.assertEqual(len(final['files']), 3)
                self.assertTrue(all(entry['size_bytes'] == 104 for entries in final['exports'].values() for entry in entries))
                helpers['export_gguf_variants'](run, methods, lambda method: self.fail('Repeated conversion'), save)

    def test_invalid_selection_and_wrong_format_cannot_claim_export_success(self):
        for name in ('train_llama_qlora.ipynb', 'train_llama_qlora_kaggle.ipynb'):
            helpers = self.helpers(name)
            with self.subTest(notebook=name), tempfile.TemporaryDirectory() as directory:
                run = Path(directory)
                output = run / 'gguf'
                output.mkdir()
                (output / 'model.Q4_K_M.gguf').write_bytes(b'GGUF' + b'\x00' * 100)
                for methods in ([], ['q4_k_m', 'Q4_K_M'], ['q2_k'], 'q5_k_m'):
                    with self.assertRaises(ValueError):
                        helpers['export_gguf_variants'](run, methods, lambda method: self.fail('Invalid selection exported'), lambda *args: None)
                with self.assertRaisesRegex(RuntimeError, 'No Q5_K_M'):
                    helpers['export_gguf_variants'](run, ['q5_k_m'], lambda method: None, lambda *args: self.fail('Wrong format accepted'))
                self.assertTrue((output / 'model.Q4_K_M.gguf').exists())

    def test_recovery_in_both_standalone_notebooks(self):
        for name in ('train_llama_qlora.ipynb', 'train_llama_qlora_kaggle.ipynb'):
            notebook = json.loads((ROOT / 'notebooks' / name).read_text())
            source = next(''.join(c['source']) for c in notebook['cells'] if c['id'] == 'optional-gguf')
            tree = ast.parse(source)
            tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
            namespace = {'Path': Path}
            exec(compile(tree, name, 'exec'), namespace)
            collect = namespace['collect_gguf_export']
            with self.subTest(notebook=name), tempfile.TemporaryDirectory() as directory:
                run = Path(directory)
                self.assertEqual(collect(run), [])
                sibling = run / 'gguf_gguf'
                sibling.mkdir()
                source_file = sibling / 'Llama-3.2-3B-Instruct.Q4_K_M.gguf'
                payload = b'GGUF' + b'\x00' * 100
                source_file.write_bytes(payload)
                intermediate = sibling / 'model.F16.gguf'
                intermediate.write_bytes(payload)
                expected = run / 'gguf' / source_file.name
                self.assertEqual(collect(run), [expected])
                self.assertEqual(expected.read_bytes(), payload)
                self.assertFalse(source_file.exists())
                self.assertTrue(intermediate.exists())
                self.assertEqual(collect(run), [expected])
                source_file.write_bytes(payload + b'conflict')
                with self.assertRaises(FileExistsError):
                    collect(run)
                self.assertEqual(expected.read_bytes(), payload)
                source_file.unlink()
                expected.write_bytes(b'NOT GGUF' + b'\x00' * 100)
                with self.assertRaisesRegex(RuntimeError, 'header'):
                    collect(run)
                expected.write_bytes(b'GGUF')
                with self.assertRaisesRegex(RuntimeError, 'too small'):
                    collect(run)

    def test_existing_export_recovers_without_model_or_training(self):
        notebook = json.loads((ROOT / 'notebooks/train_llama_qlora.ipynb').read_text())
        source = next(''.join(c['source']) for c in notebook['cells'] if c['id'] == 'optional-gguf')
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            folder = run / 'gguf_gguf'
            folder.mkdir()
            (folder / 'model.Q4_K_M.gguf').write_bytes(b'GGUF' + b'\x00' * 100)
            saved = {}
            namespace = dict(Path=Path, EXPORT_GGUF=True, RUN_MODE='full', RUN_DIR=run,
                             save_json=lambda path, payload: saved.update(payload))
            # No model exists in this namespace: recovery must not invoke conversion.
            exec(compile(source, 'export-cell', 'exec'), namespace)
            self.assertEqual(saved['files'], [str(run / 'gguf/model.Q4_K_M.gguf')])
