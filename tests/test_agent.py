"""测试 Agent ReAct 循环"""

from unittest.mock import Mock, patch
import pytest

from core.llm import LLMResponse, ToolCall
from core.tools import tool, ToolRegistry
from core.agent import Agent, AgentResult


def make_mock_llm(responses: list[LLMResponse]):
    """创建一个返回预设响应的 Mock LLM"""
    mock = Mock()
    mock.chat.side_effect = responses
    return mock


class TestAgentBasic:
    def setup_method(self):
        ToolRegistry.clear()

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

        assert "未找到工具" in result.trace[0]["observation"]
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
    def setup_method(self):
        ToolRegistry.clear()

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
