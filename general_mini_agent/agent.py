"""基于 thought、action 和 observation 的 ReAct Agent 执行器。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, NotRequired, TypedDict

from .agent_protocol import (
    AgentStopReason,
    AssistantTurn,
    StreamingTurnAccumulator,
    ToolOutcome,
    TurnDecision,
    append_assistant_turn,
    append_tool_outcomes,
    build_incomplete_trace,
    build_tool_trace,
    classify_turn,
    clean_final_content,
    invalid_arguments_result,
    safe_error_message,
)


# 为async_agent向后兼容保留的旧类定义
@dataclass
class _AccumulatedToolCall:
    """已弃用：内部工具调用累积片段，仅为async_agent兼容保留"""

    index: int
    id: str = ""
    name: str = ""
    argument_parts: list[str] = field(default_factory=list)

    @property
    def raw_arguments(self) -> str:
        return "".join(self.argument_parts)


class _ToolCallAccumulator:
    """已弃用：内部工具调用累积器，仅为async_agent兼容保留"""

    def __init__(self) -> None:
        self._calls: dict[int, _AccumulatedToolCall] = {}

    def add(self, delta: ToolCallDelta) -> None:
        call = self._calls.setdefault(delta.index, _AccumulatedToolCall(delta.index))
        if delta.id:
            if call.id and call.id != delta.id:
                raise self._protocol_error(delta.index, "id")
            call.id = delta.id
        if delta.name:
            if call.name and call.name != delta.name:
                raise self._protocol_error(delta.index, "name")
            call.name = delta.name
        if delta.arguments:
            call.argument_parts.append(delta.arguments)

    def finalize(self) -> list[_AccumulatedToolCall]:
        calls = [self._calls[index] for index in sorted(self._calls)]
        if not calls:
            raise ModelRequestError(
                "model ended with tool_calls but supplied no calls",
                error_code="stream_protocol_error",
            )
        for call in calls:
            if not call.id or not call.name:
                raise ModelRequestError(
                    f"model tool call at index {call.index} is missing identity metadata",
                    error_code="stream_protocol_error",
                )
        return calls

    @staticmethod
    def _protocol_error(index: int, field_name: str) -> ModelRequestError:
        return ModelRequestError(
            f"model tool call at index {index} has conflicting {field_name}",
            error_code="stream_protocol_error",
        )
from .context import ContextBudgetExceeded, ContextPolicy
from .events import EventSink, RunContext, RunEventEmitter
from .llm import ChatModel, ModelRequestError, ToolCallDelta
from .long_term_memory import (
    LongTermMemoryStore,
    MemoryQuery,
    MemoryStoreError,
    build_memory_context,
)
from .tools import (
    Tool,
    ToolAuthorizationPolicy,
    ToolRegistry,
)


class TraceEvent(TypedDict):
    type: str
    iteration: int
    thought: NotRequired[str]
    tool: NotRequired[str]
    arguments: NotRequired[dict[str, Any] | None]
    raw_arguments: NotRequired[str]
    index: NotRequired[int]
    tool_call_id: NotRequired[str]
    observation: NotRequired[str]
    error_code: NotRequired[str]
    final_answer: NotRequired[str]
    message: NotRequired[str]
    finish_reason: NotRequired[str]


class IterationStartEvent(TypedDict):
    type: Literal["iteration_start"]
    iteration: int


class ThoughtChunkEvent(TypedDict):
    type: Literal["thought_chunk"]
    iteration: int
    text: str


class ToolCallEvent(TypedDict):
    type: Literal["tool_call"]
    iteration: int
    index: int
    id: str
    name: str
    arguments: dict[str, Any] | None
    raw_arguments: str
    error_code: NotRequired[str]


class ObservationEvent(TypedDict):
    type: Literal["observation"]
    iteration: int
    index: int
    tool_call_id: str
    name: str
    text: str
    error_code: NotRequired[str]


class FinalAnswerEvent(TypedDict):
    type: Literal["final_answer"]
    iteration: int
    text: str


class ModelErrorEvent(TypedDict):
    type: Literal["model_error"]
    iteration: int
    error_code: str
    error: str
    status_code: NotRequired[int]


class DoneEvent(TypedDict):
    type: Literal["done"]
    content: str
    trace: list[TraceEvent]
    usage: dict[str, int]
    iterations: int
    stop_reason: AgentStopReason
    finish_reason: NotRequired[str]
    error: NotRequired[str]


StreamEvent = (
    IterationStartEvent
    | ThoughtChunkEvent
    | ToolCallEvent
    | ObservationEvent
    | FinalAnswerEvent
    | ModelErrorEvent
    | DoneEvent
)


@dataclass
class AgentResult:
    """Agent 执行结果"""
    content: str
    trace: list[TraceEvent] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    iterations: int = 0
    stop_reason: AgentStopReason = "completed"
    error: str | None = None
    run_id: str = ""


# ─── Agent 配置 ──────────────────────────────────────────────


@dataclass
class AgentConfig:
    system_prompt: str = ""
    max_iterations: int = 10
    tool_descriptions: str = ""


# ─── ReAct 提示词模板 ─────────────────────────────────────


DEFAULT_SYSTEM_PROMPT = """你是一个擅长多步推理的 AI 助手。你有以下工具可用：

