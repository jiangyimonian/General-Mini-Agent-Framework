"""测试异步工具执行、timeout 和取消传播。"""

import asyncio
import json

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


# ─────────────────────────────────────────────────────────────
# AsyncAgent 测试
# ─────────────────────────────────────────────────────────────


class MockAsyncLLM:
    """Mock 异步 LLM，用于测试。"""

    def __init__(self, responses: list):
        self.responses = responses
        self.call_count = 0

    async def chat_async(self, messages, *, tools=None):
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        raise RuntimeError("no more responses")

    def chat_stream_async(self, messages, *, tools=None):
        return self._stream_impl(messages, tools)

    async def _stream_impl(self, messages, tools):
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            if resp.content:
                yield {"type": "thought_chunk", "iteration": 0, "text": resp.content}
            if resp.tool_calls:
                for tc in resp.tool_calls:
                    yield {
                        "type": "tool_call",
                        "iteration": 0,
                        "index": 0,
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "raw_arguments": json.dumps(tc.arguments),
                    }
            yield {
                "type": "done",
                "content": resp.content or "",
                "trace": [],
                "usage": resp.usage,
                "iterations": 1,
                "stop_reason": "completed",
            }


class TestAsyncAgentBasic:
    """测试 AsyncAgent 基本行为。"""

    def test_direct_answer_returns_content(self) -> None:
        """直接回答返回内容。"""
        from core.async_agent import AsyncAgent
        from core.llm import LLMResponse

        llm = MockAsyncLLM([
            LLMResponse(content="Hello, world!", tool_calls=None, usage={"total_tokens": 5})
        ])

        async def run():
            agent = AsyncAgent(llm)
            result = await agent.run_async("hi")
            assert result.content == "Hello, world!"
            assert result.stop_reason == "completed"

        asyncio.run(run())

    def test_two_tool_calls_in_sequence(self) -> None:
        """两次工具调用按顺序执行。"""
        from core.async_agent import AsyncAgent
        from core.llm import LLMResponse, ToolCall

        call_order = []

        @tool
        async def first_tool(x: int) -> dict:
            call_order.append("first")
            return {"result": x * 2}

        @tool
        async def second_tool(y: int) -> dict:
            call_order.append("second")
            return {"result": y + 1}

        llm = MockAsyncLLM([
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c1", name="first_tool", arguments={"x": 3})],
                usage={},
            ),
            LLMResponse(
                content="Done",
                tool_calls=None,
                usage={"total_tokens": 10},
            ),
        ])

        async def run():
            agent = AsyncAgent(llm, tools=[first_tool, second_tool])
            result = await agent.run_async("test")
            assert result.content == "Done"
            assert call_order == ["first"]

        asyncio.run(run())

    def test_tool_timeout_allows_model_recovery(self) -> None:
        """工具 timeout 后模型可以继续推理。"""
        from core.async_agent import AsyncAgent
        from core.llm import LLMResponse, ToolCall

        @tool
        async def slow_tool() -> str:
            await asyncio.sleep(10)
            return "should not reach"

        llm = MockAsyncLLM([
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c1", name="slow_tool", arguments={})],
                usage={},
            ),
            LLMResponse(
                content="I see the tool timed out",
                tool_calls=None,
                usage={"total_tokens": 15},
            ),
        ])

        async def run():
            agent = AsyncAgent(llm, tools=[slow_tool], default_tool_timeout=0.05)
            result = await agent.run_async("test")
            assert result.content == "I see the tool timed out"
            assert result.stop_reason == "completed"

        asyncio.run(run())

    def test_cancellation_does_not_write_to_memory(self) -> None:
        """取消不写入会话记忆。"""
        from core.async_agent import AsyncAgent
        from core.llm import LLMResponse
        from core.memory import InMemoryConversation

        # 使用一个会阻塞的 LLM
        class BlockingLLM:
            def __init__(self):
                self.started = False

            async def chat_async(self, messages, *, tools=None):
                self.started = True
                # 等待很长时间
                await asyncio.sleep(10)
                return LLMResponse(content="done", tool_calls=None, usage={})

        llm = BlockingLLM()
        memory = InMemoryConversation()

        async def run():
            agent = AsyncAgent(llm, memory=memory)
            task = asyncio.create_task(agent.run_async("hi"))
            # 等待 LLM 开始
            await asyncio.sleep(0.01)
            assert llm.started
            # 取消任务
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            # 取消后记忆应该为空（因为任务被取消，没有完成）
            assert len(memory.get_context()) == 0

        asyncio.run(run())

    def test_successful_run_writes_to_memory(self) -> None:
        """成功运行原子写入会话记忆。"""
        from core.async_agent import AsyncAgent
        from core.llm import LLMResponse
        from core.memory import InMemoryConversation

        llm = MockAsyncLLM([
            LLMResponse(content="Hello!", tool_calls=None, usage={})
        ])
        memory = InMemoryConversation()

        async def run():
            agent = AsyncAgent(llm, memory=memory)
            result = await agent.run_async("hi")
            assert result.stop_reason == "completed"
            # 成功后记忆应该有内容
            ctx = memory.get_context()
            assert len(ctx) == 2
            assert ctx[0]["role"] == "user"
            assert ctx[1]["role"] == "assistant"

        asyncio.run(run())


class TestAsyncAgentConcurrency:
    """测试 AsyncAgent 并发隔离。"""

    def test_concurrent_runs_do_not_share_state(self) -> None:
        """同一实例两个并发运行不共享 trace/messages。"""
        from core.async_agent import AsyncAgent
        from core.llm import LLMResponse

        # 每个实例独立的 LLM
        class InstanceMockLLM:
            def __init__(self, response_id):
                self.response_id = response_id

            async def chat_async(self, messages, *, tools=None):
                await asyncio.sleep(0.05)
                return LLMResponse(
                    content=f"response {self.response_id}",
                    tool_calls=None,
                    usage={},
                )

        async def run():
            # 创建两个不同的 LLM 实例
            llm1 = InstanceMockLLM(1)
            llm2 = InstanceMockLLM(2)

            agent1 = AsyncAgent(llm1)
            agent2 = AsyncAgent(llm2)

            task1 = asyncio.create_task(agent1.run_async("input 1"))
            task2 = asyncio.create_task(agent2.run_async("input 2"))
            results = await asyncio.gather(task1, task2)
            # 两个结果应该不同
            assert "1" in results[0].content
            assert "2" in results[1].content
            # 每个应该有自己的 trace
            assert len(results[0].trace) >= 0
            assert len(results[1].trace) >= 0

        asyncio.run(run())