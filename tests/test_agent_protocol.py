"""测试 agent_protocol 模块的纯回合协议"""

import pytest

from general_mini_agent.agent_protocol import (
    AgentStopReason,
    AssistantTurn,
    ToolOutcome,
    TurnDecision,
    TurnAction,
    append_assistant_turn,
    append_tool_outcomes,
    build_incomplete_trace,
    build_tool_trace,
    classify_turn,
    clean_final_content,
    invalid_arguments_result,
    safe_error_message,
)
from general_mini_agent.llm import LLMResponse, ToolCall
from general_mini_agent.tools import ToolExecutionResult


class TestAssistantTurnFromResponse:
    """测试 AssistantTurn.from_response() 回合规范化"""

    def test_missing_finish_reason_with_text_normalizes_to_stop(self):
        """非流式响应缺少 finish_reason 且返回文本时应规范化为 stop"""
        response = LLMResponse(content="done", tool_calls=None, finish_reason="")
        turn = AssistantTurn.from_response(response)
        assert turn.finish_reason == "stop"

    def test_missing_finish_reason_with_tool_calls_remains_empty(self):
        """有工具调用时缺少 finish_reason 保持为空"""
        response = LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="c1", name="lookup", arguments={}, raw_arguments="{}")],
            finish_reason="",
        )
        turn = AssistantTurn.from_response(response)
        assert turn.finish_reason == ""

    def test_preserves_explicit_finish_reason(self):
        """保留显式的 finish_reason"""
        response = LLMResponse(content="done", tool_calls=None, finish_reason="stop")
        turn = AssistantTurn.from_response(response)
        assert turn.finish_reason == "stop"

    def test_preserves_usage(self):
        """保留 usage 字典"""
        response = LLMResponse(
            content="done",
            tool_calls=None,
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )
        turn = AssistantTurn.from_response(response)
        assert turn.usage == {"prompt_tokens": 10, "completion_tokens": 5}


class TestClassifyTurn:
    """测试 classify_turn() 终止分类"""

    def test_tool_calls_take_precedence_over_finish_reason(self):
        """工具调用优先于 finish_reason"""
        call = ToolCall(id="c1", name="lookup", arguments={"q": "x"}, raw_arguments='{"q":"x"}')
        turn = AssistantTurn(content="thinking", tool_calls=(call,), finish_reason="stop", usage={})
        decision = classify_turn(turn)
        assert decision.action == "continue"
        assert decision.stop_reason is None

    def test_stop_with_text_completes(self):
        """stop 加文本表示完成"""
        turn = AssistantTurn(content="final answer", tool_calls=(), finish_reason="stop", usage={})
        decision = classify_turn(turn)
        assert decision.action == "complete"
        assert decision.stop_reason == "completed"

    def test_tool_calls_finish_without_calls_is_model_error(self):
        """finish_reason 为 tool_calls 但无实际调用是模型错误"""
        turn = AssistantTurn(content=None, tool_calls=(), finish_reason="tool_calls", usage={})
        decision = classify_turn(turn)
        assert decision.action == "stop_error"
        assert decision.stop_reason == "model_error"
        assert decision.error_code == "stream_protocol_error"

    def test_no_content_is_model_error(self):
        """无内容是模型错误"""
        turn = AssistantTurn(content=None, tool_calls=(), finish_reason="", usage={})
        decision = classify_turn(turn)
        assert decision.action == "stop_error"
        assert decision.stop_reason == "model_error"

    @pytest.mark.parametrize("finish_reason", ["length", "content_filter", "unknown", ""])
    def test_non_stop_finish_with_text_is_incomplete(self, finish_reason: str):
        """非 stop 结束原因加文本为 incomplete"""
        turn = AssistantTurn(content="partial", tool_calls=(), finish_reason=finish_reason, usage={})
        decision = classify_turn(turn)
        assert decision.action == "stop_error"
        assert decision.stop_reason == "incomplete"
        if finish_reason:
            assert decision.message and finish_reason in decision.message


