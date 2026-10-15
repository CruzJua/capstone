"""
Synthetic Support Ticket Generator (PRO390 Capstone)

This script generates synthetic customer support data for fictional businesses using
Gemini's explicit context caching and asynchronous batch processing.

Workflow:
    prepare         Create context caches and write requests.jsonl (--dry-run for local test)
    submit          Upload requests and start the Gemini Batch job
    status          Check batch job state (--wait to poll until finished)
    download        Fetch raw results from Gemini Batch API
    extend-caches   Reset cache TTL (if batch job is taking longer)
    cleanup         Delete caches (stops storage billing) and uploaded files
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from google import genai
from google.genai._transformers import t_schema
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_OUT_DIR = DEFAULT_DATA_DIR / "generated"
DEFAULT_MODEL = "gemini-3.8-flash"

# Minimum tokens required by Gemini for context caching
MIN_CACHE_TOKENS = 4096

# Dataset mix per business (fractions sum to 1.0)
INTERACTION_MIX = [
    ("single_qa", 0.45),
    ("multi_turn", 0.15),
    ("inference", 0.10),
    ("escalation", 0.10),
    ("unanswerable", 0.20),
]

INTERACTION_TYPES = [t for t, _ in INTERACTION_MIX]

TYPE_BRIEF = {
    "single_qa": (
        "ONE customer message that the documents fully answer. "
        "is_answerable=true, action=answer, escalation_reason=none."
    ),
    "multi_turn": (
        "A short conversation: customer, agent, customer (optionally one more agent/customer pair). "
        "The LAST message is from the customer and its question is answerable from the documents; "
        "it may depend on earlier turns (pronouns, 'what about...'). Agent turns must also be "
        "document-grounded. is_answerable=true, action=answer, escalation_reason=none."
    ),
    "inference": (
        "ONE customer message whose answer is in the documents but requires combining two or more "
        "passages or applying a rule to the customer's specifics (dates, quantities, eligibility). "
        "Give 2+ evidence quotes. is_answerable=true, action=answer, escalation_reason=none."
    ),
    "escalation": (
        "ONE customer message where the documents themselves require a human, urgent contact, "
        "staff approval or handoff (e.g. FAQ entries with escalate_to_human=true, emergencies, "
        "disputes, exceptions). Give the document-supported interim guidance, then hand off. "
        "is_answerable=true, action=escalate, escalation_reason=docs_require_human, "
        "ticket_summary filled."
    ),
    "unanswerable": (
        "ONE plausible, specific, in-domain customer message whose KEY fact is NOT stated anywhere "
        "in the documents. Do not pick anything the documents address, even partially, and do not "
        "pick questions about the other businesses. is_answerable=false, evidence=[], "
        "action=escalate, escalation_reason=not_in_docs, ticket_summary filled. The answer must say "
        "you cannot confirm this, must not guess, and must offer a handoff to staff."
    ),
}

PERSONAS = [
    "polite and concise", "frustrated and terse", "anxious and over-explains",
    "casual with typos and no punctuation", "formal and precise", "confused first-time customer",
    "busy professional writing from a phone", "repeat customer who assumes you know their history",
    "elderly customer, unfamiliar with jargon", "detail-oriented, quotes specific numbers",
    "angry but reasonable", "friendly and chatty",
]

LENGTHS = ["one short line", "two or three sentences", "a detailed paragraph with specifics"]
ESCALATION_REASONS = ["none", "docs_require_human", "not_in_docs"]

SYSTEM_PROMPT = """\
You are the TEACHER model that writes training data for a small customer-support AI agent \
working for {business_name}.

The business's complete knowledge base is provided in this context as documents, each wrapped in \
"=== DOCUMENT: <filename> ===" markers. That knowledge base is the ONLY source of truth. The \
student agent will later answer ONLY from retrieved excerpts of these documents.

Hard rules
1. Never use outside knowledge for business facts. Every price, time window, phone number, policy \
and procedure in an answer must appear in the documents. Never invent any.
2. `evidence` quotes must be copied VERBATIM (same words, same order) from one document, \
15-300 characters each, with `source` equal to the exact filename in the marker. Do not paraphrase \
inside a quote. Do not stitch two passages into one quote.
3. Customer messages must read like real customers: informal, partial information, emotion, typos \
when the persona calls for it. Customers never mention "the documents" or file names, and the \
customer message must not contain the answer.
4. Answers are written as the support agent: warm, brief, direct, no filler, no markdown headings. \
Answer only what the evidence supports. If the documents flag a situation for a human or urgent \
contact, say so.
5. Fields:
   - action: "answer" if the documents let you fully resolve the message, otherwise "escalate".
   - escalation_reason: "none" | "docs_require_human" (documents say a human/urgent contact is \
needed) | "not_in_docs" (the documents lack the needed fact).
   - confidence: 0.0-1.0, how fully the evidence supports the answer. Direct match >= 0.85; \
