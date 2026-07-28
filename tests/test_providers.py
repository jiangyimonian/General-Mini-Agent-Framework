"""测试 ProviderCapabilities 和 ProviderAdapter。"""

import copy

import pytest

from core.providers import (
    DeepSeekAdapter,
    ModelCapabilityError,
    OpenAICompatibleAdapter,
    ProviderAdapter,
    ProviderCapabilities,
)


class TestProviderCapabilities:
    """测试 ProviderCapabilities 数据类。"""

    def test_default_capabilities_are_openai_compatible(self) -> None:
        """默认能力应该与 OpenAPI 兼容模型匹配。"""
        caps = ProviderCapabilities()

        assert caps.supports_tools is True
        assert caps.supports_streaming is True
        assert caps.supports_stream_usage is False
        assert caps.supports_parallel_tool_calls is True

    def test_capabilities_are_frozen(self) -> None:
        """能力对象应该是不可变的。"""
        caps = ProviderCapabilities()

        with pytest.raises(AttributeError):
            caps.supports_tools = False  # type: ignore[misc]

    def test_capabilities_can_be_customized(self) -> None:
        """可以创建自定义能力配置。"""
        caps = ProviderCapabilities(
            supports_tools=False,
            supports_streaming=False,
            supports_stream_usage=True,
            supports_parallel_tool_calls=False,
        )

        assert caps.supports_tools is False
        assert caps.supports_streaming is False
        assert caps.supports_stream_usage is True
        assert caps.supports_parallel_tool_calls is False


class TestProviderAdapterProtocol:
    """测试 ProviderAdapter 协议。"""

    def test_openai_adapter_implements_protocol(self) -> None:
        """OpenAICompatibleAdapter 实现了 ProviderAdapter 协议。"""
        adapter = OpenAICompatibleAdapter()
        assert isinstance(adapter, ProviderAdapter)

    def test_deepseek_adapter_implements_protocol(self) -> None:
        """DeepSeekAdapter 实现了 ProviderAdapter 协议。"""
        adapter = DeepSeekAdapter()
        assert isinstance(adapter, ProviderAdapter)


class TestDefensiveCopying:
    """测试防御性复制：输入字典在调用后不变，输出不共享嵌套引用。"""

    def test_openai_adapter_prepare_request_does_not_mutate_input(self) -> None:
        """OpenAICompatibleAdapter 不应该修改输入 payload。"""
        adapter = OpenAICompatibleAdapter()
        original_payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [{"type": "function", "function": {"name": "add"}}],
        }
        original_copy = copy.deepcopy(original_payload)

        result = adapter.prepare_request(original_payload)

        # 输入不变
        assert original_payload == original_copy
        # 输出是深拷贝
        assert result == original_payload
        assert result is not original_payload
        assert result["messages"] is not original_payload["messages"]
        assert result["tools"] is not original_payload["tools"]

    def test_openai_adapter_normalize_response_does_not_mutate_input(self) -> None:
        """OpenAICompatibleAdapter 不应该修改输入响应。"""
        adapter = OpenAICompatibleAdapter()
        original_response = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 10},
        }
        original_copy = copy.deepcopy(original_response)

        result = adapter.normalize_response(original_response)

        # 输入不变
        assert original_response == original_copy
        # 输出是深拷贝
        assert result == original_response
        assert result is not original_response
        assert result["choices"] is not original_response["choices"]

    def test_deepseek_adapter_prepare_request_does_not_mutate_input(self) -> None:
        """DeepSeekAdapter 不应该修改输入 payload。"""
        adapter = DeepSeekAdapter()
        original_payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        }
        original_copy = copy.deepcopy(original_payload)

        result = adapter.prepare_request(original_payload)

        # 输入不变
        assert original_payload == original_copy
        # 输出是深拷贝
        assert result is not original_payload
        assert result["messages"] is not original_payload["messages"]

    def test_deepseek_adapter_normalize_response_does_not_mutate_input(self) -> None:
        """DeepSeekAdapter 不应该修改输入响应。"""
        adapter = DeepSeekAdapter()
        original_response = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 10},
        }
        original_copy = copy.deepcopy(original_response)

        result = adapter.normalize_response(original_response)

        # 输入不变
        assert original_response == original_copy
        # 输出是深拷贝
        assert result == original_response
        assert result is not original_response


