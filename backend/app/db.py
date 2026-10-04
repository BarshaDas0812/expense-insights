"""SQLite connection management (one connection per request, closed on teardown)."""
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(database_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(database_path: str) -> None:
    """Create the schema if it does not exist. Safe to call on every start-up."""
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(database_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def reset_db(database_path: str) -> None:
    conn = connect(database_path)
    try:
        conn.execute("DROP TABLE IF EXISTS expenses")
        conn.commit()
    finally:
        conn.close()
    init_db(database_path)
