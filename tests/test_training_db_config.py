import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.rag.db_config import resolve_training_db_name


class TrainingDbConfigTests(unittest.TestCase):
    def test_returns_training_name_not_production(self):
        env = {"MONGODB_DB_NAME": "rag_knowledge_base", "MONGODB_TRAINING_DB_NAME": " capstone_dev "}
        self.assertEqual(resolve_training_db_name(env), "capstone_dev")

    def test_unset_or_blank_fails_closed_and_never_uses_production(self):
        for env in ({"MONGODB_DB_NAME": "rag_knowledge_base"}, {"MONGODB_TRAINING_DB_NAME": "  "}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                resolve_training_db_name(env)

    def test_live_baseline_run_refuses_to_start_without_training_db(self):
        # Run from a directory with no .env so nothing can supply the variable.
        env = {k: v for k, v in os.environ.items() if k != "MONGODB_TRAINING_DB_NAME"}
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/run_baselines.py"), "--finetuned-models", "some-model",
                 "--context-mode", "retriever", "--limit", "1", "--output-dir", tmp],
                capture_output=True, text=True, env=env, cwd=tmp,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MONGODB_TRAINING_DB_NAME", result.stderr)


if __name__ == "__main__":
    unittest.main()
