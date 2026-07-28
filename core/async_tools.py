"""异步工具注册与执行，支持 timeout 和取消传播。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Iterable
from typing import Any

from .tools import (
    Tool,
    ToolAuthorizationPolicy,
    ToolAuthorizationRequest,
    ToolExecutionResult,
    ToolRegistry,
    _serialize_result,
)


class AsyncToolRegistry:
    """异步工具注册与执行，支持 timeout 和取消传播。

    - async callable 直接 await
    - sync callable 通过 asyncio.to_thread 执行
    - timeout 返回 tool_timeout 错误，取消原样传播
    - 授权检查发生在任务创建前
    """

    def __init__(
        self,
        tools: Iterable[Tool | Callable[..., Any]] = (),
        *,
        authorization_policy: ToolAuthorizationPolicy | None = None,
        default_timeout: float | None = None,
    ) -> None:
        self._registry = ToolRegistry(tools, authorization_policy=authorization_policy)
        self.default_timeout = default_timeout

    def register(self, value: Tool | Callable[..., Any], **kwargs: Any) -> Tool:
        """注册工具。"""
        return self._registry.register(value, **kwargs)

    def get(self, name: str) -> Tool | None:
        """获取工具。"""
        return self._registry.get(name)

    def list(self) -> list[Tool]:
        """列出所有工具。"""
        return self._registry.list()

    def schemas(self) -> list[dict[str, Any]]:
        """返回所有工具的 OpenAI schema。"""
        return self._registry.schemas()

    async def execute_async(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolExecutionResult:
        """异步执行工具。

        - 未知工具返回 unknown_tool
        - 无效参数返回 invalid_arguments
        - 授权拒绝返回 permission_denied
        - timeout 返回 tool_timeout
        - 取消原样传播 CancelledError
        """
        registered = self.get(name)
        if registered is None:
            return ToolExecutionResult(
                content=f"unknown tool: {name}",
                error_code="unknown_tool",
            )

        # 参数绑定校验
        try:
            inspect.signature(registered.func).bind(**arguments)
        except TypeError as exc:
            return ToolExecutionResult(
                content=f"invalid arguments for tool '{name}': {exc}",
                error_code="invalid_arguments",
            )

        # 授权检查
        policy = self._registry._policy
        if policy is not None:
            request = ToolAuthorizationRequest(name=name, arguments=dict(arguments))
            try:
                decision = policy.authorize(request)
            except Exception:
                return ToolExecutionResult(
                    content="authorization error",
                    error_code="authorization_error",
                )
            if not decision.allowed:
                return ToolExecutionResult(
                    content="permission denied",
                    error_code="permission_denied",
                )

        # 执行工具
        timeout_seconds = self.default_timeout
        func = registered.func
        is_async = inspect.iscoroutinefunction(func)

        try:
            if timeout_seconds is not None:
                async with asyncio.timeout(timeout_seconds):
                    if is_async:
                        result = await func(**arguments)
                    else:
                        result = await asyncio.to_thread(func, **arguments)
            else:
                if is_async:
                    result = await func(**arguments)
                else:
                    result = await asyncio.to_thread(func, **arguments)
        except TimeoutError:
            return ToolExecutionResult(
                content="tool execution timed out",
                error_code="tool_timeout",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return ToolExecutionResult(
                content=f"tool execution failed: {type(exc).__name__}: {exc}",
                error_code="execution_failed",
            )

        return _serialize_result(result)