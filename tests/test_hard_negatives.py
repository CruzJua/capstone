import argparse
import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import business_data_cleaner as cleaner
from scripts import business_data_generator as generator
from src.documents.quality import screen_cited_quotes
from src.generation import hard_negatives as hn

POLICY = "# Returns\n\nItems may be returned within 30 days for a full refund.\n\nShipping is free over $50.\n"
OTHER = "# FAQ\n\nGift cards never expire and can be used in store.\n"


def make_data_root(root: Path) -> Path:
    tenant = root / "acme"
    tenant.mkdir(parents=True)
    (tenant / "RETURNS.md").write_text(POLICY, encoding="utf-8")
    (tenant / "FAQ.md").write_text(OTHER, encoding="utf-8")
    return root


def row(ticket_id, source, quote, interaction_type="single_qa", tenant="acme"):
    return {"ticket_id": ticket_id, "business": tenant, "interaction_type": interaction_type,
            "evidence_json": json.dumps([{"source": source, "quote": quote}])}


class QuoteScreeningTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = make_data_root(Path(self._dir.name))

    def test_keeps_exact_and_presentation_normalized_quotes(self):
        rows = [row("a", "RETURNS.md", "Items may be returned within 30 days for a full refund."),
                row("b", "RETURNS.md", "ITEMS may be   returned within 30 days")]
        kept, report = screen_cited_quotes(rows, self.root)
        self.assertEqual(len(kept), 2)
        self.assertEqual(report["rows_requiring_review"], 0)

    def test_removes_quote_missing_from_cited_source(self):
        kept, report = screen_cited_quotes([row("a", "RETURNS.md", "Refunds take 90 days to arrive.")], self.root)
        self.assertEqual(kept, [])
        self.assertEqual(report["finding_counts"], {"quote_not_found_in_cited_source": 1})

    def test_a_match_in_a_different_document_does_not_rescue_the_row(self):
        kept, report = screen_cited_quotes([row("a", "RETURNS.md", "Gift cards never expire")], self.root)
        self.assertEqual(kept, [])
        self.assertEqual(report["findings"][0]["other_documents_with_quote"], ["FAQ.md"])

    def test_unknown_source_and_unreadable_evidence_are_removed(self):
        bad = {"ticket_id": "c", "business": "acme", "interaction_type": "single_qa", "evidence_json": "not json"}
        kept, report = screen_cited_quotes([row("a", "MISSING.md", "anything at all here"), bad], self.root)
        self.assertEqual(kept, [])
        self.assertEqual(report["finding_counts"], {"unknown_source": 1, "unreadable_evidence": 1})

    def test_context_only_rows_are_not_verified(self):
        kept, report = screen_cited_quotes(
            [row("a", "RETURNS.md", "served chunk text, not a quote", interaction_type="retrieval_distractor")],
            self.root)
        self.assertEqual(len(kept), 1)
        self.assertEqual(report["rows_skipped_as_context_only"], 1)

    def test_report_mode_keeps_everything_and_empty_evidence_is_fine(self):
        rows = [row("a", "RETURNS.md", "never written anywhere in the docs"),
                {"ticket_id": "b", "business": "acme", "interaction_type": "unanswerable", "evidence_json": "[]"}]
        kept, report = screen_cited_quotes(rows, self.root, mode="report")
        self.assertEqual(len(kept), 2)
        self.assertEqual(report["rows_requiring_review"], 1)

    def test_rows_are_not_modified(self):
        original = row("a", "RETURNS.md", "never written anywhere in the docs")
        snapshot = json.dumps(original, sort_keys=True)
        screen_cited_quotes([original], self.root)
        self.assertEqual(json.dumps(original, sort_keys=True), snapshot)


def chunk(doc_id, text, section="s"):
    return {"doc_id": doc_id, "section": section, "text": text}


class ContextTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = make_data_root(Path(self._dir.name))

    def test_source_names_get_their_extension(self):
        self.assertEqual(hn.resolve_source_name(self.root / "acme", "RETURNS"), "RETURNS.md")
        self.assertEqual(hn.resolve_source_name(self.root / "acme", "nope"), "nope")

    def test_budget_skips_oversize_chunks_and_keeps_rank_order(self):
        chunks = [chunk("RETURNS", "a" * 50), chunk("FAQ", "b" * 500), chunk("RETURNS", "c" * 40)]
        context = hn.build_context(chunks, self.root / "acme", max_chars=100)
        self.assertEqual([c["quote"][0] for c in context], ["a", "c"])
        self.assertEqual(context[0]["source"], "RETURNS.md")

    def test_max_chunks_and_empty_text(self):
        chunks = [chunk("FAQ", "x" * 5)] * 6 + [chunk("FAQ", "   ")]
        self.assertEqual(len(hn.build_context(chunks, self.root / "acme", max_chunks=4)), 4)
        self.assertEqual(hn.build_context([chunk("FAQ", "")], self.root / "acme"), [])

    def test_retrieval_query_uses_recent_customer_turns(self):
        single = [{"role": "customer", "content": "Q1"}]
        multi = [{"role": "customer", "content": "Q1"}, {"role": "agent", "content": "A"},
                 {"role": "customer", "content": "Q2"}]
        self.assertEqual(hn.retrieval_query(single), "Q1")
        self.assertIn("Q1", hn.retrieval_query(multi))
        self.assertTrue(hn.retrieval_query(multi).endswith("Q2"))

    def test_selection_filters_reasons_tenants_and_is_deterministic(self):
        rows = [{"ticket_id": f"t{i}", "business": "acme", "escalation_reason": "not_in_docs"} for i in range(10)]
        rows += [{"ticket_id": "x", "business": "harbor_view", "escalation_reason": "not_in_docs"},
                 {"ticket_id": "y", "business": "acme", "escalation_reason": "none"}]
        picked = hn.select_source_tickets(rows)
        self.assertEqual(len(picked), 10)
        self.assertEqual(hn.select_source_tickets(rows, limit=3), hn.select_source_tickets(rows, limit=3))
        self.assertEqual(len(hn.select_source_tickets(rows, limit=3)), 3)


