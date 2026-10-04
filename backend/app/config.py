"""Configuration loaded from environment variables (see .env.example)."""
import os
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def load_config() -> dict:
    provider = os.environ.get("AI_PROVIDER", "auto").strip().lower()
    if provider not in ("auto", "anthropic", "rules"):
        raise RuntimeError("AI_PROVIDER must be one of: auto, anthropic, rules")
    return {
        "DATABASE_PATH": os.environ.get("DATABASE_PATH")
        or str(BACKEND_DIR / "instance" / "expenses.db"),
        "AI_PROVIDER": provider,
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        "ANTHROPIC_MODEL": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5").strip(),
        "ANTHROPIC_TIMEOUT_SECONDS": _float("ANTHROPIC_TIMEOUT_SECONDS", 30.0),
        "ANTHROPIC_TRANSPORT": None,  # tests inject a fake HTTP transport here
        "CLOCK": date.today,          # tests inject a fixed date here
    }
