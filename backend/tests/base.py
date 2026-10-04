"""Shared test setup: an isolated SQLite file per test and a fixed 'today'."""
import os
import tempfile
import unittest
from datetime import date

from app import create_app

FIXED_TODAY = date(2026, 10, 15)


def make_expense(**overrides) -> dict:
    payload = {
        "date": "2026-10-05",
        "category": "Travel",
        "description": "Flight to Delhi",
        "amount": 5400.50,
        "payment_method": "Card",
    }
    payload.update(overrides)
    return payload


class APITestCase(unittest.TestCase):
    extra_config: dict = {}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        config = {
            "TESTING": True,
            "DATABASE_PATH": os.path.join(self._tmp.name, "test.db"),
            "AI_PROVIDER": "rules",
            "ANTHROPIC_API_KEY": "",
            "CLOCK": lambda: FIXED_TODAY,
        }
        config.update(self.extra_config)
        self.app = create_app(config)
        self.client = self.app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    def create(self, **overrides) -> dict:
        response = self.client.post("/api/expenses", json=make_expense(**overrides))
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def assertValidationError(self, response, field=None):
        self.assertEqual(response.status_code, 400, response.get_json())
        body = response.get_json()
        self.assertEqual(body["error"]["code"], "validation_error")
        if field:
            self.assertIn(field, body["error"].get("details", {}))
