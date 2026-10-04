"""Deterministic, offline assistant.

Parses the question with simple rules (intent + category + time period), then answers using
the SAME retrieval tools as the LLM agent. Used when no API key is configured and as a
fallback when the LLM call fails. It handles the common question shapes, not free-form chat.
"""
import calendar
import re
from datetime import date, timedelta

from ..services.stats import month_bounds
from .tools import ToolError, execute_tool

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_NUM = r"(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")"
_SUPERLATIVE = r"(largest|biggest|highest|most expensive|costliest|top)"
MONTH_NAMES = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}

_CATEGORY_PATTERNS = {
    "Food": r"\bfoods?\b",
    "Travel": r"\btravel(?:l?ing|s)?\b",
    "Office": r"\boffice\b",
    "Software": r"\bsoftware\b",
    "Utilities": r"\butilit(?:y|ies)\b",
    "Marketing": r"\bmarketing\b",
    # "other" is a common English word, so only match it in an explicit category phrase.
    "Other": r"\b(?:on|for|in) other\b(?!\s+(?:categor|thing))|\bother category\b|\"other\"",
}
_PAYMENT_PATTERNS = {
    "Cash": r"\bcash\b",
    "Card": r"\b(?:credit |debit )?card\b",
    "UPI": r"\bupi\b",
    "Bank Transfer": r"\bbank transfers?\b",
}

HELP_TEXT = (
    "I can answer questions about your recorded expenses, for example:\n"
    "- How much did I spend on travel this month?\n"
    "- What is my highest spending category?\n"
    "- Show me the three largest expenses.\n"
    "- What percentage of my total spending went to marketing?\n"
    "- How many UPI expenses did I have last month?"
)
PERIOD_HELP_TEXT = (
    "I couldn't work out a valid time period from that question. "
    "Try something like \"in the last 7 days\" or \"in March 2026\"."
)


class PeriodError(ValueError):
    """The question names a time period that is not a valid date range."""


def _to_int(token: str) -> int:
    return int(token) if token.isdigit() else NUMBER_WORDS[token]


def extract_period(text: str, today: date):
    """Return (start, end, label). (None, None, 'overall') when no period is mentioned."""
    if re.search(r"\btoday\b", text):
        return today, today, "today"
    if re.search(r"\byesterday\b", text):
        day = today - timedelta(days=1)
        return day, day, "yesterday"
    if re.search(r"\bthis week\b", text):
        return today - timedelta(days=today.weekday()), today, "this week"
    if re.search(r"\blast week\b", text):
        end = today - timedelta(days=today.weekday() + 1)
        return end - timedelta(days=6), end, "last week"
    if re.search(r"\b(this|current) month\b", text):
        start, end = month_bounds(today)
        return start, end, "this month"
    if re.search(r"\b(last|previous) month\b", text):
        start, end = month_bounds(today.replace(day=1) - timedelta(days=1))
        return start, end, "last month"
    match = re.search(r"\b(?:last|past) " + _NUM + r" days\b", text)
    if match:
        days = _to_int(match.group(1))
        if days < 1:
            raise PeriodError(f"last {days} days")
        return today - timedelta(days=days - 1), today, f"in the last {days} days"
    if re.search(r"\b(this|current) year\b", text):
        return date(today.year, 1, 1), date(today.year, 12, 31), "this year"
    if re.search(r"\b(last|previous) year\b", text):
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), "last year"

    for name, number in MONTH_NAMES.items():
        # "may" is also a verb, so it needs a preposition or a year next to it.
        pattern = rf"\b(?:in|for|during|of) {name}\b(?: (\d{{4}}))?" if name == "may" \
            else rf"\b{name}\b(?: (\d{{4}}))?"
        match = re.search(pattern, text)
        if match:
            year = int(match.group(1)) if match.group(1) else today.year
            if not match.group(1) and number > today.month:
                year -= 1  # "in November" asked in October means last November
            if not date.min.year <= year <= date.max.year:
                raise PeriodError(f"year {year}")
            start, end = month_bounds(date(year, number, 1))
            return start, end, f"in {calendar.month_name[number]} {year}"
    return None, None, "overall"


