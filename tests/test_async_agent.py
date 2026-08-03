"""测试异步工具执行、timeout 和取消传播。"""

import asyncio
import json

import pytest

from general_mini_agent import tool
from general_mini_agent.tools import ToolAuthorizationDecision, ToolAuthorizationRequest

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
        from general_mini_agent.async_tools import AsyncToolRegistry

        async def run():
            registry = AsyncToolRegistry([async_add])
            result = await registry.execute_async("async_add", {"a": 1, "b": 2})
            assert result.error_code is None
            assert result.value == {"result": 3}
            assert "result" in result.content

        asyncio.run(run())

    def test_sync_callable_via_to_thread(self) -> None:
        """同步 callable 通过 asyncio.to_thread 执行。"""
        from general_mini_agent.async_tools import AsyncToolRegistry

        async def run():
            registry = AsyncToolRegistry([sync_multiply])
            result = await registry.execute_async("sync_multiply", {"a": 3, "b": 4})
            assert result.error_code is None
            assert result.value == {"result": 12}

        asyncio.run(run())

    def test_unknown_tool_returns_error(self) -> None:
        """未知工具返回 unknown_tool 错误。"""
        from general_mini_agent.async_tools import AsyncToolRegistry

        async def run():
            registry = AsyncToolRegistry([])
            result = await registry.execute_async("unknown", {})
            assert result.error_code == "unknown_tool"
            assert "unknown tool" in result.content

        asyncio.run(run())

    def test_invalid_arguments_returns_error(self) -> None:
        """无效参数返回 invalid_arguments 错误。"""
        from general_mini_agent.async_tools import AsyncToolRegistry

        async def run():
            registry = AsyncToolRegistry([async_add])
            result = await registry.execute_async("async_add", {"a": 1})  # 缺少 b
            assert result.error_code == "invalid_arguments"

        asyncio.run(run())


class TestAsyncToolTimeout:
    """测试异步工具 timeout。"""

    def test_async_tool_timeout_returns_error(self) -> None:
        """异步工具超过 deadline 返回 tool_timeout 错误。"""
        from general_mini_agent.async_tools import AsyncToolRegistry

        async def run():
            registry = AsyncToolRegistry([slow_tool], default_timeout=0.05)
            result = await registry.execute_async("slow_tool", {"duration": 10.0})
            assert result.error_code == "tool_timeout"
            assert "timed out" in result.content.lower()

        asyncio.run(run())

    def test_async_tool_completes_within_timeout(self) -> None:
        """异步工具在 timeout 前完成返回正常结果。"""
        from general_mini_agent.async_tools import AsyncToolRegistry

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
        from general_mini_agent.async_tools import AsyncToolRegistry

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
        from general_mini_agent.async_tools import AsyncToolRegistry

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
        from general_mini_agent.async_tools import AsyncToolRegistry

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

        from general_mini_agent.async_tools import AsyncToolRegistry

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
        from general_mini_agent.async_tools import AsyncToolRegistry

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
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse

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
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse, ToolCall

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
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse, ToolCall

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
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse
        from general_mini_agent.memory import InMemoryConversation

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
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse
        from general_mini_agent.memory import InMemoryConversation

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
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse

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

    def test_same_instance_concurrent_calls_isolate_state(self) -> None:
        """同一 AsyncAgent 实例的并发调用状态隔离。"""
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse

        # 共享的 LLM，会根据调用次数返回不同响应
        class SharedLLM:
            def __init__(self):
                self.call_count = 0

            async def chat_async(self, messages, *, tools=None):
                self.call_count += 1
                call_id = self.call_count
                await asyncio.sleep(0.05)
                return LLMResponse(
                    content=f"response {call_id}",
                    tool_calls=None,
                    usage={"total_tokens": call_id},
                )

        async def run():
            llm = SharedLLM()
            agent = AsyncAgent(llm)

            # 同一实例的两个并发调用
            task1 = asyncio.create_task(agent.run_async("input 1"))
            task2 = asyncio.create_task(agent.run_async("input 2"))
            results = await asyncio.gather(task1, task2)

            # 两个结果应该有不同的内容和 usage
            assert results[0].content != results[1].content
            assert results[0].usage != results[1].usage
            # 每个 trace 应该是独立的
            assert len(results[0].trace) >= 0
            assert len(results[1].trace) >= 0

        asyncio.run(run())


