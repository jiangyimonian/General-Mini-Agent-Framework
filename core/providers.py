"""模型提供商能力声明与请求适配器。

适配器只转换模型 HTTP payload，不执行工具、不管理 Agent 状态、不读取环境变量。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ProviderCapabilities:
    """模型提供商能力声明。"""

    supports_tools: bool = True
    supports_streaming: bool = True
    supports_stream_usage: bool = False
    supports_parallel_tool_calls: bool = True


class ModelCapabilityError(RuntimeError):
    """请求使用的功能不被当前模型提供商支持。"""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        capability: str = "",
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.capability = capability


@runtime_checkable
class ProviderAdapter(Protocol):
    """提供商适配器协议。"""

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def prepare_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """准备请求数据，验证能力并转换 payload。

        Args:
            payload: 原始请求 payload

        Returns:
            转换后的 payload（深拷贝）

        Raises:
            ModelCapabilityError: 如果请求使用的功能不被支持
        """
        ...

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        """规范化响应数据。

        Args:
            payload: 原始响应 payload

        Returns:
            规范化后的 payload（深拷贝）
        """
        ...


class OpenAICompatibleAdapter:
    """OpenAI 兼容模型的默认适配器。

    保持标准 payload 格式，不修改请求和响应结构。
    """

    def __init__(self) -> None:
        self._capabilities = ProviderCapabilities()

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def prepare_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        # 验证能力
        if not self._capabilities.supports_tools and "tools" in payload:
            raise ModelCapabilityError(
                f"{self.__class__.__name__} does not support tools",
                provider=self.__class__.__name__,
                capability="supports_tools",
            )

        if not self._capabilities.supports_streaming and payload.get("stream"):
            raise ModelCapabilityError(
                f"{self.__class__.__name__} does not support streaming",
                provider=self.__class__.__name__,
                capability="supports_streaming",
            )

        # 返回深拷贝以避免副作用
        return copy.deepcopy(payload)

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(payload)


class DeepSeekAdapter:
    """DeepSeek 模型适配器。

    处理 DeepSeek 特有的 stream usage 格式差异。
    """

    def __init__(self) -> None:
        self._capabilities = ProviderCapabilities(
            supports_tools=True,
            supports_streaming=True,
            supports_stream_usage=True,
            supports_parallel_tool_calls=True,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def prepare_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        # 验证能力
        if not self._capabilities.supports_tools and "tools" in payload:
            raise ModelCapabilityError(
                "DeepSeekAdapter does not support tools",
                provider="DeepSeekAdapter",
                capability="supports_tools",
            )

        if not self._capabilities.supports_streaming and payload.get("stream"):
            raise ModelCapabilityError(
                "DeepSeekAdapter does not support streaming",
                provider="DeepSeekAdapter",
                capability="supports_streaming",
            )

        # 深拷贝以避免修改原始数据
        result = copy.deepcopy(payload)

        # DeepSeek 需要在流式请求中显式启用 usage 统计
        if result.get("stream") and self._capabilities.supports_stream_usage:
            result.setdefault("stream_options", {})["include_usage"] = True

        return result

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        # DeepSeek 的响应格式与 OpenAI 兼容，直接返回深拷贝
        return copy.deepcopy(payload)