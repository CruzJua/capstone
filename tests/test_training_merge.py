import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.generation.training_merge import (attach_contexts, build_catalog, load_notebook_helpers,
                                           merge_training_data, realistic_context)

ROOT = Path(__file__).resolve().parent.parent
V2_NOTEBOOK = ROOT / "notebooks/train_llama_qlora_kaggle_v2.ipynb"
V1_NOTEBOOK = ROOT / "notebooks/train_llama_qlora_kaggle.ipynb"

POLICY = "# Returns\n\nItems may be returned within 30 days for a full refund.\n"
GIFT = "# FAQ\n\nGift cards never expire and can be used in store.\n"
SHIP = "# Shipping\n\nStandard shipping takes five business days.\n"


def make_row(ticket_id, query, action="answer", reason="none", answerable=True, evidence=None,
             interaction_type="single_qa", batch_key="acme-0001"):
    return {"ticket_id": ticket_id, "batch_key": batch_key, "business": "acme",
            "interaction_type": interaction_type, "category": "returns", "action": action,
            "is_answerable": answerable, "escalation_reason": reason, "confidence": 0.9,
            "customer_query": query, "answer": "A.", "rationale": "R.", "ticket_summary": "",
            "num_messages": 1,
            "messages_json": json.dumps([{"role": "customer", "content": query}]),
            "evidence_json": json.dumps(evidence or [])}


def doc(doc_id, text, section="s"):
    return {"tenant_id": "acme", "doc_id": doc_id, "section": section, "text": text}


class V2NotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v2 = load_notebook_helpers(V2_NOTEBOOK)

    def frame(self, rows):
        return pd.DataFrame(rows)

    def row(self, **extra):
        base = make_row("t1", "How long do I have to return it?",
                        evidence=[{"source": "RETURNS.md", "quote": "returned within 30 days"}])
        base.update(extra)
        return base

    def test_context_is_shown_but_only_evidence_is_cited(self):
        context = [{"source": "RETURNS.md", "section": "", "quote": "Items may be returned within 30 days for a refund."},
                   {"source": "FAQ.md", "section": "", "quote": "Gift cards never expire."}]
        frame = self.v2["validate_tickets"](self.frame([self.row(context_json=json.dumps(context))]), "other", "label_and_rationale")
        examples = self.v2["build_task_examples"](frame, "label_and_rationale", True)
        prompt = examples[0]["messages"][1]["content"]
        self.assertIn("Gift cards never expire.", prompt)
        self.assertEqual(json.loads(examples[0]["messages"][-1]["content"])["cited_sources"], ["RETURNS.md"])

    def test_escalation_with_context_and_no_evidence_is_valid(self):
        row = make_row("t2", "Do you ship to Mars?", action="escalate", reason="not_in_docs", answerable=False)
        row["context_json"] = json.dumps([{"source": "SHIP.md", "section": "", "quote": "Standard shipping takes five days."}])
        frame = self.v2["validate_tickets"](self.frame([row]), "other", "label_and_rationale")
        prompt = self.v2["build_task_examples"](frame, "label_and_rationale", True)[0]["messages"][1]["content"]
        self.assertIn("Standard shipping takes five days.", prompt)
        self.assertNotIn("(no relevant documents found)", prompt)

    def test_cited_evidence_must_be_shown(self):
        row = self.row(context_json=json.dumps([{"source": "FAQ.md", "section": "", "quote": "Gift cards never expire."}]))
        with self.assertRaisesRegex(ValueError, "not shown in the context"):
            self.v2["validate_tickets"](self.frame([row]), "other", "label_and_rationale")

    def test_empty_context_and_unanswerable_with_evidence_are_rejected(self):
        with self.assertRaises(ValueError):
            self.v2["validate_tickets"](self.frame([self.row(context_json="[]")]), "other", "label_and_rationale")
        bad = make_row("t3", "Q?", action="escalate", reason="not_in_docs", answerable=False,
                       evidence=[{"source": "A.md", "quote": "something"}])
        with self.assertRaises(ValueError):
            self.v2["validate_tickets"](self.frame([bad]), "other", "label_and_rationale")

    def test_csv_without_context_column_behaves_like_v1(self):
        rows = [self.row(), make_row("t4", "Other question?", action="escalate", reason="not_in_docs", answerable=False)]
        for notebook in (self.v2, load_notebook_helpers(V1_NOTEBOOK)):
            frame = notebook["validate_tickets"](self.frame(rows), "other", "label_and_rationale")
            prompt = notebook["build_task_examples"](frame, "label_and_rationale", True)[0]["messages"][1]["content"]
            self.assertIn("returned within 30 days", prompt)
        self.assertEqual(V1_NOTEBOOK.name, "train_llama_qlora_kaggle.ipynb")


class RealisticContextTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)
        tenant = self.root / "acme"
        tenant.mkdir()
        for name, text in (("RETURNS.md", POLICY), ("GIFT.md", GIFT), ("SHIP.md", SHIP)):
            (tenant / name).write_text(text, encoding="utf-8")
        self.docs = [doc("RETURNS", "Items may be returned within 30 days for a full refund."),
                     doc("GIFT", "Gift cards never expire and can be used in store."),
                     doc("SHIP", "Standard shipping takes five business days.")]
        self.catalog = build_catalog(self.docs, self.root)

    def retrieve_without_gold(self, query, tenant):
        return [self.docs[1], self.docs[2]]

    def test_missing_gold_chunk_is_inserted(self):
        row = make_row("t1", "Return window?", evidence=[{"source": "RETURNS.md", "quote": "returned within 30 days for a full refund"}])
        context = realistic_context(row, self.retrieve_without_gold, self.catalog, self.root)
        self.assertEqual(len(context), 3)
        self.assertTrue(any("returned within 30 days" in c["quote"] for c in context))

    def test_gold_already_retrieved_is_not_duplicated(self):
        row = make_row("t1", "Return window?", evidence=[{"source": "RETURNS.md", "quote": "returned within 30 days"}])
        context = realistic_context(row, lambda q, t: self.docs, self.catalog, self.root)
        self.assertEqual(sum("returned within 30 days" in c["quote"] for c in context), 1)

    def test_unlocatable_citation_falls_back_to_the_quote_itself(self):
        row = make_row("t1", "Q?", evidence=[{"source": "FAQ-ABC-001", "quote": "a quote that is in no chunk"}])
        context = realistic_context(row, self.retrieve_without_gold, self.catalog, self.root)
        self.assertTrue(any(c["quote"] == "a quote that is in no chunk" for c in context))

    def test_budget_trims_other_chunks_but_never_the_gold(self):
        row = make_row("t1", "Return window?", evidence=[{"source": "RETURNS.md", "quote": "returned within 30 days"}])
        context = realistic_context(row, self.retrieve_without_gold, self.catalog, self.root, max_chars=130, max_chunks=4)
        self.assertTrue(any("returned within 30 days" in c["quote"] for c in context))
        self.assertLessEqual(sum(len(c["quote"]) for c in context), 130)


class MergeTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)
        (self.root / "acme").mkdir()
        (self.root / "acme" / "RETURNS.md").write_text(POLICY, encoding="utf-8")
        self.base = pd.DataFrame([
            make_row("acme-0001_t0", "Return window?", evidence=[{"source": "RETURNS.md", "quote": "returned within 30 days"}]),
            make_row("acme-0001_t1", "Do you ship to Mars?", action="escalate", reason="not_in_docs", answerable=False,
                     interaction_type="unanswerable"),
            make_row("acme-0002_t0", "Bogus citation?", evidence=[{"source": "RETURNS.md", "quote": "refunds take ninety days"}],
                     batch_key="acme-0002"),
            make_row("acme-0003_t0", "Leftover absent question?", action="escalate", reason="not_in_docs",
                     answerable=False, interaction_type="unanswerable", batch_key="acme-0003"),
        ])
        self.plan = {"acme-hn0000": {"business": "acme", "source_ticket_id": "acme-0001_t1",
                                    "context": [{"source": "RETURNS.md", "section": "", "quote": "Items may be returned."}]}}
        self.hardneg = pd.DataFrame([make_row(
            "acme-hn0000_t0", "Do you ship to Mars?", action="escalate", reason="not_in_docs", answerable=True,
            interaction_type="retrieval_distractor", batch_key="acme-hn0000",
            evidence=[{"source": "RETURNS.md", "quote": "Items may be returned."}])])

    def test_merge_quarantines_replaces_and_reuses_batch_key(self):
        merged, report = merge_training_data(self.base, self.hardneg, self.plan, self.root)
        self.assertEqual(set(merged["ticket_id"]), {"acme-0001_t0", "acme-0003_t0", "acme-hn0000_t0"})
        self.assertEqual(report["quarantined_ids" if "quarantined_ids" in report else "quarantined_ticket_ids"], ["acme-0002_t0"])
        self.assertEqual(merged.set_index("ticket_id").loc["acme-hn0000_t0", "batch_key"], "acme-0001")
        self.assertEqual(self.base["batch_key"].iloc[1], "acme-0001")  # inputs untouched

    def test_replacement_must_ask_the_same_question(self):
        self.hardneg.loc[0, "customer_query"] = "A different question?"
        with self.assertRaisesRegex(ValueError, "original question"):
            merge_training_data(self.base, self.hardneg, self.plan, self.root)

    def test_attach_contexts_restores_answerability_and_drops_unverified_rows(self):
        merged, _ = merge_training_data(self.base, self.hardneg, self.plan, self.root)
        catalog = build_catalog([doc("RETURNS", "Items may be returned within 30 days for a full refund.")], self.root)
        out, report = attach_contexts(merged, self.plan, lambda q, t: [doc("RETURNS", "Items may be returned within 30 days for a full refund.")],
                                      catalog, self.root)
        by_id = out.set_index("ticket_id")
        self.assertEqual(report["dropped_without_verified_context"], ["acme-0003_t0"])
        self.assertNotIn("acme-0003_t0", by_id.index)
        distractor = by_id.loc["acme-hn0000_t0"]
        self.assertEqual(distractor["evidence_json"], "[]")
        self.assertFalse(distractor["is_answerable"])
        self.assertTrue(json.loads(distractor["context_json"]))
        self.assertTrue(json.loads(by_id.loc["acme-0001_t0", "context_json"]))


if __name__ == "__main__":
    unittest.main()
