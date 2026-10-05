import http.client
import io
import json
import sqlite3
import unittest
import urllib.error
from unittest import mock

from app import repository
from app.assistant.llm_client import LLMError
from app.assistant.rule_based import detect_intent, extract_period, extract_top_n
from app.assistant.tools import ToolError, execute_tool
from app.db import connect
from tests.base import FIXED_TODAY, APITestCase

# What the client sees for any Claude API failure; the details go only to the server log.
LLM_FAILURE_REASON = "the Claude API request failed"


class SeededAssistantCase(APITestCase):
    """Fixed data set; today is 2026-10-15."""

    def setUp(self):
        super().setUp()
        self.create(date="2026-10-03", category="Travel", amount=4000, description="Flight to Goa")
        self.create(date="2026-10-09", category="Travel", amount=1500, description="Hotel")
        self.create(date="2026-09-12", category="Travel", amount=9000, description="Old trip")
        self.create(date="2026-10-05", category="Software", amount=2500, description="Hosting")
        self.create(date="2026-08-20", category="Software", amount=1000, description="Domain")
        self.create(date="2026-10-11", category="Marketing", amount=2000, description="Ads",
                    payment_method="UPI")

    def ask(self, question):
        response = self.client.post("/api/assistant/query", json={"question": question})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()


class RuleBasedAssistantTests(SeededAssistantCase):
    def test_travel_this_month(self):
        body = self.ask("How much did I spend on travel this month?")
        self.assertIn("₹5,500.00", body["answer"])  # September trip excluded
        self.assertEqual(body["provider"], "rules")
        self.assertEqual(body["tool_calls"][0]["input"],
                         {"start_date": "2026-10-01", "end_date": "2026-10-31", "category": "Travel"})

    def test_highest_category(self):
        body = self.ask("What is my highest spending category?")
        self.assertIn("Travel", body["answer"])
        self.assertIn("₹14,500.00", body["answer"])

    def test_three_largest(self):
        answer = self.ask("Show me the three largest expenses.")["answer"]
        lines = answer.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("Old trip", lines[1])
        self.assertIn("Flight to Goa", lines[2])
        self.assertIn("Hosting", lines[3])

    def test_software_all_time(self):
        self.assertIn("₹3,500.00", self.ask("How much did I spend on software?")["answer"])

    def test_marketing_percentage(self):
        # 2000 / 20000 = 10%
        self.assertIn("10.0%", self.ask("What percentage of my total spending went to marketing?")["answer"])

    def test_count_with_payment_method(self):
        self.assertIn("1 UPI expense", self.ask("How many UPI expenses did I have this month?")["answer"])

    def test_list_expenses(self):
        answer = self.ask("Show me travel expenses in September")["answer"]
        self.assertIn("Old trip", answer)
        self.assertNotIn("Flight to Goa", answer)

    def test_no_matching_data(self):
        self.assertIn("no Food expenses", self.ask("How much did I spend on food last month?")["answer"])

    def test_no_matching_data_without_category(self):
        answer = self.ask("How much did I spend yesterday?")["answer"]
        self.assertEqual(answer, "You have no expenses recorded yesterday.")

    def test_count_without_category(self):
        answer = self.ask("How many expenses did I have this month?")["answer"]
        self.assertEqual(answer, "You recorded 4 expenses this month, totalling ₹10,000.00.")

    def test_invalid_periods_get_an_answer_not_a_server_error(self):
        for question in ["How much did I spend in the last 0 days?",
                         "What did I spend in january 0000?"]:
            with self.subTest(question=question):
                body = self.ask(question)
                self.assertIn("time period", body["answer"])

    def test_unrelated_question_gets_help_text_and_no_data_access(self):
        body = self.ask("What's the weather like?")
        self.assertIn("I can answer questions", body["answer"])
        self.assertEqual(body["tool_calls"], [])

    def test_question_validation(self):
        for payload in [{}, {"question": ""}, {"question": "   "}, {"question": 5},
                        {"question": "x" * 501}]:
            with self.subTest(payload=payload):
                response = self.client.post("/api/assistant/query", json=payload)
                self.assertValidationError(response)


class RuleParsingTests(unittest.TestCase):
    def test_periods(self):
        cases = {
            "this month": ("2026-10-01", "2026-10-31"),
            "last month": ("2026-09-01", "2026-09-30"),
            "this year": ("2026-01-01", "2026-12-31"),
            "in the last 7 days": ("2026-10-09", "2026-10-15"),
            "in march": ("2026-03-01", "2026-03-31"),
            "in november": ("2025-11-01", "2025-11-30"),  # future month -> last year
            "in may 2024": ("2024-05-01", "2024-05-31"),
        }
        for phrase, (start, end) in cases.items():
            with self.subTest(phrase=phrase):
                s, e, _ = extract_period(f"how much did i spend {phrase}", FIXED_TODAY)
                self.assertEqual((s.isoformat(), e.isoformat()), (start, end))

    def test_may_as_a_verb_is_not_a_month(self):
        self.assertEqual(extract_period("may i see my total", FIXED_TODAY)[0], None)

    def test_top_n(self):
        self.assertEqual(extract_top_n("show me the three largest expenses"), 3)
        self.assertEqual(extract_top_n("top 5 expenses"), 5)
        self.assertEqual(extract_top_n("the 2 most expensive purchases"), 2)
        self.assertIsNone(extract_top_n("what is my top category"))

    def test_intents(self):
        self.assertEqual(detect_intent("which category did i spend the most on"), "highest_category")
        self.assertEqual(detect_intent("what share went to food"), "percentage")
        self.assertEqual(detect_intent("what was my biggest expense"), "top_expenses")
        self.assertEqual(detect_intent("how much did i spend"), "total")


