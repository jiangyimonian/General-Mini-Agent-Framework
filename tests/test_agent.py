"""测试 Agent ReAct 循环"""

from unittest.mock import Mock

import pytest
from conftest import ScriptedChatModel, ScriptedStreamingChatModel

from core.agent import Agent
from core.llm import LLMResponse, ModelRequestError, StreamChunk, ToolCall, ToolCallDelta
from core.tools import Tool, tool


@pytest.mark.parametrize(
    "finish_reason",
    ["length", "content_filter", "future_reason", ""],
)
def test_run_stream_maps_non_terminal_finishes_to_incomplete(
    finish_reason: str,
) -> None:
    model = ScriptedStreamingChatModel(
        [],
        [[StreamChunk(content="partial", finish_reason=finish_reason)]],
    )

    events = list(Agent(llm=model, tools=[]).run_stream("question"))

    assert [event["type"] for event in events] == [
        "iteration_start",
        "thought_chunk",
        "done",
    ]
    assert events[-1]["stop_reason"] == "incomplete"
    assert events[-1]["content"] == "partial"
    assert events[-1]["finish_reason"] == finish_reason


def test_run_stream_completed_event_keys_and_order() -> None:
    model = ScriptedStreamingChatModel(
        [],
        [[StreamChunk(content="answer", finish_reason="stop")]],
    )

    events = list(Agent(llm=model, tools=[]).run_stream("question"))

    assert [event["type"] for event in events] == [
        "iteration_start",
        "thought_chunk",
        "final_answer",
        "done",
    ]
    assert events[1] == {
        "type": "thought_chunk",
        "iteration": 0,
        "text": "answer",
    }
    assert events[-1]["stop_reason"] == "completed"
    assert events[-1]["iterations"] == 1
    assert sum(event["type"] == "done" for event in events) == 1


def test_run_stream_converts_model_error_to_terminal_events() -> None:
    error = ModelRequestError(
        "invalid model stream sk-secret",
        status_code=502,
        error_code="stream_protocol_error",
    )
    model = ScriptedStreamingChatModel([], [error])

    events = list(Agent(llm=model, tools=[]).run_stream("question"))

    assert [event["type"] for event in events] == [
        "iteration_start",
        "model_error",
        "done",
    ]
    assert events[1]["error_code"] == "stream_protocol_error"
    assert events[1]["status_code"] == 502
    assert "sk-secret" not in str(events)
    assert events[-1]["stop_reason"] == "model_error"
    assert sum(event["type"] == "done" for event in events) == 1


def test_run_stream_reconstructs_multiple_tools_and_executes_by_index() -> None:
    calls: list[str] = []

    @tool
    def first(value: int) -> str:
        calls.append("first")
        return str(value)

    @tool
    def second(value: int) -> str:
        calls.append("second")
        return str(value)

    model = ScriptedStreamingChatModel([], [
        [
            StreamChunk(tool_calls=[
                ToolCallDelta(1, "c2", "second", '{"value":'),
                ToolCallDelta(0, "c1", "first", '{"value":'),
            ]),
            StreamChunk(
                tool_calls=[
                    ToolCallDelta(0, arguments="1}"),
                    ToolCallDelta(1, arguments="2}"),
                ],
                finish_reason="tool_calls",
            ),
        ],
        [StreamChunk(content="done", finish_reason="stop")],
    ])

    events = list(Agent(llm=model, tools=[first, second]).run_stream("question"))

    assert calls == ["first", "second"]
    assert [event["name"] for event in events if event["type"] == "tool_call"] == [
        "first",
        "second",
    ]
    second_request = model.stream_calls[1][0]
    assistant = second_request[-3]
    assert assistant["role"] == "assistant"
    assert [call["id"] for call in assistant["tool_calls"]] == ["c1", "c2"]
    assert [message["tool_call_id"] for message in second_request[-2:]] == ["c1", "c2"]


def test_run_stream_returns_invalid_json_to_model_for_correction() -> None:
    executions = 0

    @tool
    def add(a: int, b: int) -> int:
        nonlocal executions
        executions += 1
        return a + b

    model = ScriptedStreamingChatModel([], [
        [StreamChunk(
            tool_calls=[ToolCallDelta(0, "c1", "add", '{"a":1')],
            finish_reason="tool_calls",
        )],
        [StreamChunk(content="corrected", finish_reason="stop")],
    ])

    events = list(Agent(llm=model, tools=[add]).run_stream("question"))
    tool_event = next(event for event in events if event["type"] == "tool_call")
    observation = next(event for event in events if event["type"] == "observation")

    assert executions == 0
    assert tool_event["arguments"] is None
    assert tool_event["raw_arguments"] == '{"a":1'
    assert tool_event["error_code"] == "invalid_arguments"
    assert observation["error_code"] == "invalid_arguments"
    assert model.stream_calls[1][0][-1]["tool_call_id"] == "c1"


