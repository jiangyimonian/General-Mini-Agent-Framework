"""Demo 专用脚本化模型，用于离线测试。

不访问网络，按队列返回预设响应。只用于 Demo 和测试，不从 core 导出。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from core.llm import LLMResponse, ToolCall


@dataclass
class ScriptedChatModel:
    """脚本化同步模型，按队列返回响应。"""

    responses: list[dict[str, Any]] = field(default_factory=list)
    _index: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """返回下一个预设响应。"""
        # 记录调用
        self.calls.append({
            "messages": [dict(m) for m in messages],
            "tools": [dict(t) for t in tools] if tools else None,
        })

        if self._index >= len(self.responses):
            # 默认响应
            return LLMResponse(content="Done.", usage={})

        resp = self.responses[self._index]
        self._index += 1

        # 转换 tool_calls
        tool_calls = None
        if resp.get("tool_calls"):
            tool_calls = [
                ToolCall(
                    id=f"call_{i}",
                    name=tc["name"],
                    arguments=tc["arguments"],
                )
                for i, tc in enumerate(resp["tool_calls"])
            ]

        return LLMResponse(
            content=resp.get("content", ""),
            tool_calls=tool_calls,
            usage=resp.get("usage", {}),
        )

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Iterator[dict[str, Any]]:
        """流式响应：先 yield 文本，再 yield tool_calls。"""
        self.calls.append({
            "messages": [dict(m) for m in messages],
            "tools": [dict(t) for t in tools] if tools else None,
        })

        if self._index >= len(self.responses):
            yield {"type": "text", "text": "Done."}
            return

        resp = self.responses[self._index]
        self._index += 1

        # Yield text
        if resp.get("content"):
            yield {"type": "text", "text": resp["content"]}

        # Yield tool calls
        if resp.get("tool_calls"):
            for i, tc in enumerate(resp["tool_calls"]):
                yield {
                    "type": "tool_call",
                    "index": i,
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                }

        # Yield usage
        yield {"type": "usage", "usage": resp.get("usage", {})}


def make_scripted_llm(responses: list[dict[str, Any]]) -> ScriptedChatModel:
    """创建脚本化模型实例。"""
    return ScriptedChatModel(responses)


# ─── 预设场景 ────────────────────────────────────────────────────────


def agent_with_tool_response() -> list[dict[str, Any]]:
    """单 Agent 工具调用场景：计算器工具。"""
    return [
        {
            "content": "",
            "tool_calls": [
                {"name": "calculate", "arguments": '{"expression": "2+2"}'},
            ],
            "usage": {"total_tokens": 50, "prompt_tokens": 40, "completion_tokens": 10},
        },
        {
            "content": "The result is 4.",
            "tool_calls": None,
            "usage": {"total_tokens": 30, "prompt_tokens": 20, "completion_tokens": 10},
        },
    ]


def debate_responses() -> list[dict[str, Any]]:
    """Debate 场景：Solver、Critic 各一轮。"""
    return [
        # Solver round 1
        {
            "content": "I propose the answer is 42.",
            "tool_calls": None,
            "usage": {"total_tokens": 20, "prompt_tokens": 15, "completion_tokens": 5},
        },
        # Critic round 1
        {
            "content": "I disagree, the answer should be 43.",
            "tool_calls": None,
            "usage": {"total_tokens": 25, "prompt_tokens": 20, "completion_tokens": 5},
        },
        # Judge
        {
            "content": "After review, I conclude the answer is 42.",
            "tool_calls": None,
            "usage": {"total_tokens": 30, "prompt_tokens": 25, "completion_tokens": 5},
        },
    ]