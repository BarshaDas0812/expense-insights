"""API error types and JSON error handlers.

Every error response uses the same envelope:
    {"error": {"code": "...", "message": "...", "details": {...}}}
"""
import logging

from flask import jsonify
from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)


class APIError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message, details=None, status_code=None, code=None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code

    def to_response(self):
        body = {"error": {"code": self.code, "message": self.message}}
        if self.details:
            body["error"]["details"] = self.details
        return jsonify(body), self.status_code


class ValidationError(APIError):
    status_code = 400
    code = "validation_error"


class NotFoundError(APIError):
    status_code = 404
    code = "not_found"


class ServiceUnavailableError(APIError):
    status_code = 503
    code = "service_unavailable"


def register_error_handlers(app):
    @app.errorhandler(APIError)
    def handle_api_error(error):
        return error.to_response()

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        code = (error.name or "error").lower().replace(" ", "_")
        return jsonify({"error": {"code": code, "message": error.description}}), error.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        logger.exception("Unhandled error")
        return (
            jsonify({"error": {"code": "internal_error", "message": "An unexpected error occurred."}}),
            500,
        )
