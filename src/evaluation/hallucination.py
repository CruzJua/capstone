"""Hallucination rates (answer present vs answer absent) computed from judged-result files.

Two complementary measures, both reported per case type:

* absent_answer_rate: judge-free. Of the unanswerable (answer_absent) questions, the share where the
  model chose action=answer instead of escalating. Uses every record, judged or not.
* unsupported answer rate: judge-based. Of the responses with action=answer, the share the judge
  marked as containing unsupported claims (groundedness minor_unsupported or major_unsupported;
  "major" is also reported alone). Records the judge could not assess are not silently dropped:
  each rate is given as a lower bound (unjudged answers treated as supported) and an upper bound
  (unjudged answers treated as unsupported), plus the rate over judged answers only.
"""

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_TYPES = ("answer_present", "answer_absent")
UNSUPPORTED_ANY = ("minor_unsupported", "major_unsupported")
UNSUPPORTED_MAJOR = ("major_unsupported",)

# Heuristic text signals (crude regular expressions, NOT judged and NOT human-reviewed).
# MISSING_OR_HANDOFF_PATTERN: the answer text says the information is missing or hands off to staff.
# HANDOFF_CLAIM_PATTERN: a judge-flagged unsupported claim is about the handoff promise.
MISSING_OR_HANDOFF_PATTERN = re.compile(
    r"team member|connect(ing)? you|cannot confirm|do(es)? not (have|list|specify)"
    r"|not (listed|specified|available)|no information|not in our", re.I)
HANDOFF_CLAIM_PATTERN = re.compile(r"connect|team member", re.I)


def _ratio(numerator: int, denominator: int):
    return round(numerator / denominator, 4) if denominator else None


def load_judged_state(path: Path | str) -> Dict[str, Any]:
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("source", "judgments"):
        if key not in state:
            raise ValueError(f"{path} is not a judged-result file (missing {key!r}).")
    return state


def load_generation_records(state: Dict[str, Any], root: Path = PROJECT_ROOT) -> List[Dict[str, Any]]:
    """Records of the generation log a judged file was made from (read only).

    The log's sha256 must match the one recorded in the judged file, so the records are guaranteed to be
    the ones that were judged.
    """
    source = state["source"]
    path = Path(source["path"])
    path = path if path.is_absolute() else root / path
    raw = path.read_bytes()
    if source.get("sha256") and hashlib.sha256(raw).hexdigest() != source["sha256"]:
        raise ValueError(f"{path} does not match the sha256 recorded in the judged file.")
    return json.loads(raw)["records"]


def load_generation_answers(state: Dict[str, Any], root: Path = PROJECT_ROOT) -> Dict[str, str]:
    """Answer text per ticket from the verified generation log."""
    return {r["ticket_id"]: (r.get("model_answer") or "") for r in load_generation_records(state, root)}


def _text_signals(answered: List[Dict[str, Any]], answered_judged: List[Dict[str, Any]],
                  answers: Dict[str, str]) -> Dict[str, Any]:
    says_missing = sum(bool(MISSING_OR_HANDOFF_PATTERN.search(answers.get(j["ticket_id"], ""))) for j in answered)

    def handoff_flagged(j: Dict[str, Any]) -> bool:
        return any(HANDOFF_CLAIM_PATTERN.search(c) for c in j["verdict"].get("unsupported_claims") or [])

    def handoff_only(j: Dict[str, Any]) -> bool:
        claims = j["verdict"].get("unsupported_claims") or []
        return bool(claims) and all(HANDOFF_CLAIM_PATTERN.search(c) for c in claims)

    unsupported = [j for j in answered_judged if j["verdict"]["groundedness"] in UNSUPPORTED_ANY]
    major = [j for j in answered_judged if j["verdict"]["groundedness"] in UNSUPPORTED_MAJOR]
    return {
        "heuristic_note": "regex text signals; not judged and not human-reviewed",
        "answered_text_says_missing_or_hands_off": says_missing,
        "answered_text_confident": len(answered) - says_missing,
        "unsupported_answers_with_handoff_claim": sum(handoff_flagged(j) for j in unsupported),
        "major_unsupported_with_handoff_claim": sum(handoff_flagged(j) for j in major),
        "major_unsupported_with_only_handoff_claims": sum(handoff_only(j) for j in major),
    }


