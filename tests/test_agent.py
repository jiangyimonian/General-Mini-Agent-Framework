"""测试 Agent ReAct 循环"""

from copy import deepcopy
from typing import Any
from unittest.mock import Mock

import pytest
from conftest import ScriptedChatModel, ScriptedStreamingChatModel

from general_mini_agent.agent import Agent
from general_mini_agent.context import ContextBudgetExceeded
from general_mini_agent.llm import LLMResponse, ModelRequestError, StreamChunk, ToolCall, ToolCallDelta
from general_mini_agent.long_term_memory import (
    MemoryNamespace,
    MemoryQuery,
    MemoryStoreError,
    create_memory_record,
)
from general_mini_agent.memory import InMemoryConversation
from general_mini_agent.tools import Tool, tool


class RecordingContextPolicy:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []

    def prepare(self, messages, *, tools=None):
        self.calls.append(deepcopy((list(messages), list(tools or []))))
        return deepcopy(list(messages))


class RejectingContextPolicy:
    def prepare(self, messages, *, tools=None):
        raise ContextBudgetExceeded(input_tokens=12, input_budget=10)


LONG_TERM_NAMESPACE = MemoryNamespace("user-1", "conversation-1", "agent-1")
LONG_TERM_QUERY = MemoryQuery("python", LONG_TERM_NAMESPACE)


class RecordingStore:
    def __init__(self, records) -> None:
        self.records = records
        self.queries = []
        self.mutations = []

    def query(self, query):
        self.queries.append(query)
        return self.records

    def store(self, *args, **kwargs):
        self.mutations.append("store")

    def update(self, *args, **kwargs):
        self.mutations.append("update")

    def delete(self, *args, **kwargs):
        self.mutations.append("delete")

    def clear(self, *args, **kwargs):
        self.mutations.append("clear")


class FailOnAccessStore:
    def __getattribute__(self, name):
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        raise AssertionError(f"unexpected long-term memory access: {name}")


class FailingQueryStore:
    def query(self, query):
        raise MemoryStoreError("query", backend="test")


def test_run_retrieves_once_and_keeps_long_term_store_read_only() -> None:
    store = RecordingStore([
        create_memory_record("prefers Python", LONG_TERM_NAMESPACE),
    ])
    model = ScriptedChatModel([LLMResponse("done", None)])

    Agent(model, long_term_memory=store).run(
        "question",
        memory_query=LONG_TERM_QUERY,
    )

    assert store.queries == [LONG_TERM_QUERY]
    assert "prefers Python" in model.calls[0][0][1]["content"]
    assert store.mutations == []


def test_run_without_query_never_accesses_long_term_store() -> None:
    model = ScriptedChatModel([LLMResponse("done", None)])

    Agent(model, long_term_memory=FailOnAccessStore()).run("question")

    assert model.calls


def test_memory_error_stops_sync_run_before_model_access() -> None:
    model = ScriptedChatModel([])

    result = Agent(model, long_term_memory=FailingQueryStore()).run(
        "question",
        memory_query=LONG_TERM_QUERY,
    )

    assert result.stop_reason == "memory_error"
    assert model.calls == []


def test_stream_retrieval_and_memory_error_match_sync_contract() -> None:
    memory = InMemoryConversation()
    model = ScriptedStreamingChatModel([], [])

    events = list(
        Agent(
            model,
            memory=memory,
            long_term_memory=FailingQueryStore(),
        ).run_stream("question", memory_query=LONG_TERM_QUERY)
    )

    assert events[-1]["stop_reason"] == "memory_error"
    assert model.stream_calls == []
    assert memory.get_context() == []


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


