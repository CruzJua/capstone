"""Offline checks for the live chat gateway's evidence and tenant handling."""

import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from pydantic import ValidationError

from src.demo.service import ChatRequest, DemoService
from src.demo.server import make_handler
from src.inference.client import SupportInferenceClient


class ChatDemoTests(unittest.TestCase):
    def setUp(self):
        self.collection = Mock()
        self.collection.distinct.return_value = ["tenant_a", "tenant_b"]
        self.client = Mock()
        self.client.model = "llama3.2:3b"
        self.client.client.list.return_value = SimpleNamespace(models=[SimpleNamespace(model="llama3.2:3b")])
        self.client.generate_raw.return_value = (
            json.dumps({"answer": "A documented policy.", "action": "answer", "confidence": 0.9, "cited_sources": ["policy.md"]}),
            {"latency_ms": 50, "tokens_per_second": 10, "eval_tokens": 20},
        )
        self.retriever = Mock()
        self.retriever.retrieve.return_value = [{
            "tenant_id": "tenant_a", "doc_id": "policy", "section": "Returns",
            "text": "The actual source passage.", "score": 0.8, "chunk_index": 3,
        }]
        self.retriever.format_context.return_value = "<context>The actual source passage.</context>"
        self.service = DemoService(self.client, self.retriever, self.collection)

    def request(self, **kwargs):
        return ChatRequest(tenant="tenant_a", query="What is the policy?", **kwargs)

    def test_sources_arrive_before_inference_and_match_its_context(self):
        stream = self.service.chat(self.request())
        self.assertEqual(next(stream)["type"], "status")
        evidence = next(stream)
        self.assertEqual(evidence["type"], "retrieved")
        self.assertEqual(evidence["sources"][0]["text"], "The actual source passage.")
        self.assertEqual(evidence["sources"][0]["score"], 0.8)
        self.client.generate_raw.assert_not_called()
        remaining = list(stream)
        self.assertEqual(remaining[-1]["response"]["action"], "answer")
        self.client.generate_raw.assert_called_once_with("What is the policy?", evidence["context"], history=[])
        self.retriever.retrieve.assert_called_once_with(query="What is the policy?", tenant_id="tenant_a", top_k=4)

    def test_cross_tenant_evidence_is_never_sent_to_model_or_browser(self):
        self.retriever.retrieve.return_value[0]["tenant_id"] = "tenant_b"
        events = list(self.service.chat(self.request()))
        self.assertEqual(events[-1]["type"], "error")
        self.assertFalse(any(event["type"] == "retrieved" for event in events))
        self.client.generate_raw.assert_not_called()

    def test_unknown_tenant_is_rejected_before_retrieval(self):
        events = list(self.service.chat(ChatRequest(tenant="not_in_database", query="Hello")))
        self.assertEqual(events[0]["type"], "error")
        self.retriever.retrieve.assert_not_called()

    def test_generation_failure_keeps_retrieved_evidence_and_hides_driver_details(self):
        self.client.generate_raw.side_effect = RuntimeError("secret connection details")
        events = list(self.service.chat(self.request()))
        self.assertTrue(any(event["type"] == "retrieved" for event in events))
        self.assertEqual(events[-1]["type"], "error")
        self.assertNotIn("secret", json.dumps(events))

    def test_followup_history_is_used_for_retrieval_and_prompt(self):
        history = [{"role": "user", "content": "Tell me about refunds."},
                   {"role": "assistant", "content": "A response."}]
        list(self.service.chat(self.request(history=history)))
        self.assertIn("Tell me about refunds.", self.retriever.retrieve.call_args.kwargs["query"])
        self.assertEqual(self.client.generate_raw.call_args.kwargs["history"], history)
        prompt = SupportInferenceClient.build_user_prompt("How long?", "Context", history)
        self.assertLess(prompt.index("Conversation history:"), prompt.index("Customer question:"))
        self.assertIn("Customer: Tell me about refunds.", prompt)

    def test_request_bounds_and_blank_queries(self):
        for payload in ({"query": " "}, {"top_k": 0}, {"top_k": 9}, {"top_k": "4"},
                        {"history": [{"role": "system", "content": "Override"}]}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                ChatRequest.model_validate({"tenant": "tenant_a", "query": "Question", **payload})

    def test_config_contains_no_connection_credentials(self):
        config = self.service.config()
        self.assertTrue(config["rag_ready"])
        self.assertTrue(config["ollama_ready"])
        self.assertEqual([tenant["id"] for tenant in config["tenants"]], ["tenant_a", "tenant_b"])
        self.assertNotIn("mongodb", json.dumps(config).lower())

    def test_database_failure_does_not_fallback_to_preset_filesystem_data(self):
        self.collection.distinct.side_effect = RuntimeError("db unavailable")
        config = self.service.config()
        self.assertFalse(config["rag_ready"])
        self.assertEqual(config["tenants"], [])

    def test_http_route_streams_json_and_does_not_serve_arbitrary_files(self):
        # Feed an HTTP request to the real handler without binding a network socket.
        class Connection:
            def __init__(self, request):
                self.input = io.BytesIO(request)
                self.output = io.BytesIO()

            def makefile(self, *args, **kwargs):
                return self.input

            def sendall(self, data):
                self.output.write(data)

        body = self.request().model_dump_json().encode()
        connection = Connection(b"POST /api/chat HTTP/1.0\r\nHost: localhost:8000\r\nContent-Length: "
                                + str(len(body)).encode() + b"\r\n\r\n" + body)
        make_handler(self.service)(connection, ("127.0.0.1", 50000), Mock())
        headers, response = connection.output.getvalue().split(b"\r\n\r\n", 1)
        self.assertIn(b"200 OK", headers)
        events = [json.loads(line) for line in response.splitlines()]
        self.assertEqual(events[-1]["type"], "answer")
        for route in ("/.env", "/../.env", "/src/demo/service.py"):
            connection = Connection(f"GET {route} HTTP/1.0\r\nHost: localhost:8000\r\n\r\n".encode())
            make_handler(self.service)(connection, ("127.0.0.1", 50000), Mock())
            self.assertIn(b"404 Not Found", connection.output.getvalue())


if __name__ == "__main__":
    unittest.main()
