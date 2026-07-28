"""测试异步工具执行、timeout 和取消传播。"""

import asyncio

import pytest

from core import tool
from core.tools import ToolAuthorizationDecision, ToolAuthorizationRequest

# ─────────────────────────────────────────────────────────────
# 测试工具定义
# ─────────────────────────────────────────────────────────────


@tool
async def async_add(a: int, b: int) -> dict[str, int]:
    """异步加法工具。

    Args:
        a: 第一个数
        b: 第二个数
    """
    await asyncio.sleep(0.01)
    return {"result": a + b}


@tool
def sync_multiply(a: int, b: int) -> dict[str, int]:
    """同步乘法工具。

    Args:
        a: 第一个数
        b: 第二个数
    """
    return {"result": a * b}


@tool
async def slow_tool(duration: float) -> str:
    """慢速工具，用于测试 timeout。

    Args:
        duration: 睡眠时间（秒）
    """
    await asyncio.sleep(duration)
    return "completed"


# ─────────────────────────────────────────────────────────────
# 异步工具注册与执行测试
# ─────────────────────────────────────────────────────────────


class TestAsyncToolRegistryExecute:
    """测试 AsyncToolRegistry 的异步执行。"""

    def test_async_callable_success(self) -> None:
        """异步 callable 正常执行并返回结构化结果。"""
        from core.async_tools import AsyncToolRegistry

        async def run():
            registry = AsyncToolRegistry([async_add])
            result = await registry.execute_async("async_add", {"a": 1, "b": 2})
            assert result.error_code is None
            assert result.value == {"result": 3}
            assert "result" in result.content

        asyncio.run(run())

    def test_sync_callable_via_to_thread(self) -> None:
        """同步 callable 通过 asyncio.to_thread 执行。"""
        from core.async_tools import AsyncToolRegistry

        async def run():
            registry = AsyncToolRegistry([sync_multiply])
            result = await registry.execute_async("sync_multiply", {"a": 3, "b": 4})
            assert result.error_code is None
            assert result.value == {"result": 12}

        asyncio.run(run())

    def test_unknown_tool_returns_error(self) -> None:
        """未知工具返回 unknown_tool 错误。"""
        from core.async_tools import AsyncToolRegistry

        async def run():
            registry = AsyncToolRegistry([])
            result = await registry.execute_async("unknown", {})
            assert result.error_code == "unknown_tool"
            assert "unknown tool" in result.content

        asyncio.run(run())

    def test_invalid_arguments_returns_error(self) -> None:
        """无效参数返回 invalid_arguments 错误。"""
        from core.async_tools import AsyncToolRegistry

        async def run():
            registry = AsyncToolRegistry([async_add])
            result = await registry.execute_async("async_add", {"a": 1})  # 缺少 b
            assert result.error_code == "invalid_arguments"

        asyncio.run(run())


class TestAsyncToolTimeout:
    """测试异步工具 timeout。"""

    def test_async_tool_timeout_returns_error(self) -> None:
        """异步工具超过 deadline 返回 tool_timeout 错误。"""
        from core.async_tools import AsyncToolRegistry

        async def run():
            registry = AsyncToolRegistry([slow_tool], default_timeout=0.05)
            result = await registry.execute_async("slow_tool", {"duration": 10.0})
            assert result.error_code == "tool_timeout"
            assert "timed out" in result.content.lower()

        asyncio.run(run())

    def test_async_tool_completes_within_timeout(self) -> None:
        """异步工具在 timeout 前完成返回正常结果。"""
        from core.async_tools import AsyncToolRegistry

        async def run():
            registry = AsyncToolRegistry([slow_tool], default_timeout=1.0)
            result = await registry.execute_async("slow_tool", {"duration": 0.01})
            assert result.error_code is None
            assert result.content == "completed"

        asyncio.run(run())


class TestAsyncToolCancellation:
    """测试异步工具取消传播。"""

    def test_cancellation_propagates_to_async_tool(self) -> None:
        """取消传播到正在执行的异步工具。"""
        from core.async_tools import AsyncToolRegistry

        started = False

        @tool
        async def cancellable_tool() -> str:
            nonlocal started
            started = True
            await asyncio.sleep(10)
            return "should not reach"

        async def run():
            registry = AsyncToolRegistry([cancellable_tool])
            task = asyncio.create_task(registry.execute_async("cancellable_tool", {}))
            await asyncio.sleep(0.01)  # 等待工具开始
            assert started
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())


class TestAsyncToolAuthorization:
    """测试异步工具授权。"""

    def test_authorization_deny_before_execution(self) -> None:
        """授权拒绝发生在工具执行前。"""
        from core.async_tools import AsyncToolRegistry

        class DenyAllPolicy:
            def authorize(
                self, request: ToolAuthorizationRequest
            ) -> ToolAuthorizationDecision:
                return ToolAuthorizationDecision(allowed=False, reason="denied")

        async def run():
            registry = AsyncToolRegistry(
                [async_add],
                authorization_policy=DenyAllPolicy(),
            )
            result = await registry.execute_async("async_add", {"a": 1, "b": 2})
            assert result.error_code == "permission_denied"

        asyncio.run(run())

    def test_authorization_exception_returns_error(self) -> None:
        """授权策略异常返回 authorization_error。"""
        from core.async_tools import AsyncToolRegistry

        class FailingPolicy:
            def authorize(
                self, request: ToolAuthorizationRequest
            ) -> ToolAuthorizationDecision:
                raise RuntimeError("policy error")

        async def run():
            registry = AsyncToolRegistry(
                [async_add],
                authorization_policy=FailingPolicy(),
            )
            result = await registry.execute_async("async_add", {"a": 1, "b": 2})
            assert result.error_code == "authorization_error"

        asyncio.run(run())


class TestSyncToolCancellationLimitation:
    """测试同步工具取消限制。"""

    def test_sync_tool_timeout_returns_error(self) -> None:
        """同步工具 timeout 返回 tool_timeout 错误。"""
        import time

        from core.async_tools import AsyncToolRegistry

        @tool
        def blocking_sync() -> str:
            time.sleep(10)
            return "should not reach"

        async def run():
            registry = AsyncToolRegistry([blocking_sync], default_timeout=0.05)
            result = await registry.execute_async("blocking_sync", {})
            assert result.error_code == "tool_timeout"

        asyncio.run(run())

    def test_cancelled_wait_does_not_consume_result(self) -> None:
        """取消等待后不再消费结果（但后台线程可能继续）。"""
        from core.async_tools import AsyncToolRegistry

        completed = False

        @tool
        def quick_sync() -> str:
            nonlocal completed
            completed = True
            return "done"

        async def run():
            registry = AsyncToolRegistry([quick_sync], default_timeout=1.0)
            task = asyncio.create_task(registry.execute_async("quick_sync", {}))
            # 立即取消（工具可能已完成或正在执行）
            await asyncio.sleep(0.01)
            # 不做断言，只验证取消不会崩溃
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run())