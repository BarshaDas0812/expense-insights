"""Health check and reference data for clients."""
from flask import Blueprint, jsonify

from ..constants import CATEGORIES, CURRENCY_CODE, PAYMENT_METHODS

bp = Blueprint("meta", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@bp.get("/meta")
def meta():
    return jsonify({
        "categories": list(CATEGORIES),
        "payment_methods": list(PAYMENT_METHODS),
        "currency": CURRENCY_CODE,
    })
