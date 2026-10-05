"""Tool-calling agent: the model decides WHICH data it needs, our code retrieves it.

Flow:
  1. Send the question, today's date context and the tool definitions to the model.
  2. While the model asks for tools (stop_reason == "tool_use"), execute them against
     SQLite and send back the results.
  3. Return the model's final text answer, plus a trace of every tool call made.
"""
import json
import time
from datetime import date, timedelta

from ..constants import CATEGORIES, PAYMENT_METHODS
from ..services.stats import month_bounds
from .llm_client import LLMError
from .tools import TOOL_DEFINITIONS, ToolError, execute_tool

MAX_STEPS = 6


def build_system_prompt(today: date) -> str:
    month_start, month_end = month_bounds(today)
    last_month_start, last_month_end = month_bounds(month_start - timedelta(days=1))
    return f"""You are the expense assistant inside a small-business expense tracker.

Rules:
- Answer ONLY from data returned by the tools. Call a tool before stating any figure.
- Never invent expenses, amounts or dates. If the tools return nothing relevant, say so plainly.
- If a question is unrelated to the user's expenses, say you can only help with expense questions.
- Use the *_formatted values from tool results when quoting amounts. Currency is Indian rupees.
- Be concise: one or two sentences, or a short numbered list for multiple expenses.
- When a time period applies, mention it in the answer.

Date context (use these exact ranges; do not do your own calendar arithmetic):
- Today: {today.isoformat()}
- "This month": {month_start.isoformat()} to {month_end.isoformat()}
- "Last month": {last_month_start.isoformat()} to {last_month_end.isoformat()}
- "This year": {today.year}-01-01 to {today.year}-12-31
- With no time period mentioned, do not pass any dates (use all recorded data).

Categories: {", ".join(CATEGORIES)}.
Payment methods: {", ".join(PAYMENT_METHODS)}."""


class LLMAssistant:
    def __init__(self, client, conn, time_limit: float = 45.0):
        self.client = client
        self.conn = conn
        self.time_limit = time_limit

    def answer(self, question: str, today: date) -> dict:
        system = build_system_prompt(today)
        messages = [{"role": "user", "content": question}]
        trace = []
        deadline = time.monotonic() + self.time_limit

        for _ in range(MAX_STEPS):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LLMError(f"The assistant hit the {self.time_limit:g}-second time limit")
            # Cap each call so one slow response cannot overrun the whole question's limit.
            response = self.client.create_message(
                system=system, messages=messages, tools=TOOL_DEFINITIONS,
                timeout=min(self.client.timeout, remaining),
            )
            content = response["content"]
            if response.get("stop_reason") == "max_tokens":
                # The text or tool call was cut off mid-way; never present it as complete.
                raise LLMError("The model's response was cut off (max_tokens reached)")
            messages.append({"role": "assistant", "content": content})

            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if any(not isinstance(b.get("id"), str) for b in tool_uses):
                raise LLMError("The model returned a tool call without an id")
            if response.get("stop_reason") != "tool_use" or not tool_uses:
                text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
                if not text.strip():
                    raise LLMError("The model returned an empty answer")
                return {"answer": text.strip(), "tool_calls": trace}

            results = []
            for block in tool_uses:
                name, args = block.get("name"), block.get("input") or {}
                try:
                    output = execute_tool(self.conn, name, args)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": json.dumps(output),
                    })
                    trace.append({"tool": name, "input": args, "ok": True})
                except ToolError as exc:
                    # Report the error to the model so it can correct its arguments.
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": str(exc),
                        "is_error": True,
                    })
                    trace.append({"tool": name, "input": args, "ok": False, "error": str(exc)})
            messages.append({"role": "user", "content": results})

        raise LLMError(f"The assistant did not finish within {MAX_STEPS} steps")