def make_entry():
    return {"source_ticket_id": "acme-0001_t0", "category": "returns",
            "messages": [{"role": "customer", "content": "How long do refunds take to arrive?"}],
            "context": [{"source": "RETURNS.md", "section": "Returns",
                         "quote": "Items may be returned within 30 days for a full refund."}]}


def label(**overrides):
    base = {"action": "escalate", "escalation_reason": "not_in_docs",
            "answer": "I can't confirm how long refunds take, so I'm passing you to a teammate.",
            "confidence": 0.2, "rationale": "The returns text covers the window but not refund timing.",
            "ticket_summary": "Customer asks refund timing; not documented.", "evidence": []}
    base.update(overrides)
    return base


class FinalizeLabelTests(unittest.TestCase):
    def test_escalation_carries_retrieved_context_as_evidence(self):
        ticket, reason = hn.finalize_label(make_entry(), label())
        self.assertIsNone(reason)
        self.assertEqual(ticket["interaction_type"], "retrieval_distractor")
        self.assertEqual(ticket["evidence"], [{"source": "RETURNS.md",
                                               "quote": "Items may be returned within 30 days for a full refund."}])
        self.assertTrue(ticket["is_answerable"])
        self.assertEqual(ticket["action"], "escalate")

    def test_answer_requires_a_verbatim_quote_from_the_cited_passage(self):
        good = label(action="answer", escalation_reason="none", confidence=0.95, answer="Thirty days.",
                     ticket_summary="", evidence=[{"source": "RETURNS.md", "quote": "returned within 30 days for a full refund"}])
        ticket, reason = hn.finalize_label(make_entry(), good)
        self.assertIsNone(reason)
        self.assertEqual(ticket["interaction_type"], "single_qa")
        bad = {**good, "evidence": [{"source": "RETURNS.md", "quote": "Refunds arrive within five business days."}]}
        self.assertEqual(hn.finalize_label(make_entry(), bad)[1], "quote_not_verbatim_in_cited_passage")
        wrong_source = {**good, "evidence": [{"source": "FAQ.md", "quote": "returned within 30 days for a full refund"}]}
        self.assertEqual(hn.finalize_label(make_entry(), wrong_source)[1], "quote_not_verbatim_in_cited_passage")
        none = {**good, "evidence": []}
        self.assertEqual(hn.finalize_label(make_entry(), none)[1], "answer_without_evidence")

    def test_rejections(self):
        entry = make_entry()
        self.assertEqual(hn.finalize_label(entry, {"action": "maybe"})[1], "schema_invalid")
        self.assertEqual(hn.finalize_label(entry, label(escalation_reason="none"))[1], "action_reason_mismatch")
        self.assertEqual(hn.finalize_label(entry, label(confidence=1.5))[1], "confidence_out_of_range")
        self.assertEqual(hn.finalize_label(entry, label(answer="  "))[1], "empty_answer_or_rationale")
        self.assertEqual(hn.finalize_label(entry, label(answer="The passage doesn't say."))[1],
                         "answer_mentions_prompt_vocabulary")
        mismatch = label(action="answer", escalation_reason="not_in_docs",
                         evidence=[{"source": "RETURNS.md", "quote": "returned within 30 days"}])
        self.assertEqual(hn.finalize_label(entry, mismatch)[1], "action_reason_mismatch")

    def test_prompt_shows_passages_and_conversation_but_no_prior_label(self):
        prompt = hn.build_teacher_prompt("Acme", make_entry()["messages"], make_entry()["context"])
        self.assertIn("=== PASSAGE 1 | source: RETURNS.md", prompt)
        self.assertIn("Customer: How long do refunds take to arrive?", prompt)
        self.assertIn("Acme", prompt)