def _split_stats(judgments: List[Dict[str, Any]], answers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    answered = [j for j in judgments if j.get("model_action") == "answer"]
    answered_judged = [j for j in answered if j.get("status") == "judged"]
    answered_unjudged = len(answered) - len(answered_judged)
    any_count = sum(j["verdict"]["groundedness"] in UNSUPPORTED_ANY for j in answered_judged)
    major_count = sum(j["verdict"]["groundedness"] in UNSUPPORTED_MAJOR for j in answered_judged)
    signals = {"text_signals": _text_signals(answered, answered_judged, answers)} if answers is not None else {}
    return {
        **signals,
        "records": len(judgments),
        "judged": sum(j.get("status") == "judged" for j in judgments),
        "unjudged": sum(j.get("status") != "judged" for j in judgments),
        "model_answered": len(answered),
        "model_escalated_or_other": len(judgments) - len(answered),
        "model_answered_rate_all_records": _ratio(len(answered), len(judgments)),
        "answered_and_judged": len(answered_judged),
        "answered_but_unjudged": answered_unjudged,
        "answers_with_unsupported_claims": any_count,
        "answers_with_major_unsupported": major_count,
        "unsupported_answer_rate_judged_only": _ratio(any_count, len(answered_judged)),
        "unsupported_answer_rate_bounds": [
            _ratio(any_count, len(answered)), _ratio(any_count + answered_unjudged, len(answered))],
        "major_unsupported_answer_rate_judged_only": _ratio(major_count, len(answered_judged)),
        "major_unsupported_answer_rate_bounds": [
            _ratio(major_count, len(answered)), _ratio(major_count + answered_unjudged, len(answered))],
    }


def compute_hallucination_rates(state: Dict[str, Any], answers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Per-case-type hallucination statistics for one judged-result state.

    With ``answers`` (ticket id -> answer text) the heuristic text signals are added as well.
    """
    by_type: Dict[str, List[Dict[str, Any]]] = {name: [] for name in CASE_TYPES}
    for judgment in state["judgments"]:
        case_type = judgment.get("case_type")
        if case_type not in by_type:
            raise ValueError(f"Unexpected case_type {case_type!r} for {judgment.get('ticket_id')}.")
        by_type[case_type].append(judgment)
    source = state["source"]
    absent = _split_stats(by_type["answer_absent"], answers)
    stamp = re.search(r"\d{8}_\d{6}", str(source.get("path") or ""))
    return {
        "model": source.get("model"),
        "context_mode": source.get("context_mode"),
        "source_log_run_id": stamp.group(0) if stamp else None,
        "judge": f"{state.get('judge', {}).get('provider')}/{state.get('judge', {}).get('model')}",
        "absent_answer_rate": absent["model_answered_rate_all_records"],
        "answer_absent": absent,
        "answer_present": _split_stats(by_type["answer_present"], answers),
    }


def compute_for_files(paths: Iterable[Path | str], with_text_signals: bool = False,
                      root: Path = PROJECT_ROOT) -> List[Dict[str, Any]]:
    results = []
    for path in paths:
        state = load_judged_state(path)
        answers = load_generation_answers(state, root) if with_text_signals else None
        entry = compute_hallucination_rates(state, answers)
        entry["judged_file"] = Path(path).name
        results.append(entry)
    return results


def pass_stats(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pass counts both ways (strict and excluding unjudged) and judge-free action accuracy."""
    judgments = state["judgments"]
    records = len(judgments)
    judged = sum(j.get("status") == "judged" for j in judgments)
    passed = sum(j.get("passed") is True for j in judgments)
    action_correct = sum(bool(j.get("action_correct")) for j in judgments)
    return {
        "records": records, "judged": judged, "unjudged": records - judged, "passed": passed,
        "strict_pass_rate": passed / records if records else None,
        "pass_rate_excluding_unjudged": passed / judged if judged else None,
        "action_accuracy": action_correct / records if records else None,
    }


def _recovery(student, base, teacher):
    if None in (student, base, teacher) or teacher == base:
        return None
    return round((student - base) / (teacher - base), 4)


def compute_recovery(student: Dict[str, Any], base: Dict[str, Any], teacher: Dict[str, Any]) -> Dict[str, Any]:
    """Standard recovery = (student - base) / (teacher - base) from three judged states.

    Three variants are reported: strict pass rate (unjudged count as failures), pass rate excluding
    unjudged records, and the judge-free action accuracy. A negative value means the student scored
    below the untuned base. All three states must be the same context mode.
    """
    modes = {s["source"].get("context_mode") for s in (student, base, teacher)}
    if len(modes) != 1:
        raise ValueError(f"Student, base and teacher must share one context mode; got {sorted(map(str, modes))}.")
    stats = {name: pass_stats(s) for name, s in (("student", student), ("base", base), ("teacher", teacher))}
    out: Dict[str, Any] = {"context_mode": modes.pop(), "student_model": student["source"].get("model"),
                           "base_model": base["source"].get("model"), "teacher_model": teacher["source"].get("model")}
    for key in ("strict_pass_rate", "pass_rate_excluding_unjudged", "action_accuracy"):
        s, b, t = (stats[n][key] for n in ("student", "base", "teacher"))
        out[key] = {
            "student": round(s, 4), "base": round(b, 4), "teacher": round(t, 4),
            "teacher_minus_base": round(t - b, 4), "recovery": _recovery(s, b, t),
            "denominator_small": abs(t - b) < 0.05,
        }
    out["counts"] = {n: {k: stats[n][k] for k in ("records", "judged", "unjudged", "passed")} for n in stats}
    return out


def paired_pass_comparison(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Question-by-question strict-pass comparison of two judged states on the same questions.

    Unjudged records count as not passing. The sign test uses only the discordant questions
    (passed by exactly one model); p is the exact two-sided binomial probability under 50/50.
    """
    from math import comb
    pa = {j["ticket_id"]: j.get("passed") is True for j in a["judgments"]}
    pb = {j["ticket_id"]: j.get("passed") is True for j in b["judgments"]}
    if set(pa) != set(pb):
        raise ValueError("The two judged files do not cover the same questions.")
    both = sum(pa[k] and pb[k] for k in pa)
    a_only = sum(pa[k] and not pb[k] for k in pa)
    b_only = sum(pb[k] and not pa[k] for k in pa)
    n = a_only + b_only
    p = min(1.0, 2 * sum(comb(n, i) for i in range(min(a_only, b_only) + 1)) / 2 ** n) if n else 1.0
    return {
        "a": f"{a['source'].get('model')} ({a['source'].get('context_mode')})",
        "b": f"{b['source'].get('model')} ({b['source'].get('context_mode')})",
        "questions": len(pa), "both_pass": both, "a_only_pass": a_only, "b_only_pass": b_only,
        "neither_pass": len(pa) - both - a_only - b_only,
        "net_a_minus_b": a_only - b_only, "sign_test_p_two_sided": round(p, 4),
    }


REVIEW_LABEL_COLUMNS = ("fabricated_fact", "handoff_only", "notes")
REVIEW_COLUMNS = (
    "model", "run_id", "question_id", "question", "retrieved_doc_ids", "model_answer", "model_action",
    "judge_decision", "judge_groundedness", "judge_unsupported_claims", "judge_explanation",
    *REVIEW_LABEL_COLUMNS,
)
_CONTEXT_SOURCE = re.compile(r'<context source="([^"]+)"')


def build_review_rows(state: Dict[str, Any], records: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """One row per answer-absent question the model answered, with empty human-label columns."""
    by_ticket = {r["ticket_id"]: r for r in records}
    stamp = re.search(r"\d{8}_\d{6}", str(state["source"].get("path") or ""))
    rows = []
    for j in sorted(state["judgments"], key=lambda x: x["ticket_id"]):
        if j.get("case_type") != "answer_absent" or j.get("model_action") != "answer":
            continue
        record = by_ticket[j["ticket_id"]]
        verdict = j.get("verdict") or {}
        docs = list(dict.fromkeys(_CONTEXT_SOURCE.findall(record.get("context") or "")))
        rows.append({
            "model": state["source"].get("model", ""),
            "run_id": stamp.group(0) if stamp else "",
            "question_id": j["ticket_id"],
            "question": record["customer_query"],
            "retrieved_doc_ids": "; ".join(docs),
            "model_answer": record.get("model_answer") or "",
            "model_action": j["model_action"],
            "judge_decision": verdict.get("decision", "unjudged"),
            "judge_groundedness": verdict.get("groundedness", "unjudged"),
            "judge_unsupported_claims": " | ".join(verdict.get("unsupported_claims") or []),
            "judge_explanation": verdict.get("explanation", ""),
            **dict.fromkeys(REVIEW_LABEL_COLUMNS, ""),
        })
    return rows


def write_review_csv(path: Path | str, rows: List[Dict[str, str]]) -> None:
    """Write the review sheet; refuses to overwrite so filled-in labels are never lost."""
    with Path(path).open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _wilson(successes: int, n: int, z: float = 1.96):
    if not n:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return [round(centre - half, 4), round(centre + half, 4)]


def summarize_review_labels(path: Path | str, absent_total: int = 50) -> Dict[str, Any]:
    """Fabrication rates from a human-labelled review sheet, per model and run.

    fabricated_fact must be yes/no, handoff_only must be yes/no. Rows left blank are reported as
    unlabelled, never counted as "no". Rates (with Wilson 95% intervals):
      * fabrication_rate_among_answered: fabricated yes / labelled rows (answered absent questions).
      * fabrication_rate_all_absent: fabricated yes / absent_total (the unanswerable questions).
      * soft_escalation_rate_all_absent: handoff_only yes / absent_total.
    """
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    groups: Dict[tuple, List[Dict[str, str]]] = {}
    for row in rows:
        groups.setdefault((row["model"], row["run_id"]), []).append(row)
    summary: Dict[str, Any] = {}
    for (model, run_id), group in groups.items():
        def labels(column: str) -> List[str]:
            values = [r[column].strip().lower() for r in group]
            bad = [v for v in values if v not in ("", "yes", "no")]
            if bad:
                raise ValueError(f"{column} must be yes, no or blank; found {sorted(set(bad))}.")
            return values
        fab, hand = labels("fabricated_fact"), labels("handoff_only")
        labelled = sum(bool(a) and bool(b) for a, b in zip(fab, hand))
        fab_yes, hand_yes = fab.count("yes"), hand.count("yes")
        contradictory = sum(a == "yes" and b == "yes" for a, b in zip(fab, hand))
        summary[f"{model} {run_id}"] = {
            "rows": len(group), "fully_labelled": labelled, "unlabelled_rows": len(group) - labelled,
            "fabricated_yes": fab_yes, "handoff_only_yes": hand_yes,
            "rows_marked_both_fabricated_and_handoff_only": contradictory,
            "fabrication_rate_among_answered": round(fab_yes / labelled, 4) if labelled else None,
            "fabrication_rate_among_answered_wilson95": _wilson(fab_yes, labelled),
            "fabrication_rate_all_absent": round(fab_yes / absent_total, 4),
            "fabrication_rate_all_absent_wilson95": _wilson(fab_yes, absent_total),
            "soft_escalation_rate_all_absent": round(hand_yes / absent_total, 4),
            "complete": labelled == len(group),
        }
    return summary


def format_markdown(results: List[Dict[str, Any]]) -> str:
    """One table per context mode; modes are never mixed."""
    pct = lambda v: "n/a" if v is None else f"{v * 100:.1f}%"
    lines: List[str] = []
    for mode in sorted({r["context_mode"] for r in results}):
        lines += [f"### Context mode: `{mode}`", "",
                  "| Model | Run id | Case type | Records | Judged | Model answered | Answered, judged | Unsupported (judged only) | Unsupported bounds (low-high) | Major unsupported (judged only) |",
                  "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :---: | ---: |"]
        for entry in (r for r in results if r["context_mode"] == mode):
            for case_type in CASE_TYPES:
                s = entry[case_type]
                low, high = s["unsupported_answer_rate_bounds"]
                lines.append(
                    f"| `{entry['model']}` | {entry['source_log_run_id']} | {case_type} | {s['records']} | {s['judged']} | {s['model_answered']} "
                    f"| {s['answered_and_judged']} | {s['answers_with_unsupported_claims']}/{s['answered_and_judged']} "
                    f"({pct(s['unsupported_answer_rate_judged_only'])}) | {pct(low)}-{pct(high)} "
                    f"| {s['answers_with_major_unsupported']}/{s['answered_and_judged']} "
                    f"({pct(s['major_unsupported_answer_rate_judged_only'])}) |")
        lines.append("")
    if any("text_signals" in r["answer_absent"] for r in results):
        lines += ["### Heuristic text signals, answer-absent questions (regex, not judged, not human-reviewed)", "",
                  "| Model | Run id | Context mode | Model answered | Text says missing / hands off | Text confident | Major unsupported | ...with a handoff-related flagged claim | ...with only handoff-related claims |",
                  "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for entry in results:
            s = entry["answer_absent"]
            t = s.get("text_signals")
            if t is None:
                continue
            lines.append(
                f"| `{entry['model']}` | {entry['source_log_run_id']} | `{entry['context_mode']}` | {s['model_answered']} "
                f"| {t['answered_text_says_missing_or_hands_off']} | {t['answered_text_confident']} "
                f"| {s['answers_with_major_unsupported']} | {t['major_unsupported_with_handoff_claim']} "
                f"| {t['major_unsupported_with_only_handoff_claims']} |")
        lines.append("")
    return "\n".join(lines)