def test_run_stream_counts_latest_usage_once_per_request() -> None:
    @tool
    def noop() -> str:
        return "ok"

    model = ScriptedStreamingChatModel([], [
        [
            StreamChunk(usage={"prompt_tokens": 3, "total_tokens": 3}),
            StreamChunk(
                tool_calls=[ToolCallDelta(0, "c1", "noop", "{}")],
                finish_reason="tool_calls",
            ),
            StreamChunk(
                usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
            ),
        ],
        [
            StreamChunk(content="done", finish_reason="stop"),
            StreamChunk(
                usage={"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}
            ),
        ],
    ])

    done = list(Agent(llm=model, tools=[noop]).run_stream("question"))[-1]

    assert done["usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
    }


def test_run_stream_retains_usage_seen_before_model_error() -> None:
    class YieldThenFailModel:
        def chat_stream(self, messages, *, tools=None):
            yield StreamChunk(usage={"prompt_tokens": 4, "total_tokens": 4})
            raise ModelRequestError("stream failed")

    events = list(Agent(llm=YieldThenFailModel(), tools=[]).run_stream("question"))

    assert events[-1]["stop_reason"] == "model_error"
    assert events[-1]["usage"] == {"prompt_tokens": 4, "total_tokens": 4}


def test_run_stream_trace_and_hooks_match_public_tool_events() -> None:
    tool_hooks: list[dict] = []
    final_hooks: list[dict] = []
    model = ScriptedStreamingChatModel([], [
        [StreamChunk(
            tool_calls=[ToolCallDelta(0, "c1", "missing", "{}")],
            finish_reason="tool_calls",
        )],
        [StreamChunk(content="recovered", finish_reason="stop")],
    ])
    agent = Agent(
        llm=model,
        tools=[],
        hooks={
            "on_tool_call": tool_hooks.append,
            "on_final": final_hooks.append,
        },
    )

    done = list(agent.run_stream("question"))[-1]
    tool_trace = done["trace"][0]

    assert tool_trace["tool_call_id"] == "c1"
    assert tool_trace["index"] == 0
    assert tool_trace["raw_arguments"] == "{}"
    assert tool_trace["error_code"] == "unknown_tool"
    assert tool_hooks == [tool_trace]
    assert len(final_hooks) == 1


def test_run_stream_does_not_call_final_hook_for_incomplete_response() -> None:
    final_hooks: list[dict] = []
    model = ScriptedStreamingChatModel(
        [],
        [[StreamChunk(content="partial", finish_reason="length")]],
    )

    list(Agent(llm=model, tools=[], hooks={"on_final": final_hooks.append}).run_stream("q"))

    assert final_hooks == []


def test_run_state_is_isolated_between_invocations() -> None:
    """验证同步 run() 的状态在多次调用间隔离。"""
    model = ScriptedChatModel([
        LLMResponse(content="first", tool_calls=None, usage={"total_tokens": 2}),
        LLMResponse(content="second", tool_calls=None, usage={"total_tokens": 3}),
    ])
    agent = Agent(llm=model, tools=[])

    first_result = agent.run("one")
    second_result = agent.run("two")

    assert first_result.content == "first"
    assert second_result.content == "second"
    assert second_result.usage == {"total_tokens": 3}
    assert len(second_result.trace) == 1


def test_run_stream_state_is_isolated_between_invocations() -> None:
    model = ScriptedStreamingChatModel([], [
        [StreamChunk(content="first", finish_reason="stop", usage={"total_tokens": 2})],
        [StreamChunk(content="second", finish_reason="stop", usage={"total_tokens": 3})],
    ])
    agent = Agent(llm=model, tools=[])

    first_done = list(agent.run_stream("one"))[-1]
    second_done = list(agent.run_stream("two"))[-1]

    assert first_done["content"] == "first"
    assert second_done["content"] == "second"
    assert second_done["usage"] == {"total_tokens": 3}
    assert len(second_done["trace"]) == 1


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
        """LLM 返回空响应应该返回 model_error"""
        mock_llm = make_mock_llm([
            LLMResponse(content=None, tool_calls=None, usage={}),
        ])

        agent = Agent(llm=mock_llm, tools=[], max_iterations=5)
        result = agent.run("测试")
        assert result.stop_reason == "model_error"
        assert result.content == ""
        assert "empty response" in result.error.lower()

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


def test_two_tools_in_one_turn_builds_canonical_message_sequence() -> None:
    """验证多工具调用的消息序列符合协议规范：一次 assistant 包含所有工具调用，然后所有工具结果"""
    from conftest import StrictScriptedChatModel

    model = StrictScriptedChatModel([
        LLMResponse(
            content="use both tools",
            tool_calls=[
                ToolCall("c1", "add", {"a": 2, "b": 3}),
                ToolCall("c2", "multiply", {"a": 4, "b": 5}),
            ],
        ),
        LLMResponse(content="done", tool_calls=None),
    ])

    result = Agent(
        llm=model,
        tools=[
            Tool(lambda a, b: a + b, name="add"),
            Tool(lambda a, b: a * b, name="multiply"),
        ],
    ).run("calculate")

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


def test_agent_config_is_exported_from_core() -> None:
    from general_mini_agent import AgentConfig

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


def test_run_prepares_every_request_and_commits_completed_exchange() -> None:
    @tool
    def lookup(query: str) -> str:
        return f"result for {query}"

    policy = RecordingContextPolicy()
    memory = InMemoryConversation()
    model = ScriptedChatModel([
        LLMResponse(
            content="",
            tool_calls=[ToolCall("call-1", "lookup", {"query": "python"})],
        ),
        LLMResponse(content="final answer", tool_calls=None),
    ])

    result = Agent(
        llm=model,
        tools=[lookup],
        memory=memory,
        context_policy=policy,
    ).run("question")

    assert result.stop_reason == "completed"
    assert len(policy.calls) == 2
    assert policy.calls[1][0][-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "result for python",
    }
    assert memory.get_context() == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "final answer"},
    ]


