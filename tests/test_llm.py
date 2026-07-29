"""测试 LLM 层（响应解析逻辑，不依赖真实 API）"""

import json
from collections.abc import Iterator
from unittest.mock import Mock

import httpx
import pytest

import general_mini_agent.llm as llm_module
from general_mini_agent import StreamChunk, StreamingChatModel, ToolCallDelta
from general_mini_agent.llm import (
    LLM,
    LLMConfig,
    LLMResponse,
    ModelRequestError,
    parse_response_payload,
)


def make_streaming_llm(
    payload: bytes,
    *,
    requests: list[httpx.Request] | None = None,
    max_retries: int = 1,
) -> LLM:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return httpx.Response(200, content=payload, request=request)

    llm = LLM(
        LLMConfig(
            api_key="test-key",
            base_url="https://example.test/v1",
            max_retries=max_retries,
        )
    )
    llm._client.close()
    llm._client = httpx.Client(
        base_url=llm.config.base_url,
        transport=httpx.MockTransport(handler),
    )
    return llm


class FailingAfterFirstChunk(httpx.SyncByteStream):
    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"first"},"finish_reason":null}]}\n\n'
        raise httpx.ReadError("sensitive transport detail")


def test_model_request_error_defaults_to_request_error_code() -> None:
    error = ModelRequestError("request failed")

    assert error.error_code == "model_request_error"


def test_model_request_error_accepts_protocol_error_code() -> None:
    error = ModelRequestError(
        "invalid model stream",
        error_code="stream_protocol_error",
    )

    assert error.error_code == "stream_protocol_error"


def test_stream_chunk_exposes_indexed_tool_call_deltas() -> None:
    chunk = StreamChunk(
        content="thinking",
        tool_calls=[
            ToolCallDelta(index=1, id="call_2", name="add", arguments='{"a":'),
        ],
        finish_reason="tool_calls",
        usage={"total_tokens": 4},
    )

    assert chunk.tool_calls[0].index == 1
    assert chunk.tool_calls[0].arguments == '{"a":'


def test_streaming_chat_model_runtime_protocol_requires_both_paths() -> None:
    class CompleteModel:
        def chat(self, messages, *, tools=None) -> LLMResponse:
            return LLMResponse(content="ok", tool_calls=None)

        def chat_stream(self, messages, *, tools=None) -> Iterator[StreamChunk]:
            yield StreamChunk(content="ok", finish_reason="stop")

    assert isinstance(CompleteModel(), StreamingChatModel)


def test_chat_stream_parses_interleaved_tool_calls_and_usage() -> None:
    requests: list[httpx.Request] = []
    llm = make_streaming_llm(
        b": keep-alive\n\n"
        b'data:{"choices":[{"delta":{"tool_calls":['
        b'{"index":1,"id":"c2","function":{"name":"multiply","arguments":"{\\"a\\":"}},'
        b'{"index":0,"id":"c1","function":{"name":"add","arguments":"{\\"a\\":"}}'
        b']},"finish_reason":null}]}\n\n'
        b'data: {"choices":[{"delta":{"tool_calls":['
        b'{"index":0,"function":{"arguments":"1}"}},'
        b'{"index":1,"function":{"arguments":"2}"}}'
        b']},"finish_reason":"tool_calls"}]}\n\n'
        b'data: {"choices":[],"usage":{"prompt_tokens":3,"total_tokens":5}}\n\n'
        b"data: [DONE]\n\n",
        requests=requests,
    )

    chunks = list(llm.chat_stream([]))

    assert [delta.index for delta in chunks[0].tool_calls] == [1, 0]
    assert chunks[1].finish_reason == "tool_calls"
    assert chunks[2].usage == {"prompt_tokens": 3, "total_tokens": 5}
    request_body = json.loads(requests[0].content)
    assert request_body["stream_options"] == {"include_usage": True}


def test_chat_stream_rejects_tool_call_without_integer_index() -> None:
    llm = make_streaming_llm(
        b'data: {"choices":[{"delta":{"tool_calls":['
        b'{"id":"c1","function":{"name":"add","arguments":"{}"}}'
        b']},"finish_reason":"tool_calls"}]}\n\n'
    )

    with pytest.raises(ModelRequestError) as exc_info:
        list(llm.chat_stream([]))

    assert exc_info.value.error_code == "stream_protocol_error"


def test_chat_stream_rejects_non_json_data_without_retrying() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"data: not-json\n\n", request=request)

    llm = LLM(
        LLMConfig(
            api_key="test-key",
            base_url="https://example.test/v1",
            max_retries=3,
        )
    )
    llm._client.close()
    llm._client = httpx.Client(
        base_url=llm.config.base_url,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelRequestError) as exc_info:
        list(llm.chat_stream([]))

    assert exc_info.value.error_code == "stream_protocol_error"
    assert str(exc_info.value) == "invalid JSON in model stream"
    assert calls == 1


