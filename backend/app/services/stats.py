"""Dashboard statistics, computed with SQL aggregates (never by loading every row)."""
import calendar
from datetime import date

from .. import repository
from ..constants import CURRENCY_CODE
from ..money import paise_to_amount


def month_bounds(day: date):
    last_day = calendar.monthrange(day.year, day.month)[1]
    return day.replace(day=1), day.replace(day=last_day)


def percentage(part: int, whole: int) -> float:
    return round(part * 100 / whole, 2) if whole else 0.0


def compute_stats(conn, today: date, filters: dict | None = None) -> dict:
    """Compute dashboard statistics.

    `filters` (e.g. a date range) scopes the totals, the breakdown and the "highest" values.
    `current_month` always refers to the calendar month containing `today`, independent of
    the filters, because that is what the dashboard card represents.
    """
    filters = filters or {}

    count, total_paise = repository.summarize(conn, filters)

    month_start, month_end = month_bounds(today)
    month_count, month_total = repository.summarize(
        conn, {"start_date": month_start.isoformat(), "end_date": month_end.isoformat()}
    )

    by_category = [
        {
            "category": row["category"],
            "total_amount": paise_to_amount(row["total_paise"]),
            "expense_count": row["count"],
            "percentage": percentage(row["total_paise"], total_paise),
        }
        for row in repository.category_totals(conn, filters)
    ]

    top = repository.top_expenses(conn, filters, limit=1)

    return {
        "currency": CURRENCY_CODE,
        "filters": {
            "start_date": filters.get("start_date"),
            "end_date": filters.get("end_date"),
        },
        "total_amount": paise_to_amount(total_paise),
        "expense_count": count,
        "current_month": {
            "month": month_start.strftime("%Y-%m"),
            "total_amount": paise_to_amount(month_total),
            "expense_count": month_count,
        },
        "highest_category": by_category[0] if by_category else None,
        "highest_expense": top[0] if top else None,
        "by_category": by_category,
    }
