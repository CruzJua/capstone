"""Offline checks for the internal chat service behind the gateway's POST /api/chat."""

import json
import os
import random
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.chat.answer_stream import AnswerStreamer
from src.chat.orchestrator import AgentConfig, ChatOrchestrator, ChatServiceRequest, build_system_prompt
from src.chat.server import ENV_FILE, TOKEN_HEADER, load_env, make_handler
from src.inference.client import SYSTEM_PROMPT, SupportInferenceClient


def stream_all(text, sizes):
    streamer = AnswerStreamer()
    out, index = [], 0
    while index < len(text):
        size = sizes.pop() if sizes else 1
        out.append(streamer.feed(text[index:index + size]))
        index += size
    return "".join(out), streamer


class AnswerStreamerTests(unittest.TestCase):
    SAMPLES = [
        {"answer": "Plain answer.", "cited_sources": ["a.md"], "confidence": 0.9, "action": "answer"},
        {"answer": 'Quotes " and \\ backslash\nnewline\ttab and / slash', "cited_sources": [], "confidence": 1, "action": "escalate"},
        {"answer": "Unicode café — \U0001F600 done", "cited_sources": ["x"], "confidence": 0.5, "action": "answer"},
        {"cited_sources": ["has \"answer\" inside", ["nested", {"answer": "wrong"}]], "confidence": 0.2, "answer": "Answer last.", "action": "answer"},
        {"answer": "", "cited_sources": [], "confidence": 0.0, "action": "escalate"},
    ]

    def test_matches_json_for_arbitrary_chunking_and_escaping(self):
        rng = random.Random(7)
        for sample in self.SAMPLES:
            for ensure_ascii in (True, False):
                text = json.dumps(sample, ensure_ascii=ensure_ascii, indent=rng.choice([None, 2]))
                for _ in range(40):
                    sizes = [rng.randint(1, 9) for _ in range(len(text))]
                    streamed, streamer = stream_all(text, sizes)
                    self.assertEqual(streamed, sample["answer"], text)
                    self.assertTrue(streamer.answer_finished)

    def test_surrogate_pair_split_across_chunks(self):
        text = '{"answer": "\\ud83d\\ude00!"}'
        for split in range(1, len(text)):
            streamer = AnswerStreamer()
            streamed = streamer.feed(text[:split]) + streamer.feed(text[split:])
            self.assertEqual(streamed, "\U0001F600!")

    def test_no_answer_field_streams_nothing(self):
        streamer = AnswerStreamer()
        self.assertEqual(streamer.feed('{"confidence": 0.1, "action": "escalate"}'), "")
        self.assertFalse(streamer.answer_started)


def make_chunk(tenant="tenant_a", doc="policy", section="Returns", score=0.8, text="SECRET CHUNK TEXT"):
    return {"tenant_id": tenant, "doc_id": doc, "section": section, "score": score, "text": text, "chunk_index": 0}


class FakeOllama:
    def __init__(self, pieces):
        self.pieces = pieces
        self.calls = []
        self.closed = False

    def chat(self, **kwargs):
        self.calls.append(kwargs)

        def generator():
            try:
                for piece in self.pieces:
                    yield SimpleNamespace(message=SimpleNamespace(content=piece))
            finally:
                self.closed = True

        return generator()


def model_json(answer="Items are refundable within 30 days.", action="answer"):
    return json.dumps({"answer": answer, "cited_sources": ["policy"], "confidence": 0.9, "action": action})


def split(text, size=4):
    return [text[i:i + size] for i in range(0, len(text), size)]


