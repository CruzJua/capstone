import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv, find_dotenv
from ollama import Client

from src.inference.schema import SupportResponse

GRAMMAR_PATH = Path(__file__).resolve().parent / "grammars" / "support_response.gbnf"

SYSTEM_PROMPT = """You are a customer support assistant for a small business.
Answer the customer's question using ONLY the provided context documents.

Rules:
- If the context contains the answer, set "action" to "answer" and list the exact document names you used in "cited_sources".
- If the context does not contain the answer, or the request needs a human (emergencies, disputes, account changes), set "action" to "escalate", explain briefly in "answer", and set "cited_sources" to [].
- "confidence" is a number between 0.0 and 1.0 reflecting how fully the context supports your answer.
- Never invent policies, prices, or document names."""


@dataclass
class GenerationResult:
    response: SupportResponse
    raw: str
    latency_ms: float
    eval_tokens: int
    tokens_per_second: float


class SupportInferenceClient:
    def __init__(
        self,
        model: Optional[str] = None,
        host: Optional[str] = None,
        temperature: float = 0.2,
        env_file: Optional[Path | str] = None,
    ):
        # Load environment variables
        if env_file:
            load_dotenv(dotenv_path=env_file, override=False)
        else:
            load_dotenv(find_dotenv(usecwd=True), override=False)

        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        self.client = Client(host=host or os.getenv("OLLAMA_HOST", "http://localhost:11434"))
        self.temperature = temperature

    @staticmethod
    def build_user_prompt(query: str, context: str) -> str:
        return f"Context documents:\n{context or '(no relevant documents found)'}\n\nCustomer question:\n{query}"

    def generate_raw(self, query: str, context: str) -> tuple[str, Dict[str, float]]:
        """Runs schema-constrained generation and returns the raw JSON text plus timing metrics.

        The JSON schema is enforced at decode time by Ollama, so the text should always parse.
        """
        result = self.client.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self.build_user_prompt(query, context)},
            ],
            format=SupportResponse.model_json_schema(),
            options={"temperature": self.temperature},
        )
        eval_tokens = result.eval_count or 0
        eval_seconds = (result.eval_duration or 0) / 1e9
        metrics = {
            "latency_ms": (result.total_duration or 0) / 1e6,
            "eval_tokens": eval_tokens,
            "tokens_per_second": eval_tokens / eval_seconds if eval_seconds else 0.0,
        }
        return result.message.content, metrics

    def generate(self, query: str, context: str) -> GenerationResult:
        raw, metrics = self.generate_raw(query, context)
        return GenerationResult(
            response=SupportResponse.model_validate_json(raw),
            raw=raw,
            latency_ms=metrics["latency_ms"],
            eval_tokens=int(metrics["eval_tokens"]),
            tokens_per_second=metrics["tokens_per_second"],
        )