def extract_categories(text: str) -> list:
    return [c for c, pattern in _CATEGORY_PATTERNS.items() if re.search(pattern, text)]


def extract_payment_method(text: str):
    for method, pattern in _PAYMENT_PATTERNS.items():
        if re.search(pattern, text):
            return method
    return None


def extract_top_n(text: str):
    """'top 3', 'three largest', 'the 5 most expensive' -> the number, else None."""
    match = re.search(rf"\b{_SUPERLATIVE} {_NUM}\b", text)
    if match:
        return _to_int(match.group(2))
    match = re.search(rf"\b{_NUM} {_SUPERLATIVE}\b", text)
    if match:
        return _to_int(match.group(1))
    return None


def detect_intent(text: str) -> str:
    asks_category = re.search(r"\bcategor(y|ies)\b", text) is not None
    superlative = re.search(r"\b(highest|most|top|biggest|largest)\b", text) is not None

    if re.search(r"\b(percent|percentage|share|proportion|fraction)\b|%", text):
        return "percentage"
    if (asks_category and superlative) or re.search(r"\bwhere did i spend (the )?most\b", text):
        return "highest_category"
    if re.search(r"\b(breakdown|by category|per category|each category)\b", text):
        return "breakdown"
    if extract_top_n(text) or re.search(_SUPERLATIVE + r".*\bexpenses?\b|\bexpenses?\b.*" +
                                        _SUPERLATIVE, text):
        return "top_expenses"
    if re.search(r"\b(how many|number of|count)\b", text):
        return "count"
    if re.search(r"\b(show|list|find|which|what were)\b.*\b(expenses|transactions|purchases|payments)\b", text):
        return "list"
    if re.search(r"\b(how much|spend|spent|spending|total|cost|paid)\b", text):
        return "total"
    return "unknown"


