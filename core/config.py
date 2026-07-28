"""统一配置加载与校验。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FrameworkConfig:
    """框架配置。

    所有配置项优先级：显式参数 > GMAF_* 环境变量 > 默认值。
    """

    api_key: str
    base_url: str
    model: str
    timeout: float = 60.0
    max_retries: int = 2
    context_window: int | None = None
    reserved_output_tokens: int | None = None
    provider: str = "openai-compatible"

    def __post_init__(self) -> None:
        """交叉字段校验。"""
        # 非空校验
        if not self.api_key:
            raise ValueError("api_key is required and cannot be empty")
        if not self.base_url:
            raise ValueError("base_url is required and cannot be empty")
        if not self.model:
            raise ValueError("model is required and cannot be empty")

        # 数值范围校验
        if self.timeout <= 0:
            raise ValueError(f"timeout must be positive, got {self.timeout}")
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be non-negative, got {self.max_retries}")

        # context_window 和 reserved_output_tokens 必须同时提供
        if (self.context_window is None) != (self.reserved_output_tokens is None):
            raise ValueError(
                "context_window and reserved_output_tokens must be both set or both unset"
            )

        # context_window 必须大于 reserved_output_tokens
        if (
            self.context_window is not None
            and self.reserved_output_tokens is not None
            and self.context_window <= self.reserved_output_tokens
        ):
            raise ValueError(
                f"context_window ({self.context_window}) must be greater than "
                f"reserved_output_tokens ({self.reserved_output_tokens})"
            )

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> FrameworkConfig:
        """从环境变量和显式参数创建配置。

        优先级：显式参数 > GMAF_* 环境变量 > 默认值。

        Args:
            environ: 环境变量映射，None 表示使用 os.environ
            **overrides: 显式参数，优先级最高

        Returns:
            FrameworkConfig 实例

        Raises:
            ValueError: 配置校验失败
        """
        env = environ if environ is not None else os.environ

        # 辅助函数：获取配置值
        def get_value(name: str, env_key: str, default: Any) -> Any:
            # 最高优先级：显式参数
            if name in overrides:
                return overrides[name]
            # 次优先级：环境变量
            env_value = env.get(env_key, "")
            if env_value:
                # 类型转换
                if name in ("timeout",):
                    try:
                        return float(env_value)
                    except ValueError:
                        raise ValueError(
                            f"invalid value for {env_key}: {env_value!r}"
                        )
                elif name in ("max_retries", "context_window", "reserved_output_tokens"):
                    try:
                        return int(env_value)
                    except ValueError:
                        raise ValueError(
                            f"invalid value for {env_key}: {env_value!r}"
                        )
                else:
                    return env_value
            # 最低优先级：默认值
            return default

        # 获取所有配置值
        api_key = get_value("api_key", "GMAF_API_KEY", "")
        base_url = get_value("base_url", "GMAF_BASE_URL", "https://api.openai.com/v1")
        model = get_value("model", "GMAF_MODEL", "gpt-3.5-turbo")
        timeout = get_value("timeout", "GMAF_TIMEOUT", 60.0)
        max_retries = get_value("max_retries", "GMAF_MAX_RETRIES", 2)
        context_window = get_value("context_window", "GMAF_CONTEXT_WINDOW", None)
        reserved_output_tokens = get_value(
            "reserved_output_tokens", "GMAF_RESERVED_OUTPUT_TOKENS", None
        )
        provider = get_value("provider", "GMAF_PROVIDER", "openai-compatible")

        # 构造配置对象（在 __post_init__ 中进行校验）
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            context_window=context_window,
            reserved_output_tokens=reserved_output_tokens,
            provider=provider,
        )