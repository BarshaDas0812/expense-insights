import json
import unittest

from app.assistant.llm_client import LLMError
from app.assistant.rule_based import detect_intent, extract_period, extract_top_n
from app.assistant.tools import ToolError, execute_tool
from app.db import connect
from tests.base import FIXED_TODAY, APITestCase


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

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, url, headers, payload, timeout):
        self.requests.append(json.loads(json.dumps(payload)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


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

    def test_falls_back_to_rules_when_api_fails(self):
        self.use_transport(FakeTransport([LLMError("HTTP 529: overloaded")]))
        body = self.ask("How much did I spend on software?")
        self.assertEqual(body["provider"], "rules")
        self.assertIn("overloaded", body["fallback_reason"])
        self.assertIn("₹3,500.00", body["answer"])

    def test_runaway_tool_loop_is_stopped(self):
        self.use_transport(FakeTransport([tool_use(f"t{i}", "get_category_breakdown", {})
                                          for i in range(10)]))
        body = self.ask("What is my highest spending category?")
        self.assertEqual(body["provider"], "rules")
        self.assertIn("did not finish", body["fallback_reason"])

    def test_missing_api_key_falls_back(self):
        self.app.config["ANTHROPIC_API_KEY"] = ""
        body = self.ask("How much did I spend on software?")
        self.assertEqual(body["provider"], "rules")