def test_run_context_overflow_stops_before_model_request() -> None:
    model = ScriptedChatModel([])
    memory = InMemoryConversation()

    result = Agent(
        llm=model,
        tools=[],
        memory=memory,
        context_policy=RejectingContextPolicy(),
    ).run("sensitive question")

    assert result.stop_reason == "context_budget_exceeded"
    assert result.error == "request context requires 12 tokens; budget is 10"
    assert model.calls == []
    assert memory.get_context() == []


def test_run_non_success_and_final_hook_failure_do_not_write_memory() -> None:
    memory = InMemoryConversation()
    failing_model = Mock()
    failing_model.chat.side_effect = ModelRequestError("offline")

    result = Agent(llm=failing_model, tools=[], memory=memory).run("question")

    assert result.stop_reason == "model_error"
    assert memory.get_context() == []

    model = ScriptedChatModel([LLMResponse(content="answer", tool_calls=None)])
    agent = Agent(
        llm=model,
        tools=[],
        memory=memory,
        hooks={"on_final": Mock(side_effect=RuntimeError("hook failed"))},
    )
    with pytest.raises(RuntimeError, match="hook failed"):
        agent.run("question")
    assert memory.get_context() == []


def test_run_max_iterations_does_not_write_memory() -> None:
    @tool
    def keep_going() -> str:
        return "continue"

    memory = InMemoryConversation()
    model = ScriptedChatModel([
        LLMResponse(
            content="",
            tool_calls=[ToolCall("call-1", "keep_going", {})],
        ),
    ])

    result = Agent(
        llm=model,
        tools=[keep_going],
        max_iterations=1,
        memory=memory,
    ).run("question")

    assert result.stop_reason == "max_iterations"
    assert memory.get_context() == []