class RuleBasedAssistant:
    def __init__(self, conn):
        self.conn = conn
        self.trace = []

    def _tool(self, name: str, args: dict) -> dict:
        clean = {k: v for k, v in args.items() if v is not None}
        try:
            result = execute_tool(self.conn, name, clean)
        except ToolError as exc:
            self.trace.append({"tool": name, "input": clean, "ok": False, "error": str(exc)})
            raise
        self.trace.append({"tool": name, "input": clean, "ok": True})
        return result

    def answer(self, question: str, today: date) -> dict:
        self.trace = []
        text = " ".join(question.lower().replace("?", " ").split())
        try:
            start, end, label = extract_period(text, today)
        except PeriodError:
            return {"answer": PERIOD_HELP_TEXT, "tool_calls": []}
        dates = {
            "start_date": start.isoformat() if start else None,
            "end_date": end.isoformat() if end else None,
        }
        categories = extract_categories(text)
        method = extract_payment_method(text)
        intent = detect_intent(text)

        handler = {
            "percentage": self._percentage,
            "highest_category": self._highest_category,
            "breakdown": self._breakdown,
            "top_expenses": self._top_expenses,
            "count": self._total,
            "list": self._list,
            "total": self._total,
        }.get(intent)
        if handler is None:
            if categories or start or method:
                handler = self._total
            else:
                return {"answer": HELP_TEXT, "tool_calls": []}

        try:
            answer = handler(text=text, dates=dates, label=label, categories=categories,
                             method=method, intent=intent)
        except ToolError:
            # The parsed values failed tool validation; explain instead of returning a 500.
            answer = PERIOD_HELP_TEXT if start or end else HELP_TEXT
        return {"answer": answer, "tool_calls": self.trace}

    # --- Handlers ---------------------------------------------------------------------------

    def _total(self, *, dates, label, categories, method, intent, **_):
        targets = categories or [None]
        lines = []
        for category in targets:
            result = self._tool("get_total_spending",
                                {**dates, "category": category, "payment_method": method})
            subject = " ".join(filter(None, [category, method])) or "all"
            count = result["expense_count"]
            qualifier = f"{subject} " if subject != "all" else ""
            if count == 0:
                lines.append(f"You have no {qualifier}expenses recorded {label}.")
            elif intent == "count":
                noun = "expense" if count == 1 else "expenses"
                lines.append(f"You recorded {count} {qualifier}{noun} {label}, "
                             f"totalling {result['total_formatted']}.")
            else:
                scope = f"on {subject}" if subject != "all" else "in total"
                noun = "expense" if count == 1 else "expenses"
                lines.append(f"You spent {result['total_formatted']} {scope} {label} "
                             f"across {count} {noun}.")
        return "\n".join(lines)

    def _percentage(self, *, dates, label, categories, **_):
        result = self._tool("get_category_breakdown", dates)
        if not result["categories"]:
            return f"There are no expenses recorded {label}, so there is nothing to compare."
        rows = {r["category"]: r for r in result["categories"]}
        if not categories:
            return self._format_breakdown(result, label)
        lines = []
        for category in categories:
            row = rows.get(category)
            if row is None:
                lines.append(f"{category} accounts for 0% of your spending {label} "
                             f"(total {result['grand_total_formatted']}).")
            else:
                lines.append(f"{category} accounts for {row['percentage']}% of your spending "
                             f"{label}: {row['total_formatted']} of "
                             f"{result['grand_total_formatted']}.")
        return "\n".join(lines)

    def _highest_category(self, *, dates, label, **_):
        result = self._tool("get_category_breakdown", dates)
        if not result["categories"]:
            return f"There are no expenses recorded {label}."
        top = result["categories"][0]
        return (f"Your highest spending category {label} is {top['category']} at "
                f"{top['total_formatted']}, which is {top['percentage']}% of your total "
                f"spending of {result['grand_total_formatted']}.")

    def _breakdown(self, *, dates, label, **_):
        result = self._tool("get_category_breakdown", dates)
        if not result["categories"]:
            return f"There are no expenses recorded {label}."
        return self._format_breakdown(result, label)

    @staticmethod
    def _format_breakdown(result, label):
        lines = [f"Spending by category {label} (total {result['grand_total_formatted']}):"]
        for row in result["categories"]:
            lines.append(f"- {row['category']}: {row['total_formatted']} ({row['percentage']}%)")
        return "\n".join(lines)

    def _top_expenses(self, *, text, dates, label, categories, **_):
        explicit = extract_top_n(text)
        limit = min(explicit or (5 if re.search(r"\bexpenses\b", text) else 1), 20)
        category = categories[0] if categories else None
        result = self._tool("get_top_expenses", {**dates, "category": category, "limit": limit})
        expenses = result["expenses"]
        scope = f"{category} " if category else ""
        if not expenses:
            return f"You have no {scope}expenses recorded {label}."
        if limit == 1:
            e = expenses[0]
            return (f"Your largest {scope}expense {label} is {e['amount_formatted']} for "
                    f"\"{e['description']}\" ({e['category']}, {e['date']}, {e['payment_method']}).")
        heading = f"Your {len(expenses)} largest {scope}expenses {label}:"
        if len(expenses) < limit:
            heading = f"You asked for {limit}, but only {len(expenses)} {scope}expenses " \
                      f"are recorded {label}:"
        lines = [heading]
        for i, e in enumerate(expenses, start=1):
            lines.append(f"{i}. {e['amount_formatted']} - {e['description']} "
                         f"({e['category']}, {e['date']}, {e['payment_method']})")
        return "\n".join(lines)

    def _list(self, *, dates, label, categories, method, **_):
        category = categories[0] if categories else None
        result = self._tool("search_expenses", {**dates, "category": category,
                                                "payment_method": method, "limit": 10})
        scope = " ".join(filter(None, [category, method]))
        scope = f"{scope} " if scope else ""
        if result["total_matching"] == 0:
            return f"You have no {scope}expenses recorded {label}."
        heading = (f"You have {result['total_matching']} {scope}expenses {label}, totalling "
                   f"{result['total_matching_amount_formatted']}.")
        if result["total_matching"] > result["returned"]:
            heading += f" The {result['returned']} most recent:"
        lines = [heading]
        for e in result["expenses"]:
            lines.append(f"- {e['date']}: {e['amount_formatted']} - {e['description']} "
                         f"({e['category']}, {e['payment_method']})")
        return "\n".join(lines)
