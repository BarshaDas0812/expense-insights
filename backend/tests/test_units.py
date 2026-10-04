import unittest

from app.errors import ValidationError
from app.money import format_inr
from app.validation import parse_amount_to_paise, validate_expense_payload


class MoneyTests(unittest.TestCase):
    def test_format_inr_uses_indian_grouping(self):
        self.assertEqual(format_inr(0), "₹0.00")
        self.assertEqual(format_inr(99905), "₹999.05")
        self.assertEqual(format_inr(100000), "₹1,000.00")
        self.assertEqual(format_inr(12345678), "₹1,23,456.78")
        self.assertEqual(format_inr(1234567890), "₹1,23,45,678.90")

    def test_amount_parsing(self):
        self.assertEqual(parse_amount_to_paise(10), 1000)
        self.assertEqual(parse_amount_to_paise(10.5), 1050)
        self.assertEqual(parse_amount_to_paise("0.01"), 1)
        self.assertEqual(parse_amount_to_paise(19.99), 1999)


class PayloadValidationTests(unittest.TestCase):
    def test_partial_validation_only_checks_supplied_fields(self):
        self.assertEqual(validate_expense_payload({"amount": 5}, partial=True), {"amount_paise": 500})

    def test_read_only_fields_are_ignored(self):
        cleaned = validate_expense_payload({"id": 3, "created_at": "x", "amount": 1}, partial=True)
        self.assertEqual(cleaned, {"amount_paise": 100})

    def test_error_details_are_per_field(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_expense_payload({"amount": -1, "date": "nope"}, partial=True)
        self.assertEqual(set(ctx.exception.details), {"amount", "date"})