class TestUnsupportedCapabilities:
    """测试不支持能力时必须在网络请求前抛出 ModelCapabilityError。"""

    def test_adapter_without_tools_raises_before_request(self) -> None:
        """不支持 tools 的适配器在 prepare_request 中应该抛出错误。"""

        # 创建一个不支持 tools 的适配器
        class NoToolsAdapter:
            def __init__(self) -> None:
                self._capabilities = ProviderCapabilities(supports_tools=False)

            @property
            def capabilities(self) -> ProviderCapabilities:
                return self._capabilities

            def prepare_request(self, payload: dict) -> dict:
                if not self._capabilities.supports_tools and "tools" in payload:
                    raise ModelCapabilityError(
                        "NoToolsAdapter does not support tools",
                        provider="NoToolsAdapter",
                        capability="supports_tools",
                    )
                return copy.deepcopy(payload)

            def normalize_response(self, payload: dict) -> dict:
                return copy.deepcopy(payload)

        adapter = NoToolsAdapter()

        with pytest.raises(ModelCapabilityError) as exc_info:
            adapter.prepare_request({
                "model": "test",
                "messages": [],
                "tools": [{"type": "function", "function": {"name": "add"}}],
            })

        assert exc_info.value.provider == "NoToolsAdapter"
        assert exc_info.value.capability == "supports_tools"

    def test_adapter_without_streaming_raises_before_request(self) -> None:
        """不支持 streaming 的适配器在 prepare_request 中应该抛出错误。"""

        class NoStreamingAdapter:
            def __init__(self) -> None:
                self._capabilities = ProviderCapabilities(supports_streaming=False)

            @property
            def capabilities(self) -> ProviderCapabilities:
                return self._capabilities

            def prepare_request(self, payload: dict) -> dict:
                if not self._capabilities.supports_streaming and payload.get("stream"):
                    raise ModelCapabilityError(
                        "NoStreamingAdapter does not support streaming",
                        provider="NoStreamingAdapter",
                        capability="supports_streaming",
                    )
                return copy.deepcopy(payload)

            def normalize_response(self, payload: dict) -> dict:
                return copy.deepcopy(payload)

        adapter = NoStreamingAdapter()

        with pytest.raises(ModelCapabilityError) as exc_info:
            adapter.prepare_request({
                "model": "test",
                "messages": [],
                "stream": True,
            })

        assert exc_info.value.provider == "NoStreamingAdapter"
        assert exc_info.value.capability == "supports_streaming"

    def test_openai_adapter_accepts_tools(self) -> None:
        """OpenAICompatibleAdapter 应该接受 tools。"""
        adapter = OpenAICompatibleAdapter()

        # 不应该抛出错误
        result = adapter.prepare_request({
            "model": "gpt-4",
            "messages": [],
            "tools": [{"type": "function", "function": {"name": "add"}}],
        })

        assert "tools" in result

    def test_openai_adapter_accepts_streaming(self) -> None:
        """OpenAICompatibleAdapter 应该接受 streaming。"""
        adapter = OpenAICompatibleAdapter()

        # 不应该抛出错误
        result = adapter.prepare_request({
            "model": "gpt-4",
            "messages": [],
            "stream": True,
        })

        assert result["stream"] is True


class TestDeepSeekAdapter:
    """测试 DeepSeek 适配器的特有行为。"""

    def test_deepseek_adapter_adds_stream_usage_option(self) -> None:
        """DeepSeek 流式请求应该自动添加 stream_options.include_usage。"""
        adapter = DeepSeekAdapter()

        result = adapter.prepare_request({
            "model": "deepseek-chat",
            "messages": [],
            "stream": True,
        })

        assert result["stream_options"] == {"include_usage": True}

    def test_deepseek_adapter_does_not_add_stream_usage_for_non_stream(self) -> None:
        """非流式请求不应该添加 stream_options。"""
        adapter = DeepSeekAdapter()

        result = adapter.prepare_request({
            "model": "deepseek-chat",
            "messages": [],
            "stream": False,
        })

        assert "stream_options" not in result

    def test_deepseek_adapter_preserves_existing_stream_options(self) -> None:
        """已有的 stream_options 应该被保留并合并。"""
        adapter = DeepSeekAdapter()

        result = adapter.prepare_request({
            "model": "deepseek-chat",
            "messages": [],
            "stream": True,
            "stream_options": {"custom_option": "value"},
        })

        assert result["stream_options"] == {
            "include_usage": True,
            "custom_option": "value",
        }

    def test_deepseek_adapter_supports_stream_usage(self) -> None:
        """DeepSeek 能力声明应该支持 stream_usage。"""
        adapter = DeepSeekAdapter()

        assert adapter.capabilities.supports_stream_usage is True

    def test_deepseek_adapter_accepts_tools(self) -> None:
        """DeepSeek 应该接受 tools。"""
        adapter = DeepSeekAdapter()

        # 不应该抛出错误
        result = adapter.prepare_request({
            "model": "deepseek-chat",
            "messages": [],
            "tools": [{"type": "function", "function": {"name": "add"}}],
        })

        assert "tools" in result


class TestAdapterBoundaries:
    """测试适配器边界：只转换 payload，不执行工具、不管理 Agent 状态、不读取环境变量。"""

    def test_adapter_does_not_execute_tools(self) -> None:
        """适配器不应该执行工具。"""
        adapter = OpenAICompatibleAdapter()

        payload = {
            "model": "test",
            "messages": [],
            "tools": [{"type": "function", "function": {"name": "dangerous_tool"}}],
        }

        # prepare_request 只应该返回 payload 的拷贝，不应该执行任何工具
        result = adapter.prepare_request(payload)

        assert result == payload
        # 不应该有任何副作用

    def test_adapter_does_not_read_environment_variables(self) -> None:
        """适配器不应该读取环境变量。"""
        import os

        # 设置一个环境变量
        os.environ["TEST_ADAPTER_VAR"] = "test_value"

        adapter = OpenAICompatibleAdapter()

        # 适配器构造和 prepare_request 不应该依赖环境变量
        payload = {"model": "test", "messages": []}
        result = adapter.prepare_request(payload)

        # 清理
        del os.environ["TEST_ADAPTER_VAR"]

        assert result == payload

    def test_adapter_does_not_manage_agent_state(self) -> None:
        """适配器不应该管理 Agent 状态。"""
        adapter = OpenAICompatibleAdapter()

        # 适配器不应该有任何 Agent 相关的状态
        assert not hasattr(adapter, "agent")
        assert not hasattr(adapter, "state")

        payload = {"model": "test", "messages": []}
        result = adapter.prepare_request(payload)

        # 输出不应该包含 Agent 状态
        assert "agent" not in result
        assert "state" not in result

    def test_adapter_preserves_unknown_response_fields(self) -> None:
        """适配器应该保留未知的响应字段。"""
        adapter = OpenAICompatibleAdapter()

        response = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 10},
            "custom_field": "custom_value",
            "experimental_data": {"key": "value"},
        }

        result = adapter.normalize_response(response)

        # 未知字段应该被保留
        assert result["custom_field"] == "custom_value"
        assert result["experimental_data"] == {"key": "value"}