inference 0.6-0.85; escalation or not_in_docs 0.0-0.4.
   - rationale: 1-3 sentences linking the evidence to the answer (or explaining the absence).
   - ticket_summary: for action=escalate, a 2-4 sentence hand-off note for a human agent \
(who, what, what was already advised, urgency). Otherwise an empty string.
   - category: a short snake_case topic label (e.g. post_op_care, refunds, allergens).
6. When several examples are requested, make them clearly different from each other: different \
facts, different documents/sections, different phrasing.
"""


# ---------------------------------------------------------------------------
# Structured Output Models
# ---------------------------------------------------------------------------
class Message(BaseModel):
    role: Literal["customer", "agent"]
    content: str


class Evidence(BaseModel):
    source: str
    quote: str


class Ticket(BaseModel):
    interaction_type: Literal["single_qa", "multi_turn", "inference", "escalation", "unanswerable"]
    category: str
    messages: list[Message] = Field(min_length=1)
    is_answerable: bool
    evidence: list[Evidence]
    rationale: str
    action: Literal["answer", "escalate"]
    escalation_reason: Literal["none", "docs_require_human", "not_in_docs"]
    answer: str
    confidence: float
    ticket_summary: str


def batch_schema(num_tickets: int) -> dict:
    """Generate the structured JSON schema for Gemini response format."""
    ticket_schema = t_schema(None, Ticket).to_json_dict()
    return {
        "type": "OBJECT",
        "properties": {
            "tickets": {
                "type": "ARRAY",
                "minItems": num_tickets,
                "maxItems": num_tickets,
                "items": ticket_schema,
            }
        },
        "required": ["tickets"],
    }

# ---------- Helper Functions ----------

def log(msg: str = "") -> None:
    print(msg, flush=True)

def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)

def get_client() -> genai.Client:
    load_dotenv(ROOT / ".env")
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        die("GEMINI_API_KEY is not set.")
    return genai.Client()

# ---------- Loading Business ----------

class Business:
    """Encapsulates documentation and prompts for a single business tenant."""

    def __init__(self, key: str, path: Path, include_reference: bool):
        self.key = key
        self.path = path
        self.docs: dict[str, str] = {}

        # Read markdown, JSON, and text documentation files
        for file_path in sorted(path.rglob("*")):
            if not file_path.is_file() or file_path.suffix.lower() not in {".md", ".json", ".txt"}:
                continue
            relative_path = file_path.relative_to(path).as_posix()
            if relative_path.startswith("generation_reference/") and not include_reference:
                continue
            self.docs[relative_path] = file_path.read_text(encoding="utf-8")

        self.name = self._extract_company_name()

    def _extract_company_name(self) -> str:
        faq_file = self.path / "faq_support_knowledgebase.json"
        try:
            faq_data = json.loads(faq_file.read_text(encoding="utf-8"))
            meta = faq_data.get("knowledgebase_metadata", {})
            if meta.get("company"):
                return meta["company"]
        except (OSError, ValueError):
            pass
        return self.key.replace("_", " ").title()

    @property
    def kb_docs(self) -> list[str]:
        """Documentation files eligible to be the focus of questions."""
        return [doc for doc in self.docs if not doc.startswith("generation_reference/")]

    def corpus_text(self) -> str:
        """Concatenate all documents into a labeled context block."""
        parts = [f"Business: {self.name}\n"]
        for filename, content in self.docs.items():
            parts.append(f"=== DOCUMENT: {filename} ===\n{content.strip()}\n=== END DOCUMENT: {filename} ===\n")
        return "\n".join(parts)

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(business_name=self.name)

    def fingerprint(self, model: str) -> str:
        """Compute a hash fingerprint to detect changes in corpus or prompt."""
        hasher = hashlib.sha256()
        for piece in (model, self.system_prompt(), self.corpus_text()):
            hasher.update(piece.encode("utf-8"))
        return hasher.hexdigest()[:16]

    def token_estimate(self, client: genai.Client | None = None, model: str = DEFAULT_MODEL) -> int:
        """Count tokens via Gemini API if client is available; else use local character heuristic."""
        if client:
            try:
                res = client.models.count_tokens(model=model, contents=self.corpus_text())
                return res.total_tokens
            except Exception:
                pass
        return sum(round(len(text) / (3.3 if name.endswith(".json") else 3.9)) for name, text in self.docs.items())


def load_businesses(args) -> list[Business]:
    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        die(f"data dir not found: {data_dir}")

    selected = set(args.businesses) if args.businesses else None
    businesses = []

    for entry in sorted(data_dir.iterdir()):
        if not entry.is_dir() or entry.name == "generated" or entry.name.startswith("."):
            continue
        if selected and entry.name not in selected:
            continue
        businesses.append(Business(entry.name, entry, args.include_reference))

    if selected:
        missing = selected - {b.key for b in businesses}
        if missing:
            die(f"unknown business(es): {', '.join(sorted(missing))}")

    if not businesses:
        die(f"no businesses found in {data_dir}")
    return businesses


# ---------- Prep Helper Functions ----------

def allocate_counts(total_count: int) -> dict[str, int]:
    """Distribute total tickets across interaction types using the largest-remainder method."""
    raw_counts = {itype: total_count * fraction for itype, fraction in INTERACTION_MIX}
    rounded_counts = {itype: int(val) for itype, val in raw_counts.items()}
    leftover = total_count - sum(rounded_counts.values())

    sorted_by_remainder = sorted(raw_counts, key=lambda k: raw_counts[k] - rounded_counts[k], reverse=True)
    for itype in sorted_by_remainder[:leftover]:
        rounded_counts[itype] += 1
    return rounded_counts


def build_plan(business: Business, per_business: int, per_request: int, seed: int) -> list[dict]:
    """Generate request chunks with diverse personas, lengths, and focus documents."""
    rng = random.Random(f"{seed}:{business.key}")

    interaction_types: list[str] = []
    for itype, count in allocate_counts(per_business).items():
        interaction_types.extend([itype] * count)
    rng.shuffle(interaction_types)

    docs = business.kb_docs[:]
    rng.shuffle(docs)

    specs = []
    for idx, itype in enumerate(interaction_types):
        specs.append({
            "interaction_type": itype,
            "focus_doc": docs[idx % len(docs)],
            "persona": rng.choice(PERSONAS),
            "length": rng.choice(LENGTHS),
        })

    requests = []
    for start_idx in range(0, len(specs), per_request):
        chunk = specs[start_idx:start_idx + per_request]
        req_key = f"{business.key}-{start_idx // per_request:04d}"
        requests.append({"key": req_key, "specs": chunk})
    return requests


def build_prompt(business: Business, specs: list[dict]) -> str:
    lines = [
        f"Write {len(specs)} training example(s) for {business.name}, in the order listed. "
        "Return them in the `tickets` array.",
        "",
    ]
    for i, spec in enumerate(specs, 1):
        lines.extend([
            f"Example {i}",
            f"- interaction_type: {spec['interaction_type']}",
            f"- what it is: {TYPE_BRIEF[spec['interaction_type']]}",
            f"- center it on this document: {spec['focus_doc']}"
            + (" (the question should be in a neighboring topic that this document does NOT settle)"
               if spec["interaction_type"] == "unanswerable" else ""),
            f"- customer style: {spec['persona']}; message length: {spec['length']}",
            "",
        ])
    return "\n".join(lines).rstrip()


def request_line(key: str, cache_name: str, prompt: str, num_tickets: int, args) -> dict:
    gen_config = {
        "temperature": args.temperature,
        "maxOutputTokens": 1500 * num_tickets + 2048,
        "responseMimeType": "application/json",
        "responseJsonSchema": batch_schema(num_tickets),
    }
    if args.thinking_level:
        gen_config["thinkingConfig"] = {"thinkingLevel": args.thinking_level.upper()}

    return {
        "key": key,
        "request": {
            "cachedContent": cache_name,
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        },
    }

# ---------- State (Cache names and batch job names) ----------


def state_path(out_dir: Path) -> Path:
    return out_dir / "state.json"


def load_state(out_dir: Path) -> dict:
    path = state_path(out_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"caches": {}, "runs": {}}


def save_state(out_dir: Path, state: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path(out_dir).write_text(json.dumps(state, indent=2), encoding="utf-8")


def run_dir(args) -> Path:
    return Path(args.out_dir) / args.run_name


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_run(state: dict, name: str) -> dict:
    run = state["runs"].get(name)
    if not run:
        die(f"run '{name}' not found. Run `prepare --run-name {name}` first.")
    return run


# ---------------------------------------------------------------------------
# Subcommand: prepare
# ---------------------------------------------------------------------------
def ensure_cache(client, state: dict, business: Business, args) -> str:
    from google.genai import types

    fp = business.fingerprint(args.model)
    entry = state["caches"].get(business.key)

    if entry and entry.get("fingerprint") == fp:
        try:
            live = client.caches.get(name=entry["name"])
            log(f"  {business.key}: reusing cache {entry['name']} (expires {live.expire_time})")
            return entry["name"]
        except Exception:
            log(f"  {business.key}: stored cache expired or missing, recreating...")

    cache = client.caches.create(
        model=args.model,
        config=types.CreateCachedContentConfig(
            display_name=f"pro390-{business.key}",
            system_instruction=business.system_prompt(),
            contents=[types.Content(role="user", parts=[types.Part(text=business.corpus_text())])],
            ttl=f"{int(args.cache_ttl_hours * 3600)}s",
        ),
    )

    usage = getattr(cache, "usage_metadata", None)
    tokens = getattr(usage, "total_token_count", None)
    state["caches"][business.key] = {
        "name": cache.name,
        "fingerprint": fp,
        "model": args.model,
        "tokens": tokens,
        "created": now_iso(),
        "ttl_hours": args.cache_ttl_hours,
    }

    save_state(Path(args.out_dir), state)
    token_str = f" ({tokens:,} tokens)" if tokens else ""
    log(f"  {business.key}: created {cache.name}{token_str}")
    return cache.name


def cmd_prepare(args) -> None:
    businesses = load_businesses(args)
    out_dir = Path(args.out_dir)
    rdir = run_dir(args)
    rdir.mkdir(parents=True, exist_ok=True)
    state = load_state(out_dir)

    client = None if args.dry_run else get_client()

    too_small = [b.key for b in businesses if b.token_estimate(client, args.model) < MIN_CACHE_TOKENS]
    if too_small and not args.dry_run:
        die(f"corpus below the {MIN_CACHE_TOKENS}-token cache minimum for: {', '.join(too_small)}")

    log(f"Preparing run '{args.run_name}' with {args.model}"
        f"{'  [DRY RUN: no API calls]' if args.dry_run else ''}")

    plan: dict[str, dict] = {}
    request_lines: list[dict] = []

    for business in businesses:
        cache_name = (f"cachedContents/DRYRUN-{business.key}" if args.dry_run
                      else ensure_cache(client, state, business, args))

        for req in build_plan(business, args.per_business, args.tickets_per_request, args.seed):
            prompt = build_prompt(business, req["specs"])
            request_lines.append(request_line(req["key"], cache_name, prompt, len(req["specs"]), args))
            plan[req["key"]] = {"business": business.key, "specs": req["specs"]}

    requests_file = rdir / "requests.jsonl"
    with requests_file.open("w", encoding="utf-8") as f:
        for line in request_lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    (rdir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    state["runs"][args.run_name] = {
        "model": args.model,
        "per_business": args.per_business,
        "tickets_per_request": args.tickets_per_request,
        "dry_run": args.dry_run,
        "requests_file": str(requests_file),
        "prepared": now_iso(),
        "businesses": [b.key for b in businesses],
        "include_reference": args.include_reference,
        "cache_hours": args.cache_ttl_hours,
    }
    save_state(out_dir, state)

    total_tickets = sum(len(p["specs"]) for p in plan.values())
    log(f"\nWrote {len(request_lines):,} requests ({total_tickets:,} tickets) -> {requests_file}")
    log(f"Plan sidecar -> {rdir / 'plan.json'}")

    if args.dry_run:
        log("Dry run complete. Inspect requests.jsonl, then re-run without --dry-run.")
    else:
        log(f"Next: python scripts/business_data_generator.py submit --run-name {args.run_name}")


# ---------------------------------------------------------------------------
# Subcommand: submit
# ---------------------------------------------------------------------------
def cmd_submit(args) -> None:
    out_dir = Path(args.out_dir)
    state = load_state(out_dir)
    run = get_run(state, args.run_name)

    if run.get("dry_run"):
        die("this run was prepared with --dry-run (placeholder cache names). Re-run prepare without it.")

    if run.get("batch_job") and not args.force:
        die(f"run already submitted as {run['batch_job']}. Batch creation is not idempotent; "
            "use --force only if you really want a second job.")

    from google.genai import types

    client = get_client()
    log(f"Uploading {run['requests_file']} ...")
    uploaded = client.files.upload(
        file=run["requests_file"],
        config=types.UploadFileConfig(display_name=f"pro390-{args.run_name}-requests", mime_type="jsonl"),
    )

    job = client.batches.create(
        model=run["model"],
        src=uploaded.name,
        config={"display_name": f"pro390-{args.run_name}"},
    )

    run.update({
        "uploaded_file": uploaded.name,
        "batch_job": job.name,
        "submitted": now_iso(),
    })
    save_state(out_dir, state)

    state_name = getattr(job.state, "name", str(job.state))
    log(f"Batch job created: {job.name}  (state: {state_name})")
    log(f"Next: python scripts/business_data_generator.py status --run-name {args.run_name} --wait")


# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------
TERMINAL_STATES = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}


def cmd_status(args) -> None:
    state = load_state(Path(args.out_dir))
    run = get_run(state, args.run_name)
    if not run.get("batch_job"):
        die("run has not been submitted yet.")

    client = get_client()
    while True:
        job = client.batches.get(name=run["batch_job"])
        state_name = job.state.name if hasattr(job.state, "name") else str(job.state or "UNKNOWN")
        stats = getattr(job, "batch_stats", None)

        extra = ""
        if stats is not None:
            extra = (
                f"  succeeded={getattr(stats, 'succeeded_request_count', '?')}"
                f" failed={getattr(stats, 'failed_request_count', '?')}"
                f" pending={getattr(stats, 'pending_request_count', '?')}"
            )

        timestamp = datetime.now().strftime("%H:%M:%S")
        log(f"[{timestamp}] {state_name}{extra}")

        if state_name in TERMINAL_STATES or not args.wait:
            break
        time.sleep(args.interval)

    if state_name == "JOB_STATE_SUCCEEDED":
        log(f"Next: python scripts/business_data_generator.py download --run-name {args.run_name}")
    elif state_name in TERMINAL_STATES:
        log(f"Job ended in {state_name}: {getattr(job, 'error', None)}")


# ---------------------------------------------------------------------------
# Subcommand: extend-caches
# ---------------------------------------------------------------------------
def cmd_extend_caches(args) -> None:
    from google.genai import types

    out_dir = Path(args.out_dir)
    state = load_state(out_dir)
    client = get_client()

    for business_key, entry in state["caches"].items():
        try:
            client.caches.update(
                name=entry["name"],
                config=types.UpdateCachedContentConfig(ttl=f"{int(args.hours * 3600)}s"),
            )
            log(f"{business_key}: TTL reset to {args.hours}h from now")
        except Exception as e:
            log(f"{business_key}: could not extend ({e})")


def cmd_cleanup(args) -> None:
    out_dir = Path(args.out_dir)
    state = load_state(out_dir)
    client = get_client()

    for business_key, entry in list(state["caches"].items()):
        try:
            client.caches.delete(name=entry["name"])
            log(f"deleted cache {entry['name']} ({business_key})")
        except Exception as e:
            log(f"cache {entry['name']} already gone or not deletable ({e})")
        state["caches"].pop(business_key, None)

    if args.files:
        for run_name, run_data in state["runs"].items():
            for key in ("uploaded_file", "results_file"):
                filename = run_data.pop(key, None)
                if filename:
                    try:
                        client.files.delete(name=filename)
                        log(f"deleted file {filename}")
                    except Exception as e:
                        log(f"file {filename}: {e}")

    save_state(out_dir, state)


# ---------------------------------------------------------------------------
# Subcommand: download
# ---------------------------------------------------------------------------
def cmd_download(args) -> None:
    out_dir = Path(args.out_dir)
    state = load_state(out_dir)
    rdir = run_dir(args)
    run = get_run(state, args.run_name) if not args.results_file else state["runs"].get(args.run_name, {})

    plan_file = rdir / "plan.json"
    if not plan_file.exists():
        die(f"{plan_file} missing; run prepare first.")

    results_path = rdir / "results.jsonl"
    if args.results_file:
        results_path = Path(args.results_file)
        if not results_path.exists():
            die(f"results file not found: {results_path}")
    else:
        if not run.get("batch_job"):
            die("run has not been submitted yet.")

        client = get_client()
        job = client.batches.get(name=run["batch_job"])
        state_name = job.state.name if hasattr(job.state, "name") else str(job.state or "UNKNOWN")

        if state_name != "JOB_STATE_SUCCEEDED":
            die(f"job state is {state_name}; wait for JOB_STATE_SUCCEEDED (see `status --wait`).")
        if not (job.dest and job.dest.file_name):
            die("job has no result file.")

        run["results_file"] = job.dest.file_name
        file_bytes = client.files.download(file=job.dest.file_name)
        if file_bytes:
            results_path.parent.mkdir(parents=True, exist_ok=True)
            results_path.write_bytes(file_bytes)

        save_state(out_dir, state)
        log(f"Raw results -> {results_path}")

    log(f"\nDownload complete. Raw results saved to: {results_path}")


# ---------------------------------------------------------------------------
# CLI Parser Definition
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    doc_summary = (__doc__ or "").strip().split("\n\n")[0]
    parser = argparse.ArgumentParser(
        description=doc_summary,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    def add_common_args(subp, is_run=True):
        subp.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="path to directory with business folders")
        subp.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="output directory for batches and state")
        subp.add_argument("--businesses", nargs="*", help="specific businesses to generate for (default: all)")
        subp.add_argument("--model", default=DEFAULT_MODEL, help="Gemini teacher model name")
        subp.add_argument("--include-reference", action="store_true",
                        help="include generation_reference/ files in cache context (default: False)")
        if is_run:
            subp.add_argument("--run-name", default="pilot", help="identifier for this generation run")

    def add_sizing_args(subp):
        subp.add_argument("--per-business", type=int, default=1000, help="number of tickets per business")
        subp.add_argument("--tickets-per-request", type=int, default=1,
                        help="tickets per batch API request (1-5 recommended)")
        subp.add_argument("--cache-ttl-hours", type=float, default=24, help="cache time-to-live in hours")

    # Command: prepare
    pr_parser = subparsers.add_parser("prepare", help="create caches and write requests.jsonl")
    add_common_args(pr_parser)
    add_sizing_args(pr_parser)
    pr_parser.add_argument("--seed", type=int, default=390, help="random seed for dataset sampling")
    pr_parser.add_argument("--temperature", type=float, default=1.0, help="model temperature (default: 1.0)")
    pr_parser.add_argument("--thinking-level", default="low", choices=["", "minimal", "low", "medium", "high"],
                        help="thinking budget level (default: low)")
    pr_parser.add_argument("--dry-run", action="store_true",
                        help="generate requests and plan locally without making Gemini API calls")
    pr_parser.set_defaults(fn=cmd_prepare)

    # Command: submit
    sb_parser = subparsers.add_parser("submit", help="upload requests and create the batch job")
    add_common_args(sb_parser)
    sb_parser.add_argument("--force", action="store_true", help="force resubmission even if batch job already exists")
    sb_parser.set_defaults(fn=cmd_submit)

    # Command: status
    st_parser = subparsers.add_parser("status", help="check batch job state")
    add_common_args(st_parser)
    st_parser.add_argument("--wait", action="store_true", help="poll periodically until job reaches a terminal state")
    st_parser.add_argument("--interval", type=int, default=60, help="polling interval in seconds (default: 60)")
    st_parser.set_defaults(fn=cmd_status)

    # Command: download
    dl_parser = subparsers.add_parser("download", help="fetch raw batch job results from Gemini API")
    add_common_args(dl_parser)
    dl_parser.add_argument("--results-file", help="path to an already downloaded local results JSONL file")
    dl_parser.set_defaults(fn=cmd_download)

    # Command: extend-caches
    ec_parser = subparsers.add_parser("extend-caches", help="reset cache TTL")
    add_common_args(ec_parser, is_run=False)
    ec_parser.add_argument("--hours", type=float, default=24, help="new TTL in hours from now (default: 24)")
    ec_parser.set_defaults(fn=cmd_extend_caches)

    # Command: cleanup
    cl_parser = subparsers.add_parser("cleanup", help="delete caches (and optionally uploaded files)")
    add_common_args(cl_parser, is_run=False)
    cl_parser.add_argument("--files", action="store_true", help="also delete uploaded request and result files")
    cl_parser.set_defaults(fn=cmd_cleanup)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
