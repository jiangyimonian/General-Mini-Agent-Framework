"""测试 Agent ReAct 循环"""

from unittest.mock import Mock, patch
import pytest

from core.llm import LLMResponse, StreamChunk, ToolCall
from core.tools import tool
from core.agent import Agent, AgentResult
from conftest import ScriptedChatModel


def make_mock_llm(responses: list[LLMResponse]):
    """创建一个返回预设响应的 Mock LLM"""
    mock = Mock()
    mock.chat.side_effect = responses
    return mock


class TestAgentBasic:
    def test_direct_answer(self):
        """Agent 直接回答，不需要工具"""
        @tool
        def dummy() -> str:
            return "ok"

        mock_llm = make_mock_llm([
            LLMResponse(content="[FINAL] 你好！", tool_calls=None, usage={}),
        ])
        agent = Agent(llm=mock_llm, tools=[dummy])
        result = agent.run("你好")

        assert result.content == "你好！"
        assert result.iterations == 1

    def test_accepts_scripted_chat_model_with_completed_result(self):
        model = ScriptedChatModel([
            LLMResponse(content="[FINAL] complete", tool_calls=None, usage={}),
        ])

        result = Agent(llm=model, tools=[]).run("test")

        assert result.content == "complete"
        assert result.stop_reason == "completed"
        assert result.error is None

    def test_single_tool_call(self):
        """Agent 调用一次工具后得出答案"""
        @tool(description="计算")
        def add(a: int, b: int) -> int:
            return a + b

        mock_llm = make_mock_llm([
            # 第一次：调工具
            LLMResponse(
                content="Thought: 我需要计算",
                tool_calls=[
                    ToolCall(id="call_1", name="add", arguments={"a": 3, "b": 5})
                ],
                usage={},
            ),
            # 第二次：给出答案
            LLMResponse(
                content="[FINAL] 结果是 8",
                tool_calls=None,
                usage={},
            ),
        ])

        agent = Agent(llm=mock_llm, tools=[add], max_iterations=5)
        result = agent.run("3+5=?")

        assert result.content == "结果是 8"
        assert result.iterations == 2
        assert len(result.trace) == 2
        assert result.trace[0]["tool"] == "add"
        assert result.trace[0]["observation"] == "8"

    def test_tool_call_trace_entry_has_required_type(self):
        @tool
        def add(a: int, b: int) -> int:
            return a + b

        mock_llm = make_mock_llm([
            LLMResponse(
                content="计算",
                tool_calls=[ToolCall(id="call_1", name="add", arguments={"a": 1, "b": 2})],
                usage={},
            ),
            LLMResponse(content="[FINAL] 3", tool_calls=None, usage={}),
        ])

        result = Agent(llm=mock_llm, tools=[add]).run("1+2=?")

        assert result.trace[0]["type"] == "tool_call"

    def test_final_trace_entry_has_required_type(self):
        mock_llm = make_mock_llm([
            LLMResponse(content="[FINAL] 完成", tool_calls=None, usage={}),
        ])

        result = Agent(llm=mock_llm, tools=[]).run("测试")

        assert result.trace[0]["type"] == "final_answer"

    def test_multi_tool_call_chain(self):
        """Agent 连续调多个工具（链式推理）"""
        @tool
        def add(a: int, b: int) -> int:
            return a + b
        @tool
        def multiply(a: int, b: int) -> int:
            return a * b

        mock_llm = make_mock_llm([
            LLMResponse(content="先加", tool_calls=[
                ToolCall(id="c1", name="add", arguments={"a": 3, "b": 5})
            ], usage={}),
            LLMResponse(content="再加", tool_calls=[
                ToolCall(id="c2", name="add", arguments={"a": 8, "b": 2})
            ], usage={}),
            LLMResponse(content="再乘", tool_calls=[
                ToolCall(id="c3", name="multiply", arguments={"a": 10, "b": 4})
            ], usage={}),
            LLMResponse(content="[FINAL] 40", tool_calls=None, usage={}),
        ])

        agent = Agent(llm=mock_llm, tools=[add, multiply], max_iterations=10)
        result = agent.run("(3+5+2)*4=?")

        assert result.content == "40"
        assert result.iterations == 4
        # trace 包含 3 次工具调用 + 1 次最终答案
        tool_steps = [s for s in result.trace if "tool" in s]
        assert len(tool_steps) == 3

    def test_unknown_tool(self):
        """Agent 调用不存在的工具"""
        mock_llm = make_mock_llm([
            LLMResponse(content="调用未知工具", tool_calls=[
                ToolCall(id="c1", name="nonexistent", arguments={})
            ], usage={}),
            LLMResponse(content="[FINAL] 完成", tool_calls=None, usage={}),
        ])

        agent = Agent(llm=mock_llm, tools=[], max_iterations=5)
        result = agent.run("测试")

        assert "nonexistent" in result.trace[0]["observation"]
        assert result.trace[0]["error_code"] == "unknown_tool"
        assert result.iterations == 2

    def test_max_iterations_exceeded(self):
        """达到最大迭代次数仍无答案"""
        @tool
        def loop() -> str:
            return "继续"

        # 一直返回工具调用，不给出 Final Answer
        responses = [
            LLMResponse(content="继续循环", tool_calls=[
                ToolCall(id=f"c{i}", name="loop", arguments={})
            ], usage={})
            for i in range(5)
        ]
        mock_llm = make_mock_llm(responses)
        agent = Agent(llm=mock_llm, tools=[loop], max_iterations=3)
        result = agent.run("循环测试")

        assert "已达最大迭代次数" in result.content
        assert result.stop_reason == "max_iterations"

    def test_run_stream_trace_entries_have_required_types(self):
        @tool
        def add(a: int, b: int) -> int:
            return a + b

        mock_llm = Mock()
        mock_llm.chat_stream.side_effect = [
            [StreamChunk(
                tool_call_id="call_1",
                tool_name="add",
                tool_args='{"a": 1, "b": 2}',
                finish_reason="tool_calls",
            )],
            [StreamChunk(content="[FINAL] 3", finish_reason="stop")],
        ]

        events = list(Agent(llm=mock_llm, tools=[add]).run_stream("1+2=?"))

        assert [event["type"] for event in events[-1]["trace"]] == [
            "tool_call",
            "final_answer",
        ]

    def test_run_stream_max_iterations_done_event_has_stop_reason(self):
        mock_llm = Mock()
        mock_llm.chat_stream.return_value = []

        events = list(Agent(llm=mock_llm, tools=[], max_iterations=2).run_stream("测试"))

        assert events[-1]["type"] == "done"
        assert events[-1]["stop_reason"] == "max_iterations"

    def test_empty_response(self):
        """LLM 返回空响应"""
        mock_llm = make_mock_llm([
            LLMResponse(content=None, tool_calls=None, usage={}),
            LLMResponse(content="[FINAL] 恢复", tool_calls=None, usage={}),
        ])

        agent = Agent(llm=mock_llm, tools=[], max_iterations=5)
        result = agent.run("测试")
        assert result.content == "恢复"

    def test_usage_accumulation(self):
        """多次调用的 token 用量应累加"""
        @tool
        def dummy() -> str:
            return "ok"

        mock_llm = make_mock_llm([
            LLMResponse(content="调工具", tool_calls=[
                ToolCall(id="c1", name="dummy", arguments={})
            ], usage={"prompt_tokens": 10, "completion_tokens": 20}),
            LLMResponse(content="[FINAL] 完成", tool_calls=None,
                        usage={"prompt_tokens": 5, "completion_tokens": 10}),
        ])

        agent = Agent(llm=mock_llm, tools=[dummy])
        result = agent.run("测试")
        assert result.usage["prompt_tokens"] == 15
        assert result.usage["completion_tokens"] == 30