def test_run_stream_prepares_every_request_and_commits_once() -> None:
    @tool
    def lookup(query: str) -> str:
        return f"result for {query}"

    policy = RecordingContextPolicy()
    memory = InMemoryConversation()
    model = ScriptedStreamingChatModel([], [
        [StreamChunk(
            tool_calls=[ToolCallDelta(0, "call-1", "lookup", '{"query":"python"}')],
            finish_reason="tool_calls",
        )],
        [StreamChunk(content="final answer", finish_reason="stop")],
    ])

    events = list(Agent(
        llm=model,
        tools=[lookup],
        memory=memory,
        context_policy=policy,
    ).run_stream("question"))

    assert events[-1]["stop_reason"] == "completed"
    assert len(policy.calls) == 2
    assert policy.calls[1][0][-1]["tool_call_id"] == "call-1"
    assert memory.get_context() == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "final answer"},
    ]


def test_run_stream_context_overflow_yields_done_without_model_request() -> None:
    model = ScriptedStreamingChatModel([], [])
    memory = InMemoryConversation()

    events = list(Agent(
        llm=model,
        tools=[],
        memory=memory,
        context_policy=RejectingContextPolicy(),
    ).run_stream("sensitive question"))

    assert [event["type"] for event in events] == ["iteration_start", "done"]
    assert events[-1]["stop_reason"] == "context_budget_exceeded"
    assert events[-1]["error"] == "request context requires 12 tokens; budget is 10"
    assert model.stream_calls == []
    assert memory.get_context() == []


def test_abandoned_stream_does_not_write_memory() -> None:
    memory = InMemoryConversation()
    model = ScriptedStreamingChatModel(
        [],
        [[StreamChunk(content="answer", finish_reason="stop")]],
    )
    stream = Agent(llm=model, tools=[], memory=memory).run_stream("question")

    assert next(stream)["type"] == "iteration_start"
    stream.close()

    assert memory.get_context() == []


@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
def test_incomplete_stream_does_not_write_memory(finish_reason: str) -> None:
    memory = InMemoryConversation()
    model = ScriptedStreamingChatModel(
        [],
        [[StreamChunk(content="partial", finish_reason=finish_reason)]],
    )

    events = list(Agent(llm=model, tools=[], memory=memory).run_stream("question"))

    assert events[-1]["stop_reason"] == "incomplete"
    assert memory.get_context() == []


def test_memory_write_failure_is_not_reported_as_model_error() -> None:
    class FailingMemory:
        def get_context(self):
            return []

        def add_messages(self, messages):
            raise RuntimeError("memory write failed")

    model = ScriptedChatModel([LLMResponse(content="answer", tool_calls=None)])

    with pytest.raises(RuntimeError, match="memory write failed"):
        Agent(llm=model, tools=[], memory=FailingMemory()).run("question")