@pytest.mark.parametrize(
    "chunks",
    [
        [StreamChunk(
            tool_calls=[ToolCallDelta(0, "", "tool_name", "{}")],
            finish_reason="tool_calls",
        )],
        [StreamChunk(
            tool_calls=[ToolCallDelta(0, "c1", "", "{}")],
            finish_reason="tool_calls",
        )],
        [
            StreamChunk(tool_calls=[ToolCallDelta(0, "c1", "tool_name", "")]),
            StreamChunk(
                tool_calls=[ToolCallDelta(0, "c2", "", "{}")],
                finish_reason="tool_calls",
            ),
        ],
        [
            StreamChunk(tool_calls=[ToolCallDelta(0, "c1", "first", "")]),
            StreamChunk(
                tool_calls=[ToolCallDelta(0, "", "second", "{}")],
                finish_reason="tool_calls",
            ),
        ],
        [StreamChunk(finish_reason="tool_calls")],
    ],
)
def test_run_stream_rejects_invalid_tool_call_metadata(
    chunks: list[StreamChunk],
) -> None:
    executions = 0

    def tool_name() -> str:
        nonlocal executions
        executions += 1
        return "ok"

    model = ScriptedStreamingChatModel([], [chunks])

    events = list(Agent(llm=model, tools=[tool_name]).run_stream("question"))

    assert executions == 0
    assert [event["type"] for event in events] == [
        "iteration_start",
        "model_error",
        "done",
    ]
    assert events[1]["error_code"] == "stream_protocol_error"
    assert events[-1]["stop_reason"] == "model_error"


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
        assert result.trace[-1]["type"] == "final"

    def test_accepts_scripted_chat_model_with_completed_result(self):
        model = ScriptedChatModel([
            LLMResponse(content="[FINAL] complete", tool_calls=None, usage={}),
        ])

        result = Agent(llm=model, tools=[]).run("test")

        assert result.content == "complete"
        assert result.stop_reason == "completed"
        assert result.error is None
        assert result.trace[-1]["type"] == "final"

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

        assert result.trace[0]["type"] == "final"

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
        assert result.trace[-1] == {
            "type": "max_iterations",
            "iteration": 3,
            "message": "maximum iterations reached",
        }

    def test_run_stream_trace_entries_have_required_types(self):
        @tool
        def add(a: int, b: int) -> int:
            return a + b

        mock_llm = Mock()
        mock_llm.chat_stream.side_effect = [
            [StreamChunk(
                tool_calls=[ToolCallDelta(
                    index=0,
                    id="call_1",
                    name="add",
                    arguments='{"a": 1, "b": 2}',
                )],
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
        @tool
        def keep_going() -> str:
            return "continue"

        mock_llm = Mock()
        mock_llm.chat_stream.side_effect = [
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "call_1", "keep_going", "{}")],
                finish_reason="tool_calls",
            )],
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "call_2", "keep_going", "{}")],
                finish_reason="tool_calls",
            )],
        ]

        events = list(
            Agent(llm=mock_llm, tools=[keep_going], max_iterations=2).run_stream("测试")
        )

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


def test_unknown_tool_is_recorded_as_a_structured_error() -> None:
    model = ScriptedChatModel([
        LLMResponse(content="try", tool_calls=[ToolCall("c1", "missing", {})]),
        LLMResponse(content="done", tool_calls=None),
    ])

    result = Agent(llm=model, tools=[]).run("question")

    assert result.stop_reason == "completed"
    assert result.trace[0]["type"] == "tool_call"
    assert result.trace[0]["error_code"] == "unknown_tool"
    assert "unknown tool: missing" in result.trace[0]["observation"]


def test_tool_exception_is_recorded_and_model_can_finish() -> None:
    def explode() -> str:
        raise RuntimeError("boom")

    model = ScriptedChatModel([
        LLMResponse(content="call", tool_calls=[ToolCall("c1", "explode", {})]),
        LLMResponse(content="recovered", tool_calls=None),
    ])

    result = Agent(llm=model, tools=[Tool(explode)]).run("question")

    assert result.content == "recovered"
    assert result.trace[0]["error_code"] == "execution_failed"


def test_model_error_returns_trace_and_does_not_expose_secret() -> None:
    class FailingModel:
        def chat(self, messages, *, tools=None):
            raise ModelRequestError(
                "request failed Authorization: Bearer sk-secret",
                status_code=503,
                endpoint="/chat/completions",
            )

    result = Agent(llm=FailingModel(), tools=[]).run("question")

    assert result.stop_reason == "model_error"
    assert result.error == "model request failed"
    assert result.trace[-1]["type"] == "model_error"
    assert "sk-secret" not in str(result.trace)


def test_second_model_call_receives_tool_result() -> None:
    model = ScriptedChatModel([
        LLMResponse(
            content="use add",
            tool_calls=[ToolCall("c1", "add", {"a": 2, "b": 3})],
        ),
        LLMResponse(content="5", tool_calls=None),
    ])

    result = Agent(
        llm=model,
        tools=[Tool(lambda a, b: a + b, name="add")],
    ).run("2+3")

    assert result.content == "5"
    assert model.calls[1][0][-1] == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": "5",
    }


def test_agent_config_is_exported_from_core() -> None:
    from core import AgentConfig

    assert AgentConfig().max_iterations == 10


def test_run_includes_supplied_legacy_memory_context() -> None:
    class LegacyMemory:
        def get_context(self):
            return [{"role": "assistant", "content": "legacy context"}]

    model = ScriptedChatModel([
        LLMResponse(content="done", tool_calls=None),
    ])

    Agent(llm=model, tools=[], memory=LegacyMemory()).run("question")

    assert model.calls[0][0][1:] == [
        {"role": "assistant", "content": "legacy context"},
        {"role": "user", "content": "question"},
    ]


def test_run_stream_includes_supplied_legacy_memory_context() -> None:
    class LegacyMemory:
        def get_context(self):
            return [{"role": "assistant", "content": "legacy context"}]

    model = Mock()
    model.chat_stream.return_value = [
        StreamChunk(content="done", finish_reason="stop"),
    ]

    list(Agent(llm=model, tools=[], memory=LegacyMemory()).run_stream("question"))

    assert model.chat_stream.call_args.args[0][1:] == [
        {"role": "assistant", "content": "legacy context"},
        {"role": "user", "content": "question"},
    ]


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
                tool_calls=[ToolCallDelta(0, "call_1", "first_only", "{}")],
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
