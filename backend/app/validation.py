"""Input validation and normalisation.

The same parsers are used for request bodies, query strings and AI tool arguments, so every
entry point into the data layer enforces identical rules.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from .constants import (
    CATEGORIES,
    DEFAULT_PAGE_SIZE,
    MAX_AMOUNT_PAISE,
    MAX_DESCRIPTION_LENGTH,
    MAX_PAGE_SIZE,
    PAYMENT_METHODS,
)
from .errors import ValidationError

EXPENSE_FIELDS = ("date", "category", "description", "amount", "payment_method")
READ_ONLY_FIELDS = ("id", "created_at", "updated_at")

SORT_FIELDS = ("date", "amount", "category", "created_at", "id")
SORT_ORDERS = ("asc", "desc")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CATEGORY_LOOKUP = {c.lower(): c for c in CATEGORIES}
_PAYMENT_LOOKUP = {p.lower(): p for p in PAYMENT_METHODS}


# --- Field parsers: raise ValueError with a human-readable message -------------------------

def parse_date(value) -> date:
    # date.fromisoformat() alone is too permissive on Python 3.11+ (it accepts "20260101"),
    # so the exact YYYY-MM-DD shape is enforced first.
    if not isinstance(value, str) or not _ISO_DATE.match(value.strip()):
        raise ValueError("must be a date in YYYY-MM-DD format")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError("is not a valid calendar date") from None


def parse_amount_to_paise(value) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError("must be a number")
    try:
        if isinstance(value, (int, float)):
            amount = Decimal(str(value))
        elif isinstance(value, str) and value.strip():
            amount = Decimal(value.strip())
        else:
            raise ValueError("must be a number")
    except InvalidOperation:
        raise ValueError("must be a number") from None

    if not amount.is_finite():
        raise ValueError("must be a finite number")
    if amount <= 0:
        raise ValueError("must be greater than 0")
    if amount * 100 > MAX_AMOUNT_PAISE:
        raise ValueError("is too large")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("must have at most 2 decimal places")
    return int(amount * 100)


def parse_choice(value, lookup: dict, allowed) -> str:
    if not isinstance(value, str) or value.strip().lower() not in lookup:
        raise ValueError(f"must be one of: {', '.join(allowed)}")
    return lookup[value.strip().lower()]


def parse_category(value) -> str:
    return parse_choice(value, _CATEGORY_LOOKUP, CATEGORIES)


def parse_payment_method(value) -> str:
    return parse_choice(value, _PAYMENT_LOOKUP, PAYMENT_METHODS)


def parse_description(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a non-empty string")
    cleaned = " ".join(value.split())
    if len(cleaned) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(f"must be at most {MAX_DESCRIPTION_LENGTH} characters")
    return cleaned


def parse_int(value, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError("must be an integer")
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("must be an integer") from None
    if not minimum <= number <= maximum:
        raise ValueError(f"must be between {minimum} and {maximum}")
    return number


# --- Expense bodies -----------------------------------------------------------------------

_FIELD_PARSERS = {
    "date": ("date", lambda v: parse_date(v).isoformat()),
    "category": ("category", parse_category),
    "description": ("description", parse_description),
    "amount": ("amount_paise", parse_amount_to_paise),
    "payment_method": ("payment_method", parse_payment_method),
}


def validate_expense_payload(data, partial: bool = False) -> dict:
    """Validate a create/update body and return normalised column values.

    partial=False (POST, PUT): every field is required.
    partial=True (PATCH): only supplied fields are validated; at least one is required.
    Read-only fields (id, created_at, updated_at) are ignored so clients can send back an
    object they previously received. Any other unknown field is rejected.
    """
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")

    errors = {}
    unknown = sorted(set(data) - set(EXPENSE_FIELDS) - set(READ_ONLY_FIELDS))
    for field in unknown:
        errors[field] = "is not a recognised field"

    cleaned = {}
    for field, (column, parser) in _FIELD_PARSERS.items():
        if field not in data:
            if not partial:
                errors[field] = "is required"
            continue
        try:
            cleaned[column] = parser(data[field])
        except ValueError as exc:
            errors[field] = str(exc)

    if partial and not errors and not cleaned:
        raise ValidationError(
            f"Provide at least one field to update: {', '.join(EXPENSE_FIELDS)}."
        )
    if errors:
        raise ValidationError("Expense data is invalid.", details=errors)
    return cleaned


# --- Filters (query strings and AI tool arguments) ---------------------------------------

def build_filters(source) -> dict:
    """Parse optional filter values from a mapping (request.args or tool input).

    Returns repository filter keys: category, payment_method, start_date, end_date,
    min_paise, max_paise, q. Empty strings are treated as "not provided".
    """
    errors = {}
    filters = {}

    def present(key):
        value = source.get(key)
        return value is not None and not (isinstance(value, str) and value.strip() == "")

    simple = {
        "category": ("category", parse_category),
        "payment_method": ("payment_method", parse_payment_method),
        "start_date": ("start_date", lambda v: parse_date(v).isoformat()),
        "end_date": ("end_date", lambda v: parse_date(v).isoformat()),
        "min_amount": ("min_paise", parse_amount_to_paise),
        "max_amount": ("max_paise", parse_amount_to_paise),
    }
    for key, (target, parser) in simple.items():
        if present(key):
            try:
                filters[target] = parser(source.get(key))
            except ValueError as exc:
                errors[key] = str(exc)

    if present("q"):
        query = source.get("q")
        if not isinstance(query, str) or len(query) > 100:
            errors["q"] = "must be a string of at most 100 characters"
        else:
            filters["q"] = query.strip()

    if "start_date" in filters and "end_date" in filters and filters["start_date"] > filters["end_date"]:
        errors["end_date"] = "must be on or after start_date"
    if "min_paise" in filters and "max_paise" in filters and filters["min_paise"] > filters["max_paise"]:
        errors["max_amount"] = "must be greater than or equal to min_amount"

    if errors:
        raise ValidationError("Invalid filter parameters.", details=errors)
    return filters


def parse_list_query(args) -> dict:
    """Parse filters, sorting and pagination for GET /api/expenses."""
    filters = build_filters(args)
    errors = {}

    sort = (args.get("sort") or "date").strip().lower()
    if sort not in SORT_FIELDS:
        errors["sort"] = f"must be one of: {', '.join(SORT_FIELDS)}"
    order = (args.get("order") or "desc").strip().lower()
    if order not in SORT_ORDERS:
        errors["order"] = "must be 'asc' or 'desc'"

    page, page_size = 1, DEFAULT_PAGE_SIZE
    try:
        if args.get("page"):
            page = parse_int(args.get("page"), 1, 1_000_000)
    except ValueError as exc:
        errors["page"] = str(exc)
    try:
        if args.get("page_size"):
            page_size = parse_int(args.get("page_size"), 1, MAX_PAGE_SIZE)
    except ValueError as exc:
        errors["page_size"] = str(exc)

    if errors:
        raise ValidationError("Invalid query parameters.", details=errors)
    return {"filters": filters, "sort": sort, "order": order, "page": page, "page_size": page_size}
