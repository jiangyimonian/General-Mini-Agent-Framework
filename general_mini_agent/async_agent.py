"""异步 ReAct Agent 执行器。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from .agent import (
    DEFAULT_SYSTEM_PROMPT,
    AgentResult,
    DoneEvent,
    ModelErrorEvent,
    ObservationEvent,
    StreamEvent,
    ToolCallEvent,
    TraceEvent,
)
from .agent_kernel import (
    accumulate_usage,
    build_done_event,
    build_model_error_event,
    build_stream_final_events,
    execute_tool_calls_async,
    make_tool_executor_async,
    result_from_decision,
    result_max_iterations,
)
from .agent_protocol import (
    AgentStopReason,
    AssistantTurn,
    StreamingTurnAccumulator,
    TurnDecision,
    append_assistant_turn,
    classify_turn,
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
        long_term_memory: AsyncLongTermMemoryStore | LongTermMemoryStore | None = None,
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
            except ModelRequestError as exc:
                # 统一错误语义：记录 error_code 和 status_code
                error = str(exc)
                trace_entry: dict[str, Any] = {
                    "type": "model_error",
                    "iteration": iteration,
                    "error_code": exc.error_code,
                    "message": error,
                }
                if exc.status_code is not None:
                    trace_entry["status_code"] = exc.status_code
                trace.append(trace_entry)
                emitter.emit(
                    "run_finished", {"stop_reason": "model_error", "error": error}
                )
                return AgentResult(
                    content="",
                    trace=trace,
                    usage=total_usage,
                    iterations=iteration,
                    stop_reason="model_error",
                    error=error,
                    run_id=emitter.run_id,
                )

            accumulate_usage(total_usage, response.usage)

            # 使用协议接口处理响应
            turn = AssistantTurn.from_response(response)
            append_assistant_turn(messages, turn)
            decision = classify_turn(turn)

            if decision.action == "continue":
                # 调用共享内核执行工具
                step_outcome = await execute_tool_calls_async(
                    turn,
                    iteration,
                    make_tool_executor_async(self.registry.execute_async),
                    hook_call=lambda d: self._call_hook("on_tool_call", d),
                )
                trace.extend(step_outcome.trace_events)
                for outcome in step_outcome.outcomes:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": outcome.call.id,
                        "content": outcome.result.content,
                    })
                continue

            if decision.action in ("complete", "stop_error"):
                return result_from_decision(
                    decision=decision,
                    turn=turn,
                    trace=trace,
                    usage=total_usage,
                    iteration=iteration,
                    emitter=emitter,
                    user_input=user_input,
                    commit_fn=self._commit_exchange,
                    hook_call=self._call_hook,
                    run_id=emitter.run_id,
                )

        # 超时返回
        return result_max_iterations(
            max_iterations=self.max_iterations,
            trace=trace,
            usage=total_usage,
            emitter=emitter,
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
            yield build_done_event(
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
            yield build_done_event(
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
                yield build_done_event(
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
                    accumulator.add(chunk)
                    if chunk.content:
                        yield {
                            "type": "thought_chunk",
                            "iteration": iteration,
                            "text": chunk.content,
                        }

                # 累加 usage
                turn = accumulator.finalize()
                accumulate_usage(total_usage, turn.usage)
            except ModelRequestError as exc:
                accumulate_usage(total_usage, accumulator._usage)
                error = str(exc)
                trace.append({
                    "type": "model_error",
                    "iteration": iteration,
                    "error_code": exc.error_code,
                    "message": error,
                })
                yield build_model_error_event(
                    iteration=iteration,
                    error_code=exc.error_code,
                    error=error,
                    status_code=exc.status_code,
                )
                yield build_done_event(
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
                # 调用共享内核执行工具
                step_outcome = await execute_tool_calls_async(
                    turn,
                    iteration,
                    make_tool_executor_async(self.registry.execute_async),
                    hook_call=lambda d: self._call_hook("on_tool_call", d),
                )
                trace.extend(step_outcome.trace_events)
                for outcome in step_outcome.outcomes:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": outcome.call.id,
                        "content": outcome.result.content,
                    })

                # yield 流式事件
                for tool_event in step_outcome.stream_tool_events:
                    yield tool_event
                for obs_event in step_outcome.stream_observation_events:
                    yield obs_event
                continue

            if decision.action in ("complete", "stop_error"):
                events = build_stream_final_events(
                    decision=decision,
                    turn=turn,
                    iteration=iteration,
                    trace=trace,
                    usage=total_usage,
                    user_input=user_input,
                    commit_fn=self._commit_exchange,
                    hook_call=self._call_hook,
                )
                for event in events:
                    yield event
                return

        yield build_done_event(
            content="（已达最大迭代次数，未能得出最终答案）",
            trace=trace,
            usage=total_usage,
            iterations=self.max_iterations,
            stop_reason="max_iterations",
        )

    # ── 内部方法 ────────────────────────────────────────

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
        import inspect

        messages = [{"role": "system", "content": self.system_prompt}]
        if memory_query is not None:
            if self.long_term_memory is None:
                raise MemoryStoreError("query", backend="unconfigured")
            # 检查 query 方法是否为协程函数
            query_method = getattr(self.long_term_memory, "query", None)
            if inspect.iscoroutinefunction(query_method):
                # 异步 store：非阻塞查询
                records = await self.long_term_memory.query(memory_query)  # type: ignore
            else:
                # 同步 store：阻塞 event loop（向后兼容）
                records = self.long_term_memory.query(memory_query)  # type: ignore
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

    def _call_hook(self, name: str, data: dict) -> None:
        hook = self.hooks.get(name)
        if hook:
            hook(data)