def test_chat_stream_does_not_retry_after_yielding_output() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=FailingAfterFirstChunk(), request=request)

    llm = LLM(
        LLMConfig(
            api_key="test-key",
            base_url="https://example.test/v1",
            max_retries=3,
        )
    )
    llm._client.close()
    llm._client = httpx.Client(
        base_url=llm.config.base_url,
        transport=httpx.MockTransport(handler),
    )
    stream = llm.chat_stream([])

    assert next(stream).content == "first"
    with pytest.raises(ModelRequestError, match="model streaming request failed"):
        next(stream)
    assert calls == 1


def test_model_request_error_sanitizes_authorization_values() -> None:
    error = llm_module.ModelRequestError(
        "request failed: Authorization: Bearer authorization-secret sk-live-secret",
        status_code=401,
        endpoint="/chat/completions",
    )

    assert error.status_code == 401
    assert error.endpoint == "/chat/completions"
    assert "authorization-secret" not in str(error)
    assert "sk-live-secret" not in str(error)


def test_llm_chat_accepts_tools_as_positional_argument() -> None:
    llm = LLM(LLMConfig(api_key="test-key"))
    response = Mock()
    response.json.return_value = {
        "choices": [{
            "message": {"content": "ok", "role": "assistant"},
            "finish_reason": "stop",
        }],
        "usage": {},
        "model": "test-model",
    }
    llm._client = Mock()
    llm._client.post.return_value = response

    result = llm.chat([], [])

    assert result.content == "ok"


def test_llm_chat_wraps_non_retryable_http_errors_without_sensitive_details() -> None:
    api_key = "test-api-key"
    request = httpx.Request(
        "POST",
        "https://example.test/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    response = httpx.Response(401, content="sensitive response body", request=request)
    llm = LLM(LLMConfig(api_key=api_key, max_retries=1))
    llm._client = Mock()
    llm._client.post.return_value = response

    with pytest.raises(ModelRequestError) as exc_info:
        llm.chat([])

    error = exc_info.value
    assert str(error) == "model request returned an HTTP error"
    assert error.status_code == 401
    assert error.endpoint == "/chat/completions"
    assert api_key not in str(error)
    assert "sensitive response body" not in str(error)
    assert "Authorization" not in str(error)


def test_llm_chat_wraps_exhausted_retryable_errors_without_sensitive_details() -> None:
    api_key = "test-api-key"
    request = httpx.Request(
        "POST",
        "https://example.test/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    response = httpx.Response(503, content="sensitive response body", request=request)
    llm = LLM(LLMConfig(api_key=api_key, max_retries=2))
    llm._client = Mock()
    llm._client.post.return_value = response
    llm._sleep = Mock()

    with pytest.raises(ModelRequestError) as exc_info:
        llm.chat([])

    error = exc_info.value
    assert str(error) == "model request failed after retries"
    assert error.status_code is None
    assert error.endpoint == "/chat/completions"
    assert api_key not in str(error)
    assert "sensitive response body" not in str(error)
    assert "Authorization" not in str(error)
    assert llm._sleep.call_count == 2
    assert llm._client.post.call_count == 2


def test_llm_chat_retries_retryable_http_error_then_returns_response() -> None:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    retryable_response = httpx.Response(503, request=request)
    success_response = Mock()
    success_response.json.return_value = {
        "choices": [{
            "message": {"content": "ok", "role": "assistant"},
            "finish_reason": "stop",
        }],
        "usage": {},
        "model": "test-model",
    }
    llm = LLM(LLMConfig(api_key="test-api-key", max_retries=2))
    llm._client = Mock()
    llm._client.post.side_effect = [retryable_response, success_response]
    llm._sleep = Mock()

    result = llm.chat([])

    assert result.content == "ok"
    assert llm._client.post.call_count == 2
    assert llm._sleep.call_count == 1


def test_llm_chat_stream_wraps_non_retryable_http_errors() -> None:
    api_key = "test-api-key"
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, content="sensitive response body", request=request)

    llm = LLM(LLMConfig(api_key=api_key, base_url="https://example.test/v1", max_retries=1))
    llm._client.close()
    llm._client = httpx.Client(base_url=llm.config.base_url, transport=httpx.MockTransport(handler))

    with pytest.raises(ModelRequestError) as exc_info:
        list(llm.chat_stream([]))

    error = exc_info.value
    assert str(error) == "model request returned an HTTP error"
    assert error.status_code == 401
    assert error.endpoint == "/chat/completions"
    assert api_key not in str(error)
    assert "sensitive response body" not in str(error)
    assert len(calls) == 1


def test_llm_chat_stream_wraps_exhausted_retryable_http_errors() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, request=request)

    llm = LLM(
        LLMConfig(api_key="test-api-key", base_url="https://example.test/v1", max_retries=2),
    )
    llm._client.close()
    llm._client = httpx.Client(base_url=llm.config.base_url, transport=httpx.MockTransport(handler))
    llm._sleep = Mock()

    with pytest.raises(ModelRequestError) as exc_info:
        list(llm.chat_stream([]))

    error = exc_info.value
    assert str(error) == "model request failed after retries"
    assert error.status_code is None
    assert error.endpoint == "/chat/completions"
    assert len(calls) == 2
    assert llm._sleep.call_count == 2


