# Agent Runtime 1.1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Execution note:** 本文件是完整总计划，仅用于总览和追踪。实际实施必须按以下五份独立文档依次执行，不要直接从本文件并行分派 12 个 Task：
>
> 1. `2026-07-29-agent-runtime-1-1-0-01-protocol-foundation.md`
> 2. `2026-07-29-agent-runtime-1-1-0-02-sync-agent.md`
> 3. `2026-07-29-agent-runtime-1-1-0-03-async-parity.md`
> 4. `2026-07-29-agent-runtime-1-1-0-04-context-memory-state.md`
> 5. `2026-07-29-agent-runtime-1-1-0-05-release-integration.md`

**Goal:** 修复并统一同步、流式和异步 Agent 的工具回合、终止状态、消息协议和状态隔离，使 `1.1.0` 成为后续项目工具、权限和 CLI 的稳定内核。

**Architecture:** 在现有 Agent 生命周期外增加无 I/O 的 `agent_protocol.py`，集中定义 `AssistantTurn`、消息组装、流式回合累积和终止判断。`Agent`、`AsyncAgent` 继续保留各自的同步/异步模型与工具执行路径，但只通过共享协议处理模型回合；不引入完整状态机，也不在本计划中实现项目工具或 CLI。

**Tech Stack:** Python 3.12+, `httpx`, `pytest`, `pytest-asyncio`, `ruff`, Hatchling。运行时不新增依赖；测试不使用真实 API Key 或网络模型服务。

## Global Constraints

- 只实现 `1.1.0`；`1.1.1` 项目工具、`1.1.2` 权限交互、`1.1.3` CLI、`1.1.4` 会话和压缩不进入本计划。
- 运行时依赖保持 `httpx>=0.27.0`；不得为协议层引入第三方库。
- Python 要求保持 `>=3.12`，公共 API 入口保持 `general_mini_agent`。
- 保持 `Agent`、`AsyncAgent`、`AgentResult`、`AgentConfig`、`ToolCall`、`LLMResponse`、`ToolRegistry` 和 `@tool` 的向后兼容构造方式。
- 同步、同步流式、异步非流式和已公开的异步流式路径必须遵守相同的 canonical assistant/tool 消息关系。
- 一次模型回合只能追加一条 assistant 消息；每个 tool call 必须有一个对应 tool result；本版工具按原始顺序执行。
- 工具错误反馈给模型，不把 `unknown_tool`、参数错误、权限拒绝、执行异常和序列化失败直接升级为 Agent 终止错误。
- 非流式旧 `ChatModel` 返回有文本、无工具但没有 `finish_reason` 时，兼容为内部 `stop`；流式响应没有结束原因时不得伪造 `stop`。
- `agent_protocol.py` 只能执行纯数据转换和校验，不访问网络、不执行工具、不读写记忆、不依赖 `agent.py`。
- Agent 实例不保存单次运行的 messages、trace、usage 或工具结果；连续和并发运行必须状态隔离。
- 不在源码、测试、文档或示例中写真实 API Key；错误输出不得泄露 API Key、Authorization Header 或敏感响应正文。
- 每个任务完成独立测试后单独提交；不得把未完成的后续任务代码混入当前提交。
- 默认验证命令使用 `python -m pytest tests -v`；代码质量验证使用 `ruff check general_mini_agent tests demo` 和 `python -m compileall -q general_mini_agent demo tests`。

---

## 文件变更地图

| 文件 | 责任 | 本计划中的变化 |
|---|---|---|
| `general_mini_agent/agent_protocol.py` | 标准回合、消息组装、终止判断、流式累积 | 新建，保持无 I/O |
| `general_mini_agent/llm.py` | `ToolCall`、`LLMResponse` 和 OpenAI-compatible 响应解析 | 保留 raw arguments，增加兼容 finish reason |
| `general_mini_agent/async_llm.py` | 异步模型响应传输 | 复用同步解析契约，保留 finish reason |
| `general_mini_agent/agent.py` | 同步 Agent 生命周期 | 迁移非流式和流式回合处理，删除重复协议逻辑 |
| `general_mini_agent/async_agent.py` | 异步 Agent 生命周期 | 迁移非流式和流式回合处理 |
| `general_mini_agent/context.py` | 请求视图、预算和工具消息组 | 保持现有原子组机制，补充回归覆盖 |
| `general_mini_agent/__init__.py` | 稳定公共导出 | 保持 `AgentStopReason` 原导出路径 |
| `tests/test_llm.py` | 同步响应解析契约 | 增加 finish reason、raw arguments 和非法参数测试 |
| `tests/test_async_llm.py` | 异步响应传输契约 | 验证同步解析结果在异步路径一致 |
| `tests/test_agent_protocol.py` | 纯协议单元测试 | 新建，覆盖消息和终止矩阵 |
| `tests/test_agent.py` | 同步 Agent 行为 | 增加严格消息、多工具和终止测试 |
| `tests/test_async_agent.py` | 异步 Agent 行为 | 增加同一协议矩阵和取消测试 |
| `tests/test_context.py` | 上下文消息边界 | 增加多工具 assistant 原子组测试 |
| `tests/conftest.py` | 离线脚本模型 | 增加严格 transcript 检查替身 |
| `tests/test_runtime_contract.py` | 跨路径契约 | 新建，比较同步/流式/异步最终语义 |
| `pyproject.toml` | 版本和测试元数据 | 升级到 `1.1.0`，必要时登记 marker |
| `.github/workflows/ci.yml` | CI 命令和 wheel smoke test | 删除旧 `core` 路径和导入 |
| `README.md` | 当前能力和验证命令 | 更新 `1.1.0`、消息协议和现有命名空间 |
| `ROADMAP.md` | 未完成路线 | 写入 `1.1.1`–`1.1.4`，不把未来能力写成当前能力 |
| `CHANGELOG.md` | 用户可见变更 | 增加 `1.1.0` 条目 |
| `docs/RELEASING.md` | 发布验证手册 | 修正命名空间和编译命令 |
| `demo/live_agent_smoke.py` | 手动真实 API 工具循环 | 新建，显式环境变量运行 |
| `tests/test_docs_contract.py` | 文档契约 | 从 `1.0.0` 更新到 `1.1.0`，删除当前命令中的 `core` |
| `tests/test_package_metadata.py` | 包元数据契约 | 更新版本和 wheel 导入断言 |
| `tests/test_namespace_compat.py` | 命名空间契约 | 删除已不存在 `core` 的旧测试假设 |

---

## Task 1: 扩展模型响应契约并保留原始工具参数

**Files:**

- Modify: `general_mini_agent/llm.py:55-136`
- Modify: `general_mini_agent/async_llm.py:68-119`
- Test: `tests/test_llm.py`
- Test: `tests/test_async_llm.py`

**Interfaces:**

- Consumes: 现有 OpenAI-compatible `choices[0].message` 和 `choices[0].finish_reason`。
- Produces: 向后兼容的 `ToolCall.from_raw()`、`LLMResponse.finish_reason`、合法/非法参数都可保留现场的解析结果。

- [ ] **Step 1: Write the failing tests**

在 `tests/test_llm.py` 增加：

