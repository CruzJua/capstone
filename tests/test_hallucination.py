import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.hallucination import (
    REVIEW_COLUMNS, REVIEW_LABEL_COLUMNS, build_review_rows, compute_for_files, compute_hallucination_rates,
    compute_recovery, format_markdown, load_generation_answers, load_judged_state, paired_pass_comparison,
    pass_stats, summarize_review_labels, write_review_csv,
)


def judgment(case_type, action, status="judged", grounded="fully_grounded", ticket="t", claims=()):
    entry = {"ticket_id": ticket, "case_type": case_type, "model_action": action, "status": status}
    entry["verdict"] = ({"groundedness": grounded, "unsupported_claims": list(claims)}
                        if status == "judged" else None)
    return entry


def state(mode="retriever", judgments=()):
    return {"source": {"model": "m", "context_mode": mode, "path": "logs/x_20261105_234314.json"}, "judge": {"provider": "openai", "model": "j"},
            "judgments": list(judgments)}


class HallucinationTests(unittest.TestCase):
    def build(self):
        return state(judgments=[
            # answer_absent: 4 records. 3 answered (2 judged unsupported/major, 1 unjudged), 1 escalated.
            judgment("answer_absent", "answer", grounded="major_unsupported"),
            judgment("answer_absent", "answer", grounded="minor_unsupported"),
            judgment("answer_absent", "answer", status="failed"),
            judgment("answer_absent", "escalate"),
            # answer_present: 3 records. 2 answered (1 grounded, 1 minor), 1 escalated.
            judgment("answer_present", "answer"),
            judgment("answer_present", "answer", grounded="minor_unsupported"),
            judgment("answer_present", "escalate"),
        ])

    def test_absent_answer_rate_uses_all_records_including_unjudged(self):
        result = compute_hallucination_rates(self.build())
        self.assertEqual(result["absent_answer_rate"], 0.75)
        self.assertEqual(result["source_log_run_id"], "20261105_234314")
        self.assertEqual(result["answer_absent"]["model_answered"], 3)
        self.assertEqual(result["answer_absent"]["unjudged"], 1)

    def test_unsupported_rates_and_bounds(self):
        absent = compute_hallucination_rates(self.build())["answer_absent"]
        self.assertEqual(absent["answers_with_unsupported_claims"], 2)
        self.assertEqual(absent["answers_with_major_unsupported"], 1)
        self.assertEqual(absent["unsupported_answer_rate_judged_only"], 1.0)
        # lower bound treats the unjudged answer as supported (2/3), upper as unsupported (3/3)
        self.assertEqual(absent["unsupported_answer_rate_bounds"], [0.6667, 1.0])
        self.assertEqual(absent["major_unsupported_answer_rate_bounds"], [0.3333, 0.6667])

    def test_present_split_is_separate(self):
        present = compute_hallucination_rates(self.build())["answer_present"]
        self.assertEqual(present["model_answered"], 2)
        self.assertEqual(present["unsupported_answer_rate_judged_only"], 0.5)
        self.assertEqual(present["unsupported_answer_rate_bounds"], [0.5, 0.5])

    def test_empty_denominator_is_none_not_zero(self):
        result = compute_hallucination_rates(state(judgments=[judgment("answer_present", "escalate")]))
        self.assertIsNone(result["answer_present"]["unsupported_answer_rate_judged_only"])
        self.assertIsNone(result["answer_absent"]["model_answered_rate_all_records"])

    def test_unknown_case_type_is_rejected(self):
        with self.assertRaises(ValueError):
            compute_hallucination_rates(state(judgments=[judgment("something_else", "answer")]))

    def test_modes_get_separate_tables_and_files_are_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for mode in ("retriever", "ground_truth"):
                path = Path(tmp) / f"{mode}.json"
                path.write_text(json.dumps(self.build() | {"source": {"model": "m", "context_mode": mode}}))
                paths.append(path)
            before = [p.read_bytes() for p in paths]
            results = compute_for_files(paths)
            text = format_markdown(results)
            self.assertEqual(before, [p.read_bytes() for p in paths])
        self.assertIsNone(results[0]["source_log_run_id"])
        self.assertIn("### Context mode: `ground_truth`", text)
        self.assertIn("### Context mode: `retriever`", text)

    def signal_state(self):
        return state(judgments=[
            judgment("answer_absent", "answer", grounded="major_unsupported", ticket="a",
                     claims=["I will connect you with a team member"]),
            judgment("answer_absent", "answer", grounded="major_unsupported", ticket="b",
                     claims=["The clinic is open until 9", "I will connect you with a team member"]),
            judgment("answer_absent", "answer", grounded="major_unsupported", ticket="c",
                     claims=["The clinic is open until 9"]),
            judgment("answer_absent", "answer", grounded="minor_unsupported", ticket="d", claims=["x"]),
            judgment("answer_absent", "escalate", ticket="e"),
        ])

    def test_text_signals_are_counted_from_answer_text_and_claims(self):
        answers = {"a": "We do not have the price. I will connect you with a team member.",
                   "b": "I cannot confirm the hours.", "c": "We close at 9 PM every day.",
                   "d": "Not listed in our documents.", "e": "ignored, not answered"}
        t = compute_hallucination_rates(self.signal_state(), answers)["answer_absent"]["text_signals"]
        self.assertEqual(t["answered_text_says_missing_or_hands_off"], 3)
        self.assertEqual(t["answered_text_confident"], 1)
        self.assertEqual(t["major_unsupported_with_handoff_claim"], 2)
        self.assertEqual(t["major_unsupported_with_only_handoff_claims"], 1)
        self.assertEqual(t["unsupported_answers_with_handoff_claim"], 2)

    def test_no_text_signals_without_answers(self):
        result = compute_hallucination_rates(self.signal_state())
        self.assertNotIn("text_signals", result["answer_absent"])

    def test_generation_answers_are_verified_by_sha256(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "gen.json"
            log.write_text(json.dumps({"records": [{"ticket_id": "a", "model_answer": "hi"}]}))
            good = {"source": {"path": "gen.json", "sha256": hashlib.sha256(log.read_bytes()).hexdigest()}}
            self.assertEqual(load_generation_answers(good, Path(tmp)), {"a": "hi"})
            bad = {"source": {"path": "gen.json", "sha256": "0" * 64}}
            with self.assertRaises(ValueError):
                load_generation_answers(bad, Path(tmp))

    def review_fixture(self):
        st = state(judgments=[
            judgment("answer_absent", "answer", grounded="major_unsupported", ticket="a", claims=["c1", "c2"]),
            judgment("answer_absent", "escalate", ticket="b"),
            judgment("answer_present", "answer", ticket="c"),
            judgment("answer_absent", "answer", status="failed", ticket="d"),
        ])
        st["judgments"][0]["verdict"].update(decision="inappropriate", explanation="why")
        records = [{"ticket_id": t, "customer_query": f"q-{t}", "model_answer": f"ans-{t}",
                    "context": '<context source="DOC_A">x</context>\n<context source="DOC_B">y</context>'
                               '<context source="DOC_A">z</context>'} for t in "abcd"]
        return st, records

    def test_review_rows_cover_only_answered_absent_cases_with_empty_labels(self):
        st, records = self.review_fixture()
        rows = build_review_rows(st, records)
        self.assertEqual([r["question_id"] for r in rows], ["a", "d"])
        self.assertEqual(rows[0]["retrieved_doc_ids"], "DOC_A; DOC_B")
        self.assertEqual(rows[0]["model_action"], "answer")
        self.assertEqual(REVIEW_COLUMNS.index("model_action"), REVIEW_COLUMNS.index("model_answer") + 1)
        self.assertEqual(rows[0]["judge_unsupported_claims"], "c1 | c2")
        self.assertEqual(rows[1]["judge_decision"], "unjudged")
        for row in rows:
            self.assertEqual([row[c] for c in REVIEW_LABEL_COLUMNS], ["", "", ""])
        self.assertEqual(rows[0]["run_id"], "20261105_234314")

    def test_review_csv_refuses_to_overwrite_and_summary_uses_labels_only(self):
        st, records = self.review_fixture()
        rows = build_review_rows(st, records)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.csv"
            write_review_csv(path, rows)
            with self.assertRaises(FileExistsError):
                write_review_csv(path, rows)
            blank = summarize_review_labels(path)
            only = next(iter(blank.values()))
            self.assertEqual((only["rows"], only["fully_labelled"], only["fabricated_yes"]), (2, 0, 0))
            self.assertIsNone(only["fabrication_rate_among_answered"])
            self.assertFalse(only["complete"])
            # fill in by hand: row a fabricated, row d handoff-only
            with path.open(newline="", encoding="utf-8") as handle:
                filled = list(csv.DictReader(handle))
            filled[0].update(fabricated_fact="yes", handoff_only="no")
            filled[1].update(fabricated_fact="no", handoff_only="yes")
            path.write_text("", encoding="utf-8")
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
                writer.writeheader()
                writer.writerows(filled)
            done = next(iter(summarize_review_labels(path).values()))
            self.assertEqual((done["fully_labelled"], done["fabricated_yes"], done["handoff_only_yes"]), (2, 1, 1))
            self.assertEqual(done["fabrication_rate_among_answered"], 0.5)
            self.assertEqual(done["fabrication_rate_all_absent"], 0.02)
            self.assertTrue(done["complete"])
            filled[0]["fabricated_fact"] = "maybe"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
                writer.writeheader()
                writer.writerows(filled)
            with self.assertRaises(ValueError):
                summarize_review_labels(path)

    @staticmethod
    def scored_state(passes, mode="retriever", model="m", correct=None, unjudged=()):
        judgments = []
        for i, passed in enumerate(passes):
            status = "failed" if i in unjudged else "judged"
            entry = judgment("answer_present", "answer", status=status, ticket=f"t{i}")
            entry["passed"] = bool(passed) and status == "judged"
            entry["action_correct"] = bool(passed if correct is None else correct[i])
            judgments.append(entry)
        return {"source": {"model": model, "context_mode": mode}, "judgments": judgments}

    def test_pass_stats_strict_and_excluding_unjudged(self):
        stats = pass_stats(self.scored_state([1, 1, 0, 1], unjudged=(3,)))
        self.assertEqual((stats["passed"], stats["judged"], stats["unjudged"]), (2, 3, 1))
        self.assertEqual(stats["strict_pass_rate"], 0.5)
        self.assertAlmostEqual(stats["pass_rate_excluding_unjudged"], 2 / 3)

    def test_standard_recovery_including_negative_values(self):
        base = self.scored_state([1] * 50 + [0] * 50, model="base")
        teacher = self.scored_state([1] * 90 + [0] * 10, model="teacher")
        good = self.scored_state([1] * 70 + [0] * 30, model="good")
        worse = self.scored_state([1] * 40 + [0] * 60, model="worse")
        self.assertEqual(compute_recovery(good, base, teacher)["strict_pass_rate"]["recovery"], 0.5)
        self.assertEqual(compute_recovery(worse, base, teacher)["strict_pass_rate"]["recovery"], -0.25)

    def test_recovery_rejects_mixed_modes_and_flags_tiny_denominator(self):
        a = self.scored_state([1, 0], mode="retriever")
        b = self.scored_state([1, 0], mode="ground_truth")
        with self.assertRaises(ValueError):
            compute_recovery(a, b, a)
        same = compute_recovery(a, a, a)
        self.assertIsNone(same["strict_pass_rate"]["recovery"])
        self.assertTrue(same["strict_pass_rate"]["denominator_small"])

    def test_paired_comparison_counts_and_sign_test(self):
        a = self.scored_state([1, 1, 1, 1, 0, 0])
        b = self.scored_state([1, 0, 0, 0, 1, 0])
        result = paired_pass_comparison(a, b)
        self.assertEqual((result["both_pass"], result["a_only_pass"], result["b_only_pass"], result["neither_pass"]),
                         (1, 3, 1, 1))
        self.assertEqual(result["net_a_minus_b"], 2)
        self.assertEqual(result["sign_test_p_two_sided"], 0.625)  # 2 * (1 + 4) / 16
        with self.assertRaises(ValueError):
            paired_pass_comparison(a, self.scored_state([1, 1]))

    def test_rejects_non_judged_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_text("{}")
            with self.assertRaises(ValueError):
                load_judged_state(path)


if __name__ == "__main__":
    unittest.main()
