from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from core.llm import LLMResponse


class ScriptedChatModel:
    def __init__(self, responses: Sequence[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append((deepcopy(messages), deepcopy(tools)))
        if not self._responses:
            raise AssertionError("ScriptedChatModel has no remaining responses")
        return self._responses.pop(0)
