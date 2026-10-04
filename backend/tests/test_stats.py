from tests.base import APITestCase


class StatsTests(APITestCase):
    def test_empty_database(self):
        body = self.client.get("/api/expenses/stats").get_json()
        self.assertEqual(body["total_amount"], 0)
        self.assertEqual(body["expense_count"], 0)
        self.assertEqual(body["current_month"], {"month": "2026-10", "total_amount": 0,
                                                 "expense_count": 0})
        self.assertIsNone(body["highest_category"])
        self.assertIsNone(body["highest_expense"])
        self.assertEqual(body["by_category"], [])

    def test_statistics_with_data(self):
        # Fixed "today" is 2026-10-15 (see tests/base.py).
        self.create(date="2026-10-01", category="Travel", amount=5000, description="Flight")
        self.create(date="2026-10-14", category="Food", amount=1000, description="Lunch")
        self.create(date="2026-09-30", category="Travel", amount=2000, description="Cab")
        self.create(date="2026-10-31", category="Marketing", amount=2000, description="Ads")
        self.create(date="2026-11-01", category="Software", amount=500, description="Next month")

        body = self.client.get("/api/expenses/stats").get_json()
        self.assertEqual(body["total_amount"], 10500)
        self.assertEqual(body["expense_count"], 5)
        # Month boundaries are inclusive on both ends and exclude neighbouring months.
        self.assertEqual(body["current_month"]["total_amount"], 8000)
        self.assertEqual(body["current_month"]["expense_count"], 3)
        self.assertEqual(body["highest_category"]["category"], "Travel")
        self.assertEqual(body["highest_category"]["total_amount"], 7000)
        self.assertEqual(body["highest_expense"]["description"], "Flight")
        self.assertEqual([c["category"] for c in body["by_category"]],
                         ["Travel", "Marketing", "Food", "Software"])
        self.assertEqual(body["by_category"][0]["percentage"], 66.67)
        self.assertEqual(body["by_category"][0]["expense_count"], 2)
        self.assertAlmostEqual(sum(c["percentage"] for c in body["by_category"]), 100, delta=0.05)

    def test_ties_are_broken_deterministically(self):
        self.create(category="Software", amount=100)
        self.create(category="Food", amount=100)
        body = self.client.get("/api/expenses/stats").get_json()
        self.assertEqual(body["highest_category"]["category"], "Food")  # alphabetical on tie

    def test_date_range_scopes_totals_but_not_current_month(self):
        self.create(date="2026-10-02", category="Food", amount=300)
        self.create(date="2026-08-02", category="Travel", amount=900)
        body = self.client.get("/api/expenses/stats?start_date=2026-08-01&end_date=2026-08-31").get_json()
        self.assertEqual(body["total_amount"], 900)
        self.assertEqual(body["highest_category"]["category"], "Travel")
        self.assertEqual(body["current_month"]["total_amount"], 300)

    def test_stats_reflect_updates_and_deletes(self):
        expense = self.create(amount=100)
        self.client.patch(f"/api/expenses/{expense['id']}", json={"amount": 250})
        self.assertEqual(self.client.get("/api/expenses/stats").get_json()["total_amount"], 250)
        self.client.delete(f"/api/expenses/{expense['id']}")
        self.assertEqual(self.client.get("/api/expenses/stats").get_json()["expense_count"], 0)

    def test_invalid_stats_parameters(self):
        self.assertValidationError(self.client.get("/api/expenses/stats?start_date=bad"), "start_date")
        self.assertValidationError(self.client.get("/api/expenses/stats?category=Food"), "category")
