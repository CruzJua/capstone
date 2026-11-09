import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_baselines import describe_retriever_settings, write_retriever_settings_sidecar
from src.evaluation import generation


def fake_retriever(prefix="Represent: "):
    return SimpleNamespace(
        client=object(), db=SimpleNamespace(name="capstone_dev"), collection=SimpleNamespace(name="doc_vectors"),
        index_name="vector_index", query_prefix=prefix, reranker_model_name=None, min_rerank_score=None,
    )


class RetrieverSettingsTests(unittest.TestCase):
    def test_describes_prefix_reranker_and_database(self):
        settings = describe_retriever_settings(fake_retriever())
        self.assertTrue(settings["query_prefix_enabled"])
        self.assertEqual(settings["reranker"], "off")
        self.assertEqual(settings["relevance_cutoff"], "none")
        self.assertEqual(settings["database"], "capstone_dev")
        self.assertEqual(settings["backend"], "MongoDB Atlas")

    def test_prefix_off_and_offline_label(self):
        retriever = fake_retriever(prefix="")
        retriever.client = None
        settings = describe_retriever_settings(retriever)
        self.assertFalse(settings["query_prefix_enabled"])
        self.assertIn("not Atlas", settings["backend"])

    def test_sidecar_is_written_once_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "baseline_eval_x_retriever_1.json"
            log.write_text("{}")
            sidecar = write_retriever_settings_sidecar(log, fake_retriever(), "m")
            self.assertEqual(json.loads(sidecar.read_text())["model"], "m")
            with self.assertRaises(FileExistsError):
                write_retriever_settings_sidecar(log, fake_retriever(), "m")

    def test_initialize_services_passes_prefix_override(self):
        with patch("src.inference.client.SupportInferenceClient"), \
                patch("src.rag.retriever.RAGRetriever") as retriever_cls:
            generation.initialize_services("m", use_retriever=True)
            retriever_cls.assert_called_with(query_prefix=None, db_name=None)
            generation.initialize_services("m", use_retriever=True, query_prefix="", db_name="capstone_dev")
            retriever_cls.assert_called_with(query_prefix="", db_name="capstone_dev")


if __name__ == "__main__":
    unittest.main()
