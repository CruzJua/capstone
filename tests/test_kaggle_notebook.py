"""Check unattended input and checkpoint restoration without a Kaggle account."""

import ast
import json
import shutil
import tempfile
import unittest
from pathlib import Path


NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks/train_llama_qlora_kaggle.ipynb"


class KaggleNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notebook = json.loads(NOTEBOOK.read_text())
        cls.helpers = {"Path": Path, "json": json, "shutil": shutil}
        for cell in cls.notebook["cells"]:
            if cell["id"] not in {"input-file", "storage"}:
                continue
            tree = ast.parse("".join(cell["source"]))
            tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
            exec(compile(tree, str(NOTEBOOK), "exec"), cls.helpers)

    def test_code_compiles_and_has_no_interactive_colab_dependencies(self):
        for cell in self.notebook["cells"]:
            if cell["cell_type"] != "code":
                continue
            source = "".join(cell["source"])
            if cell["id"] == "install":
                self.assertTrue(source.startswith("%pip install"))
                continue
            compile(source, f"{NOTEBOOK}:{cell['id']}", "exec")
            for interactive_call in ("google.colab", "drive.mount(", "files.upload(", "input("):
                self.assertNotIn(interactive_call, source)
            self.assertEqual(cell["outputs"], [])

    def test_input_discovery_requires_one_attached_csv_and_can_use_cache(self):
        find_csv = self.helpers["find_training_csv"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "output/input/train_tickets.csv"
            inputs = root / "attached"
            inputs.mkdir()
            with self.assertRaisesRegex(ValueError, "found 0"):
                find_csv("", cache, inputs)
            csv = inputs / "dataset/train_tickets.csv"
            csv.parent.mkdir()
            csv.write_text("ticket_id\na\n")
            self.assertEqual(find_csv("", cache, inputs), csv)
            second = inputs / "second/train_tickets.csv"
            second.parent.mkdir()
            second.write_text("ticket_id\nb\n")
            with self.assertRaisesRegex(ValueError, "found 2"):
                find_csv("", cache, inputs)
            self.assertEqual(find_csv(str(csv), cache, inputs), csv)
            cache.parent.mkdir(parents=True)
            cache.write_text(csv.read_text())
            self.assertEqual(find_csv("", cache, inputs), cache)

    def test_resume_copies_artifacts_and_relocates_best_checkpoint_without_changing_input(self):
        restore = self.helpers["restore_run_folder"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "attached/run", root / "working/run"
            checkpoint = source / "checkpoints/checkpoint-50"
            checkpoint.mkdir(parents=True)
            (source / "run_config.json").write_text('{"run_name":"run"}')
            original_state = {"global_step": 50, "best_model_checkpoint": "/content/drive/MyDrive/old/run/checkpoints/checkpoint-50"}
            (checkpoint / "trainer_state.json").write_text(json.dumps(original_state))
            (checkpoint / "adapter_model.safetensors").write_bytes(b"fixture")
            restore(source, destination)
            restored_state = json.loads((destination / "checkpoints/checkpoint-50/trainer_state.json").read_text())
            self.assertEqual(restored_state["best_model_checkpoint"], str(destination / "checkpoints/checkpoint-50"))
            self.assertEqual(json.loads((checkpoint / "trainer_state.json").read_text()), original_state)
            self.assertTrue((destination / "checkpoints/checkpoint-50/adapter_model.safetensors").is_file())
            with self.assertRaises(FileExistsError):
                restore(source, destination)

    def test_resume_does_not_ignore_missing_best_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "attached"
            checkpoint = source / "checkpoints/checkpoint-100"
            checkpoint.mkdir(parents=True)
            (source / "run_config.json").write_text("{}")
            (checkpoint / "trainer_state.json").write_text(json.dumps({
                "global_step": 100, "best_model_checkpoint": "/old/checkpoint-50",
            }))
            with self.assertRaisesRegex(FileNotFoundError, "best checkpoint is missing"):
                self.helpers["restore_run_folder"](source, root / "output")


if __name__ == "__main__":
    unittest.main()
