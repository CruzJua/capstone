"""Judge response quality in generation-evaluation logs with an independent LLM.

Dry run by default: no network calls are made and nothing is written unless
``--execute`` is passed. Input logs are never modified; results go to a
separate file under ``logs/judged/`` (override with ``--output``).

Examples:
    # Plan only (free):
    python scripts/judge_generation.py --input logs/generation_eval_X.json \\
        --provider openai --model <judge-model>

    # Paid run (requires JUDGE_API_KEY); re-running the same command resumes:
    python scripts/judge_generation.py --input logs/generation_eval_X.json \\
        --provider openai --model <judge-model> --execute --max-calls 250

    # Re-print the scorecard of a finished/partial judged file without any calls:
    python scripts/judge_generation.py --summarize logs/judged/<file>.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import find_dotenv, load_dotenv

from src.evaluation.judge import (
    JudgeConfigError, JudgeError, JudgeIdentity, JudgeOptions, create_backend,
    default_output_path, format_scorecard, load_generation_log, load_rubric,
    check_resume_compatible, plan_judging, run_judging, summarize_judgments, _endpoint_host,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", action="append", default=[],
                        help="Generation-eval log to judge (repeatable). Never modified.")
    parser.add_argument("--summarize", metavar="JUDGED_FILE",
                        help="Print the scorecard for an existing judged file and exit (no calls).")
    parser.add_argument("--provider", default=os.getenv("JUDGE_PROVIDER"),
                        help="'openai' (any OpenAI-compatible endpoint) or 'ollama' (default: $JUDGE_PROVIDER)")
    parser.add_argument("--model", default=os.getenv("JUDGE_MODEL"),
                        help="Judge model id; must differ from the Gemini teacher and the evaluated model (default: $JUDGE_MODEL)")
    parser.add_argument("--base-url", default=os.getenv("JUDGE_BASE_URL"),
                        help="Endpoint (openai: .../v1, default https://api.openai.com/v1; ollama: host URL) (default: $JUDGE_BASE_URL)")
    parser.add_argument("--api-key-env", default="JUDGE_API_KEY",
                        help="Name of the environment variable holding the judge API key")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="Judge sampling temperature (default 0.0)")
    parser.add_argument("--timeout", type=float, default=None, help="Per-request timeout in seconds")
    parser.add_argument("--think", choices=("default", "true", "false"), default="default",
                        help="Ollama thinking control (default: leave model default unchanged). Changed settings require a separate --output.")
    parser.add_argument("--num-ctx", type=int, default=None,
                        help="Requested Ollama context size in tokens; positive integer (default: server/model setting).")
    parser.add_argument("--num-predict", type=int, default=None,
                        help="Maximum Ollama generated tokens, including thinking; positive integer (default: server/model setting).")
    parser.add_argument("--rubric", default=None, help="Rubric file (default evaluation/judge_rubric.md)")
    parser.add_argument("--output", default=None,
                        help="Judged-result path; only valid with a single --input")
    parser.add_argument("--execute", action="store_true",
                        help="Actually call the judge. Without this flag the script only plans.")
    parser.add_argument("--max-calls", type=int, default=None,
                        help="Hard cap on judge API calls in this invocation (spend guard)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Attempt at most this many records in this invocation (smoke test)")
    parser.add_argument("--max-attempts", type=int, default=2,
                        help="Calls allowed per record when replies are malformed or the service errors")
    parser.add_argument("--no-retry-failed", action="store_true",
                        help="Do not retry records that failed in an earlier run")
    parser.add_argument("--max-consecutive-failures", type=int, default=5,
                        help="Stop the run after this many failed records in a row")
    parser.add_argument("--max-payload-chars", type=int, default=30000,
                        help="Records larger than this are failed rather than truncated")
    return parser.parse_args()


def summarize_existing(path: Path, rubric_path: str | None = None) -> int:
    state = json.loads(path.read_text(encoding="utf-8"))
    try:
        log = load_generation_log(state["source"]["path"])
        identity = JudgeIdentity(**state["judge"])
    except (KeyError, TypeError, OSError) as exc:
        raise JudgeError("Cannot verify judged scorecard: restore its source log and judge identity.") from exc
    check_resume_compatible(state, log, identity, load_rubric(rubric_path))
    state["summary"] = summarize_judgments(state["judgments"])
    print(format_scorecard(state))
    return 0


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True), override=False)
    args = parse_args()
    if args.summarize:
        return summarize_existing(Path(args.summarize), args.rubric)
    if not args.input:
        raise SystemExit("error: provide --input (or --summarize).")
    if args.output and len(args.input) > 1:
        raise SystemExit("error: --output requires exactly one --input.")
    if not args.provider or not args.model:
        raise SystemExit("error: --provider and --model (or JUDGE_PROVIDER/JUDGE_MODEL) are required.")

    options = JudgeOptions(
        max_attempts=args.max_attempts, max_calls=args.max_calls, limit=args.limit,
        retry_failed=not args.no_retry_failed, max_consecutive_failures=args.max_consecutive_failures,
        max_payload_chars=args.max_payload_chars,
    )
    rubric = load_rubric(args.rubric)
    default_url = "https://api.openai.com/v1" if args.provider.strip().lower() == "openai" else os.getenv("OLLAMA_HOST", "http://localhost:11434")
    think = {"default": None, "true": True, "false": False}[args.think]
    identity = JudgeIdentity(args.provider.strip().lower(), args.model, _endpoint_host(args.base_url or default_url),
                             args.temperature, think, args.num_ctx, args.num_predict)
    exit_code, remaining_calls = 0, args.max_calls

    for input_path in args.input:
        log = load_generation_log(input_path)
        output = Path(args.output) if args.output else default_output_path(input_path, args.model, rubric.version)
        print(f"\nInput:  {input_path}\n  evaluated model: {log.model} | context: {log.context_mode} | sha256: {log.sha256[:16]}...")
        print(f"Output: {output}\nJudge:  {identity.provider}/{identity.model} | rubric {rubric.version}")
        controls = {name: identity.as_dict()[name] for name in ("think", "num_ctx", "num_predict")
                    if name in identity.as_dict()}
        if controls:
            print("Requested Ollama controls: " + json.dumps(controls, sort_keys=True))
        if not args.execute:
            plan = plan_judging(log, identity, rubric, output, options)
            print("DRY RUN (no calls made, nothing written). Plan:")
            for key, value in plan.items():
                print(f"  {key}: {value}")
            print("Re-run with --execute to judge.")
            continue

        api_key = os.getenv(args.api_key_env)
        backend = create_backend(
            identity.provider, identity.model, base_url=args.base_url, api_key=api_key,
            temperature=args.temperature, timeout=args.timeout,
            think=think, num_ctx=args.num_ctx, num_predict=args.num_predict,
        )
        per_input = JudgeOptions(**{**options.__dict__, "max_calls": remaining_calls})
        result = run_judging(log, backend, rubric, output, per_input, progress=print)
        if remaining_calls is not None:
            remaining_calls = max(0, remaining_calls - result.calls_made)
        print()
        print(format_scorecard(result.state))
        if result.aborted_reason:
            print(f"STOPPED EARLY: {result.aborted_reason}.")
            print("Review errors/attempt_diagnostics before retrying repeated failures. "
                  "The same settings resume saved judgments; changed settings require a separate --output.")
        overall = result.state["summary"]["overall"]
        if result.aborted_reason or overall["failed_judgments"] or overall["pending"]:
            exit_code = 2
        if remaining_calls == 0 and len(args.input) > 1:
            print("Call budget exhausted; remaining inputs not judged.")
            break
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (JudgeConfigError, JudgeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
