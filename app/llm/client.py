"""LLM layer: Anthropic client (structured outputs + manual tool loop) and an offline stub.

Agents depend only on the `LLMClient` protocol; any `LLMUnavailable` makes them fall back
to their deterministic offline path.
"""

import json
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import anthropic
from pydantic import BaseModel

from app.config import get_settings
from app.schemas import ToolCall

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class LLMUnavailable(RuntimeError):
    """Raised when the model cannot be used (offline, API error, refusal)."""


class LLMClient(Protocol):
    mode: str  # "llm" | "offline"

    def structured(
        self, system: str, user: str, schema: type[BaseModel], model: str | None = None
    ) -> BaseModel: ...

    def run_tools(
        self,
        system: str,
        user: str,
        tools: list[dict],
        execute: Callable[[str, dict], dict],
        model: str | None = None,
    ) -> tuple[str, list[ToolCall]]: ...


class OfflineLLM:
    mode = "offline"

    def structured(
        self, system: str, user: str, schema: type[BaseModel], model: str | None = None
    ) -> BaseModel:
        raise LLMUnavailable("LLM disabled (offline mode)")

    def run_tools(
        self,
        system: str,
        user: str,
        tools: list[dict],
        execute: Callable[[str, dict], dict],
        model: str | None = None,
    ) -> tuple[str, list[ToolCall]]:
        raise LLMUnavailable("LLM disabled (offline mode)")


def _text(response: Any) -> str:
    return "\n".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()


class AnthropicLLM:
    mode = "llm"

    def __init__(self, client: Any = None) -> None:
        self.settings = get_settings()
        self.client = client or anthropic.Anthropic(
            api_key=self.settings.anthropic_api_key or None,
            timeout=self.settings.llm_timeout_s,
            max_retries=2,
        )

    def structured(
        self, system: str, user: str, schema: type[BaseModel], model: str | None = None
    ) -> BaseModel:
        try:
            response = self.client.messages.parse(
                model=model or self.settings.llm_model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        except anthropic.APIError as exc:
            raise LLMUnavailable(f"Anthropic API error: {exc}") from exc
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise LLMUnavailable(f"no structured output (stop_reason={response.stop_reason})")
        return response.parsed_output

    def run_tools(
        self,
        system: str,
        user: str,
        tools: list[dict],
        execute: Callable[[str, dict], dict],
        model: str | None = None,
    ) -> tuple[str, list[ToolCall]]:
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        calls: list[ToolCall] = []
        iterations = 0
        try:
            response = self._create(model, system, messages, tools)
            while response.stop_reason == "tool_use" and iterations < self.settings.llm_max_tool_iterations:
                iterations += 1
                messages.append({"role": "assistant", "content": response.content})
                results = []
                for block in response.content:
                    if getattr(block, "type", None) != "tool_use":
                        continue
                    args = dict(block.input or {})
                    try:
                        result, error = execute(block.name, args), None
                    except Exception as exc:  # noqa: BLE001 - tool failures are reported back to the model
                        error = str(exc)
                        result = {"ok": False, "error": error}
                    calls.append(ToolCall(tool=block.name, ok=error is None, args=args, error=error))
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                            "is_error": error is not None,
                        }
                    )
                messages.append({"role": "user", "content": results})
                response = self._create(model, system, messages, tools)
        except anthropic.APIError as exc:
            raise LLMUnavailable(f"Anthropic API error: {exc}") from exc
        if response.stop_reason == "refusal":
            raise LLMUnavailable("model refused the request")
        return _text(response), calls

    def _create(self, model: str | None, system: str, messages: list[dict], tools: list[dict]) -> Any:
        return self.client.messages.create(
            model=model or self.settings.llm_model,
            max_tokens=4096,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice={"type": "auto"},
        )


@lru_cache
def get_llm() -> LLMClient:
    return AnthropicLLM() if get_settings().resolved_mode == "llm" else OfflineLLM()


@lru_cache
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
