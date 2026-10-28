"""Offline checks for bounded teacher requests and truthful incomplete logs."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import httpx

from src.evaluation.comparison import (
    BaselineExecutionError, GeminiTeacherAdapter, TeacherRequestError,
    run_baseline_evaluation, summarize_evaluation_log, _teacher_error_diagnostics,
)


class TeacherRuntimeTests(unittest.TestCase):
    def transport_adapter(self, handler, *, model="gemini-3.8-flash", max_attempts=1):
        from google import genai
        actual_client = genai.Client
        def client_with_transport(**arguments):
            self.assertIsNone(arguments["http_options"].timeout)
            arguments["http_options"].client_args = {"transport": httpx.MockTransport(handler)}
            return actual_client(**arguments)
        with patch("google.genai.Client", side_effect=client_with_transport):
            adapter = GeminiTeacherAdapter(model=model, api_key="unit-test-key", timeout_seconds=180,
                                           max_attempts=max_attempts)
        self.addCleanup(adapter.client.close)
        return adapter

    def test_real_sdk_sends_interactions_schema_without_server_deadline(self):
        requests = []
        answer = json.dumps({"action": "answer", "answer": "Approved", "confidence": 0.9, "cited_sources": []})
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"status": "completed", "steps": [
                {"type": "thought", "summary": [{"type": "text", "text": "PRIVATE THOUGHT"}]},
                {"type": "model_output", "content": [{"type": "text", "text": answer}]}],
                "usage": {"total_input_tokens": 10, "total_output_tokens": 3,
                          "total_thought_tokens": 7, "total_tokens": 20}})
        adapter = self.transport_adapter(handle, model="models/gemini-3.8-flash")
        raw, timing = adapter.generate_raw("Question", "Context")
        self.assertEqual(raw, answer)
        self.assertEqual(adapter.model, "gemini-3.8-flash")
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.url.path, "/v1beta/interactions")
        self.assertNotIn("x-server-timeout", request.headers)
        self.assertEqual(request.extensions["timeout"]["read"], 180)
        body = json.loads(request.content)
        self.assertEqual(body["model"], "models/gemini-3.8-flash")
        self.assertFalse(body["store"])
        self.assertFalse(body["background"])
        self.assertNotIn("previous_interaction_id", body)
        self.assertEqual(body["generation_config"], {"max_output_tokens": 65536, "thinking_level": "medium"})
        self.assertEqual(body["response_format"]["mime_type"], "application/json")
        self.assertIn("action", body["response_format"]["schema"]["properties"])
        self.assertIn("system_instruction", body)
        self.assertEqual(timing["prompt_tokens"], 10)
        self.assertEqual(timing["eval_tokens"], 10)
        self.assertEqual(timing["output_tokens"], 3)
        self.assertEqual(timing["thought_tokens"], 7)
        self.assertEqual(timing["total_tokens"], 20)

    def test_real_sdk_retry_budget_counts_initial_request_and_redacts_errors(self):
        for budget in (1, 2):
            requests = []
            def handle(request):
                requests.append(request)
                return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE", "message": "SECRET KEY"}})
            adapter = self.transport_adapter(handle, max_attempts=budget)
            with self.subTest(budget=budget), self.assertRaises(TeacherRequestError) as caught:
                adapter.generate_raw("Question", "Context")
            self.assertEqual(len(requests), budget)
            self.assertEqual(caught.exception.http_status, 503)
            self.assertNotIn("SECRET", str(caught.exception))

    @patch("google.genai.Client")
    def test_incomplete_interaction_is_not_a_successful_benchmark_response(self, client):
        adapter = GeminiTeacherAdapter(model="test-model", api_key="unit-test-key")
        for status in ("incomplete", "failed", "in_progress", "requires_action", None):
            client.return_value.interactions.create.return_value = SimpleNamespace(status=status, output_text="partial")
            with self.subTest(status=status), self.assertRaisesRegex(TeacherRequestError, "InteractionNotCompleted"):
                adapter.generate_raw("Question", "Context")

    def test_output_fallback_uses_only_final_model_output_and_usage_preserves_unknowns(self):
        interaction = SimpleNamespace(output_text=None, steps=[
            SimpleNamespace(type="model_output", content=[SimpleNamespace(type="text", text="Earlier")]),
            SimpleNamespace(type="thought", content=[SimpleNamespace(type="text", text="PRIVATE")]),
            SimpleNamespace(type="model_output", content=[SimpleNamespace(type="text", text="Final"),
                                                          SimpleNamespace(type="text", text=" answer")])])
        self.assertEqual(GeminiTeacherAdapter.output_text(interaction), "Final answer")
        self.assertTrue(all(value is None for value in GeminiTeacherAdapter.token_usage(interaction).values()))

    def test_interactions_settings_and_billable_thought_tokens_are_saved(self):
        raw = json.dumps({"action": "answer", "answer": "Answer", "confidence": 0.9})
        def handle(request):
            return httpx.Response(200, json={"status": "completed", "steps": [
                {"type": "model_output", "content": [{"type": "text", "text": raw}]}],
                "usage": {"total_input_tokens": 10, "total_output_tokens": 3,
                          "total_thought_tokens": 7, "total_tokens": 20}})
        adapter = self.transport_adapter(handle)
        question = {"ticket_id": "fixture", "customer_query": "Question", "ground_truth_action": "answer",
                    "is_answerable": True, "evidence_json": "[]"}
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), \
                patch("src.evaluation.comparison.get_hardware_metadata", return_value={}):
            _, records, log = run_baseline_evaluation(adapter, None, [question], output_dir=directory, model_role="teacher")
            data = json.loads(log.read_text())
        self.assertEqual(data["generation_settings"]["api"], "interactions")
        self.assertEqual(data["generation_settings"]["thinking_level"], "medium")
        self.assertIsNone(data["generation_settings"]["temperature"])
        self.assertFalse(data["teacher_request_settings"]["server_timeout_header"])
        self.assertEqual(records[0]["eval_tokens"], 10)
        self.assertEqual(records[0]["thought_tokens"], 7)

    @patch("google.genai.Client")
    def test_http_timeout_and_retry_budget_are_explicit(self, client):
        adapter = GeminiTeacherAdapter(model="test-model", api_key="unit-test-key",
                                       timeout_seconds=12.5, max_attempts=2)
        options = client.call_args.kwargs["http_options"]
        self.assertIsNone(options.timeout)
        self.assertEqual(options.retry_options.attempts, 2)
        self.assertEqual(client.return_value.interactions.sdk_configuration.retry_config.max_retries, 1)
        self.assertEqual(adapter.request_settings["timeout_seconds"], 12.5)
        self.assertEqual(adapter.request_settings["max_attempts"], 2)
        self.assertEqual(adapter.request_settings["api"], "interactions")
        self.assertEqual(adapter.request_settings["timeout_scope"], "client_transport_only")
        self.assertFalse(adapter.request_settings["server_timeout_header"])

    @patch("google.genai.Client")
    def test_invalid_runtime_values_fail_before_client_construction(self, client):
        for timeout, attempts in [(0, 1), (-1, 1), (float("nan"), 1),
                                  (float("inf"), 1), (1e308, 1), (True, 1), (0.0001, 1),
                                  (60, 0), (60, -1), (60, 1.5), (60, True)]:
            with self.subTest(timeout=timeout, attempts=attempts), self.assertRaises(ValueError):
                GeminiTeacherAdapter(model="test-model", api_key="unit-test-key",
                                     timeout_seconds=timeout, max_attempts=attempts)
        client.assert_not_called()

    @patch("google.genai.Client")
    def test_generation_config_is_preserved_and_provider_error_is_redacted(self, client):
        adapter = GeminiTeacherAdapter(model="test-model", api_key="unit-test-key")
        client.return_value.interactions.create.side_effect = TimeoutError("PRIVATE KEY AND REQUEST BODY")
        with self.assertRaises(TeacherRequestError) as caught:
            adapter.generate_raw("Question", "Context")
        self.assertEqual(str(caught.exception), "Gemini request failed (TimeoutError).")
        arguments = client.return_value.interactions.create.call_args.kwargs
        self.assertEqual(arguments["model"], "models/test-model")
        self.assertEqual(arguments["generation_config"], {"thinking_level": "medium", "max_output_tokens": 65536})
        self.assertEqual(arguments["response_format"]["mime_type"], "application/json")
        self.assertIn("action", arguments["response_format"]["schema"]["properties"])
        self.assertEqual(arguments["timeout"], 60.0)
        self.assertFalse(arguments["store"])
        self.assertNotIn("temperature", arguments["generation_config"])

    @patch("google.genai.Client")
    def test_safe_http_status_survives_without_provider_message(self, client):
        adapter = GeminiTeacherAdapter(model="test-model", api_key="unit-test-key")
        for attribute in ("code", "status_code", "response"):
            failure = RuntimeError("SECRET KEY IN PROVIDER MESSAGE")
            setattr(failure, attribute, SimpleNamespace(status_code=401) if attribute == "response" else 401)
            client.return_value.interactions.create.side_effect = failure
            with self.subTest(attribute=attribute), self.assertRaises(TeacherRequestError) as caught:
                adapter.generate_raw("Question", "Context")
            self.assertEqual(caught.exception.http_status, 401)
            self.assertEqual(str(caught.exception), "Gemini request failed (RuntimeError; HTTP 401).")
            self.assertNotIn("SECRET", str(caught.exception))

    def test_real_sdk_quota_codes_and_delay_survive_without_retry_or_private_data(self):
        for code in ("rate_limit_exceeded", "quota_exceeded", "too_many_requests"):
            requests = []
            def handle(request):
                requests.append(request)
                return httpx.Response(429, headers={"Retry-After": "12"}, json={"error": {
                    "code": code, "message": "SECRET KEY and private prompt",
                    "project": "PRIVATE PROJECT"}})
            adapter = self.transport_adapter(handle)
            with self.subTest(code=code), self.assertRaises(TeacherRequestError) as caught:
                adapter.generate_raw("PRIVATE QUESTION", "PRIVATE CONTEXT")
            self.assertEqual(len(requests), 1)
            self.assertEqual(caught.exception.http_status, 429)
            diagnostics = _teacher_error_diagnostics(caught.exception)
            self.assertEqual(diagnostics, {"provider_code": code, "retry_after_seconds": 12.0})
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertNotIn("PRIVATE", json.dumps(diagnostics))

    def test_quota_diagnostics_allowlist_and_structured_retry_info(self):
        error = RuntimeError("SECRET")
        error.body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3.5s"},
            {"project": "PRIVATE", "quotaMetric": "PRIVATE"}]}}
        self.assertEqual(_teacher_error_diagnostics(error), {
            "provider_code": "resource_exhausted", "retry_after_seconds": 3.5})
        error.body = {"error": {"code": "PRIVATE_SECRET", "message": "SECRET"}}
        error.response = SimpleNamespace(headers={"retry-after": "SECRET"})
        self.assertEqual(_teacher_error_diagnostics(error), {})
        error.diagnostics = {"provider_code": {"SECRET": 1}, "retry_after_seconds": float("nan"),
                             "message": "SECRET"}
        self.assertEqual(_teacher_error_diagnostics(error), {})

    def test_cli_rejects_runtime_values_before_network(self):
        from scripts.run_baselines import parse_args
        for args in (["--teacher-timeout", "nan"], ["--teacher-timeout", "0"],
                     ["--teacher-max-attempts", "0"], ["--teacher-max-attempts", "1.5"]):
            with self.subTest(args=args), patch("sys.argv", ["run_baselines.py", *args]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse_args()

    def test_cli_runtime_flags_forward_to_teacher_constructor(self):
        from scripts.run_baselines import parse_args, build_teacher_adapter
        with patch("sys.argv", ["run_baselines.py", "--models", "none", "--teacher-provider", "gemini",
                                "--teacher-model", "test-model", "--teacher-timeout", "15",
                                "--teacher-max-attempts", "2"]):
            args = parse_args()
        with patch("scripts.run_baselines.GeminiTeacherAdapter") as adapter:
            build_teacher_adapter(args.teacher_provider, args.teacher_model,
                                  timeout_seconds=args.teacher_timeout, max_attempts=args.teacher_max_attempts)
            adapter.assert_called_once_with(model="test-model", timeout_seconds=15.0, max_attempts=2)

    def test_partial_log_retains_only_completed_rows_and_records_request_limits(self):
        questions = [{"ticket_id": f"q{i}", "customer_query": "Question", "ground_truth_action": "answer",
                      "is_answerable": True, "evidence_json": "[]"} for i in range(2)]
        raw = json.dumps({"action": "answer", "answer": "Answer", "confidence": 0.9, "cited_sources": []})
        output = io.StringIO()
        def generate(*args):
            self.assertIn("REQUEST START", output.getvalue())
            if generate.calls:
                raise TeacherRequestError("TimeoutError")
            generate.calls += 1
            return raw, {"latency_ms": 1, "tokens_per_second": 1}
        generate.calls = 0
        adapter = SimpleNamespace(model="test-teacher", generate_raw=generate,
                                  request_settings={"timeout_seconds": 10.0, "max_attempts": 1})
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(output), \
                patch("src.evaluation.comparison.get_hardware_metadata", return_value={}):
            with self.assertRaisesRegex(BaselineExecutionError, "1/2 responses completed"):
                run_baseline_evaluation(adapter, None, questions, output_dir=temporary, model_role="teacher")
            files = list(Path(temporary).glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].name.startswith("baseline_incomplete"))
            data = json.loads(files[0].read_text())
            self.assertEqual(data["run_status"], "failed")
            self.assertEqual(data["requested_records"], 2)
            self.assertEqual(data["completed_records"], 1)
            self.assertEqual(len(data["records"]), 1)
            self.assertEqual(data["failure"]["ticket_id"], "q1")
            self.assertEqual(data["failure"]["error_type"], "TimeoutError")
            self.assertGreaterEqual(data["failure"]["failed_request_elapsed_ms"], 0)
            self.assertNotIn("http_status", data["failure"])
            self.assertEqual(data["teacher_request_settings"], adapter.request_settings)
            with self.assertRaisesRegex(ValueError, "Incomplete evaluation logs"):
                summarize_evaluation_log(data)

    def test_first_request_failure_saves_zero_completed_rows(self):
        question = {"ticket_id": "q0", "customer_query": "Question", "ground_truth_action": "answer",
                    "is_answerable": True, "evidence_json": "[]"}
        for failure in (TimeoutError("PRIVATE BODY"), KeyboardInterrupt()):
            adapter = SimpleNamespace(model="test-teacher", generate_raw=Mock(side_effect=failure))
            with self.subTest(error=type(failure).__name__), tempfile.TemporaryDirectory() as temporary, \
                    contextlib.redirect_stdout(io.StringIO()), \
                    patch("src.evaluation.comparison.get_hardware_metadata", return_value={}):
                with self.assertRaises(BaselineExecutionError):
                    run_baseline_evaluation(adapter, None, [question], output_dir=temporary)
                data = json.loads(next(Path(temporary).glob("*.json")).read_text())
                self.assertEqual(data["records"], [])
                self.assertEqual(data["completed_records"], 0)
                self.assertEqual(data["run_status"], "interrupted" if isinstance(failure, KeyboardInterrupt) else "failed")
                self.assertNotIn("PRIVATE BODY", json.dumps(data))

    def test_http_status_is_saved_and_printable_failure_remains_redacted(self):
        question = {"ticket_id": "q0", "customer_query": "Question", "ground_truth_action": "answer",
                    "is_answerable": True, "evidence_json": "[]"}
        failure = RuntimeError("SECRET REQUEST CONTENT")
        failure.status_code = 401
        adapter = SimpleNamespace(model="test-teacher", generate_raw=Mock(side_effect=failure))
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), \
                patch("src.evaluation.comparison.get_hardware_metadata", return_value={}):
            with self.assertRaisesRegex(BaselineExecutionError, "RuntimeError; HTTP 401") as caught:
                run_baseline_evaluation(adapter, None, [question], output_dir=temporary)
            data = json.loads(next(Path(temporary).glob("*.json")).read_text())
            self.assertEqual(data["failure"]["http_status"], 401)
            self.assertGreaterEqual(data["failure"]["failed_request_elapsed_ms"], 0)
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertNotIn("SECRET", json.dumps(data))

    def test_quota_diagnostics_are_saved_and_printed_with_zero_completed_responses(self):
        question = {"ticket_id": "q0", "customer_query": "Question", "ground_truth_action": "answer",
                    "is_answerable": True, "evidence_json": "[]"}
        failure = TeacherRequestError("RateLimitError", 429, {
            "provider_code": "quota_exceeded", "retry_after_seconds": 60, "message": "SECRET"})
        adapter = SimpleNamespace(model="test-teacher", generate_raw=Mock(side_effect=failure))
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), \
                patch("src.evaluation.comparison.get_hardware_metadata", return_value={}):
            with self.assertRaisesRegex(BaselineExecutionError, "code=quota_exceeded; retry-after=60s") as caught:
                run_baseline_evaluation(adapter, None, [question], output_dir=temporary)
            data = json.loads(next(Path(temporary).glob("*.json")).read_text())
            self.assertEqual(data["failure"]["provider_diagnostics"], {
                "provider_code": "quota_exceeded", "retry_after_seconds": 60})
            self.assertEqual(data["completed_records"], 0)
            self.assertNotIn("SECRET", json.dumps(data))
            self.assertNotIn("SECRET", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
