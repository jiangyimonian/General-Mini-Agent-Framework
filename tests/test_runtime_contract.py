"""验证同步/异步、流式/非流式四种路径的契约一致性。

契约要求：
- 相同的最终结果结构
- 相同的 trace 格式
- 相同的消息序列
- 相同的终止行为
- 相同的 memory 提交策略
"""

from __future__ import annotations

import asyncio

from general_mini_agent import tool
from general_mini_agent.agent import Agent
from general_mini_agent.async_agent import AsyncAgent
from general_mini_agent.llm import LLMResponse, StreamChunk, ToolCall, ToolCallDelta
from general_mini_agent.memory import InMemoryConversation

# ─────────────────────────────────────────────────────────────
# 工具定义
# ─────────────────────────────────────────────────────────────


@tool
def first(value: int) -> str:
    """第一个工具"""
    return f"first:{value}"


@tool
def second(value: int) -> str:
    """第二个工具"""
    return f"second:{value}"


# ─────────────────────────────────────────────────────────────
# 同步非流式测试
# ─────────────────────────────────────────────────────────────


class TestSyncNonStreamContract:
    """测试 Agent.run() 契约"""

    def test_two_tool_calls_produce_consistent_result(self) -> None:
        """模型调用两个工具后回答 done"""
        from conftest import StrictScriptedChatModel

        model = StrictScriptedChatModel([
            LLMResponse(
                content="use both tools",
                tool_calls=[
                    ToolCall("c1", "first", {"value": 1}),
                    ToolCall("c2", "second", {"value": 2}),
                ],
            ),
            LLMResponse(content="done", tool_calls=None),
        ])

        result = Agent(llm=model, tools=[first, second]).run("question")

        # 基本断言
        assert result.content == "done"
        assert result.stop_reason == "completed"
        assert result.iterations == 2
        assert [event["tool"] for event in result.trace if event["type"] == "tool_call"] == [
            "first", "second"
        ]

        # 验证第二次请求的消息序列
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

    def test_length_finish_reason_returns_incomplete(self) -> None:
        """length 结束原因返回 incomplete"""
        from conftest import ScriptedChatModel

        model = ScriptedChatModel([
            LLMResponse(content="partial", tool_calls=None, finish_reason="length"),
        ])

        result = Agent(llm=model, tools=[]).run("question")

        assert result.stop_reason == "incomplete"
        assert result.content == "partial"

    def test_empty_response_returns_model_error(self) -> None:
        """空响应返回 model_error"""
        from conftest import ScriptedChatModel

        model = ScriptedChatModel([
            LLMResponse(content=None, tool_calls=None),
        ])

        result = Agent(llm=model, tools=[]).run("question")

        assert result.stop_reason == "model_error"
        assert result.content == ""
        assert "empty response" in result.error.lower()

    def test_unknown_tool_is_recorded_with_error(self) -> None:
        """未知工具记录错误"""
        from conftest import ScriptedChatModel

        model = ScriptedChatModel([
            LLMResponse(
                content="try unknown",
                tool_calls=[ToolCall("c1", "missing", {})],
            ),
            LLMResponse(content="recovered", tool_calls=None),
        ])

        result = Agent(llm=model, tools=[]).run("question")

        assert result.stop_reason == "completed"
        assert result.content == "recovered"
        assert result.trace[0]["error_code"] == "unknown_tool"

    def test_invalid_arguments_return_error(self) -> None:
        """无效参数返回错误"""
        from conftest import ScriptedChatModel

        model = ScriptedChatModel([
            LLMResponse(
                content="call with invalid args",
                tool_calls=[ToolCall("c1", "first", {"wrong_param": 1})],
            ),
            LLMResponse(content="recovered", tool_calls=None),
        ])

        result = Agent(llm=model, tools=[first]).run("question")

        assert result.stop_reason == "completed"
        assert result.trace[0]["error_code"] == "invalid_arguments"

    def test_usage_accumulation(self) -> None:
        """多次调用的 token 用量应累加"""
        from conftest import ScriptedChatModel

        model = ScriptedChatModel([
            LLMResponse(
                content="call tool",
                tool_calls=[ToolCall("c1", "first", {"value": 1})],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            ),
            LLMResponse(
                content="done",
                tool_calls=None,
                usage={"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
            ),
        ])

        result = Agent(llm=model, tools=[first]).run("question")

        assert result.usage["prompt_tokens"] == 18
        assert result.usage["completion_tokens"] == 8
        assert result.usage["total_tokens"] == 26

    def test_final_hook_receives_copy(self) -> None:
        """on_final hook 接收 trace 副本"""
        from conftest import ScriptedChatModel

        hook_data: list[dict] = []
        model = ScriptedChatModel([
            LLMResponse(content="done", tool_calls=None, finish_reason="stop"),
        ])

        result = Agent(
            llm=model,
            tools=[],
            hooks={"on_final": hook_data.append},
        ).run("question")

        assert result.stop_reason == "completed"
        assert len(hook_data) == 1
        hook_data[0]["modified"] = "test"
        assert "modified" not in result.trace[-1]

    def test_memory_commits_only_on_completed(self) -> None:
        """memory 仅在 completed 时提交"""
        from conftest import ScriptedChatModel

        memory = InMemoryConversation()

        # incomplete 不提交
        incomplete_model = ScriptedChatModel([
            LLMResponse(content="partial", tool_calls=None, finish_reason="length"),
        ])
        Agent(llm=incomplete_model, tools=[], memory=memory).run("q1")
        assert len(memory.get_context()) == 0

        # completed 提交
        completed_model = ScriptedChatModel([
            LLMResponse(content="answer", tool_calls=None, finish_reason="stop"),
        ])
        Agent(llm=completed_model, tools=[], memory=memory).run("q2")
        assert len(memory.get_context()) == 2
        assert memory.get_context()[0]["role"] == "user"
        assert memory.get_context()[1]["role"] == "assistant"


# ─────────────────────────────────────────────────────────────
# 同步流式测试
# ─────────────────────────────────────────────────────────────


class TestSyncStreamContract:
    """测试 Agent.run_stream() 契约"""

    def test_two_tool_calls_produce_consistent_result(self) -> None:
        """模型调用两个工具后回答 done"""
        from conftest import ScriptedStreamingChatModel

        model = ScriptedStreamingChatModel([], [
            [
                StreamChunk(tool_calls=[
                    ToolCallDelta(0, "c1", "first", '{"value": 1}'),
                    ToolCallDelta(1, "c2", "second", '{"value": 2}'),
                ], finish_reason="tool_calls"),
            ],
            [StreamChunk(content="done", finish_reason="stop")],
        ])

        events = list(Agent(llm=model, tools=[first, second]).run_stream("question"))
        result = events[-1]

        # 基本断言
        assert result["content"] == "done"
        assert result["stop_reason"] == "completed"
        assert result["iterations"] == 2
        assert [event["tool"] for event in result["trace"] if event["type"] == "tool_call"] == [
            "first", "second"
        ]

        # 验证第二次请求的消息序列
        second_call_messages = model.stream_calls[1][0]
        assert len(second_call_messages) == 5
        assert second_call_messages[2]["role"] == "assistant"
        assert len(second_call_messages[2]["tool_calls"]) == 2
        assert second_call_messages[2]["tool_calls"][0]["id"] == "c1"
        assert second_call_messages[2]["tool_calls"][1]["id"] == "c2"
        assert second_call_messages[3]["tool_call_id"] == "c1"
        assert second_call_messages[4]["tool_call_id"] == "c2"

    def test_length_finish_reason_returns_incomplete(self) -> None:
        """length 结束原因返回 incomplete"""
        from conftest import ScriptedStreamingChatModel

        model = ScriptedStreamingChatModel([], [
            [StreamChunk(content="partial", finish_reason="length")],
        ])

        events = list(Agent(llm=model, tools=[]).run_stream("question"))

        assert events[-1]["stop_reason"] == "incomplete"
        assert events[-1]["content"] == "partial"

    def test_empty_response_returns_model_error(self) -> None:
        """空响应返回 model_error"""
        from conftest import ScriptedStreamingChatModel

        model = ScriptedStreamingChatModel([], [
            [StreamChunk(content=None, finish_reason=None)],
        ])

        events = list(Agent(llm=model, tools=[]).run_stream("question"))

        assert events[-1]["stop_reason"] == "model_error"
        assert events[-1]["content"] == ""

    def test_unknown_tool_is_recorded_with_error(self) -> None:
        """未知工具记录错误"""
        from conftest import ScriptedStreamingChatModel

        model = ScriptedStreamingChatModel([], [
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "c1", "missing", "{}")],
                finish_reason="tool_calls",
            )],
            [StreamChunk(content="recovered", finish_reason="stop")],
        ])

        events = list(Agent(llm=model, tools=[]).run_stream("question"))

        assert events[-1]["stop_reason"] == "completed"
        assert events[-1]["content"] == "recovered"
        tool_event = next(e for e in events if e["type"] == "tool_call")
        assert tool_event["error_code"] == "unknown_tool"

    def test_invalid_arguments_return_error(self) -> None:
        """无效参数返回错误"""
        from conftest import ScriptedStreamingChatModel

        model = ScriptedStreamingChatModel([], [
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "c1", "first", '{"wrong_param":1}')],
                finish_reason="tool_calls",
            )],
            [StreamChunk(content="recovered", finish_reason="stop")],
        ])

        events = list(Agent(llm=model, tools=[first]).run_stream("question"))

        tool_event = next(e for e in events if e["type"] == "tool_call")
        assert tool_event["error_code"] == "invalid_arguments"

    def test_usage_accumulation(self) -> None:
        """多次调用的 token 用量应累加"""
        from conftest import ScriptedStreamingChatModel

        model = ScriptedStreamingChatModel([], [
            [
                StreamChunk(usage={"prompt_tokens": 10, "completion_tokens": 5}),
                StreamChunk(
                    tool_calls=[ToolCallDelta(0, "c1", "first", '{"value":1}')],
                    finish_reason="tool_calls",
                ),
            ],
            [
                StreamChunk(content="done", finish_reason="stop"),
                StreamChunk(usage={"prompt_tokens": 8, "completion_tokens": 3}),
            ],
        ])

        events = list(Agent(llm=model, tools=[first]).run_stream("question"))

        assert events[-1]["usage"]["prompt_tokens"] == 18
        assert events[-1]["usage"]["completion_tokens"] == 8

    def test_final_hook_receives_copy(self) -> None:
        """on_final hook 接收 trace 副本"""
        from conftest import ScriptedStreamingChatModel

        hook_data: list[dict] = []
        model = ScriptedStreamingChatModel([], [
            [StreamChunk(content="done", finish_reason="stop")],
        ])

        events = list(Agent(
            llm=model,
            tools=[],
            hooks={"on_final": hook_data.append},
        ).run_stream("question"))

        assert events[-1]["stop_reason"] == "completed"
        assert len(hook_data) == 1
        hook_data[0]["modified"] = "test"
        assert "modified" not in events[-1]["trace"][-1]

    def test_memory_commits_only_on_completed(self) -> None:
        """memory 仅在 completed 时提交"""
        from conftest import ScriptedStreamingChatModel

        memory = InMemoryConversation()

        # incomplete 不提交
        incomplete_model = ScriptedStreamingChatModel([], [
            [StreamChunk(content="partial", finish_reason="length")],
        ])
        list(Agent(llm=incomplete_model, tools=[], memory=memory).run_stream("q1"))
        assert len(memory.get_context()) == 0

        # completed 提交
        completed_model = ScriptedStreamingChatModel([], [
            [StreamChunk(content="answer", finish_reason="stop")],
        ])
        list(Agent(llm=completed_model, tools=[], memory=memory).run_stream("q2"))
        assert len(memory.get_context()) == 2