class TestSyncTerminalBehavior:
    """Tests for sync run() terminal behavior and prompt."""

    @pytest.mark.parametrize("finish_reason", ["length", "content_filter", "unknown_reason"])
    def test_sync_run_maps_non_terminal_finish_reason_to_incomplete(
        self, finish_reason: str
    ) -> None:
        """Non-terminal finish reasons should return incomplete result."""
        model = ScriptedChatModel([
            LLMResponse(
                content="partial answer",
                tool_calls=None,
                finish_reason=finish_reason,
            ),
        ])

        result = Agent(llm=model, tools=[]).run("question")

        assert result.stop_reason == "incomplete"
        assert result.content == "partial answer"
        assert result.error is not None
        assert finish_reason in result.error

    def test_sync_run_returns_model_error_on_empty_response(self) -> None:
        """Empty response (no content, no tool calls) should return model_error."""
        model = ScriptedChatModel([
            LLMResponse(content=None, tool_calls=None, finish_reason=None),
        ])

        result = Agent(llm=model, tools=[]).run("question")

        assert result.stop_reason == "model_error"
        assert result.content == ""
        assert "empty response" in result.error.lower()
        assert result.iterations == 0
        # Should not append fake assistant message to messages
        assert len(model.calls) == 1

    def test_sync_run_handles_legacy_model_response_without_finish_reason(self) -> None:
        """Legacy response with text but no finish_reason should complete."""
        model = ScriptedChatModel([
            LLMResponse(content="legacy answer", tool_calls=None, finish_reason=None),
        ])

        result = Agent(llm=model, tools=[]).run("question")

        assert result.stop_reason == "completed"
        assert result.content == "legacy answer"
        assert result.error is None

    def test_sync_run_commits_memory_only_on_completed(self) -> None:
        """Memory should only be committed when stop_reason is completed."""
        from general_mini_agent.memory import InMemoryConversation

        memory = InMemoryConversation()

        # Test incomplete result (length) does not commit memory
        incomplete_model = ScriptedChatModel([
            LLMResponse(content="partial", tool_calls=None, finish_reason="length"),
        ])
        Agent(llm=incomplete_model, tools=[], memory=memory).run("question 1")
        assert memory.get_context() == []

        # Test incomplete result (content_filter) does not commit memory
        content_filter_model = ScriptedChatModel([
            LLMResponse(content="filtered", tool_calls=None, finish_reason="content_filter"),
        ])
        Agent(llm=content_filter_model, tools=[], memory=memory).run("question 2")
        assert memory.get_context() == []

        # Test model_error does not commit memory
        error_model = ScriptedChatModel([
            LLMResponse(content=None, tool_calls=None, finish_reason=None),
        ])
        Agent(llm=error_model, tools=[], memory=memory).run("question 3")
        assert memory.get_context() == []

        # Test completed result commits memory
        completed_model = ScriptedChatModel([
            LLMResponse(content="answer", tool_calls=None, finish_reason="stop"),
        ])
        Agent(llm=completed_model, tools=[], memory=memory).run("question 4")
        assert memory.get_context() == [
            {"role": "user", "content": "question 4"},
            {"role": "assistant", "content": "answer"},
        ]

    def test_sync_run_final_hook_receives_trace_copy(self) -> None:
        """Final hook should receive a copy of the final trace entry."""
        final_hooks: list[dict] = []

        model = ScriptedChatModel([
            LLMResponse(content="final answer", tool_calls=None, finish_reason="stop"),
        ])

        result = Agent(
            llm=model,
            tools=[],
            hooks={"on_final": final_hooks.append},
        ).run("question")

        assert result.stop_reason == "completed"
        assert len(final_hooks) == 1

        # Hook receives the trace entry
        hook_data = final_hooks[0]
        assert hook_data["type"] == "final"
        assert hook_data["final_answer"] == "final answer"

        # Modifying hook data should not affect result trace
        hook_data["modified"] = "test"
        assert "modified" not in result.trace[-1]

    def test_sync_run_final_hook_cannot_mutate_stored_assistant_content(self) -> None:
        """Final hook mutation should not affect stored assistant content in memory."""
        memory = InMemoryConversation()
        final_hooks: list[dict] = []

        model = ScriptedChatModel([
            LLMResponse(content="original answer", tool_calls=None, finish_reason="stop"),
        ])

        result = Agent(
            llm=model,
            tools=[],
            memory=memory,
            hooks={"on_final": final_hooks.append},
        ).run("question")

        assert result.stop_reason == "completed"
        assert len(final_hooks) == 1

        # Mutate hook data
        hook_data = final_hooks[0]
        hook_data["final_answer"] = "mutated answer"

        # Verify stored content is unchanged
        assert result.content == "original answer"
        assert memory.get_context()[1]["content"] == "original answer"