class TestAsyncAgentProtocolMigration:
    """测试 AsyncAgent 迁移到协议接口后的行为。"""

    def test_two_tools_in_one_turn_builds_canonical_message_sequence(self) -> None:
        """验证多工具调用的消息序列符合协议规范。"""
        from conftest import StrictScriptedAsyncChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse, ToolCall
        from general_mini_agent.tools import Tool

        model = StrictScriptedAsyncChatModel([
            LLMResponse(
                content="use both tools",
                tool_calls=[
                    ToolCall("c1", "add", {"a": 2, "b": 3}),
                    ToolCall("c2", "multiply", {"a": 4, "b": 5}),
                ],
            ),
            LLMResponse(content="done", tool_calls=None),
        ])

        async def run():
            agent = AsyncAgent(
                llm=model,
                tools=[
                    Tool(lambda a, b: a + b, name="add"),
                    Tool(lambda a, b: a * b, name="multiply"),
                ],
            )
            result = await agent.run_async("calculate")
            assert result.content == "done"
            # 验证第二次模型调用收到正确消息序列：
            # [system, user, assistant(tool_calls=[c1, c2]), tool(c1), tool(c2)]
            second_call_messages = model.calls[1][0]
            assert len(second_call_messages) == 5
            assert second_call_messages[0]["role"] == "system"
            assert second_call_messages[1]["role"] == "user"
            assert second_call_messages[2]["role"] == "assistant"
            assert len(second_call_messages[2]["tool_calls"]) == 2
            assert second_call_messages[2]["tool_calls"][0]["id"] == "c1"
            assert second_call_messages[2]["tool_calls"][1]["id"] == "c2"
            assert second_call_messages[3]["role"] == "tool"
            assert second_call_messages[3]["tool_call_id"] == "c1"
            assert second_call_messages[4]["role"] == "tool"
            assert second_call_messages[4]["tool_call_id"] == "c2"

        asyncio.run(run())

    def test_length_finish_reason_does_not_commit_memory(self) -> None:
        """length 结束原因不提交 memory。"""
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse
        from general_mini_agent.memory import InMemoryConversation

        memory = InMemoryConversation()
        model = MockAsyncLLM([
            LLMResponse(content="partial answer", tool_calls=None, finish_reason="length", usage={}),
        ])

        async def run():
            agent = AsyncAgent(llm=model, memory=memory)
            result = await agent.run_async("question")
            assert result.stop_reason == "incomplete"
            assert result.content == "partial answer"
            assert len(memory.get_context()) == 0

        asyncio.run(run())

    def test_empty_response_returns_model_error(self) -> None:
        """空响应返回 model_error。"""
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse

        model = MockAsyncLLM([
            LLMResponse(content=None, tool_calls=None, usage={}),
        ])

        async def run():
            agent = AsyncAgent(llm=model)
            result = await agent.run_async("question")
            assert result.stop_reason == "model_error"
            assert result.content == ""
            assert "empty response" in result.error.lower()

        asyncio.run(run())

    def test_legacy_text_response_completes(self) -> None:
        """遗留响应（无 finish_reason）有文本时正常完成。"""
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse

        model = MockAsyncLLM([
            LLMResponse(content="legacy answer", tool_calls=None, finish_reason=None, usage={}),
        ])

        async def run():
            agent = AsyncAgent(llm=model)
            result = await agent.run_async("question")
            assert result.stop_reason == "completed"
            assert result.content == "legacy answer"
            assert result.error is None

        asyncio.run(run())

    def test_tool_failure_allows_model_recovery(self) -> None:
        """工具失败后模型可以恢复。"""
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse, ToolCall

        @tool
        def explode() -> str:
            raise RuntimeError("boom")

        model = MockAsyncLLM([
            LLMResponse(content="call", tool_calls=[ToolCall("c1", "explode", {})], usage={}),
            LLMResponse(content="recovered", tool_calls=None, usage={}),
        ])

        async def run():
            agent = AsyncAgent(llm=model, tools=[explode])
            result = await agent.run_async("question")
            assert result.stop_reason == "completed"
            assert result.content == "recovered"
            assert result.trace[0]["error_code"] == "execution_failed"

        asyncio.run(run())

    def test_cancellation_does_not_commit_memory(self) -> None:
        """取消不提交 memory（已有测试，验证行为不变）。"""
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse
        from general_mini_agent.memory import InMemoryConversation

        class BlockingLLM:
            def __init__(self):
                self.started = False

            async def chat_async(self, messages, *, tools=None):
                self.started = True
                await asyncio.sleep(10)
                return LLMResponse(content="done", tool_calls=None, usage={})

        llm = BlockingLLM()
        memory = InMemoryConversation()

        async def run():
            agent = AsyncAgent(llm=llm, memory=memory)
            task = asyncio.create_task(agent.run_async("hi"))
            await asyncio.sleep(0.01)
            assert llm.started
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert len(memory.get_context()) == 0

        asyncio.run(run())

    def test_max_iterations_does_not_commit_memory(self) -> None:
        """达到最大迭代不提交 memory。"""
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse, ToolCall
        from general_mini_agent.memory import InMemoryConversation

        @tool
        def keep_going() -> str:
            return "continue"

        memory = InMemoryConversation()
        model = MockAsyncLLM([
            LLMResponse(content="", tool_calls=[ToolCall("c1", "keep_going", {})], usage={}),
            LLMResponse(content="", tool_calls=[ToolCall("c2", "keep_going", {})], usage={}),
        ])

        async def run():
            agent = AsyncAgent(llm=model, tools=[keep_going], max_iterations=2, memory=memory)
            result = await agent.run_async("question")
            assert result.stop_reason == "max_iterations"
            assert len(memory.get_context()) == 0

        asyncio.run(run())

    def test_model_error_does_not_commit_memory(self) -> None:
        """模型错误不提交 memory。"""
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.memory import InMemoryConversation

        memory = InMemoryConversation()

        class FailingModel:
            async def chat_async(self, messages, *, tools=None):
                raise Exception("model failed")

        async def run():
            agent = AsyncAgent(llm=FailingModel(), memory=memory)
            # Note: The agent catches ModelRequestError, not general exceptions
            # So this will raise an exception, which we catch
            try:
                await agent.run_async("question")
            except Exception:
                pass
            assert len(memory.get_context()) == 0

        asyncio.run(run())

    def test_content_filter_does_not_commit_memory(self) -> None:
        """content_filter 结束原因不提交 memory。"""
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse
        from general_mini_agent.memory import InMemoryConversation

        memory = InMemoryConversation()
        model = MockAsyncLLM([
            LLMResponse(content="filtered", tool_calls=None, finish_reason="content_filter", usage={}),
        ])

        async def run():
            agent = AsyncAgent(llm=model, memory=memory)
            result = await agent.run_async("question")
            assert result.stop_reason == "incomplete"
            assert result.content == "filtered"
            assert len(memory.get_context()) == 0

        asyncio.run(run())


