"""OpenAI 兼容的同步与流式 LLM 客户端。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


# ─── 类型定义 ───────────────────────────────────────────────


@dataclass
class ToolCall:
    """LLM 返回的工具调用"""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """LLM 调用结果"""
    content: str | None
    tool_calls: list[ToolCall] | None
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""


@dataclass
class StreamChunk:
    """流式响应的单个 chunk"""
    content: str = ""           # 文本增量
    finish_reason: str = ""     # "stop", "tool_calls", "length", None
    tool_call_id: str = ""      # 当前 tool call id（增量拼接中）
    tool_name: str = ""         # 当前 tool name
    tool_args: str = ""         # 当前 tool arguments JSON 片段
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class LLMConfig:
    """LLM 配置"""
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout: float = 60.0
    max_retries: int = 3


# ─── LLM 核心类 ─────────────────────────────────────────────


class LLM:
    """LLM 调用封装，通过 httpx 直调 API"""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        if not self.config.api_key:
            raise ValueError("api_key 未设置，请通过 LLMConfig 传入")
        self._client = httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
        )

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """调用 LLM，支持 function calling"""
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            body["tools"] = tools

        last_error: Exception | None = None
        for attempt in range(self.config.max_retries):
            try:
                resp = self._client.post("/chat/completions", json=body)
                resp.raise_for_status()
                data = resp.json()
                return self._parse_response(data)

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code in (429, 502, 503, 504):
                    self._sleep(attempt)
                    continue
                raise
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                self._sleep(attempt)
                continue

        raise RuntimeError(
            f"LLM 调用失败（已重试 {self.config.max_retries} 次）: {last_error}"
        )

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ):
        """流式调用 LLM，逐 chunk yield StreamChunk"""
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }
        if tools:
            body["tools"] = tools

        with self._client.stream("POST", "/chat/completions", json=body) as resp:
            resp.raise_for_status()
            # 流式解析 SSE
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]  # 去掉 "data: " 前缀
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                chunk = self._parse_stream_chunk(data)
                if chunk is not None:
                    yield chunk

    # ── 内部方法 ────────────────────────────────────────

    def _parse_stream_chunk(self, data: dict) -> StreamChunk | None:
        """解析单个 SSE data chunk"""
        if "choices" not in data or not data["choices"]:
            return None

        choice = data["choices"][0]
        delta = choice.get("delta", {})
        finish = choice.get("finish_reason", "")

        chunk = StreamChunk(
            content=delta.get("content", ""),
            finish_reason=finish or "",
            usage=data.get("usage", {}),
        )

        # 流式 tool_calls：delta 里可能包含 tool_calls 片段
        if "tool_calls" in delta:
            for tc in delta["tool_calls"]:
                # 第一个 chunk 带 id 和 function.name
                if "id" in tc:
                    chunk.tool_call_id = tc["id"]
                if "function" in tc:
                    if "name" in tc["function"]:
                        chunk.tool_name = tc["function"]["name"]
                    if "arguments" in tc["function"]:
                        chunk.tool_args = tc["function"]["arguments"]

        return chunk

    def _parse_response(self, data: dict) -> LLMResponse:
        """解析 OpenAI 兼容的 response JSON"""
        choice = data["choices"][0]
        msg = choice["message"]

        content = msg.get("content")
        tool_calls = None

        if "tool_calls" in msg and msg["tool_calls"]:
            tool_calls = []
            for tc in msg["tool_calls"]:
                tool_calls.append(ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=json.loads(tc["function"]["arguments"]),
                ))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=data.get("usage", {}),
            model=data.get("model", ""),
        )

    def _sleep(self, attempt: int) -> None:
        """指数退避：1s, 2s, 4s, ..."""
        time.sleep(2 ** attempt)

    def close(self) -> None:
        self._client.close()