class TestMessageAppenders:
    """测试消息追加器"""

    def test_multi_tool_message_sequence(self):
        """多工具消息序列应为 user, assistant, tool, tool"""
        messages = [{"role": "user", "content": "test"}]

        call1 = ToolCall(id="c1", name="lookup", arguments={"q": "x"}, raw_arguments='{"q":"x"}')
        call2 = ToolCall(id="c2", name="search", arguments={"q": "y"}, raw_arguments='{"q":"y"}')
        turn = AssistantTurn(content="thinking", tool_calls=(call1, call2), finish_reason="tool_calls", usage={})

        append_assistant_turn(messages, turn)

        # 应该只有一个 assistant 消息
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert len(assistant_msgs[0]["tool_calls"]) == 2

        # 验证工具调用 ID 顺序
        assert assistant_msgs[0]["tool_calls"][0]["id"] == "c1"
        assert assistant_msgs[0]["tool_calls"][1]["id"] == "c2"

        # 追加两个 tool 结果
        result1 = ToolExecutionResult(content="result1")
        result2 = ToolExecutionResult(content="result2")
        append_tool_outcomes(messages, [
            ToolOutcome(call1, result1),
            ToolOutcome(call2, result2),
        ])

        # 应该有两个 tool 消息
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        assert len(tool_msgs) == 2
        assert tool_msgs[0]["tool_call_id"] == "c1"
        assert tool_msgs[1]["tool_call_id"] == "c2"

    def test_raw_arguments_preserved_in_messages(self):
        """原始 JSON 参数应保留在消息中"""
        messages = []

        # 测试解析错误的情况
        call = ToolCall(id="c1", name="lookup", arguments=None, raw_arguments='{"invalid"', argument_error="invalid JSON")
        turn = AssistantTurn(content=None, tool_calls=(call,), finish_reason="tool_calls", usage={})

        append_assistant_turn(messages, turn)

        # raw_arguments 应该被保留
        assert messages[0]["tool_calls"][0]["function"]["arguments"] == '{"invalid"'


class TestCleanFinalContent:
    """测试 clean_final_content() 清理旧前缀"""

    def test_removes_final_prefixes(self):
        """应移除各种最终答案前缀"""
        assert clean_final_content("[FINAL] the answer") == "the answer"
        assert clean_final_content("Final Answer: the answer") == "the answer"
        assert clean_final_content("最终答案：the answer") == "the answer"
        assert clean_final_content("最终答案: the answer") == "the answer"

    def test_strips_whitespace(self):
        """应去除空白"""
        assert clean_final_content("  Final Answer: the answer  ") == "the answer"


class TestInvalidArgumentsResult:
    """测试 invalid_arguments_result()"""

    def test_returns_error_code(self):
        """应返回 invalid_arguments 错误码"""
        call = ToolCall(id="c1", name="lookup", arguments=None, raw_arguments='{"invalid"', argument_error="invalid JSON")
        result = invalid_arguments_result(call)
        assert result.error_code == "invalid_arguments"
        assert "invalid JSON" in result.content


class TestBuildToolTrace:
    """测试 build_tool_trace()"""

    def test_builds_trace_dict(self):
        """应构建正确的 trace 字典"""
        call = ToolCall(id="c1", name="lookup", arguments={"q": "x"}, raw_arguments='{"q":"x"}')
        result = ToolExecutionResult(content="found")
        turn = AssistantTurn(content="thinking", tool_calls=(call,), finish_reason="tool_calls", usage={})

        trace = build_tool_trace(iteration=1, turn=turn, index=0, call=call, result=result)

        assert trace["type"] == "tool_call"
        assert trace["iteration"] == 1
        assert trace["index"] == 0
        assert trace["tool_call_id"] == "c1"
        assert trace["tool"] == "lookup"
        assert trace["raw_arguments"] == '{"q":"x"}'
        assert trace["observation"] == "found"


class TestBuildIncompleteTrace:
    """测试 build_incomplete_trace()"""

    def test_builds_incomplete_dict(self):
        """应构建 incomplete trace 字典"""
        turn = AssistantTurn(content="partial", tool_calls=(), finish_reason="length", usage={})
        decision = TurnDecision(action="stop_error", stop_reason="incomplete", message="length limit")

        trace = build_incomplete_trace(iteration=1, turn=turn, decision=decision)

        assert trace["type"] == "incomplete"
        assert trace["iteration"] == 1
        assert trace["thought"] == "partial"
        assert trace["finish_reason"] == "length"


class TestSafeErrorMessage:
    """测试 safe_error_message()"""

    def test_uses_decision_message(self):
        """应使用 decision 的消息"""
        decision = TurnDecision(action="stop_error", stop_reason="model_error", message="error detail")
        assert safe_error_message(decision) == "error detail"

    def test_fallback_to_stop_reason(self):
        """缺少消息时使用 stop_reason"""
        decision = TurnDecision(action="stop_error", stop_reason="model_error")
        assert safe_error_message(decision) == "model_error"