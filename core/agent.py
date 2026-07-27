"""基于 thought、action 和 observation 的 ReAct Agent 执行器。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, NotRequired, TypedDict

from .context import ContextBudgetExceeded, ContextPolicy
from .llm import ChatModel, ModelRequestError, ToolCallDelta
from .long_term_memory import (
    LongTermMemoryStore,
    MemoryQuery,
    MemoryStoreError,
    build_memory_context,
)
from .tools import Tool, ToolExecutionResult, ToolRegistry

# ─── 结果类型 ───────────────────────────────────────────────


AgentStopReason = Literal[
    "completed",
    "max_iterations",
    "model_error",
    "incomplete",
    "context_budget_exceeded",
    "memory_error",
]


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
class _AccumulatedToolCall:
    index: int
    id: str = ""
    name: str = ""
    argument_parts: list[str] = field(default_factory=list)

    @property
    def raw_arguments(self) -> str:
        return "".join(self.argument_parts)


class _ToolCallAccumulator:
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


@dataclass
class AgentResult:
    """Agent 执行结果"""
    content: str
    trace: list[TraceEvent] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    iterations: int = 0
    stop_reason: AgentStopReason = "completed"
    error: str | None = None


# ─── Agent 配置 ──────────────────────────────────────────────


@dataclass
class AgentConfig:
    system_prompt: str = ""
    max_iterations: int = 10
    tool_descriptions: str = ""


# ─── ReAct 提示词模板 ─────────────────────────────────────


DEFAULT_SYSTEM_PROMPT = """你是一个擅长多步推理的 AI 助手。你有以下工具可用：

{tool_descriptions}

请按以下格式思考和回答：

Thought: 分析当前情况，决定下一步做什么
Action: 工具名称
Action Input: {{"参数名": "参数值"}}

...（可多次重复 Thought → Action → Observation 步骤）

当你得到足够信息后：

Thought: 我已经得到足够信息
Final Answer: 最终回答

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
    ):
        self.llm = llm
        self.max_iterations = max_iterations
        self.memory = memory
        self.context_policy = context_policy
        self.long_term_memory = long_term_memory

        self.registry = ToolRegistry(tools or [])
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
    ) -> AgentResult:
        """ReAct 循环主入口"""
        trace: list[TraceEvent] = []
        total_usage: dict[str, int] = {}

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
            return AgentResult(
                content="",
                trace=trace,
                usage=total_usage,
                iterations=0,
                stop_reason="memory_error",
                error=error,
            )
        except ContextBudgetExceeded as exc:
            error = str(exc)
            trace.append({
                "type": "context_error",
                "iteration": 0,
                "error_code": "context_budget_exceeded",
                "message": error,
            })
            return AgentResult(
                content="",
                trace=trace,
                usage=total_usage,
                iterations=0,
                stop_reason="context_budget_exceeded",
                error=error,
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
                return AgentResult(
                    content="",
                    trace=trace,
                    usage=total_usage,
                    iterations=iteration,
                    stop_reason="context_budget_exceeded",
                    error=error,
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
                return AgentResult(
                    content="",
                    trace=trace,
                    usage=total_usage,
                    iterations=iteration,
                    stop_reason="model_error",
                    error="model request failed",
                )

            self._accumulate_usage(total_usage, response.usage)

            # 情况 1：LLM 要求调用工具
            if response.tool_calls:
                for tc in response.tool_calls:
                    execution = self.registry.execute(tc.name, tc.arguments)
                    obs = execution.content
                    trace_event: TraceEvent = {
                        "type": "tool_call",
                        "iteration": iteration,
                        "thought": response.content or "",
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "observation": obs,
                    }
                    if execution.error_code is not None:
                        trace_event["error_code"] = execution.error_code
                    trace.append(trace_event)

                    self._call_hook("on_tool_call", trace[-1])

                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                        ],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": obs,
                    })

            # 情况 2：文本回复（无 tool call）→ 最终答案，直接结束
            if response.content and not response.tool_calls:
                content = response.content
                clean_content = (
                    content.replace("[FINAL]", "")
                    .replace("Final Answer:", "")
                    .replace("最终答案：", "")
                    .replace("最终答案:", "")
                    .strip()
                )
                trace.append({
                    "type": "final",
                    "iteration": iteration,
                    "thought": content,
                    "final_answer": clean_content,
                })
                self._call_hook("on_final", trace[-1])
                self._commit_exchange(user_input, clean_content)
                return AgentResult(
                    content=clean_content,
                    trace=trace,
                    usage=total_usage,
                    iterations=iteration + 1,
                )

            # 情况 3：response 既无 content 也无 tool_calls（极少数情况）
            if not response.content and not response.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": "（空响应，请继续）",
                })
                continue

        # 超时返回
        trace.append({
            "type": "max_iterations",
            "iteration": self.max_iterations,
            "message": "maximum iterations reached",
        })
        return AgentResult(
            content="（已达最大迭代次数，未能得出最终答案）",
            trace=trace,
            usage=total_usage,
            iterations=self.max_iterations,
            stop_reason="max_iterations",
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
                for chunk in self.llm.chat_stream(
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
                        execution = self.registry.execute(call.name, parsed)
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
