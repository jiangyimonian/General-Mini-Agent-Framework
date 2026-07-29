"""异步 ReAct Agent 执行器。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

# 重用同步版本的结果类型
# 重用同步版本的辅助类
from .agent import (
    DEFAULT_SYSTEM_PROMPT,
    AgentResult,
    DoneEvent,
    ModelErrorEvent,
    ObservationEvent,
    StreamEvent,
    ToolCallEvent,
    TraceEvent,
    _AccumulatedToolCall,
    _ToolCallAccumulator,
)
from .agent_protocol import (
    AgentStopReason,
    AssistantTurn,
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
from .async_llm import AsyncChatModel
from .async_tools import AsyncToolRegistry
from .context import ContextBudgetExceeded, ContextPolicy
from .events import EventSink, RunContext, RunEventEmitter
from .llm import ModelRequestError
from .long_term_memory import (
    LongTermMemoryStore,
    MemoryQuery,
    MemoryStoreError,
    build_memory_context,
)
from .tools import (
    Tool,
    ToolAuthorizationPolicy,
    ToolExecutionResult,
)


class AsyncAgent:
    """异步 ReAct Agent — 思考→行动→观察→思考...→最终答案。

    与同步 Agent 保持相同的停止原因、usage、trace、上下文预算和成功写回规则。
    每次运行创建独立的 messages、trace 和 usage 状态。
    """

    def __init__(
        self,
        llm: AsyncChatModel,
        tools: list[Tool | Callable[..., Any]] | None = None,
        system_prompt: str | None = None,
        max_iterations: int = 10,
        memory: Any | None = None,
        context_policy: ContextPolicy | None = None,
        hooks: dict[str, Callable] | None = None,
        long_term_memory: LongTermMemoryStore | None = None,
        tool_authorization_policy: ToolAuthorizationPolicy | None = None,
        default_tool_timeout: float | None = None,
        event_sink: EventSink | None = None,
    ):
        self.llm = llm
        self.max_iterations = max_iterations
        self.memory = memory
        self.context_policy = context_policy
        self.long_term_memory = long_term_memory
        self.event_sink = event_sink

        self.registry = AsyncToolRegistry(
            tools or [],
            authorization_policy=tool_authorization_policy,
            default_timeout=default_tool_timeout,
        )
        self.tools = self.registry.list()

        # 系统提示词
        tool_descs = self._format_tool_descriptions()
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT.format(
            tool_descriptions=tool_descs
        )

        # 钩子
        self.hooks = hooks or {}

    async def run_async(
        self,
        user_input: str,
        *,
        memory_query: MemoryQuery | None = None,
        run_context: RunContext | None = None,
    ) -> AgentResult:
        """异步 ReAct 循环主入口。

        每次调用创建独立的 trace、usage 和 messages 状态。
        """
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
            messages = await self._initial_messages(user_input, memory_query)
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
                response = await self.llm.chat_async(
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
                        else await self.registry.execute_async(call.name, call.arguments)
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

    def run_stream_async(
        self,
        user_input: str,
        *,
        memory_query: MemoryQuery | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """异步流式 ReAct 循环。"""
        return self._run_stream_async_impl(user_input, memory_query)

    async def _run_stream_async_impl(
        self,
        user_input: str,
        memory_query: MemoryQuery | None,
    ) -> AsyncIterator[StreamEvent]:
        """异步流式响应生成器实现。"""
        trace: list[TraceEvent] = []
        total_usage: dict[str, int] = {}
        try:
            messages = await self._initial_messages(user_input, memory_query)
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

            thought_parts: list[str] = []
            tool_calls = _ToolCallAccumulator()
            finalized_calls: list[_AccumulatedToolCall] | None = None
            finish_reason = ""
            request_usage: dict[str, int] = {}

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
                async for chunk in self.llm.chat_stream_async(
                    request_messages, tools=self.registry.schemas()
                ):
                    if chunk.content:
                        thought_parts.append(chunk.content)
                        yield {
                            "type": "thought_chunk",
                            "iteration": iteration,
                            "text": chunk.content,
                        }

                    for delta in chunk.tool_calls:
                        tool_calls.add(delta)

                    for key, value in chunk.usage.items():
                        if isinstance(value, int):
                            request_usage[key] = value
                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason
                if finish_reason == "tool_calls":
                    finalized_calls = tool_calls.finalize()
                self._accumulate_usage(total_usage, request_usage)
            except ModelRequestError as exc:
                self._accumulate_usage(total_usage, request_usage)
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

            thought = "".join(thought_parts)

            if finalized_calls is not None:
                messages.append({
                    "role": "assistant",
                    "content": thought,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": call.raw_arguments,
                            },
                        }
                        for call in finalized_calls
                    ],
                })

                for call in finalized_calls:
                    raw_arguments = call.raw_arguments
                    try:
                        parsed = json.loads(raw_arguments)
                        if not isinstance(parsed, dict):
                            raise ValueError("tool arguments must be a JSON object")
                        arguments: dict[str, Any] | None = parsed
                        execution = await self.registry.execute_async(call.name, parsed)
                    except (json.JSONDecodeError, ValueError) as exc:
                        arguments = None
                        execution = ToolExecutionResult(
                            content=f"invalid arguments for tool '{call.name}': {exc}",
                            error_code="invalid_arguments",
                        )

                    obs = execution.content
                    tool_event: ToolCallEvent = {
                        "type": "tool_call",
                        "iteration": iteration,
                        "index": call.index,
                        "id": call.id,
                        "name": call.name,
                        "arguments": arguments,
                        "raw_arguments": raw_arguments,
                    }
                    observation_event: ObservationEvent = {
                        "type": "observation",
                        "iteration": iteration,
                        "index": call.index,
                        "tool_call_id": call.id,
                        "name": call.name,
                        "text": obs,
                    }
                    if execution.error_code is not None:
                        tool_event["error_code"] = execution.error_code
                        observation_event["error_code"] = execution.error_code
                    yield tool_event
                    yield observation_event

                    trace_event: TraceEvent = {
                        "type": "tool_call",
                        "iteration": iteration,
                        "thought": thought,
                        "tool": call.name,
                        "tool_call_id": call.id,
                        "index": call.index,
                        "arguments": arguments,
                        "raw_arguments": raw_arguments,
                        "observation": obs,
                    }
                    if execution.error_code is not None:
                        trace_event["error_code"] = execution.error_code
                    trace.append(trace_event)
                    self._call_hook("on_tool_call", trace[-1])

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": obs,
                    })
                continue

            if finish_reason == "stop":
                clean = (
                    thought.replace("[FINAL]", "")
                    .replace("Final Answer:", "")
                    .replace("最终答案：", "")
                    .replace("最终答案:", "")
                    .strip()
                )
                yield {
                    "type": "final_answer",
                    "iteration": iteration,
                    "text": clean,
                }
                trace.append({
                    "type": "final_answer",
                    "iteration": iteration,
                    "thought": thought,
                    "final_answer": clean,
                })
                self._call_hook("on_final", trace[-1])
                self._commit_exchange(user_input, clean)
                yield self._done_event(
                    content=clean,
                    trace=trace,
                    usage=total_usage,
                    iterations=iteration + 1,
                    stop_reason="completed",
                    finish_reason=finish_reason,
                )
                return

            trace.append({
                "type": "incomplete",
                "iteration": iteration,
                "thought": thought,
                "finish_reason": finish_reason,
            })
            yield self._done_event(
                content=thought,
                trace=trace,
                usage=total_usage,
                iterations=iteration + 1,
                stop_reason="incomplete",
                finish_reason=finish_reason,
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
        lines = []
        for t in self.tools:
            if isinstance(t, Tool):
                params = ", ".join(t.parameters.get("properties", {}).keys())
                lines.append(f"- {t.name}({params}): {t.description}")
            else:
                lines.append(f"- {getattr(t, '__name__', str(t))}(...): 可用工具")
        return "\n".join(lines)

    def _memory_context(self) -> list[dict[str, Any]]:
        get_context = getattr(self.memory, "get_context", None)
        if callable(get_context):
            return get_context()
        return []

    async def _initial_messages(
        self,
        user_input: str,
        memory_query: MemoryQuery | None,
    ) -> list[dict[str, Any]]:
        messages = [{"role": "system", "content": self.system_prompt}]
        if memory_query is not None:
            if self.long_term_memory is None:
                raise MemoryStoreError("query", backend="unconfigured")
            # 注意：同步 store 会阻塞 event loop
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
            return messages
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