class OrchestratorTests(unittest.TestCase):
    def build(self, chunks=None, pieces=None):
        self.retriever = Mock()
        self.retriever.retrieve.return_value = [make_chunk()] if chunks is None else chunks
        self.retriever.format_context.side_effect = lambda found: "CTX:" + ",".join(c["doc_id"] for c in found)
        self.ollama = FakeOllama(split(model_json()) if pieces is None else pieces)
        client = SimpleNamespace(
            model="llama3.2:3b", client=self.ollama, build_user_prompt=SupportInferenceClient.build_user_prompt
        )
        return ChatOrchestrator(self.retriever, client)

    def request(self, **kwargs):
        kwargs.setdefault("tenant_id", "tenant_a")
        kwargs.setdefault("query", "What is the return policy?")
        return ChatServiceRequest(**kwargs)

    def test_full_stream_sources_tokens_done(self):
        events = list(self.build().stream(self.request()))
        self.assertEqual([e["type"] for e in events][0], "sources")
        self.assertEqual(
            events[-1],
            {"type": "done", "action": "answer", "confidence": 0.9, "cited_sources": ["policy"]},
        )
        text = "".join(e["text"] for e in events if e["type"] == "token")
        self.assertEqual(text, "Items are refundable within 30 days.")
        self.assertGreater(sum(e["type"] == "token" for e in events), 3)

    def test_sources_expose_only_doc_id_section_and_score(self):
        events = list(self.build().stream(self.request()))
        self.assertEqual(events[0]["sources"], [{"doc_id": "policy", "section": "Returns", "score": 0.8}])
        self.assertNotIn("SECRET CHUNK TEXT", json.dumps(events))

    def test_retrieval_is_scoped_to_the_requested_tenant_and_uses_config(self):
        config = {"max_context_chunks": 2, "similarity_threshold": 0.5, "temperature": 0.35}
        list(self.build().stream(self.request(agent_config=config)))
        self.retriever.retrieve.assert_called_once_with(
            query="What is the return policy?", tenant_id="tenant_a", top_k=2
        )
        self.assertEqual(self.ollama.calls[0]["options"], {"temperature": 0.35})
        self.assertTrue(self.ollama.calls[0]["stream"])

    def test_cross_tenant_chunk_fails_closed_before_any_generation(self):
        orchestrator = self.build(chunks=[make_chunk(), make_chunk(tenant="tenant_b", doc="leak")])
        events = list(orchestrator.stream(self.request()))
        self.assertEqual(events, [{"type": "error", "code": "retrieval_failed", "message": "Retrieval failed."}])
        self.assertEqual(self.ollama.calls, [])

    def test_retrieval_exception_is_reported_without_driver_details(self):
        orchestrator = self.build()
        self.retriever.retrieve.side_effect = RuntimeError("mongodb://user:password@host")
        events = list(orchestrator.stream(self.request()))
        self.assertEqual(events[0]["code"], "retrieval_failed")
        self.assertNotIn("password", json.dumps(events))

    def test_chunks_below_threshold_are_dropped_and_model_sees_no_context(self):
        orchestrator = self.build(chunks=[make_chunk(score=0.6)])
        events = list(orchestrator.stream(self.request()))
        self.assertEqual(events[0], {"type": "sources", "sources": []})
        self.retriever.format_context.assert_called_once_with([])
        self.assertNotIn("CTX:policy", self.ollama.calls[0]["messages"][1]["content"])

    def test_invalid_model_output_becomes_an_error_event(self):
        orchestrator = self.build(pieces=['{"answer": "Half', ' an object'])
        events = list(orchestrator.stream(self.request()))
        self.assertEqual(events[-1]["code"], "generation_failed")
        self.assertNotEqual(events[-1]["type"], "done")

    def test_ollama_failure_becomes_an_error_event(self):
        orchestrator = self.build()
        self.ollama.chat = Mock(side_effect=ConnectionError("http://internal:11434 refused"))
        events = list(orchestrator.stream(self.request()))
        # An unreachable model server is told apart from bad model output, and no internals leak.
        self.assertEqual(events[-1], {"type": "error", "code": "model_unavailable", "message": "The assistant ran into a problem."})

    def test_other_model_failures_stay_generation_failed(self):
        orchestrator = self.build()
        self.ollama.chat = Mock(side_effect=RuntimeError("model crashed at /srv/internal"))
        events = list(orchestrator.stream(self.request()))
        self.assertEqual(events[-1], {"type": "error", "code": "generation_failed", "message": "The assistant ran into a problem."})

    def test_answer_after_other_fields_still_streams(self):
        text = json.dumps({"cited_sources": [], "confidence": 0.1, "action": "escalate", "answer": "Please contact us."})
        events = list(self.build(pieces=split(text, 5)).stream(self.request()))
        self.assertEqual("".join(e["text"] for e in events if e["type"] == "token"), "Please contact us.")
        self.assertEqual(events[-1]["action"], "escalate")

    def test_an_escalation_reports_action_confidence_and_sources_for_the_gateway(self):
        reply = json.dumps(
            {"answer": "A person will follow up.", "cited_sources": [], "confidence": 0.31, "action": "escalate"}
        )
        events = list(self.build(pieces=split(reply, 7)).stream(self.request()))
        self.assertEqual(
            events[-1], {"type": "done", "action": "escalate", "confidence": 0.31, "cited_sources": []}
        )
        self.assertEqual("".join(e["text"] for e in events if e["type"] == "token"), "A person will follow up.")

    def test_closing_the_stream_stops_generation(self):
        stream = self.build().stream(self.request())
        next(stream)
        next(stream)
        stream.close()
        self.assertTrue(self.ollama.closed)

    def test_history_feeds_retrieval_and_prompt(self):
        history = [{"role": "user", "content": "Do you ship abroad?"}, {"role": "assistant", "content": "Yes."}]
        orchestrator = self.build()
        list(orchestrator.stream(self.request(history=history)))
        query = self.retriever.retrieve.call_args.kwargs["query"]
        self.assertIn("Do you ship abroad?", query)
        self.assertIn("Customer: Do you ship abroad?", self.ollama.calls[0]["messages"][1]["content"])

    def test_system_prompt_keeps_trained_text_and_appends_tenant_instructions(self):
        self.assertEqual(build_system_prompt(AgentConfig()), SYSTEM_PROMPT)
        prompt = build_system_prompt(AgentConfig(system_prompt="Be brief.", agent_tone="warm"))
        self.assertTrue(prompt.startswith(SYSTEM_PROMPT))
        self.assertTrue(prompt.endswith("Business instructions:\nBe brief.\nTone: warm"))

    def test_request_rejects_unsafe_tenant_ids_and_oversized_values(self):
        for bad in ({"tenant_id": "../x"}, {"tenant_id": "A B"}, {"query": "x" * 2001}, {"agent_config": {"temperature": 3}}):
            with self.assertRaises(ValueError):
                self.request(**bad)