# ─────────────────────────────────────────────────────────────
# 异步非流式测试
# ─────────────────────────────────────────────────────────────


class TestAsyncNonStreamContract:
    """测试 AsyncAgent.run_async() 契约"""

    def test_two_tool_calls_produce_consistent_result(self) -> None:
        """模型调用两个工具后回答 done"""
        from conftest import StrictScriptedAsyncChatModel

        model = StrictScriptedAsyncChatModel([
            LLMResponse(
                content="use both tools",
                tool_calls=[
                    ToolCall("c1", "first", {"value": 1}),
                    ToolCall("c2", "second", {"value": 2}),
                ],
            ),
            LLMResponse(content="done", tool_calls=None),
        ])

        async def run():
            result = await AsyncAgent(llm=model, tools=[first, second]).run_async("question")
            assert result.content == "done"
            assert result.stop_reason == "completed"
            assert result.iterations == 2
            assert [event["tool"] for event in result.trace if event["type"] == "tool_call"] == [
                "first", "second"
            ]

            # 验证第二次请求的消息序列
            second_call_messages = model.calls[1][0]
            assert len(second_call_messages) == 5
            assert second_call_messages[2]["role"] == "assistant"
            assert len(second_call_messages[2]["tool_calls"]) == 2
            assert second_call_messages[2]["tool_calls"][0]["id"] == "c1"
            assert second_call_messages[2]["tool_calls"][1]["id"] == "c2"

        asyncio.run(run())

    def test_length_finish_reason_returns_incomplete(self) -> None:
        """length 结束原因返回 incomplete"""
        from conftest import ScriptedAsyncChatModel

        model = ScriptedAsyncChatModel([
            LLMResponse(content="partial", tool_calls=None, finish_reason="length"),
        ])

        async def run():
            result = await AsyncAgent(llm=model, tools=[]).run_async("question")
            assert result.stop_reason == "incomplete"
            assert result.content == "partial"

        asyncio.run(run())

    def test_empty_response_returns_model_error(self) -> None:
        """空响应返回 model_error"""
        from conftest import ScriptedAsyncChatModel

        model = ScriptedAsyncChatModel([
            LLMResponse(content=None, tool_calls=None),
        ])

        async def run():
            result = await AsyncAgent(llm=model, tools=[]).run_async("question")
            assert result.stop_reason == "model_error"
            assert result.content == ""

        asyncio.run(run())

    def test_unknown_tool_is_recorded_with_error(self) -> None:
        """未知工具记录错误"""
        from conftest import ScriptedAsyncChatModel

        model = ScriptedAsyncChatModel([
            LLMResponse(
                content="try unknown",
                tool_calls=[ToolCall("c1", "missing", {})],
            ),
            LLMResponse(content="recovered", tool_calls=None),
        ])

        async def run():
            result = await AsyncAgent(llm=model, tools=[]).run_async("question")
            assert result.stop_reason == "completed"
            assert result.content == "recovered"
            assert result.trace[0]["error_code"] == "unknown_tool"

        asyncio.run(run())

    def test_invalid_arguments_return_error(self) -> None:
        """无效参数返回错误"""
        from conftest import ScriptedAsyncChatModel

        model = ScriptedAsyncChatModel([
            LLMResponse(
                content="call with invalid args",
                tool_calls=[ToolCall("c1", "first", {"wrong_param": 1})],
            ),
            LLMResponse(content="recovered", tool_calls=None),
        ])

        async def run():
            result = await AsyncAgent(llm=model, tools=[first]).run_async("question")
            assert result.trace[0]["error_code"] == "invalid_arguments"

        asyncio.run(run())

    def test_usage_accumulation(self) -> None:
        """多次调用的 token 用量应累加"""
        from conftest import ScriptedAsyncChatModel

        model = ScriptedAsyncChatModel([
            LLMResponse(
                content="call tool",
                tool_calls=[ToolCall("c1", "first", {"value": 1})],
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            ),
            LLMResponse(
                content="done",
                tool_calls=None,
                usage={"prompt_tokens": 8, "completion_tokens": 3},
            ),
        ])

        async def run():
            result = await AsyncAgent(llm=model, tools=[first]).run_async("question")
            assert result.usage["prompt_tokens"] == 18
            assert result.usage["completion_tokens"] == 8

        asyncio.run(run())

    def test_final_hook_receives_copy(self) -> None:
        """on_final hook 接收 trace 副本"""
        from conftest import ScriptedAsyncChatModel

        hook_data: list[dict] = []
        model = ScriptedAsyncChatModel([
            LLMResponse(content="done", tool_calls=None, finish_reason="stop"),
        ])

        async def run():
            result = await AsyncAgent(
                llm=model,
                tools=[],
                hooks={"on_final": hook_data.append},
            ).run_async("question")
            assert result.stop_reason == "completed"
            assert len(hook_data) == 1
            hook_data[0]["modified"] = "test"
            assert "modified" not in result.trace[-1]

        asyncio.run(run())

    def test_memory_commits_only_on_completed(self) -> None:
        """memory 仅在 completed 时提交"""
        from conftest import ScriptedAsyncChatModel

        memory = InMemoryConversation()

        async def run():
            # incomplete 不提交
            incomplete_model = ScriptedAsyncChatModel([
                LLMResponse(content="partial", tool_calls=None, finish_reason="length"),
            ])
            await AsyncAgent(llm=incomplete_model, tools=[], memory=memory).run_async("q1")
            assert len(memory.get_context()) == 0

            # completed 提交
            completed_model = ScriptedAsyncChatModel([
                LLMResponse(content="answer", tool_calls=None, finish_reason="stop"),
            ])
            await AsyncAgent(llm=completed_model, tools=[], memory=memory).run_async("q2")
            assert len(memory.get_context()) == 2

        asyncio.run(run())


