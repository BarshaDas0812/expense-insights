"""Injectable clock so that 'this month' logic is deterministic in tests."""
from datetime import date

from flask import current_app


def today() -> date:
    return current_app.config["CLOCK"]()
