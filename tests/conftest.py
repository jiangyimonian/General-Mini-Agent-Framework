from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from general_mini_agent.llm import LLMResponse, StreamChunk


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


def assert_valid_tool_transcript(messages):
    """验证消息序列的工具调用完整性。

    规则：
    1. assistant 消息中的每个 tool_call 都必须被后续的 tool 消息响应
    2. tool 消息必须在所有工具调用发出后才能出现
    3. 所有挂起的工具调用必须在消息序列结束时全部完成
    """
    pending = set()
    for index, message in enumerate(messages):
        if message["role"] == "assistant":
            # assistant 消息不能打断挂起的工具调用
            assert not pending, f"assistant interrupted pending tools at {index}"
            # 记录所有工具调用 ID
            for call in message.get("tool_calls", []):
                assert call["id"] not in pending
                pending.add(call["id"])
        elif message["role"] == "tool":
            # tool 消息必须对应挂起的工具调用
            assert message["tool_call_id"] in pending
            pending.remove(message["tool_call_id"])
        else:
            # user 或 system 消息必须在所有工具调用完成后
            assert not pending
    # 所有工具调用必须完成
    assert not pending


class StrictScriptedChatModel(ScriptedChatModel):
    """严格验证工具消息序列的脚本模型"""

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        assert_valid_tool_transcript(messages)
        return super().chat(messages, tools=tools)


class ScriptedAsyncChatModel:
    """异步版本的脚本模型，用于测试 AsyncAgent。"""

    def __init__(self, responses: Sequence[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []

    async def chat_async(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append((deepcopy(messages), deepcopy(tools)))
        if not self._responses:
            raise AssertionError("ScriptedAsyncChatModel has no remaining responses")
        return self._responses.pop(0)


class StrictScriptedAsyncChatModel(ScriptedAsyncChatModel):
    """严格验证工具消息序列的异步脚本模型"""

    async def chat_async(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        assert_valid_tool_transcript(messages)
        return await super().chat_async(messages, tools=tools)


class ScriptedAsyncStreamingChatModel:
    """异步流式脚本模型，用于测试 AsyncAgent 的 run_stream_async。"""

    def __init__(
        self,
        streams: Sequence[Sequence[StreamChunk] | Exception],
    ) -> None:
        self._streams = list(streams)
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []

    async def chat_stream_async(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ):
        from copy import deepcopy
        self.calls.append((deepcopy(messages), deepcopy(tools)))
        if not self._streams:
            raise AssertionError("ScriptedAsyncStreamingChatModel has no remaining streams")
        stream = self._streams.pop(0)
        if isinstance(stream, Exception):
            raise stream
        for chunk in stream:
            yield chunk
