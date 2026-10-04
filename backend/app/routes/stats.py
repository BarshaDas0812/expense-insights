"""Statistics endpoint used by the dashboard."""
from flask import Blueprint, jsonify, request

from ..clock import today
from ..db import get_db
from ..errors import ValidationError
from ..services.stats import compute_stats
from ..validation import build_filters

bp = Blueprint("stats", __name__, url_prefix="/api/expenses")


@bp.get("/stats")
def get_stats():
    unsupported = set(request.args) - {"start_date", "end_date"}
    if unsupported:
        raise ValidationError(
            "Unsupported query parameters.",
            details={p: "is not supported; use start_date and end_date" for p in sorted(unsupported)},
        )
    filters = build_filters(request.args)
    return jsonify(compute_stats(get_db(), today(), filters))
