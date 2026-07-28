"""测试异步 LLM 层（响应解析逻辑，不依赖真实 API）"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from core import StreamChunk
from core.llm import LLMConfig, LLMResponse, ModelRequestError


def make_async_llm(
    payload: bytes,
    *,
    requests: list[httpx.Request] | None = None,
    max_retries: int = 1,
):
    """创建使用 Mock transport 的 AsyncLLM 实例。"""
    from core.async_llm import AsyncLLM

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return httpx.Response(200, content=payload, request=request)

    llm = AsyncLLM(
        LLMConfig(
            api_key="test-key",
            base_url="https://example.test/v1",
            max_retries=max_retries,
        )
    )
    llm._client = httpx.AsyncClient(
        base_url=llm.config.base_url,
        transport=httpx.MockTransport(handler),
    )
    return llm


class TestAsyncChatModelProtocol:
    """测试 AsyncChatModel 协议。"""

    def test_async_chat_model_requires_chat_async(self) -> None:
        """AsyncChatModel 必须提供 chat_async 方法。"""
        from core.async_llm import AsyncChatModel

        class MinimalAsyncModel:
            async def chat_async(
                self,
                messages: list[dict[str, Any]],
                *,
                tools: list[dict[str, Any]] | None = None,
            ) -> LLMResponse:
                return LLMResponse(content="ok", tool_calls=None)

        assert isinstance(MinimalAsyncModel(), AsyncChatModel)

    def test_async_streaming_chat_model_requires_stream_async(self) -> None:
        """AsyncStreamingChatModel 必须提供 chat_stream_async 方法。"""
        from core.async_llm import AsyncStreamingChatModel

        class MinimalStreamingModel:
            async def chat_async(
                self,
                messages: list[dict[str, Any]],
                *,
                tools: list[dict[str, Any]] | None = None,
            ) -> LLMResponse:
                return LLMResponse(content="ok", tool_calls=None)

            def chat_stream_async(
                self,
                messages: list[dict[str, Any]],
                *,
                tools: list[dict[str, Any]] | None = None,
            ) -> AsyncIterator[StreamChunk]:
                async def gen():
                    yield StreamChunk(content="ok", finish_reason="stop")

                return gen()

        assert isinstance(MinimalStreamingModel(), AsyncStreamingChatModel)


class TestAsyncLLMTextResponse:
    """测试异步非流式文本响应。"""

    def test_chat_async_returns_text_response(self) -> None:
        """异步请求返回文本响应。"""
        llm = make_async_llm(
            b'{"choices":[{"message":{"content":"hello","role":"assistant"},'
            b'"finish_reason":"stop"}],"usage":{},"model":"test"}'
        )

        async def run():
            async with llm:
                result = await llm.chat_async([])
                assert result.content == "hello"
                assert result.tool_calls is None

        asyncio.run(run())

    def test_chat_async_uses_tools_parameter(self) -> None:
        """异步请求传递 tools 参数。"""
        requests: list[httpx.Request] = []
        llm = make_async_llm(
            b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],'
            b'"usage":{},"model":"test"}',
            requests=requests,
        )

        async def run():
            async with llm:
                await llm.chat_async(
                    [],
                    tools=[{"type": "function", "function": {"name": "add"}}],
                )

        asyncio.run(run())
        body = json.loads(requests[0].content)
        assert body["tools"] == [{"type": "function", "function": {"name": "add"}}]


class TestAsyncLLMToolResponse:
    """测试异步工具调用响应。"""

    def test_chat_async_returns_tool_calls(self) -> None:
        """异步请求返回工具调用。"""
        llm = make_async_llm(
            b'{"choices":[{"message":{"content":null,"role":"assistant",'
            b'"tool_calls":[{"id":"c1","type":"function",'
            b'"function":{"name":"add","arguments":"{\\"a\\":1}"}}]},'
            b'"finish_reason":"tool_calls"}],"usage":{},"model":"test"}'
        )

        async def run():
            async with llm:
                result = await llm.chat_async([])
                assert result.content is None
                assert result.tool_calls is not None
                assert len(result.tool_calls) == 1
                assert result.tool_calls[0].name == "add"
                assert result.tool_calls[0].arguments == {"a": 1}

        asyncio.run(run())

    def test_chat_async_returns_multiple_tool_calls(self) -> None:
        """异步请求返回多个工具调用。"""
        llm = make_async_llm(
            b'{"choices":[{"message":{"content":null,"role":"assistant",'
            b'"tool_calls":['
            b'{"id":"c1","type":"function","function":{"name":"add","arguments":"{}"}},'
            b'{"id":"c2","type":"function","function":{"name":"mul","arguments":"{}"}}'
            b']},"finish_reason":"tool_calls"}],"usage":{},"model":"test"}'
        )

        async def run():
            async with llm:
                result = await llm.chat_async([])
                assert result.tool_calls is not None
                assert len(result.tool_calls) == 2
                assert result.tool_calls[0].name == "add"
                assert result.tool_calls[1].name == "mul"

        asyncio.run(run())


class TestAsyncLLMStream:
    """测试异步流式响应。"""

    def test_chat_stream_async_yields_text_chunks(self) -> None:
        """异步流式请求返回文本 chunk。"""
        llm = make_async_llm(
            b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}\n\n'
            b"data: [DONE]\n\n"
        )

        async def run():
            async with llm:
                chunks = []
                async for chunk in llm.chat_stream_async([]):
                    chunks.append(chunk)
                assert len(chunks) == 1
                assert chunks[0].content == "hi"

        asyncio.run(run())

    def test_chat_stream_async_yields_interleaved_tool_calls(self) -> None:
        """异步流式请求返回交错的工具调用。"""
        llm = make_async_llm(
            b': keep-alive\n\n'
            b'data:{"choices":[{"delta":{"tool_calls":['
            b'{"index":1,"id":"c2","function":{"name":"multiply","arguments":"{\\"a\\":"}},'
            b'{"index":0,"id":"c1","function":{"name":"add","arguments":"{\\"a\\":"}}'
            b']},"finish_reason":null}]}\n\n'
            b'data: {"choices":[{"delta":{"tool_calls":['
            b'{"index":0,"function":{"arguments":"1}"}},'
            b'{"index":1,"function":{"arguments":"2}"}}'
            b']},"finish_reason":"tool_calls"}]}\n\n'
            b'data: {"choices":[],"usage":{"prompt_tokens":3,"total_tokens":5}}\n\n'
            b"data: [DONE]\n\n"
        )

        async def run():
            async with llm:
                chunks = []
                async for chunk in llm.chat_stream_async([]):
                    chunks.append(chunk)
                assert [delta.index for delta in chunks[0].tool_calls] == [1, 0]
                assert chunks[1].finish_reason == "tool_calls"
                assert chunks[2].usage == {"prompt_tokens": 3, "total_tokens": 5}

        asyncio.run(run())

    def test_chat_stream_async_rejects_tool_call_without_integer_index(self) -> None:
        """异步流式请求拒绝没有整数 index 的工具调用。"""
        llm = make_async_llm(
            b'data: {"choices":[{"delta":{"tool_calls":['
            b'{"id":"c1","function":{"name":"add","arguments":"{}"}}'
            b']},"finish_reason":"tool_calls"}]}\n\n'
        )

        async def run():
            async with llm:
                with pytest.raises(ModelRequestError) as exc_info:
                    async for _ in llm.chat_stream_async([]):
                        pass
                assert exc_info.value.error_code == "stream_protocol_error"

        asyncio.run(run())


class TestAsyncLLMRetry:
    """测试异步重试逻辑。"""

    def test_chat_async_retries_retryable_http_error(self) -> None:
        """异步请求重试可重试的 HTTP 错误。"""
        from core.async_llm import AsyncLLM

        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(503, request=request)
            return httpx.Response(
                200,
                content=b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],'
                b'"usage":{},"model":"test"}',
                request=request,
            )

        llm = AsyncLLM(
            LLMConfig(api_key="test-key", base_url="https://example.test/v1", max_retries=2)
        )
        llm._client = httpx.AsyncClient(
            base_url=llm.config.base_url,
            transport=httpx.MockTransport(handler),
        )

        async def run():
            async with llm:
                result = await llm.chat_async([])
                assert result.content == "ok"
                assert calls == 2

        asyncio.run(run())

    def test_chat_async_raises_after_exhausted_retries(self) -> None:
        """异步请求重试耗尽后抛出错误。"""
        from core.async_llm import AsyncLLM

        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(503, request=request)

        llm = AsyncLLM(
            LLMConfig(api_key="test-key", base_url="https://example.test/v1", max_retries=2)
        )
        llm._client = httpx.AsyncClient(
            base_url=llm.config.base_url,
            transport=httpx.MockTransport(handler),
        )

        async def run():
            async with llm:
                with pytest.raises(ModelRequestError) as exc_info:
                    await llm.chat_async([])
                assert "failed after retries" in str(exc_info.value)
                assert calls == 2

        asyncio.run(run())


class TestAsyncLLMCancellation:
    """测试异步取消传播。"""

    def test_chat_async_propagates_timeout_error(self) -> None:
        """异步请求传播超时错误。"""
        from core.async_llm import AsyncLLM

        def handler(request: httpx.Request) -> httpx.Response:
            # 模拟超时
            raise httpx.TimeoutException("request timed out")

        llm = AsyncLLM(
            LLMConfig(api_key="test-key", base_url="https://example.test/v1", max_retries=1)
        )
        llm._client = httpx.AsyncClient(
            base_url=llm.config.base_url,
            transport=httpx.MockTransport(handler),
        )

        async def run():
            async with llm:
                with pytest.raises(ModelRequestError, match="failed after retries"):
                    await llm.chat_async([])

        asyncio.run(run())


class TestAsyncLLMClientLifecycle:
    """测试异步客户端生命周期。"""

    def test_async_llm_context_manager_closes_client(self) -> None:
        """异步上下文管理器关闭客户端。"""
        from core.async_llm import AsyncLLM

        llm = AsyncLLM(LLMConfig(api_key="test-key"))

        async def run():
            async with llm:
                # 进入上下文后客户端已创建
                assert llm._client is not None
                assert not llm._client.is_closed
            # 退出上下文后客户端已关闭
            assert llm._client is None

        asyncio.run(run())

    def test_aclose_closes_client(self) -> None:
        """aclose 方法关闭客户端。"""
        from core.async_llm import AsyncLLM

        llm = AsyncLLM(LLMConfig(api_key="test-key"))

        async def run():
            # 先触发客户端创建
            llm._ensure_client()
            assert llm._client is not None
            await llm.aclose()
            assert llm._client is None

        asyncio.run(run())