"""Offline search planning, fair sampling, model isolation, and promotion checks."""

import ast
import contextlib
import gc
import io
import json
import math
import random
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks/train_llama_qlora_kaggle.ipynb"
DEFAULTS = {"learning_rate": 2e-4, "optimizer": "adamw_8bit", "lora_rank": 16,
            "lora_alpha": 16, "weight_decay": 0.01, "warmup_ratio": 0.03}


def search_helpers():
    notebook = json.loads(NOTEBOOK.read_text())
    namespace = dict(json=json, math=math, random=random, pd=pd, Path=Path, gc=gc, time=time)
    for cell in notebook["cells"]:
        if cell["id"] not in {"search-helpers", "search-engine", "input-file"}:
            continue
        tree = ast.parse("".join(cell["source"]))
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        exec(compile(tree, str(NOTEBOOK), "exec"), namespace)
    return namespace


class HyperparameterSearchTests(unittest.TestCase):
    def setUp(self):
        self.helpers = search_helpers()

    def test_grid_covers_cartesian_product_and_random_is_unique_reproducible_and_bounded(self):
        plan_search = self.helpers["build_search_plan"]
        space = {"learning_rate": [1e-4, 2e-4], "optimizer": ["adamw_8bit", "adamw_torch"]}
        plan, count = plan_search(space, DEFAULTS, "grid", 20, 42)
        self.assertEqual(count, 4)
        self.assertEqual({(item["hyperparameters"]["learning_rate"], item["hyperparameters"]["optimizer"]) for item in plan},
                         {(1e-4, "adamw_8bit"), (1e-4, "adamw_torch"), (2e-4, "adamw_8bit"), (2e-4, "adamw_torch")})
        first, _ = plan_search(space, DEFAULTS, "random", 3, 42)
        repeated, _ = plan_search(space, DEFAULTS, "random", 3, 42)
        self.assertEqual(first, repeated)
        self.assertEqual(len({json.dumps(item["hyperparameters"], sort_keys=True) for item in first}), 3)
        capped, _ = plan_search(space, DEFAULTS, "grid", 2, 42)
        self.assertEqual(capped, plan[:2])

    def test_bad_search_values_are_rejected_before_gpu_work(self):
        plan = self.helpers["build_search_plan"]
        for space in ({"learning_rate": []}, {"learning_rate": [float("nan")]},
                      {"learning_rate": [0]}, {"optimizer": ["unknown"]}, {"optimizer": [{}]},
                      {"lora_rank": [True]}, {"lora_alpha": [-1]}, {"batch_size": [2]}):
            with self.subTest(space=space), self.assertRaises(ValueError):
                plan(space, DEFAULTS, "grid", 4, 42)
        deduplicated, count = plan({"learning_rate": [1e-4, 1e-4]}, DEFAULTS, "grid", 5, 42)
        self.assertEqual(count, 1)
        self.assertEqual(len(deduplicated), 1)

    def test_real_subsets_preserve_strata_and_do_not_cross_splits(self):
        from test_training_notebook import notebook_helpers

        data_path = ROOT / "data/cleaned/train_tickets.csv"
        if not data_path.exists():
            self.skipTest("Prepared dataset not present")
        data_helpers = notebook_helpers()
        frame = data_helpers["validate_tickets"](pd.read_csv(data_path), "harbor_view", "label_and_rationale")
        train, validation = data_helpers["split_tickets"](frame, 0.1, 42)
        subset = self.helpers["stratified_ticket_subset"]
        train_subset, validation_subset = subset(train, 256, 42), subset(validation, 64, 43)
        self.assertEqual(len(train_subset), 256)
        self.assertEqual(len(validation_subset), 64)
        self.assertEqual(train_subset.ticket_id.tolist(), subset(train, 256, 42).ticket_id.tolist())
        self.assertFalse(set(train_subset.ticket_id) & set(validation_subset.ticket_id))
        self.assertFalse(set(train_subset.batch_key) & set(validation_subset.batch_key))
        for full, sampled in ((train, train_subset), (validation, validation_subset)):
            columns = ["business", "action", "is_answerable"]
            self.assertEqual(set(full.groupby(columns).groups), set(sampled.groupby(columns).groups))
            self.assertFalse(sampled.ticket_id.duplicated().any())
        with self.assertRaisesRegex(ValueError, "represent every"):
            subset(train, 2, 42)

    def test_failed_or_nonfinite_trials_cannot_win(self):
        rows = [
            {"trial_id": "a", "status": "failed", "validation_loss": 0.01},
            {"trial_id": "b", "status": "completed", "validation_loss": float("nan")},
            {"trial_id": "c", "status": "completed", "validation_loss": 1.2},
            {"trial_id": "d", "status": "completed", "validation_loss": 1.0},
            {"trial_id": "e", "status": "completed", "validation_loss": float("inf")},
        ]
        self.assertEqual([row["trial_id"] for row in self.helpers["rank_search_results"](rows)], ["d", "c"])

    def test_promotion_checks_metadata_and_reuses_search_csv_without_ambiguous_uploads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            best_path = root / "search/best_hyperparameters.json"
            best_path.parent.mkdir()
            expected = {"model_name": "base-model", "seed": 42}
            selected = {**DEFAULTS, "optimizer": "adamw_torch", "learning_rate": 1e-4}
            payload = {**expected, "search_complete": True, "hyperparameters": selected}
            best_path.write_text(json.dumps(payload))
            params, _ = self.helpers["load_promoted_parameters"](best_path, DEFAULTS, expected)
            self.assertEqual(params, selected)
            with self.assertRaisesRegex(ValueError, "mismatch"):
                self.helpers["load_promoted_parameters"](best_path, DEFAULTS, {**expected, "seed": 43})
            payload["search_complete"] = False
            best_path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "did not finish"):
                self.helpers["load_promoted_parameters"](best_path, DEFAULTS, expected)
            csv = best_path.parent / "input/train_tickets.csv"
            csv.parent.mkdir()
            csv.write_text("ticket_id\na\n")
            self.assertEqual(self.helpers["find_training_csv"]("", root / "missing", root, str(best_path)), csv)

    def test_trial_runner_builds_fresh_models_and_frees_optimizer_allocations(self):
        helpers = self.helpers
        token = SimpleNamespace(chat_template="template", pad_token_id=0, eos_token_id=1,
                                save_pretrained=Mock())
        load_model = Mock(side_effect=[(object(), token), (object(), token)])
        trainers = []

        def trainer_factory(**kwargs):
            trainer = Mock()
            trainer.evaluate.side_effect = [{"baseline_loss": 1.8}, {"selected_loss": 1.0}]
            checkpoint = Path(kwargs["args"].output_dir) / "checkpoint-60"
            trainer.state = SimpleNamespace(global_step=60, best_model_checkpoint=str(checkpoint),
                                            log_history=[{"step": 60, "loss": 1.1, "eval_loss": 1.0}])

            def train():
                checkpoint.mkdir(parents=True)
                return SimpleNamespace(metrics={"train_loss": 1.1})

            trainer.train.side_effect = train
            trainer.save_model.side_effect = lambda path: Path(path).mkdir(parents=True)
            trainers.append(trainer)
            return trainer

        def save_json(path, payload):
            Path(path).write_text(json.dumps(payload))

        helpers.update({
            "load_qlora_model": load_model, "tokenizer": token,
            "torch": SimpleNamespace(cuda=Mock()), "SFTTrainer": trainer_factory,
            "SFTConfig": lambda **kwargs: SimpleNamespace(**kwargs),
            "CheckpointAuditCallback": Mock(), "is_bfloat16_supported": lambda: False,
            "TRAIN_BATCH_SIZE": 1, "GRADIENT_ACCUMULATION_STEPS": 8,
            "SEARCH_MAX_STEPS": 60, "SEARCH_EVAL_STEPS": 30,
            "SEED": 42, "MAX_SEQ_LENGTH": 2048,
            "train_dataset": ["shared training samples"], "collator": object(),
            "save_json": save_json, "verify_checkpoint": lambda path: {"path": str(path)},
            "search_loss_plot": Mock(),
        })
        with tempfile.TemporaryDirectory() as directory:
            for index in range(2):
                result = helpers["run_search_trial"](
                    {"trial_id": f"trial_{index}", "hyperparameters": DEFAULTS},
                    Path(directory) / f"trial_{index}", ["shared validation samples"],
                )
                self.assertEqual(result["status"], "completed", result)
                self.assertEqual(result["optimizer_steps"], 60)
        self.assertEqual(load_model.call_count, 2)
        self.assertEqual(len(trainers), 2)
        for trainer in trainers:
            trainer.accelerator.free_memory.assert_called_once_with()
        self.assertEqual(helpers["torch"].cuda.empty_cache.call_count, 2)

    def test_search_orchestration_persists_best_and_resume_skips_completed_trials(self):
        helpers = self.helpers
        notebook = json.loads(NOTEBOOK.read_text())
        engine = next(cell for cell in notebook["cells"] if cell["id"] == "search-engine")
        tree = ast.parse("".join(engine["source"]))
        tree.body = [node for node in tree.body if isinstance(node, ast.If)]

        def save_json(path, payload):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps(payload))

        def fake_trial(spec, directory, scoring_dataset):
            directory.mkdir(parents=True)
            self.assertEqual(scoring_dataset, [0, 2])
            return {**spec, "status": "completed", "validation_loss": 1 / int(spec["trial_id"].split("_")[-1]),
                    "wall_seconds": 1.0, "directory": str(directory)}

        runner = Mock(side_effect=fake_trial)
        with tempfile.TemporaryDirectory() as directory:
            helpers.update({
                "RUN_MODE": "search", "RESUME": False, "RUN_DIR": Path(directory),
                "SEARCH_SPACE": {"learning_rate": [1e-4, 2e-4], "optimizer": ["adamw_8bit", "adamw_torch"]},
                "BASE_HYPERPARAMETERS": DEFAULTS, "SEARCH_METHOD": "grid", "SEARCH_MAX_TRIALS": 4,
                "SEARCH_MAX_STEPS": 60, "SEARCH_EVAL_STEPS": 30,
                "TRAIN_BATCH_SIZE": 1, "GRADIENT_ACCUMULATION_STEPS": 8,
                "MODEL_NAME": "test-model", "DATA_SHA256": "hash", "HELD_OUT_TENANT": "held_out",
                "SEED": 42, "VALIDATION_FRACTION": 0.1, "TASK_MODE": "label_and_rationale",
                "INCLUDE_SERVING_LABELS": True, "MAX_SEQ_LENGTH": 2048,
                "train_df": [0] * 8, "validation_df": [0] * 2, "train_dataset": [0] * 24,
                "validation_encoded": [{"task": "serving_label"}, {"task": "rationale"}, {"task": "serving_label"}],
                "validation_dataset": SimpleNamespace(select=lambda indices: indices),
                "importlib": SimpleNamespace(metadata=SimpleNamespace(version=lambda name: "test", distributions=lambda: [])),
                "torch": SimpleNamespace(cuda=SimpleNamespace(get_device_name=lambda index: "test-gpu")),
                "sys": SimpleNamespace(version="test-python"), "save_json": save_json,
                "run_search_trial": runner, "display": Mock(), "ALLOW_ENVIRONMENT_CHANGE": False,
            })
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(tree, str(NOTEBOOK), "exec"), helpers)
            best = json.loads((Path(directory) / "best_hyperparameters.json").read_text())
            self.assertTrue(best["search_complete"])
            self.assertEqual(best["best_trial_id"], "trial_004")
            self.assertEqual(best["successful_trials"], 4)
            self.assertEqual(best["objective"], "serving_label_completion_loss")
            self.assertTrue((Path(directory) / "search_results.csv").exists())
            self.assertEqual(runner.call_count, 4)
            helpers["RESUME"] = True
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(tree, str(NOTEBOOK), "exec"), helpers)
            self.assertEqual(runner.call_count, 4)


if __name__ == "__main__":
    unittest.main()