# ─────────────────────────────────────────────────────────────
# 异步流式测试
# ─────────────────────────────────────────────────────────────


class TestAsyncStreamContract:
    """测试 AsyncAgent.run_stream_async() 契约"""

    def test_two_tool_calls_produce_consistent_result(self) -> None:
        """模型调用两个工具后回答 done"""
        from conftest import ScriptedAsyncStreamingChatModel

        model = ScriptedAsyncStreamingChatModel([
            [
                StreamChunk(tool_calls=[
                    ToolCallDelta(0, "c1", "first", '{"value": 1}'),
                    ToolCallDelta(1, "c2", "second", '{"value": 2}'),
                ], finish_reason="tool_calls"),
            ],
            [StreamChunk(content="done", finish_reason="stop")],
        ])

        async def run():
            events = []
            agent = AsyncAgent(llm=model, tools=[first, second])
            async for event in agent.run_stream_async("question"):
                events.append(event)

            result = events[-1]
            assert result["content"] == "done"
            assert result["stop_reason"] == "completed"
            assert result["iterations"] == 2
            assert [event["tool"] for event in result["trace"] if event["type"] == "tool_call"] == [
                "first", "second"
            ]

            # 验证第二次请求的消息序列
            second_call_messages = model.calls[1][0]
            assert len(second_call_messages) == 5
            assert second_call_messages[2]["role"] == "assistant"
            assert len(second_call_messages[2]["tool_calls"]) == 2
            assert second_call_messages[2]["tool_calls"][0]["id"] == "c1"
            assert second_call_messages[2]["tool_calls"][1]["id"] == "c2"

        asyncio.run(run())

    def test_length_finish_reason_returns_incomplete(self) -> None:
        """length 结束原因返回 incomplete"""
        from conftest import ScriptedAsyncStreamingChatModel

        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(content="partial", finish_reason="length")],
        ])

        async def run():
            events = []
            async for event in AsyncAgent(llm=model, tools=[]).run_stream_async("question"):
                events.append(event)
            assert events[-1]["stop_reason"] == "incomplete"
            assert events[-1]["content"] == "partial"

        asyncio.run(run())

    def test_empty_response_returns_model_error(self) -> None:
        """空响应返回 model_error"""
        from conftest import ScriptedAsyncStreamingChatModel

        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(content=None, finish_reason=None)],
        ])

        async def run():
            events = []
            async for event in AsyncAgent(llm=model, tools=[]).run_stream_async("question"):
                events.append(event)
            assert events[-1]["stop_reason"] == "model_error"
            assert events[-1]["content"] == ""

        asyncio.run(run())

    def test_unknown_tool_is_recorded_with_error(self) -> None:
        """未知工具记录错误"""
        from conftest import ScriptedAsyncStreamingChatModel

        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "c1", "missing", "{}")],
                finish_reason="tool_calls",
            )],
            [StreamChunk(content="recovered", finish_reason="stop")],
        ])

        async def run():
            events = []
            async for event in AsyncAgent(llm=model, tools=[]).run_stream_async("question"):
                events.append(event)
            assert events[-1]["stop_reason"] == "completed"
            assert events[-1]["content"] == "recovered"
            tool_event = next(e for e in events if e["type"] == "tool_call")
            assert tool_event["error_code"] == "unknown_tool"

        asyncio.run(run())

    def test_invalid_arguments_return_error(self) -> None:
        """无效参数返回错误"""
        from conftest import ScriptedAsyncStreamingChatModel

        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "c1", "first", '{"wrong_param":1}')],
                finish_reason="tool_calls",
            )],
            [StreamChunk(content="recovered", finish_reason="stop")],
        ])

        async def run():
            events = []
            async for event in AsyncAgent(llm=model, tools=[first]).run_stream_async("question"):
                events.append(event)
            tool_event = next(e for e in events if e["type"] == "tool_call")
            assert tool_event["error_code"] == "invalid_arguments"

        asyncio.run(run())

    def test_usage_accumulation(self) -> None:
        """多次调用的 token 用量应累加"""
        from conftest import ScriptedAsyncStreamingChatModel

        model = ScriptedAsyncStreamingChatModel([
            [
                StreamChunk(usage={"prompt_tokens": 10, "completion_tokens": 5}),
                StreamChunk(
                    tool_calls=[ToolCallDelta(0, "c1", "first", '{"value":1}')],
                    finish_reason="tool_calls",
                ),
            ],
            [
                StreamChunk(content="done", finish_reason="stop"),
                StreamChunk(usage={"prompt_tokens": 8, "completion_tokens": 3}),
            ],
        ])

        async def run():
            events = []
            async for event in AsyncAgent(llm=model, tools=[first]).run_stream_async("question"):
                events.append(event)
            assert events[-1]["usage"]["prompt_tokens"] == 18
            assert events[-1]["usage"]["completion_tokens"] == 8

        asyncio.run(run())

    def test_final_hook_receives_copy(self) -> None:
        """on_final hook 接收 trace 副本"""
        from conftest import ScriptedAsyncStreamingChatModel

        hook_data: list[dict] = []
        model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(content="done", finish_reason="stop")],
        ])

        async def run():
            events = []
            agent = AsyncAgent(
                llm=model,
                tools=[],
                hooks={"on_final": hook_data.append},
            )
            async for event in agent.run_stream_async("question"):
                events.append(event)
            assert events[-1]["stop_reason"] == "completed"
            assert len(hook_data) == 1
            hook_data[0]["modified"] = "test"
            assert "modified" not in events[-1]["trace"][-1]

        asyncio.run(run())

    def test_memory_commits_only_on_completed(self) -> None:
        """memory 仅在 completed 时提交"""
        from conftest import ScriptedAsyncStreamingChatModel

        memory = InMemoryConversation()

        async def run():
            # incomplete 不提交
            incomplete_model = ScriptedAsyncStreamingChatModel([
                [StreamChunk(content="partial", finish_reason="length")],
            ])
            async for _ in AsyncAgent(
                llm=incomplete_model, tools=[], memory=memory
            ).run_stream_async("q1"):
                pass
            assert len(memory.get_context()) == 0

            # completed 提交
            completed_model = ScriptedAsyncStreamingChatModel([
                [StreamChunk(content="answer", finish_reason="stop")],
            ])
            async for _ in AsyncAgent(
                llm=completed_model, tools=[], memory=memory
            ).run_stream_async("q2"):
                pass
            assert len(memory.get_context()) == 2

        asyncio.run(run())