class TestAgentHooks:
    def test_on_tool_call_hook(self):
        """hooks.on_tool_call 应被调用"""
        @tool
        def add(a: int, b: int) -> int:
            return a + b

        mock_llm = make_mock_llm([
            LLMResponse(content="计算", tool_calls=[
                ToolCall(id="c1", name="add", arguments={"a": 1, "b": 2})
            ], usage={}),
            LLMResponse(content="[FINAL] 3", tool_calls=None, usage={}),
        ])

        hook_data = []
        agent = Agent(
            llm=mock_llm, tools=[add],
            hooks={"on_tool_call": lambda d: hook_data.append(d)},
        )
        agent.run("测试")

        assert len(hook_data) == 1
        assert hook_data[0]["tool"] == "add"

    def test_on_final_hook(self):
        """hooks.on_final 应被调用"""
        mock_llm = make_mock_llm([
            LLMResponse(content="[FINAL] 完成", tool_calls=None, usage={}),
        ])

        hook_data = []
        agent = Agent(
            llm=mock_llm, tools=[],
            hooks={"on_final": lambda d: hook_data.append(d)},
        )
        agent.run("测试")

        assert len(hook_data) == 1
        assert hook_data[0]["final_answer"] == "完成"


class TestAgentToolIsolation:
    def test_agents_send_only_their_own_tool_schemas(self):
        @tool
        def first_only() -> str:
            return "first"

        @tool
        def second_only() -> str:
            return "second"

        first_model = ScriptedChatModel([
            LLMResponse(content="[FINAL] first", tool_calls=None, usage={}),
        ])
        second_model = ScriptedChatModel([
            LLMResponse(content="[FINAL] second", tool_calls=None, usage={}),
        ])
        first_agent = Agent(llm=first_model, tools=[first_only])
        second_agent = Agent(llm=second_model, tools=[second_only])

        first_agent.run("one")
        second_agent.run("two")

        first_names = [
            schema["function"]["name"] for schema in first_model.calls[0][1]
        ]
        second_names = [
            schema["function"]["name"] for schema in second_model.calls[0][1]
        ]
        assert first_names == ["first_only"]
        assert second_names == ["second_only"]

    def test_agent_cannot_execute_tool_owned_by_another_agent(self):
        calls = 0

        def private_tool() -> str:
            nonlocal calls
            calls += 1
            return "private result"

        owner = Agent(
            llm=ScriptedChatModel([
                LLMResponse(content="[FINAL] owner", tool_calls=None, usage={}),
            ]),
            tools=[private_tool],
        )
        outsider_model = ScriptedChatModel([
            LLMResponse(
                content="try private",
                tool_calls=[ToolCall(id="call_1", name="private_tool", arguments={})],
                usage={},
            ),
            LLMResponse(content="[FINAL] done", tool_calls=None, usage={}),
        ])
        outsider = Agent(llm=outsider_model, tools=[])

        owner.run("owner")
        result = outsider.run("outsider")

        assert calls == 0
        assert result.trace[0]["error_code"] == "unknown_tool"

    def test_streaming_agents_expose_only_local_tools_and_reject_leaked_tools(self):
        @tool
        def first_only() -> str:
            return "first"

        @tool
        def second_only() -> str:
            return "second"

        first_model = Mock()
        first_model.chat_stream.side_effect = [
            [StreamChunk(content="[FINAL] first", finish_reason="stop")],
        ]
        second_model = Mock()
        second_model.chat_stream.side_effect = [
            [StreamChunk(
                tool_call_id="call_1",
                tool_name="first_only",
                tool_args="{}",
                finish_reason="tool_calls",
            )],
            [StreamChunk(content="[FINAL] second", finish_reason="stop")],
        ]

        first_agent = Agent(llm=first_model, tools=[first_only])
        second_agent = Agent(llm=second_model, tools=[second_only])

        first_events = list(first_agent.run_stream("one"))
        second_events = list(second_agent.run_stream("two"))

        first_schemas = first_model.chat_stream.call_args_list[0].kwargs["tools"]
        second_schemas = second_model.chat_stream.call_args_list[0].kwargs["tools"]
        assert [schema["function"]["name"] for schema in first_schemas] == ["first_only"]
        assert [schema["function"]["name"] for schema in second_schemas] == ["second_only"]
        assert "first_only" not in [schema["function"]["name"] for schema in second_schemas]
        assert second_events[-1]["trace"][0]["error_code"] == "unknown_tool"
        assert first_events[-1]["content"] == "first"
