"""Retrieval tools for the AI assistant.

These are the ONLY way the assistant reads expense data. Each tool runs a targeted,
parameterised query (aggregates or a capped number of rows) so the model never receives
the whole database. Both the LLM agent and the offline rule-based assistant use them.
"""
from .. import repository
from ..constants import CATEGORIES, PAYMENT_METHODS
from ..errors import ValidationError
from ..money import format_inr, paise_to_amount
from ..services.stats import percentage
from ..validation import build_filters, parse_int

MAX_TOP_EXPENSES = 20
MAX_SEARCH_RESULTS = 25

_DATE_PROPS = {
    "start_date": {"type": "string", "description": "Inclusive start date, YYYY-MM-DD."},
    "end_date": {"type": "string", "description": "Inclusive end date, YYYY-MM-DD."},
}
_CATEGORY_PROP = {"category": {"type": "string", "enum": list(CATEGORIES)}}
_PAYMENT_PROP = {"payment_method": {"type": "string", "enum": list(PAYMENT_METHODS)}}

TOOL_DEFINITIONS = [
    {
        "name": "get_total_spending",
        "description": (
            "Total amount spent and number of expenses, optionally filtered by date range, "
            "category and payment method. Use for 'how much did I spend...' and "
            "'how many expenses...' questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {**_DATE_PROPS, **_CATEGORY_PROP, **_PAYMENT_PROP},
        },
    },
    {
        "name": "get_category_breakdown",
        "description": (
            "Spending per category with totals, counts and percentage of the overall total, "
            "sorted highest first. Use for highest-category, percentage/share and breakdown "
            "questions."
        ),
        "input_schema": {"type": "object", "properties": {**_DATE_PROPS}},
    },
    {
        "name": "get_top_expenses",
        "description": "The largest individual expenses, sorted by amount descending.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_TOP_EXPENSES},
                **_DATE_PROPS,
                **_CATEGORY_PROP,
            },
        },
    },
    {
        "name": "search_expenses",
        "description": (
            "Find individual expenses matching filters, e.g. a keyword in the description. "
            f"Returns at most {MAX_SEARCH_RESULTS} rows plus the total number of matches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword to match in descriptions."},
                **_DATE_PROPS,
                **_CATEGORY_PROP,
                **_PAYMENT_PROP,
                "min_amount": {"type": "number"},
                "max_amount": {"type": "number"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_RESULTS},
            },
        },
    },
]


class ToolError(Exception):
    """Raised for unknown tools or invalid tool arguments."""


def _filters(args: dict, allowed: tuple) -> dict:
    unknown = set(args) - set(allowed)
    if unknown:
        raise ToolError(f"Unknown argument(s): {', '.join(sorted(unknown))}")
    source = dict(args)
    if "query" in source:
        source["q"] = source.pop("query")
    try:
        return build_filters(source)
    except ValidationError as exc:
        raise ToolError(f"{exc.message} {exc.details}") from None


def _limit(args: dict, default: int, maximum: int) -> int:
    if args.get("limit") is None:
        return default
    try:
        return parse_int(args["limit"], 1, maximum)
    except ValueError as exc:
        raise ToolError(f"limit {exc}") from None


def _compact(expense: dict) -> dict:
    """Only the fields the model needs; timestamps would just waste tokens."""
    return {
        "id": expense["id"],
        "date": expense["date"],
        "category": expense["category"],
        "description": expense["description"],
        "amount": expense["amount"],
        "amount_formatted": format_inr(round(expense["amount"] * 100)),
        "payment_method": expense["payment_method"],
    }


def _applied(filters: dict) -> dict:
    return {k: v for k, v in filters.items() if k in ("start_date", "end_date", "category",
                                                      "payment_method", "q")}


def get_total_spending(conn, args):
    filters = _filters(args, ("start_date", "end_date", "category", "payment_method"))
    count, total = repository.summarize(conn, filters)
    return {
        "filters": _applied(filters),
        "total_amount": paise_to_amount(total),
        "total_formatted": format_inr(total),
        "expense_count": count,
    }


def get_category_breakdown(conn, args):
    filters = _filters(args, ("start_date", "end_date"))
    rows = repository.category_totals(conn, filters)
    grand_total = sum(r["total_paise"] for r in rows)
    return {
        "filters": _applied(filters),
        "grand_total": paise_to_amount(grand_total),
        "grand_total_formatted": format_inr(grand_total),
        "categories": [
            {
                "category": r["category"],
                "total_amount": paise_to_amount(r["total_paise"]),
                "total_formatted": format_inr(r["total_paise"]),
                "expense_count": r["count"],
                "percentage": percentage(r["total_paise"], grand_total),
            }
            for r in rows
        ],
    }


def get_top_expenses(conn, args):
    limit = _limit(args, default=5, maximum=MAX_TOP_EXPENSES)
    filters = _filters({k: v for k, v in args.items() if k != "limit"},
                       ("start_date", "end_date", "category"))
    rows = repository.top_expenses(conn, filters, limit)
    return {"filters": _applied(filters), "expenses": [_compact(r) for r in rows]}


def search_expenses(conn, args):
    limit = _limit(args, default=10, maximum=MAX_SEARCH_RESULTS)
    filters = _filters(
        {k: v for k, v in args.items() if k != "limit"},
        ("query", "start_date", "end_date", "category", "payment_method",
         "min_amount", "max_amount"),
    )
    rows, total_count, total_paise = repository.list_expenses(conn, filters, "date", "desc",
                                                              limit, 0)
    return {
        "filters": _applied(filters),
        "total_matching": total_count,
        "total_matching_amount_formatted": format_inr(total_paise),
        "returned": len(rows),
        "expenses": [_compact(r) for r in rows],
    }


_REGISTRY = {
    "get_total_spending": get_total_spending,
    "get_category_breakdown": get_category_breakdown,
    "get_top_expenses": get_top_expenses,
    "search_expenses": search_expenses,
}


def execute_tool(conn, name: str, args: dict | None) -> dict:
    handler = _REGISTRY.get(name)
    if handler is None:
        raise ToolError(f"Unknown tool: {name}")
    if args is not None and not isinstance(args, dict):
        raise ToolError("Tool input must be an object")
    return handler(conn, args or {})
