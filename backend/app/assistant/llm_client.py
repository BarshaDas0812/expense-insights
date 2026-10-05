"""Minimal Anthropic Messages API client using only the standard library.

The HTTP transport is injectable so the agent loop can be tested without network access.
"""
import http.client
import json
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class LLMError(Exception):
    """The language model could not be reached or returned an unusable response."""


def urllib_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise LLMError(f"Anthropic API returned HTTP {exc.code}: {body}") from None
    # OSError covers URLError, timeouts and connections reset mid-read; HTTPException covers
    # malformed HTTP responses; ValueError covers undecodable or non-JSON bodies.
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise LLMError(f"Could not reach the Anthropic API: {exc}") from None


class AnthropicClient:
    def __init__(self, api_key: str, model: str, timeout: float = 30.0, transport=None):
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.transport = transport or urllib_transport

    def create_message(self, *, system: str, messages: list, tools: list,
                       max_tokens: int = 1024, timeout: float = None) -> dict:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "tools": tools,
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        response = self.transport(API_URL, headers, payload,
                                  self.timeout if timeout is None else timeout)
        content = response.get("content") if isinstance(response, dict) else None
        if not isinstance(content, list) or not all(isinstance(b, dict) for b in content):
            raise LLMError("Unexpected response shape from the Anthropic API")
        return response
