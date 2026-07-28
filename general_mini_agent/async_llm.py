"""OpenAI 兼容的异步 LLM 客户端。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

import httpx

from .llm import (
    LLMConfig,
    LLMResponse,
    ModelRequestError,
    StreamChunk,
    parse_response_payload,
    parse_stream_chunk_payload,
)


@runtime_checkable
class AsyncChatModel(Protocol):
    """异步 Chat Model 协议。"""

    async def chat_async(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...


@runtime_checkable
class AsyncStreamingChatModel(AsyncChatModel, Protocol):
    """异步流式 Chat Model 协议。"""

    def chat_stream_async(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]: ...


class AsyncLLM:
    """异步 LLM 调用封装，通过 httpx AsyncClient 直调 API。"""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig()
        if not self.config.api_key:
            raise ValueError("api_key 未设置，请通过 LLMConfig 传入")
        self._client: httpx.AsyncClient | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        """确保客户端已创建。"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def chat_async(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """异步调用 LLM，支持 function calling。"""
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            body["tools"] = tools

        client = self._ensure_client()
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries):
            try:
                resp = await client.post("/chat/completions", json=body)
                resp.raise_for_status()
                data = resp.json()
                return parse_response_payload(data)

            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code in (429, 502, 503, 504):
                    await self._async_sleep(attempt)
                    continue
                raise ModelRequestError(
                    "model request returned an HTTP error",
                    status_code=exc.response.status_code,
                    endpoint="/chat/completions",
                ) from exc
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_error = exc
                await self._async_sleep(attempt)
                continue
            except httpx.TransportError as exc:
                # 让 CancelledError 原样传播
                if isinstance(exc, asyncio.CancelledError):
                    raise
                last_error = exc
                await self._async_sleep(attempt)
                continue

        raise ModelRequestError(
            "model request failed after retries",
            endpoint="/chat/completions",
        ) from last_error

    def chat_stream_async(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """异步流式调用 LLM，逐 chunk yield StreamChunk。"""
        return self._chat_stream_async_impl(messages, tools)

    async def _chat_stream_async_impl(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[StreamChunk]:
        """异步流式响应生成器实现。"""
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

        client = self._ensure_client()
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries):
            yielded_chunk = False
            try:
                async with client.stream("POST", "/chat/completions", json=body) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or line.startswith(":") or not line.startswith("data:"):
                            continue
                        data_str = line[5:]
                        if data_str.startswith(" "):
                            data_str = data_str[1:]
                        if data_str == "[DONE]":
                            return
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
                    await self._async_sleep(attempt)
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
                # 让 CancelledError 原样传播
                if isinstance(exc, asyncio.CancelledError):
                    raise
                last_error = exc
                if yielded_chunk:
                    raise ModelRequestError(
                        "model streaming request failed",
                        endpoint="/chat/completions",
                    ) from exc
                await self._async_sleep(attempt)
                continue

        raise ModelRequestError(
            "model request failed after retries",
            endpoint="/chat/completions",
        ) from last_error

    async def _async_sleep(self, attempt: int) -> None:
        """异步指数退避：1s, 2s, 4s, ..."""
        await asyncio.sleep(2 ** attempt)

    async def aclose(self) -> None:
        """关闭异步客户端。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> AsyncLLM:
        """异步上下文管理器入口。"""
        self._ensure_client()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """异步上下文管理器出口。"""
        await self.aclose()