class ServerTests(unittest.TestCase):
    def start(self, orchestrator, token=""):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(orchestrator, token))
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    @staticmethod
    def post(url, payload, headers=None):
        request = urllib.request.Request(
            url + "/v1/chat", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        return urllib.request.urlopen(request, timeout=5)

    def test_streams_ndjson_events(self):
        orchestrator = Mock()
        orchestrator.stream.side_effect = lambda request: iter([
            {"type": "sources", "sources": []}, {"type": "token", "text": "Hi"}, {"type": "done", "action": "answer"},
        ])
        url = self.start(orchestrator)
        with self.post(url, {"tenant_id": "tenant_a", "query": "hello"}) as response:
            self.assertEqual(response.headers["Content-Type"], "application/x-ndjson; charset=utf-8")
            events = [json.loads(line) for line in response.read().decode().splitlines()]
        self.assertEqual([e["type"] for e in events], ["sources", "token", "done"])
        self.assertEqual(orchestrator.stream.call_args.args[0].tenant_id, "tenant_a")

    def test_rejects_invalid_requests_and_wrong_token(self):
        orchestrator = Mock()
        url = self.start(orchestrator, token="s3cret")

        def status_of(payload, headers=None):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.post(url, payload, headers)
            caught.exception.close()
            return caught.exception.code

        self.assertEqual(status_of({"tenant_id": "tenant_a", "query": "hello"}), 401)
        self.assertEqual(status_of({"tenant_id": "tenant_a", "query": "hello"}, {TOKEN_HEADER: "wrong"}), 401)
        self.assertEqual(status_of({"tenant_id": "BAD ID", "query": "hello"}, {TOKEN_HEADER: "s3cret"}), 400)
        orchestrator.stream.assert_not_called()

    def test_correct_token_is_accepted(self):
        orchestrator = Mock()
        orchestrator.stream.side_effect = lambda request: iter([{"type": "done", "action": "answer"}])
        url = self.start(orchestrator, token="s3cret")
        with self.post(url, {"tenant_id": "tenant_a", "query": "hello"}, {TOKEN_HEADER: "s3cret"}) as response:
            self.assertEqual(response.status, 200)


class LiveServiceDatabaseTests(unittest.TestCase):
    """The live chat service must read MONGODB_DB_NAME (production), never MONGODB_TRAINING_DB_NAME."""

    ENV = {
        "MONGODB_URI": "mongodb://db.invalid:27017",
        "MONGODB_DB_NAME": "live_database_x",
        "MONGODB_TRAINING_DB_NAME": "training_database_y",
        "MONGODB_COLLECTION_NAME": "chunks_z",
    }

    def build_retriever(self, env=None, **kwargs):
        from src.rag.retriever import RAGRetriever

        with patch.dict(os.environ, env or self.ENV, clear=True), \
                patch("src.rag.retriever.MongoClient") as mongo_client, \
                patch("src.rag.retriever.SentenceTransformer"):
            retriever = RAGRetriever(env_file=Path(tempfile.gettempdir()) / "no-such-dir" / ".env", **kwargs)
        return retriever, mongo_client

    def test_retriever_uses_the_live_database_when_both_variables_are_set(self):
        retriever, mongo_client = self.build_retriever()
        mongo_client.return_value.__getitem__.assert_called_once_with("live_database_x")
        mongo_client.return_value.__getitem__.return_value.__getitem__.assert_called_once_with("chunks_z")
        self.assertNotIn("training_database_y", str(mongo_client.mock_calls))

    def test_the_chat_service_builds_its_retriever_without_a_database_override(self):
        from src.chat import server

        built = {}

        class SpyRetriever:
            def __init__(self, **kwargs):
                built.update(kwargs)

        with patch.dict(os.environ, self.ENV, clear=True), \
                patch("src.rag.retriever.RAGRetriever", SpyRetriever), \
                patch("src.inference.client.SupportInferenceClient", Mock()):
            server.build_orchestrator()
        self.assertNotIn("db_name", built)
        self.assertEqual(built["server_selection_timeout_ms"], server.DEFAULT_SERVER_SELECTION_TIMEOUT_MS)

    def test_selection_timeout_is_bounded_and_configurable(self):
        from src.chat.server import DEFAULT_SERVER_SELECTION_TIMEOUT_MS, server_selection_timeout_ms

        self.assertEqual(server_selection_timeout_ms({}), DEFAULT_SERVER_SELECTION_TIMEOUT_MS)
        self.assertEqual(server_selection_timeout_ms({"MONGODB_SERVER_SELECTION_TIMEOUT_MS": "1500"}), 1500)
        for bad in ("abc", "0", "-5"):
            self.assertEqual(
                server_selection_timeout_ms({"MONGODB_SERVER_SELECTION_TIMEOUT_MS": bad}),
                DEFAULT_SERVER_SELECTION_TIMEOUT_MS,
            )

    def test_the_timeout_reaches_the_mongo_client(self):
        _, mongo_client = self.build_retriever(server_selection_timeout_ms=1500)
        self.assertEqual(mongo_client.call_args.kwargs, {"serverSelectionTimeoutMS": 1500})
        _, default_client = self.build_retriever()
        self.assertEqual(default_client.call_args.kwargs, {})


class EnvLoadingTests(unittest.TestCase):
    def write_env(self, text):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / ".env"
        path.write_text(text)
        return path

    def test_reads_the_service_token_and_settings_from_the_env_file(self):
        path = self.write_env('CHAT_BACKEND_TOKEN=file-secret\nOLLAMA_MODEL="llama3.2:3b"\n')
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHAT_BACKEND_TOKEN", None)
            os.environ.pop("OLLAMA_MODEL", None)
            self.assertTrue(load_env(path))
            self.assertEqual(os.environ["CHAT_BACKEND_TOKEN"], "file-secret")
            self.assertEqual(os.environ["OLLAMA_MODEL"], "llama3.2:3b")

    def test_variables_already_in_the_environment_win_over_the_file(self):
        path = self.write_env("CHAT_BACKEND_TOKEN=file-secret\n")
        with patch.dict(os.environ, {"CHAT_BACKEND_TOKEN": "shell-secret"}):
            load_env(path)
            self.assertEqual(os.environ["CHAT_BACKEND_TOKEN"], "shell-secret")

    def test_a_missing_env_file_is_not_an_error(self):
        self.assertFalse(load_env(Path(tempfile.gettempdir()) / "definitely-missing-dir" / ".env"))

    def test_default_env_file_is_the_repository_root_env(self):
        self.assertEqual(ENV_FILE.name, ".env")
        self.assertEqual(ENV_FILE.parent, Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    unittest.main()
