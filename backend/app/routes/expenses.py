"""CRUD endpoints for expenses."""
from flask import Blueprint, jsonify, request, url_for

from .. import repository
from ..db import get_db
from ..errors import NotFoundError, ValidationError
from ..money import paise_to_amount
from ..validation import parse_list_query, validate_expense_payload

bp = Blueprint("expenses", __name__, url_prefix="/api/expenses")


def _json_body():
    data = request.get_json(silent=True)
    if data is None:
        raise ValidationError("Request body must be valid JSON with Content-Type: application/json.")
    return data


def _get_or_404(expense_id: int) -> dict:
    expense = repository.get_expense(get_db(), expense_id)
    if expense is None:
        raise NotFoundError(f"Expense {expense_id} was not found.")
    return expense


@bp.get("")
def list_expenses():
    query = parse_list_query(request.args)
    offset = (query["page"] - 1) * query["page_size"]
    items, total_count, total_paise = repository.list_expenses(
        get_db(), query["filters"], query["sort"], query["order"], query["page_size"], offset
    )
    return jsonify({
        "items": items,
        "pagination": {
            "page": query["page"],
            "page_size": query["page_size"],
            "total_items": total_count,
            "total_pages": max(1, -(-total_count // query["page_size"])),
        },
        "summary": {"total_amount": paise_to_amount(total_paise)},
    })


@bp.post("")
def create_expense():
    data = validate_expense_payload(_json_body())
    expense = repository.create_expense(get_db(), data)
    response = jsonify(expense)
    response.status_code = 201
    response.headers["Location"] = url_for("expenses.get_expense", expense_id=expense["id"])
    return response


@bp.get("/<int:expense_id>")
def get_expense(expense_id: int):
    return jsonify(_get_or_404(expense_id))


@bp.put("/<int:expense_id>")
def replace_expense(expense_id: int):
    """Full update: every field is required."""
    data = validate_expense_payload(_json_body(), partial=False)
    _get_or_404(expense_id)
    return jsonify(repository.update_expense(get_db(), expense_id, data))


@bp.patch("/<int:expense_id>")
def patch_expense(expense_id: int):
    """Partial update: only the supplied fields change."""
    data = validate_expense_payload(_json_body(), partial=True)
    _get_or_404(expense_id)
    return jsonify(repository.update_expense(get_db(), expense_id, data))


@bp.delete("/<int:expense_id>")
def delete_expense(expense_id: int):
    if not repository.delete_expense(get_db(), expense_id):
        raise NotFoundError(f"Expense {expense_id} was not found.")
    return "", 204
