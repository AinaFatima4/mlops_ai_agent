"""Minimal client for any OpenAI-compatible chat completions API (Ollama, Groq, Gemini)."""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_TIMEOUT_SECONDS = 180
THINKING_BLOCK_REGEX = re.compile(r"<think>.*?</think>", re.DOTALL)


class LlmUnavailableError(Exception):
    """Raised when the language model cannot be reached or returns an unusable response."""


@dataclass(frozen=True)
class LlmToolCall:
    call_id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class LlmResponse:
    content: str
    tool_calls: list[LlmToolCall] = field(default_factory=list)
    finish_reason: str = "stop"

    def as_assistant_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": tool_call.call_id,
                    "type": "function",
                    "function": {"name": tool_call.name, "arguments": tool_call.arguments_json},
                }
                for tool_call in self.tool_calls
            ]
        return message


class ChatModel(Protocol):
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LlmResponse: ...


def parse_chat_completion(body: dict[str, Any]) -> LlmResponse:
    try:
        choice = body["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise LlmUnavailableError(f"Unexpected LLM response shape: {str(body)[:300]}") from error

    tool_calls = []
    for index, raw_call in enumerate(message.get("tool_calls") or []):
        function = raw_call.get("function", {})
        arguments = function.get("arguments", "{}")
        # Some servers return arguments as an object instead of a JSON string
        arguments_json = arguments if isinstance(arguments, str) else json.dumps(arguments)
        tool_calls.append(
            LlmToolCall(
                call_id=raw_call.get("id") or f"call_{index}",
                name=function.get("name", ""),
                arguments_json=arguments_json or "{}",
            )
        )
    content = THINKING_BLOCK_REGEX.sub("", message.get("content") or "").strip()
    return LlmResponse(
        content=content,
        tool_calls=tool_calls,
        finish_reason=choice.get("finish_reason") or "stop",
    )


class OpenAiCompatibleChatModel:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.http_client = httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LlmResponse:
        request_body = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0,
        }
        if self.reasoning_effort:
            # Limits how long reasoning models think before answering
            request_body["reasoning_effort"] = self.reasoning_effort
        try:
            response = self.http_client.post("/chat/completions", json=request_body)
        except httpx.TimeoutException as error:
            raise LlmUnavailableError("The language model timed out") from error
        except httpx.HTTPError as error:
            raise LlmUnavailableError(f"The language model is unreachable: {error}") from error
        if response.status_code >= 400:
            raise LlmUnavailableError(
                f"The language model returned HTTP {response.status_code}: {response.text[:300]}"
            )
        return parse_chat_completion(response.json())


def create_chat_model() -> OpenAiCompatibleChatModel:
    return OpenAiCompatibleChatModel(
        base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
        model=os.environ.get("LLM_MODEL", DEFAULT_MODEL),
        api_key=os.environ.get("LLM_API_KEY", "ollama"),
        timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
        reasoning_effort=os.environ.get("LLM_REASONING_EFFORT") or None,
    )
