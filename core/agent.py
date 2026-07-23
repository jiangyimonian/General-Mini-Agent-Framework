"""基于 thought、action 和 observation 的 ReAct Agent 执行器。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, NotRequired, TypedDict

from .llm import ChatModel, ModelRequestError
from .tools import Tool, ToolRegistry

# ─── 结果类型 ───────────────────────────────────────────────


AgentStopReason = Literal["completed", "max_iterations", "model_error"]


class TraceEvent(TypedDict):
    type: str
    iteration: int
    thought: NotRequired[str]
    tool: NotRequired[str]
    arguments: NotRequired[dict[str, Any]]
    observation: NotRequired[str]
    error_code: NotRequired[str]
    final_answer: NotRequired[str]
    message: NotRequired[str]


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
        hooks: dict[str, Callable] | None = None,
    ):
        self.llm = llm
        self.max_iterations = max_iterations
        self.memory = memory

        self.registry = ToolRegistry(tools or [])
        self.tools = self.registry.list()

        # 系统提示词
        tool_descs = self._format_tool_descriptions()
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT.format(
            tool_descriptions=tool_descs
        )

        # 钩子
        self.hooks = hooks or {}

    def run(self, user_input: str) -> AgentResult:
        """ReAct 循环主入口"""
        trace: list[TraceEvent] = []
        total_usage: dict[str, int] = {}

        # 构建初始消息
        messages = [{"role": "system", "content": self.system_prompt}]

        # 加载短期记忆
        messages.extend(self._memory_context())

        # 加入用户输入
        messages.append({"role": "user", "content": user_input})

        # ── ReAct 循环 ────────────────────────────────
        for iteration in range(self.max_iterations):
            try:
                response = self.llm.chat(messages, tools=self.registry.schemas())
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

    def run_stream(self, user_input: str):
        """ReAct 循环流式版 — 逐事件 yield，供上层实时消费"""
        trace: list[TraceEvent] = []
        total_usage: dict[str, int] = {}
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self._memory_context())
        messages.append({"role": "user", "content": user_input})

        for iteration in range(self.max_iterations):
            yield {"type": "iteration_start", "iteration": iteration}

            # 流式累积
            thought_parts: list[str] = []
            tool_calls_buffer: dict[int, dict] = {}  # index → 累积的 tool_call 片段

            for chunk in self.llm.chat_stream(
                messages, tools=self.registry.schemas()
            ):
                if chunk.content:
                    thought_parts.append(chunk.content)
                    yield {"type": "thought_chunk", "text": chunk.content}

                # 初始化 tool call 缓冲区
                if chunk.tool_call_id:
                    idx = 0  # 简化：同一轮只有一个 tool call
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": chunk.tool_call_id,
                            "name": chunk.tool_name,
                            "arguments": "",
                        }
                # 补充 name 和 arguments（可能来自后续 chunk）
                if chunk.tool_call_id or chunk.tool_args:
                    if 0 in tool_calls_buffer:
                        if chunk.tool_name:
                            tool_calls_buffer[0]["name"] = chunk.tool_name
                        tool_calls_buffer[0]["arguments"] += chunk.tool_args

                if chunk.usage:
                    self._accumulate_usage(total_usage, chunk.usage)

                if chunk.finish_reason == "stop":
                    break
                elif chunk.finish_reason == "tool_calls":
                    break

            thought = "".join(thought_parts)

            # 情况 1：有工具调用
            if tool_calls_buffer:
                for tc_data in tool_calls_buffer.values():
                    try:
                        arguments = json.loads(tc_data["arguments"])
                    except (json.JSONDecodeError, KeyError):
                        arguments = {}

                    execution = self.registry.execute(tc_data["name"], arguments)
                    obs = execution.content

                    yield {
                        "type": "tool_call",
                        "name": tc_data["name"],
                        "arguments": arguments,
                    }
                    yield {"type": "observation", "text": obs}

                    trace_event: TraceEvent = {
                        "type": "tool_call",
                        "iteration": iteration,
                        "thought": thought,
                        "tool": tc_data["name"],
                        "arguments": arguments,
                        "observation": obs,
                    }
                    if execution.error_code is not None:
                        trace_event["error_code"] = execution.error_code
                    trace.append(trace_event)
                    self._call_hook("on_tool_call", trace[-1])

                    messages.append({
                        "role": "assistant",
                        "content": thought,
                        "tool_calls": [{
                            "id": tc_data["id"],
                            "type": "function",
                            "function": {
                                "name": tc_data["name"],
                                "arguments": json.dumps(arguments),
                            },
                        }],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_data["id"],
                        "content": obs,
                    })
                continue

            # 情况 2：文本回复（无 tool call）→ 最终答案，直接结束
            if thought:
                clean = (
                    thought.replace("[FINAL]", "")
                    .replace("Final Answer:", "")
                    .replace("最终答案：", "")
                    .replace("最终答案:", "")
                    .strip()
                )
                yield {"type": "final_answer", "text": clean}
                trace.append({
                    "type": "final_answer",
                    "iteration": iteration,
                    "thought": thought,
                    "final_answer": clean,
                })
                self._call_hook("on_final", trace[-1])
                yield {
                    "type": "done",
                    "content": clean,
                    "trace": trace,
                    "usage": total_usage,
                    "iterations": iteration + 1,
                }
                return

            if not thought:
                messages.append({
                    "role": "assistant",
                    "content": "（空响应，请继续）",
                })

        yield {
            "type": "done",
            "content": "（已达最大迭代次数，未能得出最终答案）",
            "trace": trace,
            "usage": total_usage,
            "iterations": self.max_iterations,
            "stop_reason": "max_iterations",
        }

    # ── 内部方法 ────────────────────────────────────────

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

    def _accumulate_usage(self, total: dict, current: dict) -> None:
        for key, val in current.items():
            if isinstance(val, int):
                total[key] = total.get(key, 0) + val

    def _call_hook(self, name: str, data: dict) -> None:
        hook = self.hooks.get(name)
        if hook:
            hook(data)