{tool_descriptions}

当你需要使用工具时，直接调用工具即可。你可以多次调用工具来收集信息。

当你得到足够信息后，直接给出最终回答。

请用中文思考并回答问题。"""


# ─── Agent 类 ───────────────────────────────────────────────


class Agent:
    """ReAct Agent — 思考→行动→观察→思考...→最终答案"""

    def __init__(
        self,
        llm: ChatModel,
        tools: list[Tool | Callable[..., Any]] | None = None,
        system_prompt: str | None = None,
        max_iterations: int = 10,
        memory: Any | None = None,
        context_policy: ContextPolicy | None = None,
        hooks: dict[str, Callable] | None = None,
        long_term_memory: LongTermMemoryStore | None = None,
        tool_authorization_policy: ToolAuthorizationPolicy | None = None,
        event_sink: EventSink | None = None,
    ):
        self.llm = llm
        self.max_iterations = max_iterations
        self.memory = memory
        self.context_policy = context_policy
        self.long_term_memory = long_term_memory
        self.event_sink = event_sink

        self.registry = ToolRegistry(
            tools or [],
            authorization_policy=tool_authorization_policy,
        )
        self.tools = self.registry.list()

        # 系统提示词
        tool_descs = self._format_tool_descriptions()
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT.format(
            tool_descriptions=tool_descs
        )

        # 钩子
        self.hooks = hooks or {}

    def run(
        self,
        user_input: str,
        *,
        memory_query: MemoryQuery | None = None,
        run_context: RunContext | None = None,
    ) -> AgentResult:
        """ReAct 循环主入口"""
        trace: list[TraceEvent] = []
        total_usage: dict[str, int] = {}

        # 创建事件发射器
        emitter = RunEventEmitter(
            run_id=run_context.run_id if run_context else None,
            parent_run_id=run_context.parent_run_id if run_context else None,
            sink=self.event_sink,
        )

        # 发射运行开始事件
        emitter.emit("run_started", {"input": user_input})

        # 构建初始消息
        try:
            messages = self._initial_messages(user_input, memory_query)
        except MemoryStoreError as exc:
            error = str(exc)
            trace.append({
                "type": "memory_error",
                "iteration": 0,
                "error_code": "memory_error",
                "message": error,
            })
            emitter.emit("run_finished", {"stop_reason": "memory_error", "error": error})
            return AgentResult(
                content="",
                trace=trace,
                usage=total_usage,
                iterations=0,
                stop_reason="memory_error",
                error=error,
                run_id=emitter.run_id,
            )
        except ContextBudgetExceeded as exc:
            error = str(exc)
            trace.append({
                "type": "context_error",
                "iteration": 0,
                "error_code": "context_budget_exceeded",
                "message": error,
            })
            emitter.emit("run_finished", {"stop_reason": "context_budget_exceeded", "error": error})
            return AgentResult(
                content="",
                trace=trace,
                usage=total_usage,
                iterations=0,
                stop_reason="context_budget_exceeded",
                error=error,
                run_id=emitter.run_id,
            )

        # ── ReAct 循环 ────────────────────────────────
        for iteration in range(self.max_iterations):
            try:
                request_messages = self._prepare_request(messages)
            except ContextBudgetExceeded as exc:
                error = str(exc)
                trace.append({
                    "type": "context_error",
                    "iteration": iteration,
                    "error_code": "context_budget_exceeded",
                    "message": error,
                })
                emitter.emit(
                    "run_finished", {"stop_reason": "context_budget_exceeded", "error": error}
                )
                return AgentResult(
                    content="",
                    trace=trace,
                    usage=total_usage,
                    iterations=iteration,
                    stop_reason="context_budget_exceeded",
                    error=error,
                    run_id=emitter.run_id,
                )

            try:
                response = self.llm.chat(
                    request_messages,
                    tools=self.registry.schemas(),
                )
            except ModelRequestError:
                trace.append({
                    "type": "model_error",
                    "iteration": iteration,
                    "message": "model request failed",
                })
                emitter.emit(
                    "run_finished", {"stop_reason": "model_error", "error": "model request failed"}
                )
                return AgentResult(
                    content="",
                    trace=trace,
                    usage=total_usage,
                    iterations=iteration,
                    stop_reason="model_error",
                    error="model request failed",
                    run_id=emitter.run_id,
                )

            self._accumulate_usage(total_usage, response.usage)

            # 使用协议接口处理响应
            turn = AssistantTurn.from_response(response)
            append_assistant_turn(messages, turn)
            decision = classify_turn(turn)

            if decision.action == "continue":
                # 执行所有工具调用
                outcomes = []
                for index, call in enumerate(turn.tool_calls):
                    execution = (
                        invalid_arguments_result(call)
                        if call.arguments is None
                        else self.registry.execute(call.name, call.arguments)
                    )
                    outcomes.append(ToolOutcome(call, execution))
                    trace_event = build_tool_trace(iteration, turn, index, call, execution)
                    trace.append(trace_event)
                    self._call_hook("on_tool_call", dict(trace_event))
                append_tool_outcomes(messages, outcomes)
                continue

            if decision.action == "complete":
                return self._result_from_decision(
                    decision, turn, trace, total_usage, iteration, emitter, user_input
                )

            if decision.action == "stop_error":
                return self._result_from_decision(
                    decision, turn, trace, total_usage, iteration, emitter, user_input
                )

        # 超时返回
        trace.append({
            "type": "max_iterations",
            "iteration": self.max_iterations,
            "message": "maximum iterations reached",
        })
        emitter.emit("run_finished", {"stop_reason": "max_iterations"})
        return AgentResult(
            content="（已达最大迭代次数，未能得出最终答案）",
            trace=trace,
            usage=total_usage,
            iterations=self.max_iterations,
            stop_reason="max_iterations",
            run_id=emitter.run_id,
        )

    def run_stream(
        self,
        user_input: str,
        *,
        memory_query: MemoryQuery | None = None,
    ) -> Iterator[StreamEvent]:
        """ReAct 循环流式版 — 逐事件 yield，供上层实时消费"""
        trace: list[TraceEvent] = []
        total_usage: dict[str, int] = {}
        try:
            messages = self._initial_messages(user_input, memory_query)
        except MemoryStoreError as exc:
            error = str(exc)
            trace.append({
                "type": "memory_error",
                "iteration": 0,
                "error_code": "memory_error",
                "message": error,
            })
            yield {"type": "iteration_start", "iteration": 0}
            yield self._done_event(
                content="",
                trace=trace,
                usage=total_usage,
                iterations=0,
                stop_reason="memory_error",
                error=error,
            )
            return
        except ContextBudgetExceeded as exc:
            error = str(exc)
            trace.append({
                "type": "context_error",
                "iteration": 0,
                "error_code": "context_budget_exceeded",
                "message": error,
            })
            yield {"type": "iteration_start", "iteration": 0}
            yield self._done_event(
                content="",
                trace=trace,
                usage=total_usage,
                iterations=0,
                stop_reason="context_budget_exceeded",
                error=error,
            )
            return

        for iteration in range(self.max_iterations):
            yield {"type": "iteration_start", "iteration": iteration}

            accumulator = StreamingTurnAccumulator()

            try:
                request_messages = self._prepare_request(messages)
            except ContextBudgetExceeded as exc:
                error = str(exc)
                trace.append({
                    "type": "context_error",
                    "iteration": iteration,
                    "error_code": "context_budget_exceeded",
                    "message": error,
                })
                yield self._done_event(
                    content="",
                    trace=trace,
                    usage=total_usage,
                    iterations=iteration,
                    stop_reason="context_budget_exceeded",
                    error=error,
                )
                return

            try:
                for chunk in self.llm.chat_stream(
                    request_messages, tools=self.registry.schemas()
                ):
                    accumulator.add(chunk)
                    if chunk.content:
                        yield {
                            "type": "thought_chunk",
                            "iteration": iteration,
                            "text": chunk.content,
                        }

                # 累加 usage
                turn = accumulator.finalize()
                self._accumulate_usage(total_usage, turn.usage)
            except ModelRequestError as exc:
                self._accumulate_usage(total_usage, accumulator._usage)
                error = str(exc)
                trace.append({
                    "type": "model_error",
                    "iteration": iteration,
                    "error_code": exc.error_code,
                    "message": error,
                })
                model_error: ModelErrorEvent = {
                    "type": "model_error",
                    "iteration": iteration,
                    "error_code": exc.error_code,
                    "error": error,
                }
                if exc.status_code is not None:
                    model_error["status_code"] = exc.status_code
                yield model_error
                yield self._done_event(
                    content="",
                    trace=trace,
                    usage=total_usage,
                    iterations=iteration + 1,
                    stop_reason="model_error",
                    error=error,
                )
                return

            # 使用协议接口处理回合
            append_assistant_turn(messages, turn)
            decision = classify_turn(turn)

            if decision.action == "continue":
                # 执行所有工具调用
                outcomes = []
                for index, call in enumerate(turn.tool_calls):
                    execution = (
                        invalid_arguments_result(call)
                        if call.arguments is None
                        else self.registry.execute(call.name, call.arguments)
                    )
                    outcomes.append(ToolOutcome(call, execution))

                    # 构建并发送事件
                    tool_event: ToolCallEvent = {
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

                    observation_event: ObservationEvent = {
                        "type": "observation",
                        "iteration": iteration,
                        "index": index,
                        "tool_call_id": call.id,
                        "name": call.name,
                        "text": execution.content,
                    }
                    if execution.error_code is not None:
                        observation_event["error_code"] = execution.error_code

                    yield tool_event
                    yield observation_event

                    # 构建trace事件
                    trace_event = build_tool_trace(iteration, turn, index, call, execution)
                    trace.append(trace_event)
                    self._call_hook("on_tool_call", dict(trace_event))

                append_tool_outcomes(messages, outcomes)
                continue

            if decision.action == "complete":
                clean = clean_final_content(turn.content or "")
                yield {
                    "type": "final_answer",
                    "iteration": iteration,
                    "text": clean,
                }
                trace.append({
                    "type": "final_answer",
                    "iteration": iteration,
                    "thought": turn.content or "",
                    "final_answer": clean,
                })
                self._call_hook("on_final", dict(trace[-1]))
                self._commit_exchange(user_input, clean)
                yield self._done_event(
                    content=clean,
                    trace=trace,
                    usage=total_usage,
                    iterations=iteration + 1,
                    stop_reason="completed",
                    finish_reason=turn.finish_reason,
                )
                return

            if decision.action == "stop_error":
                trace_event = build_incomplete_trace(iteration, turn, decision)
                trace.append(trace_event)
                yield self._done_event(
                    content=turn.content or "",
                    trace=trace,
                    usage=total_usage,
                    iterations=iteration + 1,
                    stop_reason=decision.stop_reason or "incomplete",
                    finish_reason=turn.finish_reason,
                    error=safe_error_message(decision),
                )
                return

        yield self._done_event(
            content="（已达最大迭代次数，未能得出最终答案）",
            trace=trace,
            usage=total_usage,
            iterations=self.max_iterations,
            stop_reason="max_iterations",
        )

    # ── 内部方法 ────────────────────────────────────────

    @staticmethod
    def _done_event(
        *,
        content: str,
        trace: list[TraceEvent],
        usage: dict[str, int],
        iterations: int,
        stop_reason: AgentStopReason,
        finish_reason: str | None = None,
        error: str | None = None,
    ) -> DoneEvent:
        event: DoneEvent = {
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

    def _format_tool_descriptions(self) -> str:
        """生成工具描述文本（嵌入 system prompt）"""
        if not self.tools:
            return "（无可用工具）"
        from .tools import Tool
        lines = []
        for t in self.tools:
            if isinstance(t, Tool):
                params = ", ".join(t.parameters.get("properties", {}).keys())
                lines.append(f"- {t.name}({params}): {t.description}")
            else:
                # 兼容原始函数（有 name 属性）
                lines.append(f"- {getattr(t, '__name__', str(t))}(...): 可用工具")
        return "\n".join(lines)

    def _memory_context(self) -> list[dict[str, Any]]:
        get_context = getattr(self.memory, "get_context", None)
        if callable(get_context):
            return get_context()
        return []

    def _initial_messages(
        self,
        user_input: str,
        memory_query: MemoryQuery | None,
    ) -> list[dict[str, Any]]:
        messages = [{"role": "system", "content": self.system_prompt}]
        if memory_query is not None:
            if self.long_term_memory is None:
                raise MemoryStoreError("query", backend="unconfigured")
            records = self.long_term_memory.query(memory_query)
            memory_message = build_memory_context(
                records,
                memory_query.max_context_tokens,
            )
            if memory_message is not None:
                messages.append(memory_message)
        messages.extend(self._memory_context())
        messages.append({"role": "user", "content": user_input})
        return messages

    def _prepare_request(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self.context_policy is None:
            return list(messages)  # 返回副本，避免外部修改影响
        return self.context_policy.prepare(
            messages,
            tools=self.registry.schemas(),
        )

    def _commit_exchange(self, user_input: str, assistant_content: str) -> None:
        add_messages = getattr(self.memory, "add_messages", None)
        if callable(add_messages):
            add_messages([
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": assistant_content},
            ])

    def _accumulate_usage(self, total: dict, current: dict) -> None:
        for key, val in current.items():
            if isinstance(val, int):
                total[key] = total.get(key, 0) + val

    def _call_hook(self, name: str, data: dict) -> None:
        hook = self.hooks.get(name)
        if hook:
            hook(data)

    def _result_from_decision(
        self,
        decision: TurnDecision,
        turn: AssistantTurn,
        trace: list[TraceEvent],
        usage: dict[str, int],
        iteration: int,
        emitter: RunEventEmitter,
        user_input: str,
    ) -> AgentResult:
        """集中处理 decision 的结果创建和 run_finished 事件发射"""
        if decision.action == "complete":
            clean_content = clean_final_content(turn.content or "")
            trace.append({
                "type": "final",
                "iteration": iteration,
                "thought": turn.content or "",
                "final_answer": clean_content,
            })
            self._call_hook("on_final", dict(trace[-1]))
            self._commit_exchange(user_input, clean_content)
            emitter.emit("run_finished", {"stop_reason": "completed", "answer": clean_content})
            return AgentResult(
                content=clean_content,
                trace=trace,
                usage=usage,
                iterations=iteration + 1,
                run_id=emitter.run_id,
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
                {"stop_reason": decision.stop_reason or "model_error", "error": error_message}
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
                run_id=emitter.run_id,
            )

        # 兜底：不应到达这里
        return AgentResult(
            content="",
            trace=trace,
            usage=usage,
            iterations=iteration,
            stop_reason="model_error",
            error=f"unexpected decision action: {decision.action}",
            run_id=emitter.run_id,
        )