class ToolTests(SeededAssistantCase):
    def run_tool(self, name, args):
        conn = connect(self.app.config["DATABASE_PATH"])
        try:
            return execute_tool(conn, name, args)
        finally:
            conn.close()

    def test_search_results_are_capped(self):
        for i in range(30):
            self.create(description=f"Bulk {i}", amount=10)
        result = self.run_tool("search_expenses", {"query": "bulk", "limit": 25})
        self.assertEqual(result["returned"], 25)
        self.assertEqual(result["total_matching"], 30)

    def test_invalid_arguments_raise_tool_error(self):
        with self.assertRaises(ToolError):
            self.run_tool("search_expenses", {"limit": 500})
        with self.assertRaises(ToolError):
            self.run_tool("get_total_spending", {"category": "Bogus"})
        with self.assertRaises(ToolError):
            self.run_tool("get_total_spending", {"sql": "DROP TABLE expenses"})
        with self.assertRaises(ToolError):
            self.run_tool("delete_everything", {})


class FakeTransport:
    """Replays scripted Anthropic API responses and records every request."""

    def __init__(self, responses, clock=None, seconds_per_call=0):
        self.responses = list(responses)
        self.requests = []
        self.timeouts = []
        self.clock = clock
        self.seconds_per_call = seconds_per_call

    def __call__(self, url, headers, payload, timeout):
        self.requests.append(json.loads(json.dumps(payload)))
        self.timeouts.append(timeout)
        if self.clock:
            self.clock.now += self.seconds_per_call
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClock:
    """Stands in for time.monotonic; FakeTransport moves it forward on each API call."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def tool_use(tool_id, name, args):
    return {"stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": args}]}


def final(text):
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}


class LLMAgentTests(SeededAssistantCase):
    extra_config = {"AI_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key",
                    "ANTHROPIC_MODEL": "test-model"}

    def use_transport(self, transport):
        self.app.config["ANTHROPIC_TRANSPORT"] = transport
        return transport

    def test_tool_loop_retrieves_data_then_answers(self):
        transport = self.use_transport(FakeTransport([
            tool_use("t1", "get_total_spending",
                     {"category": "Travel", "start_date": "2026-10-01", "end_date": "2026-10-31"}),
            final("You spent ₹5,500.00 on travel this month."),
        ]))
        body = self.ask("How much did I spend on travel this month?")
        self.assertEqual(body["provider"], "anthropic")
        self.assertEqual(body["answer"], "You spent ₹5,500.00 on travel this month.")
        self.assertEqual(body["tool_calls"][0]["tool"], "get_total_spending")

        first, second = transport.requests
        # The model receives date context and tool definitions, not the expense table.
        self.assertIn("2026-10-15", first["system"])
        self.assertIn("2026-10-01 to 2026-10-31", first["system"])
        self.assertEqual({t["name"] for t in first["tools"]},
                         {"get_total_spending", "get_category_breakdown",
                          "get_top_expenses", "search_expenses"})
        self.assertNotIn("Old trip", json.dumps(first))
        # The tool result sent back contains only the aggregate that was asked for.
        tool_result = second["messages"][-1]["content"][0]
        self.assertEqual(tool_result["tool_use_id"], "t1")
        self.assertEqual(json.loads(tool_result["content"])["total_formatted"], "₹5,500.00")

    def test_tool_errors_are_returned_to_the_model(self):
        transport = self.use_transport(FakeTransport([
            tool_use("t1", "get_total_spending", {"category": "Groceries"}),
            tool_use("t2", "get_total_spending", {"category": "Food"}),
            final("You have no food expenses."),
        ]))
        body = self.ask("How much on groceries?")
        self.assertEqual([c["ok"] for c in body["tool_calls"]], [False, True])
        error_result = transport.requests[1]["messages"][-1]["content"][0]
        self.assertTrue(error_result["is_error"])

    def ask_and_capture_log(self, question):
        with self.assertLogs("app.assistant.service", "WARNING") as logs:
            body = self.ask(question)
        return body, "\n".join(logs.output)

    def test_falls_back_to_rules_when_api_fails(self):
        self.use_transport(FakeTransport([LLMError("HTTP 529: overloaded")]))
        body, log = self.ask_and_capture_log("How much did I spend on software?")
        self.assertEqual(body["provider"], "rules")
        self.assertEqual(body["fallback_reason"], LLM_FAILURE_REASON)
        self.assertIn("overloaded", log)
        self.assertIn("₹3,500.00", body["answer"])

    def test_http_error_body_is_not_sent_to_client(self):
        error = urllib.error.HTTPError(
            "https://api.anthropic.com/v1/messages", 400, "Bad Request", {},
            io.BytesIO(b'{"error": "secret-detail"}'))
        with mock.patch("urllib.request.urlopen", side_effect=error):
            body, log = self.ask_and_capture_log("How much did I spend on software?")
        self.assertEqual(body["provider"], "rules")
        self.assertEqual(body["fallback_reason"], LLM_FAILURE_REASON)
        self.assertNotIn("secret-detail", json.dumps(body))
        self.assertIn("secret-detail", log)

    def test_runaway_tool_loop_is_stopped(self):
        self.use_transport(FakeTransport([tool_use(f"t{i}", "get_category_breakdown", {})
                                          for i in range(10)]))
        body, log = self.ask_and_capture_log("What is my highest spending category?")
        self.assertEqual(body["provider"], "rules")
        self.assertEqual(body["fallback_reason"], LLM_FAILURE_REASON)
        self.assertIn("did not finish", log)

    def test_question_time_limit_falls_back_to_rules(self):
        clock = FakeClock()
        transport = self.use_transport(FakeTransport(
            [tool_use(f"t{i}", "get_category_breakdown", {}) for i in range(10)],
            clock=clock, seconds_per_call=20))
        with mock.patch("app.assistant.llm_agent.time.monotonic", clock):
            body, log = self.ask_and_capture_log("What is my highest spending category?")
        self.assertEqual(body["provider"], "rules")
        self.assertEqual(body["fallback_reason"], LLM_FAILURE_REASON)
        self.assertIn("time limit", log)
        # Calls start at t=0, 20 and 40 seconds; at t=60 the 45-second limit has passed.
        self.assertEqual(len(transport.requests), 3)

    def test_per_call_timeout_is_capped_by_remaining_time(self):
        clock = FakeClock()
        transport = self.use_transport(FakeTransport(
            [tool_use(f"t{i}", "get_category_breakdown", {}) for i in range(10)],
            clock=clock, seconds_per_call=20))
        with mock.patch("app.assistant.llm_agent.time.monotonic", clock):
            self.ask_and_capture_log("What is my highest spending category?")
        self.assertEqual(transport.timeouts, [30, 25, 5])

    def test_missing_api_key_falls_back(self):
        self.app.config["ANTHROPIC_API_KEY"] = ""
        body = self.ask("How much did I spend on software?")
        self.assertEqual(body["provider"], "rules")

    def assertFellBack(self, body):
        self.assertEqual(body["provider"], "rules")
        self.assertIn("₹3,500.00", body["answer"])
        self.assertTrue(body["fallback_reason"])

    def test_connection_errors_while_reading_fall_back(self):
        # The default urllib transport is used; only the socket layer is faked.
        for error in [ConnectionResetError("connection reset by peer"),
                      http.client.RemoteDisconnected("remote end closed connection")]:
            with self.subTest(error=type(error).__name__):
                with mock.patch("urllib.request.urlopen") as urlopen:
                    urlopen.return_value.__enter__.return_value.read.side_effect = error
                    self.assertFellBack(self.ask("How much did I spend on software?"))

    def test_undecodable_response_falls_back(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"\xff\xfe"
            self.assertFellBack(self.ask("How much did I spend on software?"))

    def test_malformed_responses_fall_back(self):
        malformed = [
            {"stop_reason": "end_turn", "content": ["not a block"]},
            {"stop_reason": "end_turn", "content": "not a list"},
            {"stop_reason": "tool_use",
             "content": [{"type": "tool_use", "name": "get_total_spending", "input": {}}]},
        ]
        for response in malformed:
            with self.subTest(response=response):
                self.use_transport(FakeTransport([response]))
                self.assertFellBack(self.ask("How much did I spend on software?"))

    def test_unexpected_tool_failure_falls_back_without_leaking_details(self):
        original = repository.summarize
        calls = []

        def locked_once(conn, filters):
            calls.append(filters)
            if len(calls) == 1:
                raise sqlite3.OperationalError("database is locked")
            return original(conn, filters)

        self.use_transport(FakeTransport([tool_use("t1", "get_total_spending", {})]))
        with mock.patch.object(repository, "summarize", side_effect=locked_once):
            body = self.ask("How much did I spend on software?")
        self.assertFellBack(body)
        self.assertNotIn("locked", body["fallback_reason"])

    def test_fallback_handles_questions_the_rules_cannot_date(self):
        self.use_transport(FakeTransport([LLMError("HTTP 529: overloaded")]))
        body = self.ask("How much did I spend in the last 0 days?")
        self.assertEqual(body["provider"], "rules")
        self.assertIn("time period", body["answer"])

    def test_truncated_answer_is_not_shown_as_complete(self):
        self.use_transport(FakeTransport([
            {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "You spent ₹3,"}]},
        ]))
        body, log = self.ask_and_capture_log("How much did I spend on software?")
        self.assertFellBack(body)
        self.assertNotEqual(body["answer"], "You spent ₹3,")
        self.assertEqual(body["fallback_reason"], LLM_FAILURE_REASON)
        self.assertIn("cut off", log)