class TestAgentToolAuthorization:
    """Tests for authorization policy integration in Agent."""

    def test_sync_agent_recovers_from_permission_denied(self) -> None:
        """Agent receives permission_denied observation and continues."""
        calls = []

        @tool
        def restricted(value: str) -> str:
            calls.append(value)
            return f"executed:{value}"

        class DenyPolicy:
            def authorize(self, request: Any) -> Any:
                from general_mini_agent.tools import ToolAuthorizationDecision

                return ToolAuthorizationDecision(allowed=False, reason="blocked")

        model = ScriptedChatModel([
            LLMResponse(
                content="try tool",
                tool_calls=[ToolCall("c1", "restricted", {"value": "test"})],
            ),
            LLMResponse(content="recovered", tool_calls=None),
        ])

        result = Agent(
            llm=model,
            tools=[restricted],
            tool_authorization_policy=DenyPolicy(),
        ).run("question")

        assert result.stop_reason == "completed"
        assert result.content == "recovered"
        assert calls == []
        assert result.trace[0]["error_code"] == "permission_denied"
        tool_message = model.calls[1][0][-1]
        assert tool_message["role"] == "tool"
        assert "permission denied" in tool_message["content"].lower()

    def test_streaming_agent_uses_deterministic_json_observation(self) -> None:
        """Structured tool results use identical JSON across observation and trace."""

        @tool
        def fetch() -> dict[str, Any]:
            return {"items": [1, True, None], "status": "ok"}

        model = ScriptedStreamingChatModel([], [
            [StreamChunk(
                tool_calls=[ToolCallDelta(0, "c1", "fetch", "{}")],
                finish_reason="tool_calls",
            )],
            [StreamChunk(content="done", finish_reason="stop")],
        ])

        events = list(Agent(llm=model, tools=[fetch]).run_stream("question"))

        observation = next(e for e in events if e["type"] == "observation")
        trace_entry = events[-1]["trace"][0]

        expected_json = '{"items":[1,true,null],"status":"ok"}'
        assert observation["text"] == expected_json
        assert trace_entry["observation"] == expected_json
        second_request = model.stream_calls[1][0]
        tool_message = second_request[-1]
        assert tool_message["content"] == expected_json


def test_stream_executes_complete_tool_calls_with_stop_finish_reason() -> None:
    """工具调用存在时即使finish_reason='stop'也要执行。"""

    @tool
    def add(a: int, b: int) -> int:
        return a + b

    model = ScriptedStreamingChatModel([], [
        [StreamChunk(
            tool_calls=[ToolCallDelta(0, "c1", "add", '{"a":1,"b":2}')],
            finish_reason="stop",  # 不是"tool_calls"
        )],
        [StreamChunk(content="done", finish_reason="stop")],
    ])

    events = list(Agent(llm=model, tools=[add]).run_stream("question"))

    # 应该执行工具调用
    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0]["name"] == "add"

    # 应该继续循环并完成
    assert events[-1]["stop_reason"] == "completed"


def test_stream_text_without_finish_reason_returns_incomplete() -> None:
    """流式文本没有finish_reason时应返回incomplete。"""
    model = ScriptedStreamingChatModel([], [
        [StreamChunk(content="partial answer")],  # 无finish_reason
    ])

    events = list(Agent(llm=model, tools=[]).run_stream("question"))

    assert events[-1]["stop_reason"] == "incomplete"
    assert events[-1]["content"] == "partial answer"


def test_stream_multi_tool_request_executes_all_in_order() -> None:
    """一条消息中多个工具调用按索引顺序执行。"""
    calls = []

    @tool
    def first(x: int) -> int:
        calls.append(("first", x))
        return x

    @tool
    def second(x: int) -> int:
        calls.append(("second", x))
        return x

    model = ScriptedStreamingChatModel([], [
        [StreamChunk(
            tool_calls=[
                ToolCallDelta(1, "c2", "second", '{"x":'),
                ToolCallDelta(0, "c1", "first", '{"x":'),
            ],
        ),
        StreamChunk(
            tool_calls=[
                ToolCallDelta(0, arguments="1}"),
                ToolCallDelta(1, arguments="2}"),
            ],
            finish_reason="tool_calls",
        )],
        [StreamChunk(content="done", finish_reason="stop")],
    ])

    events = list(Agent(llm=model, tools=[first, second]).run_stream("question"))

    # 按索引顺序执行
    assert calls == [("first", 1), ("second", 2)]
    # 验证事件顺序
    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert [e["name"] for e in tool_events] == ["first", "second"]
