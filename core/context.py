"""Token counting and request context budget policies."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class TokenCounter(Protocol):
    """Count tokens used by a complete model request input."""

    def count(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> int: ...


class ContextPolicy(Protocol):
    """Prepare a bounded message snapshot for one model request."""

    def prepare(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]: ...


class OversizedContentHandler(Protocol):
    """Replace protected content that cannot fit the configured budget."""

    def __call__(
        self,
        messages: Sequence[Mapping[str, Any]],
        input_budget: int,
    ) -> list[dict[str, Any]]: ...


class ApproximateTokenCounter:
    """Dependency-free deterministic estimate based on serialized characters."""

    def __init__(self, characters_per_token: int = 4) -> None:
        if characters_per_token <= 0:
            raise ValueError("characters_per_token must be positive")
        self.characters_per_token = characters_per_token

    def count(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> int:
        payload = {
            "messages": list(messages),
            "tools": list(tools or []),
        }
        characters = len(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        return max(1, math.ceil(characters / self.characters_per_token))


class ContextBudgetExceeded(Exception):
    """Raised when protected request content cannot fit the input budget."""

    def __init__(self, input_tokens: int, input_budget: int) -> None:
        self.input_tokens = input_tokens
        self.input_budget = input_budget
        super().__init__(
            f"request context requires {input_tokens} tokens; budget is {input_budget}"
        )


class TokenBudgetContext:
    """Enforce an explicit input budget for one model request."""

    def __init__(
        self,
        context_window: int,
        reserved_output_tokens: int,
        *,
        token_counter: TokenCounter | None = None,
        oversized_content_handler: OversizedContentHandler | None = None,
    ) -> None:
        if context_window <= 0:
            raise ValueError("context_window must be positive")
        if reserved_output_tokens <= 0:
            raise ValueError("reserved_output_tokens must be positive")
        if reserved_output_tokens >= context_window:
            raise ValueError("reserved_output_tokens must be smaller than context_window")
        self.context_window = context_window
        self.reserved_output_tokens = reserved_output_tokens
        self.input_budget = context_window - reserved_output_tokens
        self.token_counter = token_counter or ApproximateTokenCounter()
        self.oversized_content_handler = oversized_content_handler

    def prepare(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        prepared = copy.deepcopy([dict(message) for message in messages])
        input_tokens = self.token_counter.count(prepared, tools=tools)
        if input_tokens > self.input_budget:
            raise ContextBudgetExceeded(input_tokens, self.input_budget)
        return prepared