class EndToEndMockTeacherTests(unittest.TestCase):
    """prepare-hardneg -> (mock teacher) -> finalize-hardneg -> cleaner, with no API or network."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.data = make_data_root(self.tmp / "data")
        self.out = self.tmp / "generated"
        self.source_csv = self.tmp / "train.csv"
        rows = [{"ticket_id": f"acme-000{i}_t0", "business": "acme", "escalation_reason": reason,
                 "category": "returns",
                 "messages_json": json.dumps([{"role": "customer", "content": f"Question number {i}?"}])}
                for i, reason in enumerate(["not_in_docs", "not_in_docs", "docs_require_human", "none"])]
        with self.source_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def args(self, **extra):
        values = dict(data_dir=str(self.data), out_dir=str(self.out), businesses=None, model="gemini-3.8-flash",
                      include_reference=False, document_parser="legacy", run_name="hn_test",
                      source_csv=str(self.source_csv), reasons=["not_in_docs", "docs_require_human"],
                      exclude_tenants=["harbor_view"], limit=None, top_k=4, max_context_chars=3000, seed=390,
                      temperature=0.2, thinking_level="low", force=False)
        values.update(extra)
        return argparse.Namespace(**values)

    @staticmethod
    def fake_retrieve(query, tenant):
        return [chunk("RETURNS", "Items may be returned within 30 days for a full refund."),
                chunk("FAQ", "Gift cards never expire and can be used in store.")]

    def raw_result(self, key, payload):
        text = json.dumps({"tickets": [payload]})
        return {"key": key, "response": {"candidates": [{"content": {"parts": [{"text": text}]}}]}}

    def test_full_flow(self):
        generator.cmd_prepare_hardneg(self.args(), retrieve_fn=self.fake_retrieve)
        rdir = self.out / "hn_test"
        requests = [json.loads(line) for line in (rdir / "requests.jsonl").read_text().splitlines()]
        self.assertEqual(len(requests), 3)  # the "none" ticket is not selected
        self.assertTrue(all("cachedContent" not in r["request"] for r in requests))
        plan = json.loads((rdir / "plan.json").read_text())
        self.assertEqual(set(plan), {r["key"] for r in requests})
        self.assertEqual(json.loads((self.out / "state.json").read_text())["runs"]["hn_test"]["kind"], "hardneg")

        keys = sorted(plan)
        good_escalation = label()
        good_answer = label(action="answer", escalation_reason="none", confidence=0.9, answer="Thirty days.",
                            ticket_summary="", evidence=[{"source": "RETURNS.md",
                                                          "quote": "returned within 30 days for a full refund"}])
        bad_answer = label(action="answer", escalation_reason="none", confidence=0.9, answer="Sixty days.",
                           ticket_summary="", evidence=[{"source": "RETURNS.md",
                                                         "quote": "returned within 60 days for a full refund"}])
        results = [self.raw_result(keys[0], good_escalation), self.raw_result(keys[1], good_answer),
                   self.raw_result(keys[2], bad_answer)]
        (rdir / "results.jsonl").write_text("\n".join(json.dumps(r) for r in results) + "\n", encoding="utf-8")

        generator.cmd_finalize_hardneg(self.args())
        rejected = json.loads((rdir / "rejected.json").read_text())
        self.assertEqual([r["reason"] for r in rejected], ["quote_not_verbatim_in_cited_passage"])

        df = cleaner.load_results_to_dataframe(rdir / "results_finalized.jsonl")
        self.assertEqual(len(df), 2)
        self.assertTrue(all(df["ticket_id"].str.startswith("acme-hn")))
        self.assertEqual(set(df["business"]), {"acme"})

        # Rules the training notebook enforces on every CSV row.
        for record in df.to_dict(orient="records"):
            evidence = json.loads(record["evidence_json"])
            self.assertTrue(record["is_answerable"])
            self.assertTrue(evidence)
            if record["action"] == "escalate":
                self.assertEqual(record["interaction_type"], "retrieval_distractor")

        screened, report = cleaner_screen(df, self.data)
        self.assertEqual(len(screened), 2)  # escalation skipped as context, answer verified
        self.assertEqual(report["rows_skipped_as_context_only"], 1)

    def test_prepare_refuses_to_overwrite_and_skips_tickets_without_context(self):
        generator.cmd_prepare_hardneg(self.args(), retrieve_fn=self.fake_retrieve)
        with self.assertRaises(SystemExit):
            generator.cmd_prepare_hardneg(self.args(), retrieve_fn=self.fake_retrieve)
        with self.assertRaises(SystemExit):
            generator.cmd_prepare_hardneg(self.args(run_name="hn_empty"), retrieve_fn=lambda q, t: [])
        skipped = json.loads((self.out / "hn_empty" / "skipped.json").read_text())
        self.assertEqual(len(skipped), 3)
        self.assertFalse((self.out / "hn_empty" / "requests.jsonl").exists())

    def test_cost_estimate_uses_recorded_rates(self):
        estimate = generator.estimate_cost("gemini-3.8-flash", ["x" * 3500] * 10)
        self.assertEqual(estimate["requests"], 10)
        self.assertGreater(estimate["estimated_usd_list_price"], 0)
        self.assertIsNone(generator.estimate_cost("unknown-model", ["x"]))


def cleaner_screen(df, data_root):
    return screen_cited_quotes(df.to_dict(orient="records"), data_root)


if __name__ == "__main__":
    unittest.main()
