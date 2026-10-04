"""Data-access layer. The only module that contains SQL.

All values are bound as parameters. Column names used in ORDER BY come from a fixed
whitelist, never from user input directly.
"""
import sqlite3

from .money import paise_to_amount

_SORT_COLUMNS = {
    "date": "date",
    "amount": "amount_paise",
    "category": "category",
    "created_at": "created_at",
    "id": "id",
}
_WRITABLE_COLUMNS = ("date", "category", "description", "amount_paise", "payment_method")


def row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "date": row["date"],
        "category": row["category"],
        "description": row["description"],
        "amount": paise_to_amount(row["amount_paise"]),
        "payment_method": row["payment_method"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_where(filters: dict):
    clauses, params = [], []
    if filters.get("category"):
        clauses.append("category = ?")
        params.append(filters["category"])
    if filters.get("payment_method"):
        clauses.append("payment_method = ?")
        params.append(filters["payment_method"])
    if filters.get("start_date"):
        clauses.append("date >= ?")
        params.append(filters["start_date"])
    if filters.get("end_date"):
        clauses.append("date <= ?")
        params.append(filters["end_date"])
    if filters.get("min_paise") is not None:
        clauses.append("amount_paise >= ?")
        params.append(filters["min_paise"])
    if filters.get("max_paise") is not None:
        clauses.append("amount_paise <= ?")
        params.append(filters["max_paise"])
    if filters.get("q"):
        clauses.append("description LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(filters['q'])}%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


# --- CRUD ---------------------------------------------------------------------------------

def create_expense(conn, data: dict) -> dict:
    columns = [c for c in _WRITABLE_COLUMNS if c in data]
    cursor = conn.execute(
        f"INSERT INTO expenses ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        [data[c] for c in columns],
    )
    conn.commit()
    return get_expense(conn, cursor.lastrowid)


def get_expense(conn, expense_id: int):
    row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    return row_to_dict(row) if row else None


def update_expense(conn, expense_id: int, data: dict):
    columns = [c for c in _WRITABLE_COLUMNS if c in data]
    assignments = ", ".join(f"{c} = ?" for c in columns)
    cursor = conn.execute(
        f"UPDATE expenses SET {assignments}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = ?",
        [data[c] for c in columns] + [expense_id],
    )
    conn.commit()
    if cursor.rowcount == 0:
        return None
    return get_expense(conn, expense_id)


def delete_expense(conn, expense_id: int) -> bool:
    cursor = conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    conn.commit()
    return cursor.rowcount > 0


def list_expenses(conn, filters: dict, sort: str = "date", order: str = "desc",
                  limit: int = 50, offset: int = 0):
    """Return (items, total_count, total_paise) for the filtered set."""
    where, params = build_where(filters)
    count, total_paise = summarize(conn, filters)
    column = _SORT_COLUMNS[sort]
    direction = "ASC" if order == "asc" else "DESC"
    rows = conn.execute(
        f"SELECT * FROM expenses{where} ORDER BY {column} {direction}, id {direction} "
        "LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return [row_to_dict(r) for r in rows], count, total_paise


# --- Aggregates ---------------------------------------------------------------------------

def summarize(conn, filters: dict):
    """Return (count, total_paise) for the filtered set."""
    where, params = build_where(filters)
    row = conn.execute(
        f"SELECT COUNT(*) AS n, COALESCE(SUM(amount_paise), 0) AS total FROM expenses{where}",
        params,
    ).fetchone()
    return row["n"], row["total"]


def category_totals(conn, filters: dict):
    """Return [{category, total_paise, count}] ordered by total desc (ties: name asc)."""
    where, params = build_where(filters)
    rows = conn.execute(
        f"SELECT category, SUM(amount_paise) AS total, COUNT(*) AS n FROM expenses{where} "
        "GROUP BY category ORDER BY total DESC, category ASC",
        params,
    ).fetchall()
    return [{"category": r["category"], "total_paise": r["total"], "count": r["n"]} for r in rows]


def top_expenses(conn, filters: dict, limit: int):
    where, params = build_where(filters)
    rows = conn.execute(
        f"SELECT * FROM expenses{where} ORDER BY amount_paise DESC, date DESC, id DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    return [row_to_dict(r) for r in rows]
