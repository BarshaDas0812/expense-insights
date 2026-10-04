from tests.base import APITestCase, make_expense


class CreateExpenseTests(APITestCase):
    def test_create_returns_201_with_location_and_normalised_fields(self):
        response = self.client.post("/api/expenses", json=make_expense(
            category="travel", payment_method="upi", description="  Cab   to airport  "))
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(response.headers["Location"], f"/api/expenses/{body['id']}")
        self.assertEqual(body["category"], "Travel")
        self.assertEqual(body["payment_method"], "UPI")
        self.assertEqual(body["description"], "Cab to airport")
        self.assertEqual(body["amount"], 5400.5)
        self.assertIn("created_at", body)

    def test_create_persists_to_database(self):
        created = self.create()
        response = self.client.get(f"/api/expenses/{created['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), created)

    def test_amount_is_stored_exactly(self):
        # 0.1 + 0.2 style float errors must not appear: amounts are stored as integer paise.
        a = self.create(amount=0.1)
        b = self.create(amount=0.2)
        stats = self.client.get("/api/expenses/stats").get_json()
        self.assertEqual(stats["total_amount"], 0.3)
        self.assertEqual(a["amount"] + b["amount"], 0.30000000000000004)  # why we don't use floats

    def test_amount_accepts_numeric_string(self):
        self.assertEqual(self.create(amount="99.99")["amount"], 99.99)

    def test_missing_fields_are_reported_together(self):
        response = self.client.post("/api/expenses", json={})
        self.assertValidationError(response)
        details = response.get_json()["error"]["details"]
        self.assertEqual(set(details), {"date", "category", "description", "amount", "payment_method"})

    def test_invalid_values_are_rejected(self):
        cases = {
            "amount": [0, -5, "abc", True, None, 12.345, 1e15],
            "date": ["2026-02-30", "15/10/2026", "20261015", 20261015, ""],
            "category": ["Groceries", "", 5],
            "payment_method": ["Cheque", None],
            "description": ["", "   ", "x" * 256, 42],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    response = self.client.post("/api/expenses", json=make_expense(**{field: value}))
                    self.assertValidationError(response, field)

    def test_unknown_fields_are_rejected(self):
        response = self.client.post("/api/expenses", json=make_expense(vendor="Acme"))
        self.assertValidationError(response, "vendor")

    def test_non_json_body_is_rejected(self):
        response = self.client.post("/api/expenses", data="not json",
                                    content_type="application/json")
        self.assertValidationError(response)

    def test_json_array_body_is_rejected(self):
        response = self.client.post("/api/expenses", json=[make_expense()])
        self.assertValidationError(response)


class RetrieveExpenseTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.create(date="2026-10-01", category="Food", description="Team lunch", amount=1200,
                    payment_method="UPI")
        self.create(date="2026-09-20", category="Travel", description="Flight to Pune",
                    amount=6500, payment_method="Card")
        self.create(date="2026-10-10", category="Software", description="Cloud hosting",
                    amount=3000, payment_method="Card")
        self.create(date="2026-08-02", category="Food", description="Client dinner 50% off",
                    amount=2400, payment_method="Cash")

    def list(self, query=""):
        response = self.client.get(f"/api/expenses{query}")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_list_returns_all_sorted_by_date_desc_by_default(self):
        body = self.list()
        self.assertEqual([e["date"] for e in body["items"]],
                         ["2026-10-10", "2026-10-01", "2026-09-20", "2026-08-02"])
        self.assertEqual(body["pagination"]["total_items"], 4)
        self.assertEqual(body["summary"]["total_amount"], 13100)

    def test_get_single_expense(self):
        expense_id = self.list()["items"][0]["id"]
        body = self.client.get(f"/api/expenses/{expense_id}").get_json()
        self.assertEqual(body["description"], "Cloud hosting")

    def test_get_missing_expense_returns_404(self):
        response = self.client.get("/api/expenses/9999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "not_found")

    def test_filter_by_category_and_payment_method(self):
        self.assertEqual(len(self.list("?category=food")["items"]), 2)
        body = self.list("?category=Food&payment_method=UPI")
        self.assertEqual([e["description"] for e in body["items"]], ["Team lunch"])

    def test_filter_by_date_range(self):
        body = self.list("?start_date=2026-09-01&end_date=2026-09-30")
        self.assertEqual([e["description"] for e in body["items"]], ["Flight to Pune"])

    def test_filter_by_amount_range(self):
        body = self.list("?min_amount=2000&max_amount=3000")
        self.assertEqual({e["description"] for e in body["items"]},
                         {"Cloud hosting", "Client dinner 50% off"})

    def test_text_search_is_case_insensitive_and_escapes_wildcards(self):
        self.assertEqual(len(self.list("?q=FLIGHT")["items"]), 1)
        # A literal "%" must not act as a SQL wildcard.
        self.assertEqual([e["description"] for e in self.list("?q=50%25")["items"]],
                         ["Client dinner 50% off"])

    def test_sort_by_amount_ascending(self):
        amounts = [e["amount"] for e in self.list("?sort=amount&order=asc")["items"]]
        self.assertEqual(amounts, sorted(amounts))

    def test_pagination(self):
        body = self.list("?page=2&page_size=3")
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["pagination"], {"page": 2, "page_size": 3, "total_items": 4,
                                              "total_pages": 2})

    def test_invalid_query_parameters_return_400(self):
        for query, field in [("?sort=password", "sort"), ("?order=up", "order"),
                             ("?page=0", "page"), ("?page_size=1000", "page_size"),
                             ("?category=Nope", "category"), ("?start_date=yesterday", "start_date"),
                             ("?start_date=2026-10-10&end_date=2026-10-01", "end_date")]:
            with self.subTest(query=query):
                self.assertValidationError(self.client.get(f"/api/expenses{query}"), field)


class UpdateExpenseTests(APITestCase):
    def test_put_replaces_all_fields(self):
        expense = self.create()
        response = self.client.put(f"/api/expenses/{expense['id']}", json=make_expense(
            date="2026-10-06", category="Office", description="Monitor", amount=15000,
            payment_method="Bank Transfer"))
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual((body["category"], body["amount"], body["payment_method"]),
                         ("Office", 15000, "Bank Transfer"))
        self.assertEqual(self.client.get(f"/api/expenses/{expense['id']}").get_json(), body)

    def test_put_accepts_object_previously_returned(self):
        expense = self.create()
        expense["description"] = "Edited"
        response = self.client.put(f"/api/expenses/{expense['id']}", json=expense)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["description"], "Edited")

    def test_put_requires_all_fields(self):
        expense = self.create()
        response = self.client.put(f"/api/expenses/{expense['id']}", json={"amount": 10})
        self.assertValidationError(response, "date")

    def test_patch_updates_only_given_fields(self):
        expense = self.create()
        response = self.client.patch(f"/api/expenses/{expense['id']}", json={"amount": 42})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["amount"], 42)
        self.assertEqual(body["description"], expense["description"])

    def test_patch_with_empty_body_is_rejected(self):
        expense = self.create()
        self.assertValidationError(self.client.patch(f"/api/expenses/{expense['id']}", json={}))

    def test_invalid_update_does_not_change_data(self):
        expense = self.create()
        response = self.client.patch(f"/api/expenses/{expense['id']}",
                                     json={"amount": 10, "category": "Bogus"})
        self.assertValidationError(response, "category")
        self.assertEqual(self.client.get(f"/api/expenses/{expense['id']}").get_json(), expense)

    def test_update_missing_expense_returns_404(self):
        self.assertEqual(self.client.put("/api/expenses/9999", json=make_expense()).status_code, 404)
        self.assertEqual(self.client.patch("/api/expenses/9999", json={"amount": 1}).status_code, 404)


