"""Chooses the assistant implementation and handles fallback.

AI_PROVIDER:
  "anthropic" - always use the LLM agent (fails over to rules if the call errors)
  "rules"     - always use the offline rule-based assistant
  "auto"      - LLM agent if ANTHROPIC_API_KEY is set, otherwise rules (default)
"""
import logging

from .llm_agent import LLMAssistant
from .llm_client import AnthropicClient, LLMError
from .rule_based import RuleBasedAssistant

logger = logging.getLogger(__name__)


def _wants_llm(config) -> bool:
    provider = config.get("AI_PROVIDER", "auto")
    if provider == "rules":
        return False
    if provider == "anthropic":
        return True
    return bool(config.get("ANTHROPIC_API_KEY"))


def answer_question(question: str, conn, today, config) -> dict:
    if _wants_llm(config):
        try:
            client = AnthropicClient(
                api_key=config.get("ANTHROPIC_API_KEY", ""),
                model=config["ANTHROPIC_MODEL"],
                timeout=config["ANTHROPIC_TIMEOUT_SECONDS"],
                transport=config.get("ANTHROPIC_TRANSPORT"),
            )
            result = LLMAssistant(client, conn).answer(question, today)
            return {**result, "provider": "anthropic", "model": config["ANTHROPIC_MODEL"]}
        except LLMError as exc:
            logger.warning("LLM assistant failed, falling back to rules: %s", exc)
            result = RuleBasedAssistant(conn).answer(question, today)
            return {**result, "provider": "rules", "fallback_reason": str(exc)}

    result = RuleBasedAssistant(conn).answer(question, today)
    return {**result, "provider": "rules"}
