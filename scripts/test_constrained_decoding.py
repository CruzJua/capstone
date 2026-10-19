import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv
from pydantic import ValidationError

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

# Load environment variables from project root .env
load_dotenv(project_root / ".env")

from src.inference.client import GRAMMAR_PATH, SYSTEM_PROMPT, SupportInferenceClient
from src.inference.schema import SupportResponse

REQUIRED_TYPES = {"answer": str, "cited_sources": list, "confidence": (int, float), "action": str}


def build_context(evidence_json: Any) -> str:
    """Builds a context block from the ticket's ground-truth evidence quotes, grouped by source."""
    if not isinstance(evidence_json, str) or not evidence_json.strip():
        return ""
    grouped: Dict[str, List[str]] = {}
    for item in json.loads(evidence_json):
        if isinstance(item, dict) and item.get("source"):
            grouped.setdefault(item["source"], []).append(item.get("quote", ""))
    return "\n\n".join(
        f"[Source: {source}]\n" + "\n".join(quotes) for source, quotes in grouped.items()
    )


def load_samples(dataset: Path, n: int, seed: int) -> pd.DataFrame:
    """Samples roughly 3/4 answerable and 1/4 unanswerable tickets so both actions get exercised."""
    df = pd.read_csv(dataset)
    answerable = df["is_answerable"].astype(str).str.lower() == "true"
    n_unanswerable = max(1, n // 4)
    return pd.concat([
        df[answerable].sample(n=n - n_unanswerable, random_state=seed),
        df[~answerable].sample(n=n_unanswerable, random_state=seed),
    ]).sample(frac=1, random_state=seed)


def validate(raw: str) -> Optional[str]:
    """Returns None if the raw output is valid, otherwise a description of the failure."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"json.loads failed: {e}"
    if not isinstance(data, dict):
        return "top-level value is not an object"
    for key, expected in REQUIRED_TYPES.items():
        if key not in data:
            return f"missing key '{key}'"
        if not isinstance(data[key], expected) or isinstance(data[key], bool):
            return f"key '{key}' has type {type(data[key]).__name__}"
    if not all(isinstance(s, str) for s in data["cited_sources"]):
        return "cited_sources contains a non-string"
    try:
        SupportResponse.model_validate(data)
    except ValidationError as e:
        return f"pydantic validation failed: {e.errors()[0]['msg']}"
    return None


def find_ollama_gguf(model: str) -> Optional[Path]:
    """Resolves the GGUF blob Ollama stores for a model, so llama.cpp can reuse the same weights."""
    try:
        modelfile = subprocess.run(
            ["ollama", "show", "--modelfile", model], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in modelfile.splitlines():
        if line.startswith("FROM "):
            path = Path(line[5:].strip())
            if path.exists():
                return path
    return None


def run_llama_cpp(binary: str, gguf: Path, query: str, context: str, max_tokens: int) -> tuple[str, float]:
    prompt = (
        f"System:\n{SYSTEM_PROMPT}\n\n"
        f"User:\n{SupportInferenceClient.build_user_prompt(query, context)}\n\n"
        "Assistant:\n"
    )
    start = time.perf_counter()
    proc = subprocess.run(
        [
            binary, "-m", str(gguf), "-p", prompt,
            "--grammar-file", str(GRAMMAR_PATH),
            "-n", str(max_tokens), "--temp", "0.2",
            "-no-cnv", "--no-display-prompt",
        ],
        capture_output=True, text=True, timeout=300,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    out = proc.stdout
    # Grammar guarantees one JSON object; strip any non-JSON log noise around it
    return out[out.find("{"): out.rfind("}") + 1], latency_ms


def summarize(name: str, records: List[Dict[str, Any]]) -> bool:
    n = len(records)
    failures = [r for r in records if r["error"]]
    print(f"\n=== {name}: {n - len(failures)}/{n} valid ({(n - len(failures)) / n:.0%}) ===")
    print(f"  avg latency:      {sum(r['latency_ms'] for r in records) / n:,.0f} ms")
    tps = [r["tokens_per_second"] for r in records if r.get("tokens_per_second")]
    if tps:
        print(f"  avg tokens/sec:   {sum(tps) / len(tps):.1f}")
        print(f"  avg output toks:  {sum(r['eval_tokens'] for r in records) / n:.0f}")
    actions = pd.Series([r["action"] for r in records if r["action"]]).value_counts().to_dict()
    print(f"  actions:          {actions}")
    agree = [r for r in records if r["action"] and r["expected_action"]]
    if agree:
        matched = sum(r["action"] == r["expected_action"] for r in agree)
        print(f"  action agreement: {matched}/{len(agree)} vs ground truth (quality signal, not a pass criterion)")
    for r in failures:
        print(f"  FAIL [{r['ticket_id']}]: {r['error']}\n       raw: {r['raw'][:200]!r}")
    return not failures


def main():
    parser = argparse.ArgumentParser(description="Verify constrained decoding always yields schema-valid JSON.")
    parser.add_argument("--dataset", default=str(project_root / "data/cleaned/cleaned_tickets.csv"))
    parser.add_argument("--num-prompts", type=int, default=15)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--model", default=None, help="Ollama model (default: $OLLAMA_MODEL or llama3.2:3b)")
    parser.add_argument("--llama-bin", default=None, help="Path to llama-cli/llama-completion (auto-detected on PATH)")
    parser.add_argument("--gguf", default=None, help="GGUF for llama.cpp (default: the Ollama model's blob)")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--skip-ollama", action="store_true")
    args = parser.parse_args()

    samples = load_samples(Path(args.dataset), args.num_prompts, args.seed)
    client = SupportInferenceClient(model=args.model)
    all_passed = True

    if not args.skip_ollama:
        print(f"Running {len(samples)} prompts through Ollama structured output ({client.model})...")
        # Untimed warm-up so model load time does not skew the latency average
        client.generate_raw("Hello", "")
        records = []
        for i, (_, ticket) in enumerate(samples.iterrows(), 1):
            context = build_context(ticket["evidence_json"])
            raw, metrics = client.generate_raw(ticket["customer_query"], context)
            error = validate(raw)
            action = None if error else json.loads(raw)["action"]
            records.append({
                "ticket_id": ticket["ticket_id"], "raw": raw, "error": error, "action": action,
                "expected_action": ticket.get("action") if ticket.get("action") in ("answer", "escalate") else None,
                **metrics,
            })
            status = "ok " if not error else "ERR"
            print(f"  [{i:>2}/{len(samples)}] {status} {action or '-':<8} {metrics['latency_ms']:>7,.0f} ms  {ticket['ticket_id']}")
        all_passed &= summarize("Ollama structured output", records)

    binary = args.llama_bin or shutil.which("llama-completion") or shutil.which("llama-cli")
    if not binary:
        print("\nllama.cpp binary not found; skipping GBNF test. Build it with:")
        print("  git clone https://github.com/ggerganov/llama.cpp")
        print("  cmake -B llama.cpp/build llama.cpp && cmake --build llama.cpp/build --config Release -j")
        print("  then pass --llama-bin llama.cpp/build/bin/llama-cli")
    else:
        gguf = Path(args.gguf) if args.gguf else find_ollama_gguf(client.model)
        if not gguf:
            print("\nNo GGUF found for llama.cpp; pass --gguf path/to/model.gguf")
        else:
            print(f"\nRunning {len(samples)} prompts through {binary} --grammar-file {GRAMMAR_PATH.name}...")
            records = []
            for i, (_, ticket) in enumerate(samples.iterrows(), 1):
                raw, latency_ms = run_llama_cpp(
                    binary, gguf, ticket["customer_query"], build_context(ticket["evidence_json"]), args.max_tokens
                )
                error = validate(raw)
                records.append({
                    "ticket_id": ticket["ticket_id"], "raw": raw, "error": error, "latency_ms": latency_ms,
                    "action": None if error else json.loads(raw)["action"], "expected_action": None,
                })
                print(f"  [{i:>2}/{len(samples)}] {'ok ' if not error else 'ERR'} {latency_ms:>7,.0f} ms  {ticket['ticket_id']}")
            all_passed &= summarize("llama.cpp GBNF grammar", records)

    print("\nRESULT:", "PASS - 100% schema-valid responses" if all_passed else "FAIL - see errors above")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
