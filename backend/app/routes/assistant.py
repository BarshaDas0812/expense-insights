"""AI assistant endpoint."""
from flask import Blueprint, current_app, jsonify, request

from ..assistant.service import answer_question
from ..clock import today
from ..db import get_db
from ..errors import ValidationError

bp = Blueprint("assistant", __name__, url_prefix="/api/assistant")

MAX_QUESTION_LENGTH = 500


@bp.post("/query")
def query():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object like {\"question\": \"...\"}.")
    question = body.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValidationError("Question is required.", details={"question": "must be a non-empty string"})
    if len(question) > MAX_QUESTION_LENGTH:
        raise ValidationError(
            "Question is too long.",
            details={"question": f"must be at most {MAX_QUESTION_LENGTH} characters"},
        )
    result = answer_question(question.strip(), get_db(), today(), current_app.config)
    return jsonify({"question": question.strip(), **result})
