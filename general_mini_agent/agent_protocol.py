"""共享 Agent 回合协议 —— 纯函数和数据类，不依赖 agent.py，不执行 I/O。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from .llm import LLMResponse, ModelRequestError, StreamChunk, ToolCall, ToolCallDelta
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


# ─── 流式回合累积器 ───────────────────────────────────────────


@dataclass
class _AccumulatedToolCall:
    """累积的工具调用片段"""

    index: int
    id: str = ""
    name: str = ""
    argument_parts: list[str] = field(default_factory=list)

    @property
    def raw_arguments(self) -> str:
        """拼接原始参数片段"""
        return "".join(self.argument_parts)


class StreamingTurnAccumulator:
    """流式回合累积器 —— 累积 StreamChunk 并转换为 AssistantTurn"""

    def __init__(self) -> None:
        self._content_parts: list[str] = []
        self._tool_calls: dict[int, _AccumulatedToolCall] = {}
        self._finish_reason: str = ""
        self._usage: dict[str, int] = {}

    def add(self, chunk: StreamChunk) -> None:
        """添加一个流式 chunk"""
        # 累积文本内容
        if chunk.content:
            self._content_parts.append(chunk.content)

        # 累积工具调用片段
        for delta in chunk.tool_calls:
            call = self._tool_calls.setdefault(
                delta.index, _AccumulatedToolCall(delta.index)
            )
            # 检查 ID 冲突
            if delta.id:
                if call.id and call.id != delta.id:
                    raise ModelRequestError(
                        f"model tool call at index {delta.index} has conflicting id",
                        error_code="stream_protocol_error",
                    )
                call.id = delta.id
            # 检查名称冲突
            if delta.name:
                if call.name and call.name != delta.name:
                    raise ModelRequestError(
                        f"model tool call at index {delta.index} has conflicting name",
                        error_code="stream_protocol_error",
                    )
                call.name = delta.name
            # 累积参数片段
            if delta.arguments:
                call.argument_parts.append(delta.arguments)

        # 记录 finish_reason
        if chunk.finish_reason:
            self._finish_reason = chunk.finish_reason

        # 更新 usage（保留最新的）
        if chunk.usage:
            self._usage = chunk.usage

    def finalize(self) -> AssistantTurn:
        """转换为不可变的 AssistantTurn"""
        # 拼接文本内容
        content = "".join(self._content_parts)

        # 转换工具调用
        tool_calls: list[ToolCall] = []
        if self._tool_calls:
            # 按索引排序
            sorted_calls = [self._tool_calls[idx] for idx in sorted(self._tool_calls)]

            # 验证并转换为 ToolCall
            for accumulated in sorted_calls:
                # 检查身份完整性
                if not accumulated.id or not accumulated.name:
                    raise ModelRequestError(
                        f"model tool call at index {accumulated.index} is missing identity metadata",
                        error_code="stream_protocol_error",
                    )
                # 通过 ToolCall.from_raw() 解析参数
                call = ToolCall.from_raw(
                    call_id=accumulated.id,
                    name=accumulated.name,
                    raw_arguments=accumulated.raw_arguments,
                )
                tool_calls.append(call)

        # 检查 finish_reason="tool_calls" 但无调用的情况
        if self._finish_reason == "tool_calls" and not tool_calls:
            raise ModelRequestError(
                "model ended with tool_calls but supplied no calls",
                error_code="stream_protocol_error",
            )

        # 流式响应不合成 stop，保持原样
        return AssistantTurn(
            content=content or None,
            tool_calls=tuple(tool_calls),
            finish_reason=self._finish_reason,
            usage=self._usage,
        )