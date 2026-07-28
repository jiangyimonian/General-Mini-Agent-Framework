"""安全日志接口。

库日志不包含消息正文、工具参数、长期记忆正文、认证头或 API Key。
"""

from __future__ import annotations

import logging
from typing import Any


def get_logger(name: str) -> logging.Logger:
    """获取以 general_mini_agent 为前缀的 logger。

    Logger 只添加 NullHandler，不配置根 logger、handler 或全局日志级别。

    Args:
        name: logger 名称后缀

    Returns:
        logging.Logger 实例
    """
    # 确保 logger 名称以 general_mini_agent 开头
    if not name.startswith("general_mini_agent"):
        full_name = f"general_mini_agent.{name}"
    else:
        full_name = name

    logger = logging.getLogger(full_name)

    # 只添加 NullHandler，不配置其他 handler 或 formatter
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    return logger


def safe_log_fields(
    *,
    run_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    error_code: str | None = None,
    elapsed_ms: float | None = None,
) -> dict[str, str | float]:
    """构建安全日志字段字典。

    只包含允许列表中的字段，排除敏感信息（API Key、消息正文、工具参数等）。

    Args:
        run_id: 运行 ID
        provider: 模型提供商
        model: 模型名称
        error_code: 错误代码
        elapsed_ms: 耗时（毫秒）

    Returns:
        包含非空字段的字典
    """
    fields: dict[str, str | float] = {}

    if run_id is not None:
        fields["run_id"] = run_id
    if provider is not None:
        fields["provider"] = provider
    if model is not None:
        fields["model"] = model
    if error_code is not None:
        fields["error_code"] = error_code
    if elapsed_ms is not None:
        fields["elapsed_ms"] = elapsed_ms

    return fields