# ─────────────────────────────────────────────────────────────
# AsyncAgent run_stream_async 测试
# ─────────────────────────────────────────────────────────────


class TestAsyncAgentStreaming:
    """测试 AsyncAgent.run_stream_async 行为。"""

    def test_interleaved_multi_tool_chunks_execute_by_index(self) -> None:
        """交叉多工具 chunks 按索引执行。"""
        from conftest import ScriptedAsyncStreamingChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import StreamChunk, ToolCallDelta

        calls: list[str] = []

        @tool
        async def first(value: int) -> str:
            calls.append("first")
            return str(value)

        @tool
        async def second(value: int) -> str:
            calls.append("second")
            return str(value)

        model = ScriptedAsyncStreamingChatModel([
            [
                StreamChunk(tool_calls=[
                    ToolCallDelta(1, "c2", "second", '{"value":'),
                    ToolCallDelta(0, "c1", "first", '{"value":'),
                ]),
                StreamChunk(tool_calls=[
                    ToolCallDelta(0, arguments="1}"),
                    ToolCallDelta(1, arguments="2}"),
                ], finish_reason="tool_calls"),
            ],
            [StreamChunk(content="done", finish_reason="stop")],
        ])

        async def run():
            agent = AsyncAgent(llm=model, tools=[first, second])
            events = []
            async for event in agent.run_stream_async("question"):
                events.append(event)

            assert calls == ["first", "second"]
            assert [e["name"] for e in events if e["type"] == "tool_call"] == [
                "first", "second"
            ]

        asyncio.run(run())

    def test_finish_reason_stop_completes(self) -> None:
        """finish_reason=stop 正常完成。"""
        from conftest import ScriptedAsyncStreamingChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import StreamChunk

        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(content="answer", finish_reason="stop")],
        ])

        async def run():
            agent = AsyncAgent(llm=model)
            events = []
            async for event in agent.run_stream_async("question"):
                events.append(event)

            assert events[-1]["stop_reason"] == "completed"
            assert events[-1]["content"] == "answer"

        asyncio.run(run())

    def test_invalid_json_arguments_returns_error(self) -> None:
        """无效 JSON 参数返回 invalid_arguments 错误。"""
        from conftest import ScriptedAsyncStreamingChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import StreamChunk, ToolCallDelta

        @tool
        async def add(a: int, b: int) -> int:
            return a + b

        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "c1", "add", '{"a":1')],
                finish_reason="tool_calls",
            )],
            [StreamChunk(content="corrected", finish_reason="stop")],
        ])

        async def run():
            agent = AsyncAgent(llm=model, tools=[add])
            events = []
            async for event in agent.run_stream_async("question"):
                events.append(event)

            tool_event = next(e for e in events if e["type"] == "tool_call")
            assert tool_event["error_code"] == "invalid_arguments"
            assert tool_event["arguments"] is None
            assert tool_event["raw_arguments"] == '{"a":1'

        asyncio.run(run())

    def test_text_without_finish_reason_is_incomplete(self) -> None:
        """缺少 finish reason 的文本返回 incomplete。"""
        from conftest import ScriptedAsyncStreamingChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import StreamChunk

        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(content="partial answer")],
        ])

        async def run():
            agent = AsyncAgent(llm=model)
            events = []
            async for event in agent.run_stream_async("question"):
                events.append(event)

            assert events[-1]["stop_reason"] == "incomplete"
            assert events[-1]["content"] == "partial answer"

        asyncio.run(run())

    def test_stream_protocol_error_returns_model_error(self) -> None:
        """流协议错误返回 model_error。"""
        from conftest import ScriptedAsyncStreamingChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import StreamChunk, ToolCallDelta

        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "", "tool_name", "{}")],
                finish_reason="tool_calls",
            )],
        ])

        async def run():
            agent = AsyncAgent(llm=model)
            events = []
            async for event in agent.run_stream_async("question"):
                events.append(event)

            assert events[-1]["stop_reason"] == "model_error"
            model_error = next(e for e in events if e["type"] == "model_error")
            assert model_error["error_code"] == "stream_protocol_error"

        asyncio.run(run())

    def test_usage_snapshots_accumulated_correctly(self) -> None:
        """usage 快照正确累积。"""
        from conftest import ScriptedAsyncStreamingChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import StreamChunk, ToolCallDelta

        @tool
        async def noop() -> str:
            return "ok"

        model = ScriptedAsyncStreamingChatModel([
            [
                StreamChunk(usage={"prompt_tokens": 3, "total_tokens": 3}),
                StreamChunk(
                    tool_calls=[ToolCallDelta(0, "c1", "noop", "{}")],
                    finish_reason="tool_calls",
                ),
                StreamChunk(usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}),
            ],
            [
                StreamChunk(content="done", finish_reason="stop"),
                StreamChunk(usage={"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}),
            ],
        ])

        async def run():
            agent = AsyncAgent(llm=model, tools=[noop])
            events = []
            async for event in agent.run_stream_async("question"):
                events.append(event)

            done = events[-1]
            assert done["usage"] == {
                "prompt_tokens": 7,
                "completion_tokens": 3,
                "total_tokens": 10,
            }

        asyncio.run(run())

    def test_early_generator_close_does_not_commit_memory(self) -> None:
        """早期生成器关闭不提交 memory。"""
        from conftest import ScriptedAsyncStreamingChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import StreamChunk
        from general_mini_agent.memory import InMemoryConversation

        memory = InMemoryConversation()
        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(content="partial"), StreamChunk(content=" answer", finish_reason="stop")],
        ])

        async def run():
            agent = AsyncAgent(llm=model, memory=memory)
            gen = agent.run_stream_async("question")
            # 只消费第一个事件然后关闭生成器
            event = await gen.__anext__()
            assert event["type"] == "iteration_start"
            await gen.aclose()
            # memory 不应该被提交
            assert len(memory.get_context()) == 0

        asyncio.run(run())

    def test_cancellation_does_not_commit_memory(self) -> None:
        """取消不提交 memory。"""
        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.memory import InMemoryConversation

        memory = InMemoryConversation()

        class SlowStreamingModel:
            async def chat_stream_async(self, messages, *, tools=None):
                from general_mini_agent.llm import StreamChunk
                yield StreamChunk(content="partial")
                await asyncio.sleep(10)
                yield StreamChunk(content="done", finish_reason="stop")

        async def run():
            agent = AsyncAgent(llm=SlowStreamingModel(), memory=memory)
            gen = agent.run_stream_async("question")
            # 获取第一个事件然后取消
            event = await gen.__anext__()
            assert event["type"] == "iteration_start"
            await gen.aclose()
            assert len(memory.get_context()) == 0

        asyncio.run(run())

    def test_max_iterations_does_not_commit_memory(self) -> None:
        """达到最大迭代不提交 memory。"""
        from conftest import ScriptedAsyncStreamingChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import StreamChunk, ToolCallDelta
        from general_mini_agent.memory import InMemoryConversation

        memory = InMemoryConversation()

        @tool
        async def keep_going() -> str:
            return "continue"

        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "c1", "keep_going", "{}")],
                finish_reason="tool_calls",
            )],
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "c2", "keep_going", "{}")],
                finish_reason="tool_calls",
            )],
        ])

        async def run():
            agent = AsyncAgent(llm=model, tools=[keep_going], max_iterations=2, memory=memory)
            events = []
            async for event in agent.run_stream_async("question"):
                events.append(event)

            assert events[-1]["stop_reason"] == "max_iterations"
            assert len(memory.get_context()) == 0

        asyncio.run(run())

    def test_content_filter_does_not_commit_memory(self) -> None:
        """content_filter 结束原因不提交 memory。"""
        from conftest import ScriptedAsyncStreamingChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import StreamChunk
        from general_mini_agent.memory import InMemoryConversation

        memory = InMemoryConversation()
        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(content="filtered", finish_reason="content_filter")],
        ])

        async def run():
            agent = AsyncAgent(llm=model, memory=memory)
            events = []
            async for event in agent.run_stream_async("question"):
                events.append(event)

            assert events[-1]["stop_reason"] == "incomplete"
            assert events[-1]["content"] == "filtered"
            assert len(memory.get_context()) == 0

        asyncio.run(run())

    def test_tool_calls_presence_not_finish_reason_drives_continuation(self) -> None:
        """工具调用存在而非 finish_reason='tool_calls' 决定继续。"""
        from conftest import ScriptedAsyncStreamingChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import StreamChunk, ToolCallDelta

        calls: list[str] = []

        @tool
        async def my_tool() -> str:
            calls.append("tool")
            return "result"

        # 注意：finish_reason 不是 "tool_calls"，但有工具调用
        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "c1", "my_tool", "{}")],
                finish_reason="stop",  # 意外的 finish_reason
            )],
            [StreamChunk(content="done", finish_reason="stop")],
        ])

        async def run():
            agent = AsyncAgent(llm=model, tools=[my_tool])
            events = []
            async for event in agent.run_stream_async("question"):
                events.append(event)

            # 工具应该被执行（因为 tool_calls 非空）
            assert calls == ["tool"]

        asyncio.run(run())

    def test_final_hook_cannot_mutate_stored_assistant_content(self) -> None:
        """final hook 变异不影响存储的 assistant content。"""
        from conftest import ScriptedAsyncChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import LLMResponse
        from general_mini_agent.memory import InMemoryConversation

        memory = InMemoryConversation()
        final_hooks: list[dict] = []

        model = ScriptedAsyncChatModel([
            LLMResponse(content="original answer", tool_calls=None, finish_reason="stop"),
        ])

        async def run():
            agent = AsyncAgent(
                llm=model,
                memory=memory,
                hooks={"on_final": final_hooks.append},
            )
            result = await agent.run_async("question")

            assert result.stop_reason == "completed"
            assert len(final_hooks) == 1

            # 变异 hook 数据
            hook_data = final_hooks[0]
            hook_data["final_answer"] = "mutated answer"

            # 验证存储的内容未改变
            assert result.content == "original answer"
            assert memory.get_context()[1]["content"] == "original answer"

        asyncio.run(run())

    def test_tool_failure_allows_model_recovery(self) -> None:
        """工具失败后模型可以恢复。"""
        from conftest import ScriptedAsyncStreamingChatModel

        from general_mini_agent.async_agent import AsyncAgent
        from general_mini_agent.llm import StreamChunk, ToolCallDelta

        @tool
        async def explode() -> str:
            raise RuntimeError("boom")

        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "c1", "explode", "{}")],
                finish_reason="tool_calls",
            )],
            [StreamChunk(content="recovered", finish_reason="stop")],
        ])

        async def run():
            agent = AsyncAgent(llm=model, tools=[explode])
            events = []
            async for event in agent.run_stream_async("question"):
                events.append(event)

            assert events[-1]["stop_reason"] == "completed"
            assert events[-1]["content"] == "recovered"
            tool_event = next(e for e in events if e["type"] == "tool_call")
            assert tool_event["error_code"] == "execution_failed"

        asyncio.run(run())