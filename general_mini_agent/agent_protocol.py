"""共享 Agent 回合协议 —— 纯函数和数据类，不依赖 agent.py，不执行 I/O。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from .llm import LLMResponse, ToolCall
from .tools import ToolExecutionResult

# ─── 类型定义 ───────────────────────────────────────────────

AgentStopReason = Literal[
    "completed",
    "max_iterations",
    "model_error",
    "incomplete",
    "context_budget_exceeded",
    "memory_error",
]

TurnAction = Literal["continue", "complete", "stop_error"]


# ─── 数据类 ───────────────────────────────────────────────


@dataclass(frozen=True)
class AssistantTurn:
    """模型返回的 assistant 回合"""

    content: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str | None
    usage: dict[str, int]

    @classmethod
    def from_response(cls, response: LLMResponse) -> AssistantTurn:
        """从 LLMResponse 构造回合，规范化缺少的 finish_reason。

        非流式响应缺少 finish_reason 且返回文本时规范化为 "stop"。
        有工具调用时保持为空，避免与后续 "tool_calls" 冲突。
        """
        # 规范化 finish_reason
        finish = response.finish_reason
        if not finish:
            # 非流式响应缺少 finish_reason：有文本无工具调用时为 "stop"
            if response.content and not response.tool_calls:
                finish = "stop"
            else:
                # 有工具调用或无内容时保持为空
                finish = ""

        # 转换工具调用为不可变元组
        calls = tuple(response.tool_calls) if response.tool_calls else ()

        return cls(
            content=response.content,
            tool_calls=calls,
            finish_reason=finish,
            usage=response.usage,
        )


@dataclass(frozen=True)
class ToolOutcome:
    """工具执行结果"""

    call: ToolCall
    result: ToolExecutionResult


@dataclass(frozen=True)
class TurnDecision:
    """回合终止决策"""

    action: TurnAction
    stop_reason: AgentStopReason | None = None
    error_code: str | None = None
    message: str | None = None


# ─── 消息追加器 ───────────────────────────────────────────────


def append_assistant_turn(messages: list[dict[str, Any]], turn: AssistantTurn) -> None:
    """追加 assistant 消息，保留 raw_arguments。"""
    if not turn.tool_calls:
        messages.append({
            "role": "assistant",
            "content": turn.content or "",
        })
        return

    # 使用 raw_arguments 或确定性 JSON 回退
    tool_calls_data = []
    for call in turn.tool_calls:
        raw = call.raw_arguments or json.dumps(
            call.arguments or {}, ensure_ascii=False, separators=(",", ":")
        )
        tool_calls_data.append({
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": raw,
            },
        })

    messages.append({
        "role": "assistant",
        "content": turn.content or "",
        "tool_calls": tool_calls_data,
    })


def append_tool_outcomes(
    messages: list[dict[str, Any]], outcomes: list[ToolOutcome]
) -> None:
    """追加多个 tool 消息。"""
    for outcome in outcomes:
        messages.append({
            "role": "tool",
            "tool_call_id": outcome.call.id,
            "content": outcome.result.content,
        })


# ─── 回合分类 ───────────────────────────────────────────────


def classify_turn(turn: AssistantTurn) -> TurnDecision:
    """分类回合终止原因。

    优先级：
    1. 非空工具调用 -> continue
    2. stop + 文本 -> complete
    3. finish_reason="tool_calls" 但无调用 -> model_error
    4. 无内容 -> model_error
    5. 其他文本结果 -> incomplete
    """
    # 1. 工具调用优先
    if turn.tool_calls:
        return TurnDecision(action="continue")

    # 2. stop + 文本表示完成
    if turn.finish_reason == "stop" and turn.content:
        return TurnDecision(action="complete", stop_reason="completed")

    # 3. finish_reason="tool_calls" 但无调用
    if turn.finish_reason == "tool_calls":
        return TurnDecision(
            action="stop_error",
            stop_reason="model_error",
            error_code="stream_protocol_error",
            message="model returned tool_calls finish reason but no calls",
        )

    # 4. 无内容
    if not turn.content:
        return TurnDecision(
            action="stop_error",
            stop_reason="model_error",
            message="model returned empty response",
        )

    # 5. 其他情况为 incomplete
    message = None
    if turn.finish_reason:
        message = f"model returned non-terminal finish reason: {turn.finish_reason}"

    return TurnDecision(
        action="stop_error",
        stop_reason="incomplete",
        message=message,
    )


# ─── 辅助函数 ───────────────────────────────────────────────


def clean_final_content(content: str) -> str:
    """清理旧版最终答案前缀。"""
    return (
        content.replace("[FINAL]", "")
        .replace("Final Answer:", "")
        .replace("最终答案：", "")
        .replace("最终答案:", "")
        .strip()
    )


def invalid_arguments_result(call: ToolCall) -> ToolExecutionResult:
    """构造无效参数错误结果。"""
    error_msg = call.argument_error or "invalid arguments"
    return ToolExecutionResult(
        content=f"invalid arguments for tool '{call.name}': {error_msg}",
        error_code="invalid_arguments",
    )


def build_tool_trace(
    iteration: int, turn: AssistantTurn, index: int, call: ToolCall, result: ToolExecutionResult
) -> dict[str, Any]:
    """构建工具调用 trace 事件。"""
    trace: dict[str, Any] = {
        "type": "tool_call",
        "iteration": iteration,
        "index": index,
        "tool_call_id": call.id,
        "tool": call.name,
        "arguments": call.arguments,
        "raw_arguments": call.raw_arguments,
        "observation": result.content,
    }
    if result.error_code is not None:
        trace["error_code"] = result.error_code
    return trace


def build_incomplete_trace(
    iteration: int, turn: AssistantTurn, decision: TurnDecision
) -> dict[str, Any]:
    """构建 incomplete trace 事件。"""
    trace: dict[str, Any] = {
        "type": "incomplete",
        "iteration": iteration,
        "thought": turn.content or "",
        "finish_reason": turn.finish_reason or "",
    }
    if decision.message:
        trace["message"] = decision.message
    return trace


def safe_error_message(decision: TurnDecision) -> str:
    """安全错误消息，不回显模型响应。"""
    if decision.message:
        return decision.message
    if decision.stop_reason:
        return decision.stop_reason
    return "unknown error"