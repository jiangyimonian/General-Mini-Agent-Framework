"""共享 Agent ReAct 内核 — 纯函数与数据类，不执行 I/O。

四个入口（run / run_stream / run_async / run_stream_async）的决策逻辑
完全一致，差异仅在同步/异步的 I/O 方式和一次性/流式的事件编织。
本模块把决策、工具执行循环、结果构造等共享逻辑抽成纯函数，
供四条路径调用，消除重复。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .agent_protocol import (
    AgentStopReason,
    AssistantTurn,
    ToolOutcome,
    TurnDecision,
    build_incomplete_trace,
    build_tool_trace,
    clean_final_content,
    invalid_arguments_result,
    safe_error_message,
)
from .llm import ToolCall
from .tools import ToolExecutionResult

if TYPE_CHECKING:
    from .agent import (
        AgentResult,
        DoneEvent,
        ModelErrorEvent,
        ObservationEvent,
        StreamEvent,
        ToolCallEvent,
        TraceEvent,
    )
    from .events import RunEventEmitter


# ─── 一轮工具执行的结果 ─────────────────────────────────────────


@dataclass
class ToolStepOutcome:
    """一轮 continue 决策下所有工具调用的执行结果。"""

    outcomes: list[ToolOutcome]
    trace_events: list[dict[str, Any]]
    stream_tool_events: list[dict[str, Any]]  # ToolCallEvent 列表
    stream_observation_events: list[dict[str, Any]]  # ObservationEvent 列表


# ─── usage 累加 ───────────────────────────────────────────────


def accumulate_usage(total: dict[str, int], current: dict[str, int]) -> None:
    """按 key 累加 int 类型的 usage 数值。"""
    for key, val in current.items():
        if isinstance(val, int):
            total[key] = total.get(key, 0) + val


# ─── 工具执行循环（同步版）─────────────────────────────────────


def execute_tool_calls_sync(
    turn: AssistantTurn,
    iteration: int,
    tool_executor: Callable[[ToolCall], ToolExecutionResult],
    hook_call: Callable[[dict[str, Any]], None] | None = None,
) -> ToolStepOutcome:
    """同步执行一轮的所有工具调用，返回 outcomes、trace 事件和流式事件。

    tool_executor: 接受 ToolCall，返回 ToolExecutionResult 的可调用对象。
                   调用方负责包装 invalid_arguments_result 的分支。
    hook_call: on_tool_call 钩子（接收 trace 事件 dict 的副本）。
    """
    outcomes: list[ToolOutcome] = []
    trace_events: list[dict[str, Any]] = []
    stream_tool_events: list[dict[str, Any]] = []
    stream_observation_events: list[dict[str, Any]] = []

    for index, call in enumerate(turn.tool_calls):
        execution = tool_executor(call)
        outcomes.append(ToolOutcome(call, execution))

        trace_event = build_tool_trace(iteration, turn, index, call, execution)
        trace_events.append(trace_event)
        if hook_call is not None:
            hook_call(dict(trace_event))

        tool_event: dict[str, Any] = {
            "type": "tool_call",
            "iteration": iteration,
            "index": index,
            "id": call.id,
            "name": call.name,
            "arguments": call.arguments,
            "raw_arguments": call.raw_arguments or "",
        }
        if execution.error_code is not None:
            tool_event["error_code"] = execution.error_code
        stream_tool_events.append(tool_event)

        observation_event: dict[str, Any] = {
            "type": "observation",
            "iteration": iteration,
            "index": index,
            "tool_call_id": call.id,
            "name": call.name,
            "text": execution.content,
        }
        if execution.error_code is not None:
            observation_event["error_code"] = execution.error_code
        stream_observation_events.append(observation_event)

    return ToolStepOutcome(
        outcomes=outcomes,
        trace_events=trace_events,
        stream_tool_events=stream_tool_events,
        stream_observation_events=stream_observation_events,
    )


# ─── 工具执行循环（异步版）─────────────────────────────────────


async def execute_tool_calls_async(
    turn: AssistantTurn,
    iteration: int,
    tool_executor: Callable[[ToolCall], Any],  # coroutine 返回 ToolExecutionResult
    hook_call: Callable[[dict[str, Any]], None] | None = None,
) -> ToolStepOutcome:
    """异步执行一轮的所有工具调用，返回 outcomes、trace 事件和流式事件。

    tool_executor: 接受 ToolCall，返回协程（await 后得 ToolExecutionResult）。
    """
    outcomes: list[ToolOutcome] = []
    trace_events: list[dict[str, Any]] = []
    stream_tool_events: list[dict[str, Any]] = []
    stream_observation_events: list[dict[str, Any]] = []

    for index, call in enumerate(turn.tool_calls):
        execution = await tool_executor(call)
        outcomes.append(ToolOutcome(call, execution))

        trace_event = build_tool_trace(iteration, turn, index, call, execution)
        trace_events.append(trace_event)
        if hook_call is not None:
            hook_call(dict(trace_event))

        tool_event: dict[str, Any] = {
            "type": "tool_call",
            "iteration": iteration,
            "index": index,
            "id": call.id,
            "name": call.name,
            "arguments": call.arguments,
            "raw_arguments": call.raw_arguments or "",
        }
        if execution.error_code is not None:
            tool_event["error_code"] = execution.error_code
        stream_tool_events.append(tool_event)

        observation_event: dict[str, Any] = {
            "type": "observation",
            "iteration": iteration,
            "index": index,
            "tool_call_id": call.id,
            "name": call.name,
            "text": execution.content,
        }
        if execution.error_code is not None:
            observation_event["error_code"] = execution.error_code
        stream_observation_events.append(observation_event)

    return ToolStepOutcome(
        outcomes=outcomes,
        trace_events=trace_events,
        stream_tool_events=stream_tool_events,
        stream_observation_events=stream_observation_events,
    )


# ─── 工具执行器辅助：统一 invalid_arguments 分支 ───────────────


def make_tool_executor_sync(
    registry_execute: Callable[[str, dict[str, Any]], ToolExecutionResult],
) -> Callable[[ToolCall], ToolExecutionResult]:
    """构造同步工具执行器，统一处理 arguments is None 的情况。"""

    def executor(call: ToolCall) -> ToolExecutionResult:
        if call.arguments is None:
            return invalid_arguments_result(call)
        return registry_execute(call.name, call.arguments)

    return executor


def make_tool_executor_async(
    registry_execute_async: Callable[[str, dict[str, Any]], Any],
) -> Callable[[ToolCall], Any]:
    """构造异步工具执行器，统一处理 arguments is None 的情况。"""

    async def executor(call: ToolCall) -> ToolExecutionResult:
        if call.arguments is None:
            return invalid_arguments_result(call)
        return await registry_execute_async(call.name, call.arguments)

    return executor


# ─── done 事件构造 ───────────────────────────────────────────


def build_done_event(
    *,
    content: str,
    trace: list[dict[str, Any]],
    usage: dict[str, int],
    iterations: int,
    stop_reason: AgentStopReason,
    finish_reason: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """统一构造 done 事件（返回 dict，兼容 DoneEvent TypedDict）。"""
    event: dict[str, Any] = {
        "type": "done",
        "content": content,
        "trace": trace,
        "usage": usage,
        "iterations": iterations,
        "stop_reason": stop_reason,
    }
    if finish_reason is not None:
        event["finish_reason"] = finish_reason
    if error is not None:
        event["error"] = error
    return event


# ─── model_error 事件构造 ────────────────────────────────────


def build_model_error_event(
    iteration: int,
    error_code: str,
    error: str,
    status_code: int | None = None,
) -> dict[str, Any]:
    """构造 model_error 流式事件。"""
    event: dict[str, Any] = {
        "type": "model_error",
        "iteration": iteration,
        "error_code": error_code,
        "error": error,
    }
    if status_code is not None:
        event["status_code"] = status_code
    return event


# ─── 非流式：decision → AgentResult ──────────────────────────


def result_from_decision(
    decision: TurnDecision,
    turn: AssistantTurn,
    trace: list[dict[str, Any]],
    usage: dict[str, int],
    iteration: int,
    emitter: RunEventEmitter,
    user_input: str,
    commit_fn: Callable[[str, str], None],
    hook_call: Callable[[str, dict[str, Any]], None] | None,
    run_id: str,
    trace_type_final: str = "final",
) -> AgentResult:
    """根据 decision 构造非流式 AgentResult 并发射 run_finished。

    trace_type_final: 非流式为 "final"，保持历史行为。
    """
    # 延迟导入避免循环依赖
    from .agent import AgentResult

    if decision.action == "complete":
        clean_content = clean_final_content(turn.content or "")
        trace_entry = {
            "type": trace_type_final,
            "iteration": iteration,
            "thought": turn.content or "",
            "final_answer": clean_content,
        }
        trace.append(trace_entry)
        if hook_call is not None:
            hook_call("on_final", dict(trace_entry))
        commit_fn(user_input, clean_content)
        emitter.emit("run_finished", {"stop_reason": "completed", "answer": clean_content})
        return AgentResult(
            content=clean_content,
            trace=trace,
            usage=usage,
            iterations=iteration + 1,
            run_id=run_id,
        )

    if decision.action == "stop_error":
        error_message = safe_error_message(decision)
        trace.append({
            "type": "model_error",
            "iteration": iteration,
            "message": error_message,
        })
        emitter.emit(
            "run_finished",
            {"stop_reason": decision.stop_reason or "model_error", "error": error_message},
        )
        # For incomplete results, return the content; for model_error, return empty
        content = turn.content if decision.stop_reason == "incomplete" else ""
        return AgentResult(
            content=content,
            trace=trace,
            usage=usage,
            iterations=iteration,
            stop_reason=decision.stop_reason or "model_error",
            error=error_message,
            run_id=run_id,
        )

    # 兜底：不应到达这里
    return AgentResult(
        content="",
        trace=trace,
        usage=usage,
        iterations=iteration,
        stop_reason="model_error",
        error=f"unexpected decision action: {decision.action}",
        run_id=run_id,
    )


# ─── 流式：complete/stop_error 事件序列 ──────────────────────


def build_stream_final_events(
    decision: TurnDecision,
    turn: AssistantTurn,
    iteration: int,
    trace: list[dict[str, Any]],
    usage: dict[str, int],
    user_input: str,
    commit_fn: Callable[[str, str], None],
    hook_call: Callable[[str, dict[str, Any]], None] | None,
) -> list[dict[str, Any]]:
    """构造流式 complete 或 stop_error 的事件序列。

    返回 list[StreamEvent]，调用方逐个 yield。
    """
    events: list[dict[str, Any]] = []

    if decision.action == "complete":
        clean = clean_final_content(turn.content or "")
        events.append({
            "type": "final_answer",
            "iteration": iteration,
            "text": clean,
        })
        trace.append({
            "type": "final_answer",
            "iteration": iteration,
            "thought": turn.content or "",
            "final_answer": clean,
        })
        if hook_call is not None:
            hook_call("on_final", dict(trace[-1]))
        commit_fn(user_input, clean)
        events.append(build_done_event(
            content=clean,
            trace=trace,
            usage=usage,
            iterations=iteration + 1,
            stop_reason="completed",
            finish_reason=turn.finish_reason,
        ))
        return events

    if decision.action == "stop_error":
        trace_event = build_incomplete_trace(iteration, turn, decision)
        trace.append(trace_event)
        events.append(build_done_event(
            content=turn.content or "",
            trace=trace,
            usage=usage,
            iterations=iteration + 1,
            stop_reason=decision.stop_reason or "incomplete",
            finish_reason=turn.finish_reason,
            error=safe_error_message(decision),
        ))
        return events

    return events


# ─── max_iterations 终止（非流式）────────────────────────────


def result_max_iterations(
    max_iterations: int,
    trace: list[dict[str, Any]],
    usage: dict[str, int],
    emitter: RunEventEmitter,
    run_id: str,
) -> AgentResult:
    """构造 max_iterations 的 AgentResult。"""
    from .agent import AgentResult

    trace.append({
        "type": "max_iterations",
        "iteration": max_iterations,
        "message": "maximum iterations reached",
    })
    emitter.emit("run_finished", {"stop_reason": "max_iterations"})
    return AgentResult(
        content="（已达最大迭代次数，未能得出最终答案）",
        trace=trace,
        usage=usage,
        iterations=max_iterations,
        stop_reason="max_iterations",
        run_id=run_id,
    )