class DeleteExpenseTests(APITestCase):
    def test_delete_removes_expense(self):
        expense = self.create()
        response = self.client.delete(f"/api/expenses/{expense['id']}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.data, b"")
        self.assertEqual(self.client.get(f"/api/expenses/{expense['id']}").status_code, 404)
        self.assertEqual(self.client.get("/api/expenses").get_json()["items"], [])

    def test_delete_missing_expense_returns_404(self):
        self.assertEqual(self.client.delete("/api/expenses/9999").status_code, 404)

    def test_delete_only_affects_target(self):
        keep = self.create(description="Keep me")
        remove = self.create(description="Remove me")
        self.client.delete(f"/api/expenses/{remove['id']}")
        items = self.client.get("/api/expenses").get_json()["items"]
        self.assertEqual([e["id"] for e in items], [keep["id"]])


class GeneralApiTests(APITestCase):
    def test_unknown_route_returns_json_404(self):
        response = self.client.get("/api/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.get_json())

    def test_wrong_method_returns_json_405(self):
        response = self.client.delete("/api/expenses")
        self.assertEqual(response.status_code, 405)
        self.assertIn("error", response.get_json())

    def test_meta_lists_categories_and_payment_methods(self):
        body = self.client.get("/api/meta").get_json()
        self.assertIn("Marketing", body["categories"])
        self.assertIn("UPI", body["payment_methods"])