def test_llm_chat_stream_retries_retryable_http_error_then_yields_chunks() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            content=(
                b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
                b"data: [DONE]\n\n"
            ),
            request=request,
        )

    llm = LLM(
        LLMConfig(api_key="test-api-key", base_url="https://example.test/v1", max_retries=2),
    )
    llm._client.close()
    llm._client = httpx.Client(base_url=llm.config.base_url, transport=httpx.MockTransport(handler))
    llm._sleep = Mock()

    chunks = list(llm.chat_stream([]))

    assert [chunk.content for chunk in chunks] == ["ok"]
    assert len(calls) == 2
    assert llm._sleep.call_count == 1


class TestLLMResponseParsing:
    """测试 parse_response_payload 的 JSON 解析逻辑"""

    def test_text_response(self):
        data = {
            "choices": [{
                "message": {"content": "你好！", "role": "assistant"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "deepseek-chat",
        }
        resp = parse_response_payload(data)
        assert resp.content == "你好！"
        assert resp.tool_calls is None
        assert resp.usage["total_tokens"] == 15

    def test_tool_call_response(self):
        data = {
            "choices": [{
                "message": {
                    "content": "我需要计算",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "calculate",
                            "arguments": json.dumps({"expression": "3 + 5"}),
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {},
            "model": "deepseek-chat",
        }
        resp = parse_response_payload(data)
        assert resp.content == "我需要计算"
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "calculate"
        assert resp.tool_calls[0].arguments == {"expression": "3 + 5"}

    def test_multiple_tool_calls(self):
        data = {
            "choices": [{
                "message": {
                    "content": "同时计算多个",
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "add", "arguments": '{"a":1,"b":2}'},
                        },
                        {
                            "id": "c2",
                            "type": "function",
                            "function": {"name": "multiply", "arguments": '{"a":3,"b":4}'},
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {},
            "model": "deepseek-chat",
        }
        resp = parse_response_payload(data)
        assert len(resp.tool_calls) == 2
        assert resp.tool_calls[0].name == "add"
        assert resp.tool_calls[1].name == "multiply"

    def test_no_content_no_tool_calls(self):
        """极少数情况：LLM 返回空消息"""
        data = {
            "choices": [{
                "message": {"role": "assistant"},
                "finish_reason": "stop",
            }],
            "usage": {},
            "model": "deepseek-chat",
        }
        resp = parse_response_payload(data)
        assert resp.content is None
        assert resp.tool_calls is None

    def test_empty_tool_calls_list(self):
        """工具调用列表为空"""
        data = {
            "choices": [{
                "message": {
                    "content": "好的",
                    "role": "assistant",
                    "tool_calls": [],
                },
                "finish_reason": "stop",
            }],
            "usage": {},
            "model": "deepseek-chat",
        }
        resp = parse_response_payload(data)
        assert resp.content == "好的"
        assert resp.tool_calls is None


class TestLLMInit:
    def test_missing_api_key(self):
        with pytest.raises(ValueError, match="api_key"):
            LLM(LLMConfig(api_key=""))

    def test_custom_config(self):
        config = LLMConfig(
            api_key="sk-test",
            base_url="https://custom.com/v1",
            model="custom-model",
            temperature=0.5,
        )
        llm = LLM(config)
        assert llm.config.model == "custom-model"
        assert llm.config.temperature == 0.5


class TestModelResponseContract:
    """测试模型响应契约：保留 finish_reason 和原始工具参数"""

    def test_parse_response_payload_preserves_finish_reason_and_raw_arguments(self):
        """解析响应负载时保留 finish_reason 和原始参数"""
        response = parse_response_payload({
            "choices": [{
                "message": {"content": "use tool", "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {"name": "lookup", "arguments": '{"q":"x"}'},
                }]},
                "finish_reason": "tool_calls",
            }],
        })
        assert response.finish_reason == "tool_calls"
        assert response.tool_calls[0].arguments == {"q": "x"}
        assert response.tool_calls[0].raw_arguments == '{"q":"x"}'

    @pytest.mark.parametrize("raw", ['{"q":', '[1, 2]'])
    def test_invalid_tool_arguments_are_retained(self, raw):
        """无效的工具参数被保留"""
        response = parse_response_payload({
            "choices": [{
                "message": {"content": None, "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {"name": "lookup", "arguments": raw},
                }]},
                "finish_reason": "tool_calls",
            }],
        })
        call = response.tool_calls[0]
        assert call.arguments is None
        assert call.raw_arguments == raw
        assert call.argument_error

    def test_legacy_llm_response_constructor_remains_valid(self):
        """遗留的 LLMResponse 构造函数保持有效"""
        assert LLMResponse(content="ok", tool_calls=None).finish_reason == ""