```python
def test_parse_response_payload_preserves_finish_reason_and_raw_arguments() -> None:
    response = parse_response_payload({
        "choices": [{
            "message": {
                "content": "need data",
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"query":"python"}',
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"total_tokens": 4},
    })

    assert response.finish_reason == "tool_calls"
    assert response.tool_calls is not None
    assert response.tool_calls[0].arguments == {"query": "python"}
    assert response.tool_calls[0].raw_arguments == '{"query":"python"}'
    assert response.tool_calls[0].argument_error is None


@pytest.mark.parametrize(
    "raw_arguments",
    ['{"query":', '["not", "an", "object"]'],
)
def test_parse_response_payload_retains_invalid_tool_arguments(raw_arguments: str) -> None:
    response = parse_response_payload({
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": raw_arguments},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    })

    call = response.tool_calls[0]
    assert call.arguments is None
    assert call.raw_arguments == raw_arguments
    assert call.argument_error


def test_legacy_llm_response_without_finish_reason_remains_constructible() -> None:
    response = LLMResponse(content="ok", tool_calls=None)

    assert response.finish_reason == ""
```

在 `tests/test_async_llm.py` 增加一个 HTTP mock 响应，确认异步非流式结果也保留 `finish_reason == "stop"`。复用现有 `httpx.MockTransport` fixture，不创建真实客户端请求。

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_llm.py::test_parse_response_payload_preserves_finish_reason_and_raw_arguments tests/test_llm.py::test_parse_response_payload_retains_invalid_tool_arguments -v
```

Expected: FAIL because `LLMResponse` has no `finish_reason`, `ToolCall` has no raw argument fields, and invalid JSON currently raises during payload parsing.

- [ ] **Step 3: Implement the minimal response contract**

在 `general_mini_agent/llm.py`：

1. 将 `ToolCall.arguments` 改为 `dict[str, Any] | None`，追加默认字段 `raw_arguments: str = ""` 和 `argument_error: str | None = None`。
2. 增加兼容构造方法：

```python
@classmethod
def from_raw(cls, *, call_id: str, name: str, raw_arguments: str) -> ToolCall:
    try:
        parsed = json.loads(raw_arguments or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("tool arguments must be a JSON object")
        return cls(call_id, name, parsed, raw_arguments or "{}", None)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return cls(call_id, name, None, raw_arguments, str(exc))
```

3. 在 `LLMResponse` 已有默认字段之后追加 `finish_reason: str = ""`。
4. 让 `parse_response_payload()` 从 `choice.get("finish_reason") or ""` 读取结束原因，并使用 `ToolCall.from_raw()`，不能让单个非法工具参数丢弃整个响应。
5. 保持现有合法 JSON 对象的解析结果和工具调用顺序。

在 `general_mini_agent/async_llm.py`，确认异步非流式解析调用共享 `parse_response_payload()`；如果当前代码重复构造 `LLMResponse`，改为传入 `finish_reason`，不要复制参数解析逻辑。

- [ ] **Step 4: Run focused tests**

Run:

```bash
python -m pytest tests/test_llm.py tests/test_async_llm.py -v
```

Expected: PASS；现有 `LLMResponse(content="...", tool_calls=None)` 构造测试继续通过。

- [ ] **Step 5: Commit**

```bash
git add general_mini_agent/llm.py general_mini_agent/async_llm.py tests/test_llm.py tests/test_async_llm.py
git commit -m "feat: preserve model finish reasons and raw tool arguments"
```

---

## Task 2: 建立纯协议模块

**Files:**

- Create: `general_mini_agent/agent_protocol.py`
- Create: `tests/test_agent_protocol.py`
- Modify: `general_mini_agent/agent.py:29-35, 1-20`
- Modify: `general_mini_agent/async_agent.py:1-20`

**Interfaces:**

- Consumes: `LLMResponse`, `ToolCall`, `ToolExecutionResult`。
- Produces: `AgentStopReason`、`AssistantTurn`、`ToolOutcome`、`TurnDecision`、消息组装函数、终止分类函数、trace 构造函数、错误结果构造函数和最终文本清理函数。

- [ ] **Step 1: Write the failing protocol tests**

新建 `tests/test_agent_protocol.py`，先写这些测试：

```python
import pytest

from general_mini_agent.agent_protocol import (
    AssistantTurn,
    TurnDecision,
    append_assistant_turn,
    append_tool_outcomes,
    classify_turn,
    clean_final_content,
)
from general_mini_agent.llm import LLMResponse, ToolCall
from general_mini_agent.tools import ToolExecutionResult


def test_normalized_legacy_text_response_is_completed() -> None:
    turn = AssistantTurn.from_response(
        LLMResponse(content="answer", tool_calls=None, finish_reason="")
    )

    assert turn.finish_reason == "stop"
    assert classify_turn(turn) == TurnDecision(action="complete", stop_reason="completed")


def test_tool_calls_take_precedence_over_finish_reason() -> None:
    turn = AssistantTurn.from_response(LLMResponse(
        content="using tools",
        tool_calls=[ToolCall("c1", "lookup", {"q": "x"})],
        finish_reason="length",
    ))

    assert classify_turn(turn).action == "continue"


@pytest.mark.parametrize("finish_reason", ["length", "content_filter", "future_reason"])
def test_non_terminal_finish_is_incomplete(finish_reason: str) -> None:
    turn = AssistantTurn("partial", (), finish_reason, {})

    assert classify_turn(turn) == TurnDecision(
        action="stop_error",
        stop_reason="incomplete",
        error_code="incomplete_model_response",
    )


def test_empty_response_is_model_error() -> None:
    decision = classify_turn(AssistantTurn(None, (), "stop", {}))

    assert decision.stop_reason == "model_error"
    assert decision.error_code == "empty_model_response"


def test_append_multiple_tool_calls_keeps_one_assistant_and_ordered_results() -> None:
    messages = [{"role": "user", "content": "question"}]
    turn = AssistantTurn(
        "checking",
        (
            ToolCall("c1", "first", {"value": 1}),
            ToolCall("c2", "second", {"value": 2}),
        ),
        "tool_calls",
        {},
    )
    outcomes = (
        ToolOutcome(turn.tool_calls[0], ToolExecutionResult(content="one")),
        ToolOutcome(turn.tool_calls[1], ToolExecutionResult(content="two")),
    )

    append_assistant_turn(messages, turn)
    append_tool_outcomes(messages, outcomes)

    assert [message["role"] for message in messages] == ["user", "assistant", "tool", "tool"]
    assert len(messages[1]["tool_calls"]) == 2
    assert [message["tool_call_id"] for message in messages[2:]] == ["c1", "c2"]


def test_clean_final_content_keeps_legacy_prefix_compatibility() -> None:
    assert clean_final_content("[FINAL] Final Answer: done") == "done"
```

`ToolOutcome` 在测试中使用真实 `ToolExecutionResult`，确保协议层只消费结果，不执行工具。

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_agent_protocol.py -v
```

Expected: FAIL with import errors because `agent_protocol.py` and its interfaces do not exist。

- [ ] **Step 3: Implement the pure protocol module**

实现以下完整接口：

```python
AgentStopReason = Literal[
    "completed",
    "max_iterations",
    "model_error",
    "incomplete",
    "context_budget_exceeded",
    "memory_error",
]

TurnAction = Literal["continue", "complete", "stop_error"]


@dataclass(frozen=True)
class AssistantTurn:
    content: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str | None
    usage: dict[str, int]

    @classmethod
    def from_response(cls, response: LLMResponse) -> "AssistantTurn":
        calls = tuple(response.tool_calls or ())
        reason = response.finish_reason or None
        if reason is None and response.content and not calls:
            reason = "stop"
        return cls(response.content, calls, reason, dict(response.usage))


@dataclass(frozen=True)
class ToolOutcome:
    call: ToolCall
    result: ToolExecutionResult


@dataclass(frozen=True)
class TurnDecision:
    action: TurnAction
    stop_reason: AgentStopReason | None = None
    error_code: str | None = None
    message: str | None = None
```

`classify_turn()` 使用以下精确顺序：

```python
if turn.tool_calls:
    return TurnDecision("continue")
if turn.finish_reason == "stop" and turn.content:
    return TurnDecision("complete", "completed")
if turn.finish_reason == "tool_calls":
    return TurnDecision("stop_error", "model_error", "missing_tool_calls")
if not turn.content:
    return TurnDecision("stop_error", "model_error", "empty_model_response")
return TurnDecision("stop_error", "incomplete", "incomplete_model_response")
```

`append_assistant_turn()` 始终追加一条 assistant 消息，参数优先使用 `call.raw_arguments`，为空时使用 `json.dumps(call.arguments or {}, ensure_ascii=False, separators=(",", ":"))`。`append_tool_outcomes()` 按传入顺序追加一个 tool message per outcome。两者都不能修改传入的 `ToolCall` 或 `ToolExecutionResult`。

同一模块还必须提供后续执行器使用的确定签名：

```python
def invalid_arguments_result(call: ToolCall) -> ToolExecutionResult: ...

def build_tool_trace(
    iteration: int,
    turn: AssistantTurn,
    index: int,
    call: ToolCall,
    result: ToolExecutionResult,
) -> dict[str, Any]: ...

def build_incomplete_trace(
    iteration: int,
    turn: AssistantTurn,
    decision: TurnDecision,
) -> dict[str, Any]: ...

def safe_error_message(decision: TurnDecision) -> str: ...
```

`invalid_arguments_result()` 返回 `error_code="invalid_arguments"`；`build_tool_trace()` 产生包含 `type`, `iteration`, `thought`, `tool`, `tool_call_id`, `index`, `arguments`, `raw_arguments`, `observation` 的字典，并在结果有错误时加入 `error_code`；`build_incomplete_trace()` 使用 `type="incomplete"` 和本轮 finish reason；`safe_error_message()` 只从固定错误码映射到安全文本，不回显模型原文。

Task 4 使用的同步 Agent 辅助方法签名固定为：

```python
def _result_from_decision(
    self,
    decision: TurnDecision,
    turn: AssistantTurn,
    trace: list[TraceEvent],
    usage: dict[str, int],
    iterations: int,
    emitter: RunEventEmitter,
) -> AgentResult: ...
```

把 `AgentStopReason` 从 `agent.py` 移到协议模块；`agent.py` 和包根目录改为导入后重新导出，保持 `from general_mini_agent.agent import AgentStopReason` 不变。

- [ ] **Step 4: Run focused protocol and import tests**

Run:

```bash
python -m pytest tests/test_agent_protocol.py tests/test_namespace_compat.py -v
```

Expected: PASS；旧导入路径仍能得到同一个 `AgentStopReason` 类型别名。

- [ ] **Step 5: Commit**

```bash
git add general_mini_agent/agent_protocol.py general_mini_agent/agent.py general_mini_agent/async_agent.py tests/test_agent_protocol.py
git commit -m "feat: add shared agent turn protocol"
```

---

## Task 3: 迁移并测试流式回合累积器

**Files:**

- Modify: `general_mini_agent/agent_protocol.py`
- Modify: `general_mini_agent/llm.py:138-180`
- Test: `tests/test_agent_protocol.py`
- Test: `tests/test_llm.py`

**Interfaces:**

- Consumes: `StreamChunk` 的文本、按 index 的 `ToolCallDelta`、usage 快照和 finish reason。
- Produces: `StreamingTurnAccumulator.add(chunk)` 与 `finalize() -> AssistantTurn`。

- [ ] **Step 1: Write the failing accumulator tests**

```python
from general_mini_agent.agent_protocol import StreamingTurnAccumulator
from general_mini_agent.llm import StreamChunk, ToolCallDelta


def test_streaming_accumulator_reconstructs_interleaved_calls_by_index() -> None:
    accumulator = StreamingTurnAccumulator()
    accumulator.add(StreamChunk(content="checking ", tool_calls=[
        ToolCallDelta(1, "c2", "second", '{"value":'),
        ToolCallDelta(0, "c1", "first", '{"value":'),
    ]))
    accumulator.add(StreamChunk(
        content="now",
        tool_calls=[
            ToolCallDelta(0, arguments="1}"),
            ToolCallDelta(1, arguments="2}"),
        ],
        finish_reason="tool_calls",
        usage={"total_tokens": 5},
    ))

    turn = accumulator.finalize()

    assert turn.content == "checking now"
    assert [call.id for call in turn.tool_calls] == ["c1", "c2"]
    assert [call.name for call in turn.tool_calls] == ["first", "second"]
    assert turn.finish_reason == "tool_calls"
    assert turn.usage == {"total_tokens": 5}


def test_streaming_accumulator_continues_on_calls_without_tool_calls_finish_reason() -> None:
    accumulator = StreamingTurnAccumulator()
    accumulator.add(StreamChunk(
        tool_calls=[ToolCallDelta(0, "c1", "lookup", "{}")],
        finish_reason="stop",
    ))

    assert accumulator.finalize().tool_calls


def test_streaming_accumulator_rejects_tool_calls_finish_without_calls() -> None:
    accumulator = StreamingTurnAccumulator()
    accumulator.add(StreamChunk(finish_reason="tool_calls"))

    with pytest.raises(ModelRequestError, match="no calls"):
        accumulator.finalize()


def test_streaming_text_without_finish_reason_remains_incomplete() -> None:
    accumulator = StreamingTurnAccumulator()
    accumulator.add(StreamChunk(content="partial"))

    turn = accumulator.finalize()

    assert turn.finish_reason is None
    assert classify_turn(turn).stop_reason == "incomplete"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_agent_protocol.py -k streaming -v
```

Expected: FAIL because the accumulator is still private to `agent.py` and only finalizes when `finish_reason == "tool_calls"`。

- [ ] **Step 3: Implement the accumulator**

把当前 `_AccumulatedToolCall` 和 `_ToolCallAccumulator` 的身份冲突校验迁移到 `agent_protocol.py`。实现规则：

```python
class StreamingTurnAccumulator:
    def __init__(self) -> None:
        self._parts: dict[int, _PendingToolCall] = {}
        self._text: list[str] = []
        self._finish_reason: str | None = None
        self._usage: dict[str, int] = {}

    def add(self, chunk: StreamChunk) -> None:
        self._text.append(chunk.content)
        for delta in chunk.tool_calls:
            pending = self._parts.setdefault(delta.index, _PendingToolCall(delta.index))
            pending.merge(delta)
        if chunk.finish_reason:
            self._finish_reason = chunk.finish_reason
        for key, value in chunk.usage.items():
            if isinstance(value, int):
                self._usage[key] = value

    def finalize(self) -> AssistantTurn:
        calls = tuple(
            self._parts[index].to_tool_call()
            for index in sorted(self._parts)
        )
        if self._finish_reason == "tool_calls" and not calls:
            raise ModelRequestError(
                "model ended with tool_calls but supplied no calls",
                error_code="stream_protocol_error",
            )
        return AssistantTurn(
            "".join(self._text) or None,
            calls,
            self._finish_reason,
            dict(self._usage),
        )
```

`_PendingToolCall.merge()` 必须拒绝同一 index 的 ID 或名称冲突；缺少 ID 或名称时 `to_tool_call()` 抛 `ModelRequestError(error_code="stream_protocol_error")`。调用参数通过 `ToolCall.from_raw()` 解析，非法 JSON 仍返回带 `argument_error` 的调用，不在累积阶段执行工具。

- [ ] **Step 4: Run focused tests**

Run:

```bash
python -m pytest tests/test_agent_protocol.py -k streaming tests/test_llm.py -k stream -v
```

Expected: PASS；原有流式增量解析测试不变。

- [ ] **Step 5: Commit**

```bash
git add general_mini_agent/agent_protocol.py general_mini_agent/llm.py tests/test_agent_protocol.py tests/test_llm.py
git commit -m "feat: centralize streaming turn accumulation"
```

---

## Task 4: 为同步非流式 Agent 接入标准回合协议

**Files:**

- Modify: `general_mini_agent/agent.py:261-460`
- Modify: `tests/conftest.py`
- Test: `tests/test_agent.py`

**Interfaces:**

- Consumes: `self.llm.chat()`, `ToolRegistry.execute()` 和 `agent_protocol` 的 `AssistantTurn`。
- Produces: 合法的多工具 canonical transcript、结构化工具 trace 和可恢复的工具错误。

- [ ] **Step 1: Add a strict transcript test double and failing behavior tests**

在 `tests/conftest.py` 增加独立校验函数，不能复用被测的 context 私有实现：

```python
def assert_valid_tool_transcript(messages: list[dict[str, Any]]) -> None:
    pending: set[str] = set()
    for index, message in enumerate(messages):
        role = message["role"]
        if role == "assistant":
            assert not pending, f"assistant appeared before results at {index}"
            for call in message.get("tool_calls", []):
                call_id = call["id"]
                assert call_id not in pending
                pending.add(call_id)
        elif role == "tool":
            call_id = message["tool_call_id"]
            assert call_id in pending
            pending.remove(call_id)
        else:
            assert not pending, f"message interrupted tool turn at {index}"
    assert not pending


class StrictScriptedChatModel(ScriptedChatModel):
    def chat(self, messages, *, tools=None):
        assert_valid_tool_transcript(messages)
        return super().chat(messages, tools=tools)
```

在 `tests/test_agent.py` 增加：

```python
def test_sync_agent_keeps_multiple_tool_calls_in_one_assistant_message() -> None:
    @tool
    def first(value: int) -> str:
        return f"first:{value}"

    @tool
    def second(value: int) -> str:
        return f"second:{value}"

    model = StrictScriptedChatModel([
        LLMResponse(
            content="checking",
            tool_calls=[
                ToolCall("c1", "first", {"value": 1}),
                ToolCall("c2", "second", {"value": 2}),
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", tool_calls=None, finish_reason="stop"),
    ])

    result = Agent(model, tools=[first, second]).run("question")

    assert result.content == "done"
    assistant = model.calls[1][0][-3]
    assert len(assistant["tool_calls"]) == 2
    assert [message["tool_call_id"] for message in model.calls[1][0][-2:]] == ["c1", "c2"]
```

- [ ] **Step 2: Run the regression test to verify it fails**

Run:

```bash
python -m pytest tests/test_agent.py::test_sync_agent_keeps_multiple_tool_calls_in_one_assistant_message -v
```

Expected: FAIL because current `Agent.run()` appends one assistant/tool pair for each call。

- [ ] **Step 3: Replace the sync response handling block**

在模型请求成功后立即执行：

```python
turn = AssistantTurn.from_response(response)
self._accumulate_usage(total_usage, turn.usage)
append_assistant_turn(messages, turn)
decision = classify_turn(turn)

if decision.action == "continue":
    outcomes: list[ToolOutcome] = []
    for index, call in enumerate(turn.tool_calls):
        if call.arguments is None:
            execution = ToolExecutionResult(
                content=f"invalid arguments for tool '{call.name}': "
                        f"{call.argument_error or 'invalid JSON object'}",
                error_code="invalid_arguments",
            )
        else:
            execution = self.registry.execute(call.name, call.arguments)
        outcomes.append(ToolOutcome(call, execution))

        trace_event = build_tool_trace(iteration, turn, index, call, execution)
        trace.append(trace_event)
        self._call_hook("on_tool_call", dict(trace_event))

    append_tool_outcomes(messages, outcomes)
    continue

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
        usage=total_usage,
        iterations=iteration + 1,
        run_id=emitter.run_id,
    )

return self._result_from_decision(
    decision,
    turn,
    trace,
    total_usage,
    iteration + 1,
    emitter,
)
```

实现 `build_tool_trace()` 时保留现有 trace 的 `type`, `iteration`, `thought`, `tool`, `arguments`, `observation` 字段，并增加 `tool_call_id`, `index`, `raw_arguments`；有错误时追加 `error_code`。`_result_from_decision()` 负责把 `stop_error` 转成现有 `AgentResult`，错误文本使用固定安全消息，不回显原始模型响应。

删除同步路径中逐工具追加 assistant 消息的代码和“空响应，请继续”的伪造消息逻辑。

- [ ] **Step 4: Run sync Agent tests**

Run:

```bash
python -m pytest tests/test_agent.py -v
```

Expected: PASS；原有单工具、链式工具、未知工具、工具异常、最大迭代、memory 和 hook 测试保持通过，多工具严格 transcript 测试通过。

- [ ] **Step 5: Commit**

```bash
git add general_mini_agent/agent.py tests/conftest.py tests/test_agent.py
git commit -m "fix: build canonical sync tool turns"
```

---

## Task 5: 固化同步非流式终止、提示词和记忆行为

**Files:**

- Modify: `general_mini_agent/agent.py:200-220, 261-460`
- Test: `tests/test_agent.py`
- Test: `tests/test_memory.py`

**Interfaces:**

- Consumes: `TurnDecision` 和 `AgentResult` 的现有公共结构。
- Produces: `completed`, `incomplete`, `model_error`、memory commit 和默认 prompt 的明确行为。

- [ ] **Step 1: Write terminal and compatibility tests**

```python
@pytest.mark.parametrize("finish_reason", ["length", "content_filter", "future_reason"])
def test_sync_non_terminal_finish_does_not_commit_memory(finish_reason: str) -> None:
    memory = InMemoryConversation()
    model = ScriptedChatModel([
        LLMResponse(content="partial", tool_calls=None, finish_reason=finish_reason),
    ])

    result = Agent(model, memory=memory).run("question")

    assert result.stop_reason == "incomplete"
    assert result.content == "partial"
    assert memory.get_context() == []


def test_sync_empty_response_is_model_error_without_fake_followup() -> None:
    model = ScriptedChatModel([
        LLMResponse(content=None, tool_calls=None, finish_reason="stop"),
    ])

    result = Agent(model).run("question")

    assert result.stop_reason == "model_error"
    assert result.error == "model returned an empty response"
    assert len(model.calls) == 1


def test_sync_legacy_model_without_finish_reason_still_completes() -> None:
    model = ScriptedChatModel([LLMResponse(content="answer", tool_calls=None)])

    result = Agent(model).run("question")

    assert result.stop_reason == "completed"
    assert result.content == "answer"


def test_default_prompt_uses_native_tools_without_text_react_markers() -> None:
    prompt = Agent(ScriptedChatModel([])).system_prompt

    assert "tool" in prompt.lower()
    assert "Action Input:" not in prompt
    assert "Final Answer:" not in prompt


def test_final_hook_receives_copy_of_trace_entry() -> None:
    received: list[dict] = []

    def hook(event: dict) -> None:
        received.append(event)
        event["final_answer"] = "mutated by hook"

    result = Agent(
        ScriptedChatModel([LLMResponse(content="answer", tool_calls=None)]),
        hooks={"on_final": hook},
    ).run("question")

    assert received[0]["final_answer"] == "mutated by hook"
    assert result.trace[-1]["final_answer"] == "answer"
```

- [ ] **Step 2: Run tests to verify terminal tests fail**

Run:

```bash
python -m pytest tests/test_agent.py -k "non_terminal or empty_response or legacy_model or default_prompt or final_hook" -v
```

Expected: FAIL because current sync Agent treats text without tool calls as completed, fakes empty responses, and uses the text ReAct prompt。

- [ ] **Step 3: Implement terminal and prompt behavior**

把 `DEFAULT_SYSTEM_PROMPT` 改成协议中的原生工具调用提示词，并继续通过 `.format(tool_descriptions=...)` 注入工具列表。不要要求模型输出 `Thought:`、`Action:`、`Action Input:` 或 `Final Answer:`。

让 `stop_error` 返回：

```python
AgentResult(
    content=turn.content or "",
    trace=trace + [{
        "type": decision.error_code or "incomplete",
        "iteration": iteration,
        "thought": turn.content or "",
        "finish_reason": turn.finish_reason or "",
        "message": decision.message or "model response was incomplete",
    }],
    usage=total_usage,
    iterations=iteration + 1,
    stop_reason=decision.stop_reason or "model_error",
    error=safe_error_message(decision),
    run_id=emitter.run_id,
)
```

`empty_model_response` 的安全错误文本固定为 `model returned an empty response`；`incomplete_model_response` 固定为 `model response was incomplete`。所有异常路径发出一次 `run_finished`，不调用 `on_final`，不调用 `_commit_exchange()`。

保留 `clean_final_content()` 对 `[FINAL]`、`Final Answer:`、`最终答案：` 和 `最终答案:` 的兼容清理，但只用于展示文本。

- [ ] **Step 4: Run focused and full sync tests**

Run:

```bash
python -m pytest tests/test_agent.py tests/test_memory.py -v
```

Expected: PASS；旧的 `[FINAL]` 兼容测试继续通过，非正常响应不再写 memory。

- [ ] **Step 5: Commit**

```bash
git add general_mini_agent/agent.py tests/test_agent.py tests/test_memory.py
git commit -m "fix: classify sync terminal model responses"
```

---

## Task 6: 迁移同步流式 Agent

**Files:**

- Modify: `general_mini_agent/agent.py:124-170, 463-750`
- Test: `tests/test_agent.py`

**Interfaces:**

- Consumes: `StreamingTurnAccumulator`, `classify_turn`, `append_assistant_turn` 和 `append_tool_outcomes`。
- Produces: 流式文本事件保持兼容，完整工具回合在响应结束后执行，终止事件与同步非流式一致。

- [ ] **Step 1: Add failing stream behavior tests**

```python
def test_stream_executes_complete_tool_call_even_when_finish_reason_is_stop() -> None:
    executions: list[str] = []

    @tool
    def lookup() -> str:
        executions.append("lookup")
        return "result"

    model = ScriptedStreamingChatModel([], [
        [StreamChunk(
            tool_calls=[ToolCallDelta(0, "c1", "lookup", "{}")],
            finish_reason="stop",
        )],
        [StreamChunk(content="done", finish_reason="stop")],
    ])

    events = list(Agent(model, tools=[lookup]).run_stream("question"))

    assert executions == ["lookup"]
    assert events[-1]["stop_reason"] == "completed"


def test_stream_text_without_finish_reason_is_incomplete() -> None:
    model = ScriptedStreamingChatModel([], [[StreamChunk(content="partial")]])

    events = list(Agent(model).run_stream("question"))

    assert events[-1]["stop_reason"] == "incomplete"
    assert events[-1]["finish_reason"] == ""


def test_stream_multi_tool_request_keeps_all_calls_in_one_assistant_message() -> None:
    @tool
    def first() -> str:
        return "one"

    @tool
    def second() -> str:
        return "two"

    model = ScriptedStreamingChatModel([], [
        [StreamChunk(tool_calls=[
            ToolCallDelta(1, "c2", "second", "{}"),
            ToolCallDelta(0, "c1", "first", "{}"),
        ], finish_reason="tool_calls")],
        [StreamChunk(content="done", finish_reason="stop")],
    ])

    list(Agent(model, tools=[first, second]).run_stream("question"))

    assistant = model.stream_calls[1][0][-3]
    assert [call["id"] for call in assistant["tool_calls"]] == ["c1", "c2"]


def test_stream_incomplete_response_does_not_write_memory() -> None:
    memory = InMemoryConversation()
    model = ScriptedStreamingChatModel([], [[StreamChunk(content="partial", finish_reason="length")]])

    events = list(Agent(model, memory=memory).run_stream("question"))

    assert events[-1]["stop_reason"] == "incomplete"
    assert memory.get_context() == []
```

- [ ] **Step 2: Run tests to verify stream migration fails**

Run:

```bash
python -m pytest tests/test_agent.py -k "stream_executes_complete or stream_text_without or stream_multi_tool_request" -v
```

Expected: FAIL because current code only finalizes calls when `finish_reason == "tool_calls"` and owns a duplicate accumulator。

- [ ] **Step 3: Replace the stream loop with shared turn handling**

在每轮开始创建 `StreamingTurnAccumulator()`。消费模型 chunk 时保留现有 `thought_chunk` 事件，并把每个 chunk 交给 `accumulator.add(chunk)`。流结束后：

```python
turn = accumulator.finalize()
self._accumulate_usage(total_usage, turn.usage)
append_assistant_turn(messages, turn)
decision = classify_turn(turn)

if decision.action == "continue":
    outcomes = self._execute_stream_tool_calls(turn, iteration, trace)
    append_tool_outcomes(messages, outcomes)
    continue

if decision.action == "complete":
    clean = clean_final_content(turn.content or "")
    yield {"type": "final_answer", "iteration": iteration, "text": clean}
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

yield self._done_event(
    content=turn.content or "",
    trace=trace + [build_incomplete_trace(iteration, turn, decision)],
    usage=total_usage,
    iterations=iteration + 1,
    stop_reason=decision.stop_reason or "model_error",
    finish_reason=turn.finish_reason or "",
    error=safe_error_message(decision),
)
return
```

`_execute_stream_tool_calls()` 的签名固定为 `def _execute_stream_tool_calls(self, turn: AssistantTurn, iteration: int, trace: list[TraceEvent]) -> tuple[ToolOutcome, ...]`。它必须先建立全部 `ToolOutcome`，再追加结果；公开事件可以在每个工具完成后 yield，但 canonical messages 只能在 assistant 已追加后按顺序追加 tool messages。参数解析失败时不执行 registry，使用 `call.argument_error` 生成 `invalid_arguments`。

捕获 `ModelRequestError` 时保留已收集的最后 usage，错误事件和 `done` 事件维持现有顺序。消费者提前关闭生成器时不调用提交记忆逻辑。

删除 `agent.py` 中旧的 `_AccumulatedToolCall` 和 `_ToolCallAccumulator` 定义，改为从 `agent_protocol` 导入。

- [ ] **Step 4: Run all sync stream tests**

Run:

```bash
python -m pytest tests/test_agent.py -k stream -v
```

Expected: PASS；已有交错工具、非法 JSON、usage、模型错误、hook 和提前不完成测试全部保留。

- [ ] **Step 5: Commit**

```bash
git add general_mini_agent/agent.py tests/test_agent.py
git commit -m "fix: align sync streaming with turn protocol"
```

---

## Task 7: 为异步非流式 Agent 接入相同协议

**Files:**

- Modify: `general_mini_agent/async_agent.py:86-290`
- Test: `tests/test_async_agent.py`

**Interfaces:**

- Consumes: `await self.llm.chat_async()` 和 `await self.registry.execute_async()`。
- Produces: 与同步非流式路径相同的消息、终止、trace、memory 和取消语义。

- [ ] **Step 1: Write failing async protocol tests**

在 `tests/test_async_agent.py` 增加：

```python
def test_async_agent_keeps_multiple_tool_calls_in_one_assistant_message() -> None:
    async def scenario():
        @tool
        def first(value: int) -> str:
            return f"first:{value}"

        @tool
        def second(value: int) -> str:
            return f"second:{value}"

        model = ScriptedAsyncChatModel([
            LLMResponse(
                content="checking",
                tool_calls=[
                    ToolCall("c1", "first", {"value": 1}),
                    ToolCall("c2", "second", {"value": 2}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="done", tool_calls=None, finish_reason="stop"),
        ])
        result = await AsyncAgent(model, tools=[first, second]).run_async("question")
        return result, model

    result, model = asyncio.run(scenario())

    assert result.content == "done"
    assistant = model.calls[1][0][-3]
    assert len(assistant["tool_calls"]) == 2


def test_async_agent_incomplete_response_does_not_commit_memory() -> None:
    async def scenario():
        memory = InMemoryConversation()
        model = ScriptedAsyncChatModel([
            LLMResponse(content="partial", tool_calls=None, finish_reason="length"),
        ])
        result = await AsyncAgent(model, memory=memory).run_async("question")
        return result, memory

    result, memory = asyncio.run(scenario())

    assert result.stop_reason == "incomplete"
    assert memory.get_context() == []
```

在 `tests/conftest.py` 增加以下最小异步脚本模型，供 Task 7 和 Task 8 共用；它只记录测试输入，不保存 Agent 运行状态：

```python
class ScriptedAsyncChatModel:
    def __init__(self, responses: Sequence[LLMResponse], streams=()) -> None:
        self.responses = list(responses)
        self.streams = list(streams)
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []
        self.stream_calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []

    async def chat_async(self, messages, *, tools=None):
        self.calls.append((deepcopy(messages), deepcopy(tools)))
        if not self.responses:
            raise AssertionError("ScriptedAsyncChatModel has no remaining responses")
        return self.responses.pop(0)

    async def chat_stream_async(self, messages, *, tools=None):
        self.stream_calls.append((deepcopy(messages), deepcopy(tools)))
        if not self.streams:
            raise AssertionError("ScriptedAsyncChatModel has no remaining streams")
        stream = self.streams.pop(0)
        if isinstance(stream, Exception):
            raise stream
        for chunk in stream:
            yield chunk
```

不要复用当前只返回 `done` 事件的 `MockAsyncLLM` 流式替身，因为它不验证 canonical messages。

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_async_agent.py -k "multiple_tool_calls or incomplete_response" -v
```

Expected: FAIL because current async path逐调用追加 assistant/tool，并将非流式文本默认视为成功。

- [ ] **Step 3: Replace async response handling**

将同步 Task 4 的回合处理改写为异步版本，核心代码必须保持同一顺序。AsyncAgent 的两个收尾辅助方法使用以下签名：

```python
async def _finish_completed_run(
    self, user_input: str, turn: AssistantTurn, trace: list[TraceEvent],
    usage: dict[str, int], iteration: int, emitter: RunEventEmitter,
) -> AgentResult: ...

def _finish_stopped_run(
    self, decision: TurnDecision, turn: AssistantTurn, trace: list[TraceEvent],
    usage: dict[str, int], iterations: int, emitter: RunEventEmitter,
) -> AgentResult: ...
```

核心代码必须保持同一顺序：

```python
turn = AssistantTurn.from_response(response)
self._accumulate_usage(total_usage, turn.usage)
append_assistant_turn(messages, turn)
decision = classify_turn(turn)

if decision.action == "continue":
    outcomes: list[ToolOutcome] = []
    for index, call in enumerate(turn.tool_calls):
        if call.arguments is None:
            execution = invalid_arguments_result(call)
        else:
            execution = await self.registry.execute_async(call.name, call.arguments)
        outcomes.append(ToolOutcome(call, execution))
        trace_event = build_tool_trace(iteration, turn, index, call, execution)
        trace.append(trace_event)
        self._call_hook("on_tool_call", dict(trace_event))
    append_tool_outcomes(messages, outcomes)
    continue

if decision.action == "complete":
    return self._finish_completed_run(...)

return self._finish_stopped_run(...)
```

保留当前 `CancelledError` 直接传播的行为；不要在 `except Exception` 中吞掉取消。工具超时仍由 `AsyncToolRegistry` 返回结构化错误，让模型可以恢复。

- [ ] **Step 4: Run async tests**

Run:

```bash
python -m pytest tests/test_async_agent.py -v
```

Expected: PASS；已有工具超时、取消、授权、并发运行、memory 提交和状态隔离测试全部通过。

- [ ] **Step 5: Commit**

```bash
git add general_mini_agent/async_agent.py tests/test_async_agent.py tests/conftest.py
git commit -m "fix: align async agent with turn protocol"
```

---

## Task 8: 迁移异步流式 Agent 并完成四路径语义统一

**Files:**

- Modify: `general_mini_agent/async_agent.py:291-565`
- Test: `tests/test_async_agent.py`
- Test: `tests/test_runtime_contract.py`

**Interfaces:**

- Consumes: `AsyncLLM.chat_stream_async()`、共享 `StreamingTurnAccumulator` 和异步工具执行。
- Produces: 异步流式与同步流式相同的最终 canonical transcript、stop reason、usage 和记忆条件。

- [ ] **Step 1: Write cross-path contract tests**

新建 `tests/test_runtime_contract.py`，使用同一个逻辑场景：第一轮同时调用两个工具，第二轮返回文本。

```python
def normalize_request(messages):
    return [
        {
            "role": message["role"],
            "content": message.get("content"),
            **({"tool_call_ids": [call["id"] for call in message["tool_calls"]]}
               if message.get("tool_calls") else {}),
            **({"tool_call_id": message["tool_call_id"]}
               if message.get("tool_call_id") else {}),
        }
        for message in messages
    ]


def assert_two_tool_turn(messages):
    assistant = next(message for message in messages if message.get("tool_calls"))
    assert assistant["role"] == "assistant"
    assert [call["id"] for call in assistant["tool_calls"]] == ["c1", "c2"]
    assert [message["tool_call_id"] for message in messages if message["role"] == "tool"] == [
        "c1", "c2",
    ]
```

为同步非流式、同步流式、异步非流式和已公开异步流式分别创建最小脚本模型，断言：

```python
assert result.content == "done"
assert result.stop_reason == "completed"
assert result.iterations == 2
assert [event["tool"] for event in result.trace if event["type"] == "tool_call"] == [
    "first", "second",
]
```

如果某条异步流式公共入口在当前仓库没有稳定测试接口，则只测试已公开的 `run_stream_async()`，不新增接口。

- [ ] **Step 2: Run the cross-path tests before migration**

Run:

```bash
python -m pytest tests/test_runtime_contract.py -v
```

Expected: FAIL in at least the async streaming or transcript assertions，明确指出剩余不一致路径。

- [ ] **Step 3: Replace async streaming loop**

将当前 `_ToolCallAccumulator` 使用替换为共享 `StreamingTurnAccumulator`。消费 `async for chunk` 时：

```python
accumulator = StreamingTurnAccumulator()
    async for chunk in self.llm.chat_stream_async(...):
    accumulator.add(chunk)
    if chunk.content:
        yield {"type": "thought_chunk", "iteration": iteration, "text": chunk.content}

turn = accumulator.finalize()
self._accumulate_usage(total_usage, turn.usage)
append_assistant_turn(messages, turn)
decision = classify_turn(turn)
```

工具调用分支用 `await self.registry.execute_async()` 顺序生成 `ToolOutcome`，然后一次性 `append_tool_outcomes()`。文本分支、incomplete 分支、模型异常分支和 `done` 事件字段与同步流式保持一致。

不要把 `finish_reason == "tool_calls"` 作为唯一工具执行条件；只要 `turn.tool_calls` 非空就继续。流式没有 finish reason 且只有文本时返回 `incomplete`。

删除 `async_agent.py` 内重复的 `_AccumulatedToolCall` 和 `_ToolCallAccumulator`。

- [ ] **Step 4: Run async and cross-path tests**

Run:

```bash
python -m pytest tests/test_async_agent.py tests/test_runtime_contract.py -v
```

Expected: PASS；四条路径的规范消息和最终语义一致。

- [ ] **Step 5: Commit**

```bash
git add general_mini_agent/async_agent.py tests/test_async_agent.py tests/test_runtime_contract.py
git commit -m "fix: unify async streaming turn semantics"
```

---

## Task 9: 固化上下文原子组、记忆提交和状态隔离

**Files:**

- Modify: `general_mini_agent/context.py` only if the new tests expose a regression
- Test: `tests/test_context.py`
- Test: `tests/test_agent.py`
- Test: `tests/test_async_agent.py`

**Interfaces:**

- Consumes: canonical assistant/tool messages generated by Tasks 4–8。
- Produces: context policy 不拆散工具回合的回归证明；所有非成功路径不提交 memory 的契约证明。

- [ ] **Step 1: Add atomic multi-tool context test**

```python
def test_trimming_keeps_multiple_tool_results_with_one_assistant_call() -> None:
    policy = TokenBudgetContext(
        context_window=8,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
    )
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "old"},
        {
            "role": "assistant",
            "content": "checking",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
                {"id": "c2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "one"},
        {"role": "tool", "tool_call_id": "c2", "content": "two"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "current"},
    ]

    prepared = policy.prepare(messages)

    assistant_indexes = [
        index for index, message in enumerate(prepared)
        if message.get("role") == "assistant" and message.get("tool_calls")
    ]
    for index in assistant_indexes:
        ids = {call["id"] for call in prepared[index]["tool_calls"]}
        assert ids == {
            message["tool_call_id"]
            for message in prepared[index + 1:]
            if message.get("role") == "tool"
        }
```

增加或保留以下 Agent 断言：

```python
assert memory.get_context() == []
```

用于 `incomplete`、`model_error`、`max_iterations`、流提前关闭和异步取消；同一 Agent 连续调用与同一 AsyncAgent 并发调用必须互不共享 trace/messages。

- [ ] **Step 2: Run context and isolation tests**

Run:

```bash
python -m pytest tests/test_context.py tests/test_agent.py tests/test_async_agent.py -k "context or memory or isolation orcancel" -v
```

Expected: PASS。当前 `context.py` 已有 atomic tool unit 实现时，不修改生产代码；只有测试暴露 assistant 多调用组被拆散时，才修正 `_group_atomic_units()` 并保持现有单工具行为。

- [ ] **Step 3: Inspect for shared mutable run state**

确认 `Agent.__init__()` 和 `AsyncAgent.__init__()` 不增加以下字段：`messages`、`trace`、`usage`、`iteration`、`pending_tool_calls`。这些对象只能在 `run()`、`run_stream()` 或异步对应方法内部创建。

- [ ] **Step 4: Commit**

若只增加测试：

```bash
git add tests/test_context.py tests/test_agent.py tests/test_async_agent.py
git commit -m "test: lock context and run state isolation contracts"
```

若修正 `context.py`，将其与对应测试一起提交，提交信息使用：

```bash
git commit -m "fix: keep multi-tool messages atomic during trimming"
```

---

## Task 10: 更新公共导出、版本和旧命名空间契约

**Files:**

- Modify: `general_mini_agent/__init__.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_docs_contract.py`
- Modify: `tests/test_package_metadata.py`
- Modify: `tests/test_namespace_compat.py`
- Modify: `README.md`
- Modify: `docs/RELEASING.md`
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`
- Modify: `demo/workflow_demo.py` only for its current `core` import/comment
- Modify: `demo/offline.py` only for its current `core` import/comment

**Interfaces:**

- Consumes: 已完成的 `1.1.0` Agent Runtime。
- Produces: 安装包版本、文档、CI 和源码命名空间全部指向 `general_mini_agent`，并准确描述当前能力。

- [ ] **Step 1: Update contract tests first**

把 `tests/test_package_metadata.py` 中版本断言改为：

```python
def test_pyproject_declares_version_1_1_0() -> None:
    content = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "1.1.0"' in content
```

把 CI wheel smoke contract 改为检查：

```python
assert "import general_mini_agent" in workflow
assert "from general_mini_agent import Agent, Debate, LLM, MemoryQuery" in workflow
assert "Path(general_mini_agent.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())" in workflow
```

把文档测试中的当前验证命令改为不含 `core` 的版本，并增加：

```python
assert "1.1.0" in readme
assert "canonical" in readme.lower() or "assistant/tool" in readme
```

清理 `tests/test_namespace_compat.py` 中“core 应产生弃用警告”的过期断言，保留对 `general_mini_agent` 稳定导入和 wheel 安装导入的测试。

- [ ] **Step 2: Run contract tests to verify they fail**

Run:

```bash
python -m pytest tests/test_docs_contract.py tests/test_package_metadata.py tests/test_namespace_compat.py -v
```

Expected: FAIL on old version `1.0.0` and old `core` CI assertions。

- [ ] **Step 3: Update package, CI and documents**

执行以下确定修改：

1. `pyproject.toml` 将版本改为 `1.1.0`，不增加运行时依赖。
2. `.github/workflows/ci.yml` 将 `ruff check core tests demo` 改为 `ruff check general_mini_agent tests demo`；将 `compileall -q core demo tests` 改为 `compileall -q general_mini_agent demo tests`；wheel smoke 从 `import core` 改为 `import general_mini_agent`，从包根导入 `Agent, Debate, LLM, MemoryQuery`。
3. `README.md` 顶部和当前能力章节改为 `1.1.0`，说明原生 tool call 回合、多工具顺序执行、同步/流式/异步路径和错误反馈；删除当前命令中的 `core`；历史迁移说明可以保留为历史记录，但不能说 `core` 仍可使用。
4. `docs/RELEASING.md` 修正 lint、compile、wheel troubleshooting 中的包路径为 `general_mini_agent`。
5. `ROADMAP.md` 保留当前能力和验证命令，增加尚未实现的 `1.1.1`–`1.1.4` 目标；不在 README 的稳定能力段描述项目工具或 CLI。
6. `CHANGELOG.md` 在顶部增加 `## [1.1.0]`，至少记录：统一回合协议、多工具消息修复、finish reason、空响应错误、默认 prompt 和旧 `core` 文档清理。
7. 用 `rg -n "core" README.md docs/RELEASING.md ROADMAP.md demo .github tests` 逐项处理当前代码、命令和导入；保留 changelog 中明确的历史迁移记录。

- [ ] **Step 4: Run documentation and metadata tests**

Run:

```bash
python -m pytest tests/test_docs_contract.py tests/test_package_metadata.py tests/test_namespace_compat.py -v
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add general_mini_agent/__init__.py pyproject.toml .github/workflows/ci.yml README.md ROADMAP.md CHANGELOG.md docs/RELEASING.md demo tests/test_docs_contract.py tests/test_package_metadata.py tests/test_namespace_compat.py
git commit -m "chore: prepare 1.1.0 package and namespace contracts"
```

---

## Task 11: 添加手动真实 API 工具循环冒烟入口

**Files:**

- Create: `demo/live_agent_smoke.py`
- Modify: `README.md`
- Modify: `docs/RELEASING.md`

**Interfaces:**

- Consumes: `FrameworkConfig.from_env()`, `LLMConfig`, `LLM`, `Agent` 和 `@tool`。
- Produces: 显式开关、无密钥输出的真实 OpenAI-compatible 工具循环验证入口。

- [ ] **Step 1: Write the smoke script contract test**

在 `tests/test_docs_contract.py` 增加静态契约：

```python
def test_live_smoke_is_explicit_and_does_not_contain_real_keys() -> None:
    smoke = Path("demo/live_agent_smoke.py").read_text(encoding="utf-8")

    assert "GMAF_API_KEY" in smoke
    assert "Agent(" in smoke
    assert "@tool" in smoke
    assert "calculator" in smoke
    assert "sk-" not in smoke
```

- [ ] **Step 2: Run the contract test to verify it fails**

Run:

```bash
python -m pytest tests/test_docs_contract.py::test_live_smoke_is_explicit_and_does_not_contain_real_keys -v
```

Expected: FAIL because the smoke script does not exist。

- [ ] **Step 3: Implement the manual smoke script**

脚本使用以下结构，不自动加载 `.env`，不打印 key：

```python
from general_mini_agent import Agent, LLM, LLMConfig, tool
from general_mini_agent.config import FrameworkConfig


@tool(description="Evaluate a simple integer addition")
def calculator(a: int, b: int) -> int:
    return a + b


def main() -> int:
    config = FrameworkConfig.from_env()
    llm = LLM(LLMConfig(
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        timeout=config.timeout,
        max_retries=config.max_retries,
    ))
    try:
        result = Agent(llm, tools=[calculator], max_iterations=4).run(
            "Use the calculator tool to compute 19 + 23, then explain the result."
        )
        print(result.content)
        print(f"stop_reason={result.stop_reason} iterations={result.iterations}")
        return 0 if result.stop_reason == "completed" else 1
    finally:
        llm.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

在脚本顶部 docstring 写明运行前必须设置 `GMAF_API_KEY`，可选设置 `GMAF_BASE_URL` 和 `GMAF_MODEL`；未配置时让 `FrameworkConfig` 返回安全的配置错误，不打印秘密。

- [ ] **Step 4: Run static and compile verification**

Run:

```bash
python -m pytest tests/test_docs_contract.py::test_live_smoke_is_explicit_and_does_not_contain_real_keys -v
python -m compileall -q demo/live_agent_smoke.py
```

Expected: PASS。不要在默认测试中运行脚本，不要用真实 key 验证本地实现。

- [ ] **Step 5: Commit**

```bash
git add demo/live_agent_smoke.py README.md docs/RELEASING.md tests/test_docs_contract.py
git commit -m "docs: add opt-in live agent smoke test"
```

---

## Task 12: 完整离线验证、构建和发布检查

**Files:**

- Modify: only files exposed by verification failures; do not introduce unrelated refactors

**Interfaces:**

- Consumes: Tasks 1–11 的全部代码、测试、文档和元数据。
- Produces: 可审查的 `1.1.0` 候选提交链、离线测试结果和构建产物验证结果。

- [ ] **Step 1: Run the complete offline test suite**

Run:

```bash
python -m pytest tests -v
```

Expected: PASS；任何失败先定位到具体任务对应的契约，不跳过测试，不使用真实 API Key。

- [ ] **Step 2: Run lint, compile and diff checks**

Run:

```bash
ruff check general_mini_agent tests demo
python -m compileall -q general_mini_agent demo tests
git diff --check HEAD~12..HEAD
```

Expected: 三条命令均成功；若提交数量因修订不同，使用从 `1.1.0` 实施分支起点到当前 HEAD 的实际范围替换最后一条命令。

- [ ] **Step 3: Build and inspect distributions**

Run：

```bash
python -m pip install ".[dev,release]"
python -m build
python -m twine check dist/*
```

Expected：生成包含 `general_mini_agent` 的 sdist 和 wheel，`twine check` 通过，包元数据版本为 `1.1.0`。

- [ ] **Step 4: Install the wheel in a clean environment**

在临时虚拟环境执行：

```bash
python -m venv .tmp-wheel-smoke
.tmp-wheel-smoke\Scripts\python -m pip install dist\*.whl
.tmp-wheel-smoke\Scripts\python -c "import general_mini_agent; from general_mini_agent import Agent, Debate, LLM, MemoryQuery; print(general_mini_agent.__file__)"
```

Expected：导入来自临时环境的 `site-packages`，不是仓库工作目录；导入四个稳定对象成功。验证结束后删除明确的 `.tmp-wheel-smoke` 临时目录，不删除仓库其他目录或文件。

- [ ] **Step 5: Run optional live smoke only with explicit authorization**

配置真实 API 后手动执行：

```bash
GMAF_API_KEY=your-key-here python demo/live_agent_smoke.py
```

PowerShell 等价命令：

```powershell
$env:GMAF_API_KEY = "your-key-here"
python demo/live_agent_smoke.py
```

Expected：模型至少完成一次 calculator 工具调用并返回 `stop_reason=completed`。如果没有可用密钥，只在发布记录中标注“live smoke 未执行”，不能伪造通过结果。

- [ ] **Step 6: Verify final worktree and implementation handoff**

Run:

```bash
git status --short
git log --oneline --decorate -15
```

Expected：工作区没有未预期修改；交付给下一位 Agent 的内容包括本计划、各任务提交和完整验证输出。

---

## 后续 `1.1.x` 进入条件

以下内容不能在 `1.1.0` 实施中提前编码，只作为后续 Agent 的入口条件：

### `1.1.1` 项目工具

前置条件是 `1.1.0` 的 canonical transcript、顺序工具回合、错误反馈和 context 原子组全部稳定。新增工具必须显式 workspace；读工具和写/执行工具的能力默认分离，mutation/execute 默认关闭。

### `1.1.2` 权限

前置条件是 `1.1.1` 工具都能声明 `read`、`write`、`execute`、`external` 风险属性。权限请求必须是结构化事件，不直接在 Agent 内读取终端输入。

### `1.1.3` CLI

前置条件是 `1.1.2` 可以由上层处理 `allow`、`deny`、`ask`。CLI 只调用 Agent 和权限 API，不重新实现模型循环。

### `1.1.4` 会话与压缩

前置条件是 CLI 已能稳定展示 trace 和取消状态。Conversation Memory、Session Store、Trace Store 必须三个独立边界，不能将完整 trace 直接塞进模型上下文。

## Self-Review Checklist

- [x] 规格中的 `1.1.0` 核心回合、消息配对、终止矩阵、工具错误、同步/流式/异步路径、记忆、上下文、测试和发布要求均有对应任务。
- [x] `1.1.1`–`1.1.4` 只写进入条件，没有混入当前实现任务。
- [x] 旧 `ChatModel` 无 `finish_reason` 的兼容分支与流式缺失结束帧的严格行为已分别写入 Task 1、Task 2、Task 3 和 Task 6。
- [x] `ToolCall`、`LLMResponse`、`AssistantTurn`、`ToolOutcome`、`TurnDecision` 和累积器的方法名在后续任务中保持一致。
- [x] 每个生产代码行为都有先行测试、失败命令、最小实现和通过命令。
- [x] 没有使用占位语句或未定义的后续步骤。
- [x] 计划不要求真实 API Key，真实 API 只存在于显式手工冒烟步骤。
- [x] 计划没有要求删除用户数据；临时 wheel 环境是唯一可清理目标。
