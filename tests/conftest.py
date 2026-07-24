from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from core.llm import LLMResponse, StreamChunk


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


class ScriptedStreamingChatModel(ScriptedChatModel):
    def __init__(
        self,
        responses: Sequence[LLMResponse],
        streams: Sequence[Sequence[StreamChunk] | Exception],
    ) -> None:
        super().__init__(responses)
        self._streams = list(streams)
        self.stream_calls: list[
            tuple[list[dict[str, Any]], list[dict[str, Any]] | None]
        ] = []

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ):
        self.stream_calls.append((deepcopy(messages), deepcopy(tools)))
        if not self._streams:
            raise AssertionError("ScriptedStreamingChatModel has no remaining streams")
        stream = self._streams.pop(0)
        if isinstance(stream, Exception):
            raise stream
        yield from stream
