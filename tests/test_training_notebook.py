"""Exercise the standalone Colab notebook's data/masking logic without a GPU."""

import ast
import json
import math
import random
import tempfile
import unittest
from html import escape
from pathlib import Path
from unittest.mock import Mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks/train_llama_qlora.ipynb"


def notebook_helpers():
    notebook = json.loads(NOTEBOOK.read_text())
    namespace = dict(json=json, math=math, random=random, escape=escape, Path=Path, pd=pd)
    helper_cells = {"input-file", "data-helpers", "example-helpers", "tokenization-helpers", "checkpoint-helpers"}
    for cell in notebook["cells"]:
        if cell["id"] not in helper_cells:
            continue
        tree = ast.parse("".join(cell["source"]))
        # Import no training stack and execute no runtime-specific top-level code.
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) or (
            isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in {"SUPPORT_SYSTEM_PROMPT", "TASK_SYSTEM_PROMPT"}
                for target in node.targets
            )
        )]
        exec(compile(tree, str(NOTEBOOK), "exec"), namespace)
    return namespace


class TinyChatTokenizer:
    """Deterministic template stand-in for checking boundaries, not token quality."""

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        assert tokenize
        text = "".join(f"<{turn['role']}>\n{turn['content']}<end>" for turn in messages)
        if add_generation_prompt:
            text += "<assistant>\n"
        return list(text.encode("utf-8"))


class TrainingNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helpers = notebook_helpers()

    def setUp(self):
        self.frame = pd.DataFrame([
            {
                "ticket_id": f"{tenant}-{batch}-{index}",
                "batch_key": f"{tenant}-{batch}", "business": tenant,
                "customer_query": f"Question {tenant} {batch} {index}?",
                "answer": "TEACHER TARGET MUST NOT APPEAR IN PROMPT",
                "action": "answer" if index == 0 else "escalate",
                "confidence": 0.9 if index == 0 else 0.2,
                "is_answerable": index == 0,
                "rationale": "RATIONALE TARGET MUST NOT APPEAR IN LABEL PROMPT",
                "evidence_json": json.dumps([{"source": "policy.md", "quote": "Grounded rule."}]) if index == 0 else "[]",
                "messages_json": json.dumps([
                    {"role": "customer", "content": f"Question {tenant} {batch} {index}?"},
                    {"role": "agent", "content": "TEACHER TARGET MUST NOT APPEAR IN PROMPT"},
                ]),
            }
            for tenant in ("tenant_a", "tenant_b") for batch in range(5) for index in range(2)
        ])

    def validated(self):
        return self.helpers["validate_tickets"](self.frame, "held_out", "label_and_rationale")

    def test_files_sidebar_input_is_cached_and_reused_without_widget(self):
        read_input = self.helpers["read_training_input"]
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime/train_tickets.csv"
            cache = Path(directory) / "drive/input/train_tickets.csv"
            runtime.parent.mkdir()
            self.frame.to_csv(runtime, index=False)
            widget = Mock(side_effect=AssertionError("Should not call upload widget"))
            path, frame = read_input("runtime", runtime, "unused", cache, widget)
            self.assertEqual(path, cache)
            self.assertEqual(len(frame), len(self.frame))
            self.assertEqual(cache.read_bytes(), runtime.read_bytes())
            runtime.unlink()
            _, repeated = read_input("runtime", runtime, "unused", cache, widget)
            self.assertEqual(len(repeated), len(self.frame))
            widget.assert_not_called()

    def test_widget_failure_explains_recovery_without_creating_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "input/train_tickets.csv"
            error = Exception("MessageError")
            widget = Mock(side_effect=error)
            with self.assertRaisesRegex(RuntimeError, "Files sidebar") as raised:
                self.helpers["read_training_input"]("upload", "unused", "unused", cache, widget)
            self.assertIs(raised.exception.__cause__, error)
            self.assertFalse(cache.exists())

    def test_widget_retries_reuse_completed_cache(self):
        read_input = self.helpers["read_training_input"]
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "input/train_tickets.csv"
            widget = Mock(return_value={"train_tickets.csv": self.frame.to_csv(index=False).encode()})
            read_input("upload", "unused", "unused", cache, widget)
            read_input("upload", "unused", "unused", cache, widget)
            widget.assert_called_once_with()

    def test_notebook_is_colab_ready_and_code_compiles(self):
        notebook = json.loads(NOTEBOOK.read_text())
        self.assertEqual(notebook["nbformat"], 4)
        self.assertEqual(notebook["metadata"]["accelerator"], "GPU")
        self.assertEqual(len({cell["id"] for cell in notebook["cells"]}), len(notebook["cells"]))
        for cell in notebook["cells"]:
            if cell["cell_type"] != "code":
                continue
            self.assertEqual(cell["outputs"], [])
            self.assertIsNone(cell["execution_count"])
            source = "".join(cell["source"])
            # The installation cell is the only IPython magic.
            if cell["id"] == "install":
                self.assertTrue(source.startswith("%pip install"))
            else:
                compile(source, f"{NOTEBOOK}:{cell['id']}", "exec")

    def test_entire_real_training_dataset_can_be_formatted(self):
        dataset = ROOT / "data/cleaned/train_tickets.csv"
        if not dataset.is_file():
            self.skipTest("Prepared training CSV is not present.")
        frame = self.helpers["validate_tickets"](pd.read_csv(dataset), "harbor_view", "label_and_rationale")
        train, validation = self.helpers["split_tickets"](frame, 0.1, 42)
        for part in (train, validation):
            examples = self.helpers["build_task_examples"](part, "label_and_rationale", True)
            self.assertEqual(len(examples), 3 * len(part))
        self.assertEqual(len(train) + len(validation), len(frame))

    def test_split_is_reproducible_with_no_ticket_or_batch_leakage(self):
        frame = self.validated()
        split = self.helpers["split_tickets"]
        train, validation = split(frame, 0.2, 42)
        repeated_train, repeated_validation = split(frame, 0.2, 42)
        self.assertEqual(train.ticket_id.tolist(), repeated_train.ticket_id.tolist())
        self.assertEqual(validation.ticket_id.tolist(), repeated_validation.ticket_id.tolist())
        self.assertFalse(set(train.ticket_id) & set(validation.ticket_id))
        self.assertFalse(set(train.batch_key) & set(validation.batch_key))
        self.assertEqual(set(train.business), {"tenant_a", "tenant_b"})
        self.assertEqual(set(validation.business), {"tenant_a", "tenant_b"})

    def test_held_out_tenant_and_invalid_targets_are_rejected(self):
        validate = self.helpers["validate_tickets"]
        with self.assertRaisesRegex(ValueError, "Held-out"):
            validate(self.frame, "tenant_a", "label_and_rationale")
        for column, value in (("confidence", 1.2), ("is_answerable", "unknown"), ("action", "invent")):
            bad = self.frame.copy().astype({column: object})
            bad.loc[0, column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                validate(bad, "held_out", "label_and_rationale")
        duplicate = pd.concat([self.frame, self.frame.iloc[:1]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "Duplicate ticket"):
            validate(duplicate, "held_out", "label_and_rationale")

    def test_targets_and_final_teacher_reply_are_excluded_from_prompts(self):
        examples = self.helpers["build_task_examples"](self.validated().iloc[:2], "label_and_rationale", True)
        self.assertEqual(len(examples), 6)
        for example in examples:
            prompt = "\n".join(turn["content"] for turn in example["messages"][:-1])
            self.assertNotIn("TEACHER TARGET", prompt)
            self.assertNotIn("RATIONALE TARGET", prompt)
            if example["task"] != "rationale":
                target = json.loads(example["messages"][-1]["content"])
                self.assertEqual(set(target), {"answer", "cited_sources", "confidence", "action"})
                self.assertEqual(target["cited_sources"], ["policy.md"] if target["action"] == "answer" else [])

    def test_multiturn_history_is_retained_before_last_customer(self):
        row = self.validated().iloc[0].to_dict()
        row["messages_json"] = json.dumps([
            {"role": "customer", "content": "Earlier question"},
            {"role": "agent", "content": "Earlier agent response"},
            {"role": "customer", "content": row["customer_query"]},
            {"role": "agent", "content": row["answer"]},
        ])
        prompt = self.helpers["ticket_user_prompt"](row)
        self.assertIn("Customer: Earlier question", prompt)
        self.assertIn("Support: Earlier agent response", prompt)
        self.assertNotIn(row["answer"], prompt)

    def test_answerable_human_escalation_keeps_its_label(self):
        frame = self.frame.copy()
        frame.loc[0, "action"] = "escalate"
        frame = self.helpers["validate_tickets"](frame, "held_out", "label_and_rationale")
        example = self.helpers["build_task_examples"](frame.iloc[:1], "label_only", False)[0]
        target = json.loads(example["messages"][-1]["content"])
        self.assertEqual(target["action"], "escalate")
        self.assertEqual(target["cited_sources"], [])
        self.assertIn("Grounded rule", example["messages"][1]["content"])

    def test_serving_examples_match_existing_client_prompt(self):
        from src.inference.client import SYSTEM_PROMPT, SupportInferenceClient

        row = self.validated().iloc[0]
        examples = self.helpers["build_task_examples"](self.validated().iloc[:1], "label_only", True)
        serving = next(example for example in examples if example["task"] == "serving_label")
        self.assertEqual(serving["messages"][0]["content"], SYSTEM_PROMPT)
        context = self.helpers["format_evidence"](row["evidence"])
        self.assertEqual(serving["messages"][1]["content"],
                         SupportInferenceClient.build_user_prompt(row["customer_query"], context))

    def test_completion_mask_and_no_silent_truncation(self):
        examples = self.helpers["build_task_examples"](self.validated().iloc[:1], "label_and_rationale", True)
        tokenize = self.helpers["tokenize_examples"]
        encoded = tokenize(examples, TinyChatTokenizer(), 10000)
        for row in encoded:
            first_target = next(index for index, label in enumerate(row["labels"]) if label != -100)
            self.assertGreater(first_target, 0)
            self.assertEqual(row["labels"][:first_target], [-100] * first_target)
            self.assertEqual(row["labels"][first_target:], row["input_ids"][first_target:])
            self.assertEqual(len(row["labels"]), len(row["attention_mask"]))
        with self.assertRaisesRegex(ValueError, "exceed MAX_SEQ_LENGTH"):
            tokenize(examples, TinyChatTokenizer(), 8)

    def test_checkpoint_audit_requires_full_resumable_state(self):
        verify = self.helpers["verify_checkpoint"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "Incomplete checkpoint"):
                verify(path)
            for filename in ("adapter_config.json", "optimizer.pt", "scheduler.pt", "adapter_model.safetensors", "rng_state.pth"):
                (path / filename).write_bytes(b"fixture")
            (path / "trainer_state.json").write_text(json.dumps({"global_step": 10, "epoch": 0.25}))
            self.assertEqual(verify(path)["global_step"], 10)
            (path / "optimizer.pt").write_bytes(b"")
            with self.assertRaisesRegex(RuntimeError, "optimizer.pt"):
                verify(path)


if __name__ == "__main__":
    unittest.main()