# ─────────────────────────────────────────────────────────────
# 跨路径一致性测试
# ─────────────────────────────────────────────────────────────


class TestCrossPathParity:
    """验证四种路径产生一致的结果"""

    def test_all_paths_produce_same_result_structure(self) -> None:
        """四种路径产生相同的结果结构"""
        from conftest import (
            ScriptedAsyncChatModel,
            ScriptedAsyncStreamingChatModel,
            ScriptedChatModel,
            ScriptedStreamingChatModel,
        )

        # 同步非流式
        sync_model = ScriptedChatModel([
            LLMResponse(
                content="use tools",
                tool_calls=[
                    ToolCall("c1", "first", {"value": 1}),
                    ToolCall("c2", "second", {"value": 2}),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            ),
            LLMResponse(
                content="done", tool_calls=None,
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            ),
        ])
        sync_result = Agent(llm=sync_model, tools=[first, second]).run("question")

        # 同步流式
        stream_model = ScriptedStreamingChatModel([], [
            [StreamChunk(tool_calls=[
                ToolCallDelta(0, "c1", "first", '{"value": 1}'),
                ToolCallDelta(1, "c2", "second", '{"value": 2}'),
            ], finish_reason="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 5})],
            [StreamChunk(
                content="done", finish_reason="stop",
                usage={"prompt_tokens": 5, "completion_tokens": 3}
            )],
        ])
        stream_events = list(Agent(llm=stream_model, tools=[first, second]).run_stream("question"))
        stream_result = stream_events[-1]

        # 异步非流式
        async_model = ScriptedAsyncChatModel([
            LLMResponse(
                content="use tools",
                tool_calls=[
                    ToolCall("c1", "first", {"value": 1}),
                    ToolCall("c2", "second", {"value": 2}),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            ),
            LLMResponse(
                content="done", tool_calls=None,
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            ),
        ])

        async def run_async():
            return await AsyncAgent(llm=async_model, tools=[first, second]).run_async("question")

        async_result = asyncio.run(run_async())

        # 异步流式
        async_stream_model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(tool_calls=[
                ToolCallDelta(0, "c1", "first", '{"value": 1}'),
                ToolCallDelta(1, "c2", "second", '{"value": 2}'),
            ], finish_reason="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 5})],
            [StreamChunk(
                content="done", finish_reason="stop",
                usage={"prompt_tokens": 5, "completion_tokens": 3}
            )],
        ])

        async def run_async_stream():
            events = []
            agent = AsyncAgent(llm=async_stream_model, tools=[first, second])
            async for event in agent.run_stream_async("question"):
                events.append(event)
            return events[-1]

        async_stream_result = asyncio.run(run_async_stream())

        # 验证一致性
        for result, name in [
            (sync_result, "sync"),
            (stream_result, "stream"),
            (async_result, "async"),
            (async_stream_result, "async_stream"),
        ]:
            # 获取 content（stream 结果是 dict）
            content = result["content"] if isinstance(result, dict) else result.content
            stop_reason = result["stop_reason"] if isinstance(result, dict) else result.stop_reason
            iterations = result["iterations"] if isinstance(result, dict) else result.iterations
            trace = result["trace"] if isinstance(result, dict) else result.trace
            usage = result["usage"] if isinstance(result, dict) else result.usage

            assert content == "done", f"{name}: content mismatch"
            assert stop_reason == "completed", f"{name}: stop_reason mismatch"
            assert iterations == 2, f"{name}: iterations mismatch"

            tool_calls = [event["tool"] for event in trace if event["type"] == "tool_call"]
            assert tool_calls == ["first", "second"], f"{name}: trace mismatch"

            assert usage["prompt_tokens"] == 15, f"{name}: usage mismatch"
            assert usage["completion_tokens"] == 8, f"{name}: usage mismatch"

    def test_all_paths_handle_length_finish_reason_consistently(self) -> None:
        """四种路径一致处理 length 结束原因"""
        from conftest import (
            ScriptedAsyncChatModel,
            ScriptedAsyncStreamingChatModel,
            ScriptedChatModel,
            ScriptedStreamingChatModel,
        )

        # 同步非流式
        sync_model = ScriptedChatModel([
            LLMResponse(content="partial", tool_calls=None, finish_reason="length"),
        ])
        sync_result = Agent(llm=sync_model, tools=[]).run("question")

        # 同步流式
        stream_model = ScriptedStreamingChatModel([], [
            [StreamChunk(content="partial", finish_reason="length")],
        ])
        stream_result = list(Agent(llm=stream_model, tools=[]).run_stream("question"))[-1]

        # 异步非流式
        async_model = ScriptedAsyncChatModel([
            LLMResponse(content="partial", tool_calls=None, finish_reason="length"),
        ])
        async_result = asyncio.run(AsyncAgent(llm=async_model, tools=[]).run_async("question"))

        # 异步流式
        async_stream_model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(content="partial", finish_reason="length")],
        ])
        async def run():
            events = []
            agent = AsyncAgent(llm=async_stream_model, tools=[])
            async for event in agent.run_stream_async("question"):
                events.append(event)
            return events[-1]
        async_stream_result = asyncio.run(run())

        # 验证一致性
        for result, name in [
            (sync_result, "sync"),
            (stream_result, "stream"),
            (async_result, "async"),
            (async_stream_result, "async_stream"),
        ]:
            stop_reason = result["stop_reason"] if isinstance(result, dict) else result.stop_reason
            content = result["content"] if isinstance(result, dict) else result.content

            assert stop_reason == "incomplete", f"{name}: stop_reason should be incomplete"
            assert content == "partial", f"{name}: content should be preserved"

    def test_all_paths_handle_empty_response_consistently(self) -> None:
        """四种路径一致处理空响应"""
        from conftest import (
            ScriptedAsyncChatModel,
            ScriptedAsyncStreamingChatModel,
            ScriptedChatModel,
            ScriptedStreamingChatModel,
        )

        # 同步非流式
        sync_model = ScriptedChatModel([
            LLMResponse(content=None, tool_calls=None),
        ])
        sync_result = Agent(llm=sync_model, tools=[]).run("question")

        # 同步流式
        stream_model = ScriptedStreamingChatModel([], [
            [StreamChunk(content=None, finish_reason=None)],
        ])
        stream_result = list(Agent(llm=stream_model, tools=[]).run_stream("question"))[-1]

        # 异步非流式
        async_model = ScriptedAsyncChatModel([
            LLMResponse(content=None, tool_calls=None),
        ])
        async_result = asyncio.run(AsyncAgent(llm=async_model, tools=[]).run_async("question"))

        # 异步流式
        async_stream_model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(content=None, finish_reason=None)],
        ])
        async def run():
            events = []
            agent = AsyncAgent(llm=async_stream_model, tools=[])
            async for event in agent.run_stream_async("question"):
                events.append(event)
            return events[-1]
        async_stream_result = asyncio.run(run())

        # 验证一致性
        for result, name in [
            (sync_result, "sync"),
            (stream_result, "stream"),
            (async_result, "async"),
            (async_stream_result, "async_stream"),
        ]:
            stop_reason = result["stop_reason"] if isinstance(result, dict) else result.stop_reason
            content = result["content"] if isinstance(result, dict) else result.content

            assert stop_reason == "model_error", f"{name}: stop_reason should be model_error"
            assert content == "", f"{name}: content should be empty"

    def test_all_paths_handle_content_filter_consistently(self) -> None:
        """四种路径一致处理 content_filter 结束原因"""
        from conftest import (
            ScriptedAsyncChatModel,
            ScriptedAsyncStreamingChatModel,
            ScriptedChatModel,
            ScriptedStreamingChatModel,
        )

        # 同步非流式
        sync_memory = InMemoryConversation()
        sync_model = ScriptedChatModel([
            LLMResponse(content="filtered", tool_calls=None, finish_reason="content_filter"),
        ])
        sync_result = Agent(llm=sync_model, tools=[], memory=sync_memory).run("question")

        # 同步流式
        stream_memory = InMemoryConversation()
        stream_model = ScriptedStreamingChatModel([], [
            [StreamChunk(content="filtered", finish_reason="content_filter")],
        ])
        stream_result = list(Agent(llm=stream_model, tools=[], memory=stream_memory).run_stream("question"))[-1]

        # 异步非流式
        async_memory = InMemoryConversation()
        async_model = ScriptedAsyncChatModel([
            LLMResponse(content="filtered", tool_calls=None, finish_reason="content_filter"),
        ])
        async_result = asyncio.run(AsyncAgent(llm=async_model, tools=[], memory=async_memory).run_async("question"))

        # 异步流式
        async_stream_memory = InMemoryConversation()
        async_stream_model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(content="filtered", finish_reason="content_filter")],
        ])
        async def run():
            events = []
            agent = AsyncAgent(llm=async_stream_model, tools=[], memory=async_stream_memory)
            async for event in agent.run_stream_async("question"):
                events.append(event)
            return events[-1]
        async_stream_result = asyncio.run(run())

        # 验证一致性
        for result, memory, name in [
            (sync_result, sync_memory, "sync"),
            (stream_result, stream_memory, "stream"),
            (async_result, async_memory, "async"),
            (async_stream_result, async_stream_memory, "async_stream"),
        ]:
            stop_reason = result["stop_reason"] if isinstance(result, dict) else result.stop_reason
            content = result["content"] if isinstance(result, dict) else result.content

            assert stop_reason == "incomplete", f"{name}: stop_reason should be incomplete"
            assert content == "filtered", f"{name}: content should be preserved"
            assert len(memory.get_context()) == 0, f"{name}: memory should be empty"

    def test_all_paths_final_hook_cannot_mutate_stored_content(self) -> None:
        """四种路径的 final hook 都不能变异存储的 assistant content"""
        from conftest import (
            ScriptedAsyncChatModel,
            ScriptedAsyncStreamingChatModel,
            ScriptedChatModel,
            ScriptedStreamingChatModel,
        )

        # 同步非流式
        sync_memory = InMemoryConversation()
        sync_hooks: list[dict] = []
        sync_model = ScriptedChatModel([
            LLMResponse(content="original", tool_calls=None, finish_reason="stop"),
        ])
        sync_result = Agent(
            llm=sync_model,
            tools=[],
            memory=sync_memory,
            hooks={"on_final": sync_hooks.append},
        ).run("question")
        sync_hooks[0]["final_answer"] = "mutated"

        # 同步流式
        stream_memory = InMemoryConversation()
        stream_hooks: list[dict] = []
        stream_model = ScriptedStreamingChatModel([], [
            [StreamChunk(content="original", finish_reason="stop")],
        ])
        stream_events = list(Agent(
            llm=stream_model,
            tools=[],
            memory=stream_memory,
            hooks={"on_final": stream_hooks.append},
        ).run_stream("question"))
        stream_hooks[0]["final_answer"] = "mutated"

        # 异步非流式
        async_memory = InMemoryConversation()
        async_hooks: list[dict] = []
        async_model = ScriptedAsyncChatModel([
            LLMResponse(content="original", tool_calls=None, finish_reason="stop"),
        ])
        async def run_async():
            result = await AsyncAgent(
                llm=async_model,
                tools=[],
                memory=async_memory,
                hooks={"on_final": async_hooks.append},
            ).run_async("question")
            async_hooks[0]["final_answer"] = "mutated"
            return result
        async_result = asyncio.run(run_async())

        # 异步流式
        async_stream_memory = InMemoryConversation()
        async_stream_hooks: list[dict] = []
        async_stream_model = ScriptedAsyncStreamingChatModel([
            [StreamChunk(content="original", finish_reason="stop")],
        ])
        async def run_async_stream():
            events = []
            agent = AsyncAgent(
                llm=async_stream_model,
                tools=[],
                memory=async_stream_memory,
                hooks={"on_final": async_stream_hooks.append},
            )
            async for event in agent.run_stream_async("question"):
                events.append(event)
            async_stream_hooks[0]["final_answer"] = "mutated"
            return events[-1]
        async_stream_result = asyncio.run(run_async_stream())

        # 验证一致性：变异不应该影响存储的内容
        for result, memory, name in [
            (sync_result, sync_memory, "sync"),
            (stream_events[-1], stream_memory, "stream"),
            (async_result, async_memory, "async"),
            (async_stream_result, async_stream_memory, "async_stream"),
        ]:
            content = result["content"] if isinstance(result, dict) else result.content
            assert content == "original", f"{name}: result content should not be mutated"
            assert memory.get_context()[1]["content"] == "original", f"{name}: stored content should not be mutated"