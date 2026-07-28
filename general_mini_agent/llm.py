"""OpenAI 兼容的同步与流式 LLM 客户端。"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import httpx


@runtime_checkable
class ChatModel(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...


class ModelRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        endpoint: str = "",
        error_code: Literal[
            "model_request_error", "stream_protocol_error"
        ] = "model_request_error",
    ) -> None:
        super().__init__(self._sanitize(message))
        self.status_code = status_code
        self.endpoint = endpoint
        self.error_code = error_code

    @staticmethod
    def _sanitize(message: str) -> str:
        sanitized = re.sub(
            r"(?i)(authorization\s*:\s*(?:bearer\s+)?)\S+",
            r"\1[REDACTED]",
            message,
        )
        return re.sub(r"\bsk-[A-Za-z0-9_-]+\b", "[REDACTED]", sanitized)


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


@dataclass(frozen=True)
class ToolCallDelta:
    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class StreamChunk:
    """流式响应的单个 chunk"""
    content: str = ""
    tool_calls: list[ToolCallDelta] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)


@runtime_checkable
class StreamingChatModel(ChatModel, Protocol):
    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamChunk]: ...


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


# ─── 纯解析函数（同步/异步共用）───────────────────────────────


def parse_response_payload(data: dict[str, Any]) -> LLMResponse:
    """解析 OpenAI 兼容的 response JSON（纯函数，不依赖实例状态）。"""
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


def parse_stream_chunk_payload(data: dict[str, Any]) -> StreamChunk | None:
    """解析单个 SSE data chunk（纯函数，不依赖实例状态）。

    返回 None 表示只有 usage 或空 chunk。
    抛出 ModelRequestError 表示协议错误。
    """
    usage = data.get("usage") or {}
    choices = data.get("choices") or []
    if not choices:
        return StreamChunk(usage=usage) if usage else None

    choice = choices[0]
    delta = choice.get("delta") or {}
    tool_calls: list[ToolCallDelta] = []
    for raw_call in delta.get("tool_calls") or []:
        index = raw_call.get("index")
        if not isinstance(index, int):
            raise ModelRequestError(
                "model stream tool call is missing an integer index",
                endpoint="/chat/completions",
                error_code="stream_protocol_error",
            )
        function = raw_call.get("function") or {}
        tool_calls.append(
            ToolCallDelta(
                index=index,
                id=raw_call.get("id") or "",
                name=function.get("name") or "",
                arguments=function.get("arguments") or "",
            )
        )

    return StreamChunk(
        content=delta.get("content") or "",
        tool_calls=tool_calls,
        finish_reason=choice.get("finish_reason") or "",
        usage=usage,
    )


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
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
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
                return parse_response_payload(data)

            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code in (429, 502, 503, 504):
                    self._sleep(attempt)
                    continue
                raise ModelRequestError(
                    "model request returned an HTTP error",
                    status_code=exc.response.status_code,
                    endpoint="/chat/completions",
                ) from exc
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_error = exc
                self._sleep(attempt)
                continue

        raise ModelRequestError(
            "model request failed after retries",
            endpoint="/chat/completions",
        ) from last_error

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamChunk]:
        """流式调用 LLM，逐 chunk yield StreamChunk"""
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = tools

        last_error: Exception | None = None
        for attempt in range(self.config.max_retries):
            yielded_chunk = False
            try:
                with self._client.stream("POST", "/chat/completions", json=body) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line or line.startswith(":") or not line.startswith("data:"):
                            continue
                        data_str = line[5:]
                        if data_str.startswith(" "):
                            data_str = data_str[1:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError as exc:
                            raise ModelRequestError(
                                "invalid JSON in model stream",
                                endpoint="/chat/completions",
                                error_code="stream_protocol_error",
                            ) from exc

                        chunk = parse_stream_chunk_payload(data)
                        if chunk is not None:
                            yielded_chunk = True
                            yield chunk
                return
            except ModelRequestError:
                raise
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if not yielded_chunk and exc.response.status_code in (429, 502, 503, 504):
                    self._sleep(attempt)
                    continue
                if yielded_chunk:
                    raise ModelRequestError(
                        "model streaming request failed",
                        endpoint="/chat/completions",
                    ) from exc
                raise ModelRequestError(
                    "model request returned an HTTP error",
                    status_code=exc.response.status_code,
                    endpoint="/chat/completions",
                ) from exc
            except httpx.TransportError as exc:
                last_error = exc
                if yielded_chunk:
                    raise ModelRequestError(
                        "model streaming request failed",
                        endpoint="/chat/completions",
                    ) from exc
                self._sleep(attempt)
                continue
        raise ModelRequestError(
            "model request failed after retries",
            endpoint="/chat/completions",
        ) from last_error

    def _sleep(self, attempt: int) -> None:
        """指数退避：1s, 2s, 4s, ..."""
        time.sleep(2 ** attempt)

    def close(self) -> None:
        self._client.close()
