# Agent Runtime 1.1.0 Plan 01: Protocol Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Execute this document before Plan 02.

**Goal:** 建立统一的模型响应、工具调用、canonical message 和流式回合协议，为所有 Agent 执行路径提供稳定基础。

**Architecture:** 扩展 `ToolCall` 和 `LLMResponse` 但保持旧构造方式；新建无 I/O 的 `agent_protocol.py`，集中处理回合规范化、工具消息组装、终止分类和流式累积。该模块不得执行工具、调用网络或依赖 `agent.py`。

**Tech Stack:** Python 3.12+, `httpx`, `pytest`。不新增运行时依赖，不使用真实 API。

## Global Constraints

- 只处理模型协议和纯协议层，不修改 Agent 主循环。
- 现有 `LLMResponse(content=..., tool_calls=...)` 构造必须继续有效。
- `ToolCall` 保留原有前三个构造参数，并允许非法参数被记录而不是抛出解析异常。
- 一次 assistant 回合必须对应一条 assistant 消息；多个 tool call 后逐条追加 tool result。
- 非流式旧模型缺少 `finish_reason` 且返回文本时兼容为 `stop`；流式缺少结束帧时保持 incomplete。
- `AgentStopReason` 原导入路径必须保持不变。
- 每个子任务单独测试和提交。

## Files

- Create: `general_mini_agent/agent_protocol.py`
- Modify: `general_mini_agent/llm.py`
- Modify: `general_mini_agent/async_llm.py`
- Modify: `general_mini_agent/agent.py` only for `AgentStopReason` re-export and imports
- Modify: `general_mini_agent/async_agent.py` only for protocol imports
- Test: `tests/test_agent_protocol.py`
- Test: `tests/test_llm.py`
- Test: `tests/test_async_llm.py`

## Task 1A: Model Response Contract

### Interfaces

Produce:

```python
ToolCall.from_raw(
    *, call_id: str, name: str, raw_arguments: str
) -> ToolCall

LLMResponse.finish_reason: str
ToolCall.raw_arguments: str
ToolCall.argument_error: str | None
```

### Steps

- [ ] Write tests in `tests/test_llm.py` for finish reason, raw JSON, invalid JSON, non-object JSON, and legacy construction:

```python
def test_parse_response_payload_preserves_finish_reason_and_raw_arguments():
    response = parse_response_payload({
        "choices": [{
            "message": {"content": "use tool", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "lookup", "arguments": '{"q":"x"}'},
            }]},
            "finish_reason": "tool_calls",
        }],
    })
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].arguments == {"q": "x"}
    assert response.tool_calls[0].raw_arguments == '{"q":"x"}'


@pytest.mark.parametrize("raw", ['{"q":', '[1, 2]'])
def test_invalid_tool_arguments_are_retained(raw):
    response = parse_response_payload({
        "choices": [{
            "message": {"content": None, "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "lookup", "arguments": raw},
            }]},
            "finish_reason": "tool_calls",
        }],
    })
    call = response.tool_calls[0]
    assert call.arguments is None
    assert call.raw_arguments == raw
    assert call.argument_error


def test_legacy_llm_response_constructor_remains_valid():
    assert LLMResponse(content="ok", tool_calls=None).finish_reason == ""
```

- [ ] Run `python -m pytest tests/test_llm.py -k "finish_reason or raw_arguments or invalid_tool_arguments or legacy_llm" -v`; expect failure before implementation.
- [ ] Change `ToolCall.arguments` to `dict[str, Any] | None`, append default `raw_arguments` and `argument_error`, and implement:

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

- [ ] Add `finish_reason: str = ""` after existing default fields on `LLMResponse`.
- [ ] Update `parse_response_payload()` to populate finish reason and call `ToolCall.from_raw()`.
- [ ] Confirm `AsyncLLM` reuses the same parser and preserves finish reason.
- [ ] Run `python -m pytest tests/test_llm.py tests/test_async_llm.py -v`; expect PASS.
- [ ] Commit:

```bash
git add general_mini_agent/llm.py general_mini_agent/async_llm.py tests/test_llm.py tests/test_async_llm.py
git commit -m "feat: preserve model finish reasons and raw tool arguments"
```

## Task 1B: Pure Turn Protocol

### Interfaces

Create `general_mini_agent/agent_protocol.py` with:

```python
AgentStopReason = Literal[
    "completed", "max_iterations", "model_error", "incomplete",
    "context_budget_exceeded", "memory_error",
]
TurnAction = Literal["continue", "complete", "stop_error"]

@dataclass(frozen=True)
class AssistantTurn:
    content: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str | None
    usage: dict[str, int]

    @classmethod
    def from_response(cls, response: LLMResponse) -> "AssistantTurn": ...

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

Also provide:

```python
append_assistant_turn(messages, turn) -> None
append_tool_outcomes(messages, outcomes) -> None
classify_turn(turn) -> TurnDecision
clean_final_content(content: str) -> str
invalid_arguments_result(call) -> ToolExecutionResult
build_tool_trace(iteration, turn, index, call, result) -> dict[str, Any]
build_incomplete_trace(iteration, turn, decision) -> dict[str, Any]
safe_error_message(decision) -> str
```

### Steps

- [ ] Create `tests/test_agent_protocol.py` with tests for: legacy text normalization to `stop`, tool calls taking precedence over finish reason, `length`/`content_filter`/unknown reason as incomplete, empty response as model error, and legacy final prefix cleanup.
- [ ] Add a multi-tool message test asserting the exact role sequence `user, assistant, tool, tool`, one assistant message, IDs `c1`, `c2` in order, and raw arguments preserved.
- [ ] Run `python -m pytest tests/test_agent_protocol.py -v`; expect import failure before implementation.
- [ ] Implement `AssistantTurn.from_response()` so missing non-stream finish reason becomes `stop` only when there is text and no tool call.
- [ ] Implement `classify_turn()` in this order: non-empty tool calls -> continue; `stop` plus text -> complete; explicit `tool_calls` without calls -> model error; no content -> model error; every other text result -> incomplete.
- [ ] Implement message appenders using raw JSON first and deterministic JSON fallback:

```python
raw = call.raw_arguments or json.dumps(
    call.arguments or {}, ensure_ascii=False, separators=(",", ":")
)
```

- [ ] Implement fixed safe error messages and trace fields without echoing model responses.
- [ ] Move `AgentStopReason` to this module; import and re-export it from `agent.py` and preserve the package root export.
- [ ] Run `python -m pytest tests/test_agent_protocol.py tests/test_namespace_compat.py -v`; expect PASS.
- [ ] Commit:

```bash
git add general_mini_agent/agent_protocol.py general_mini_agent/agent.py general_mini_agent/async_agent.py tests/test_agent_protocol.py
git commit -m "feat: add shared agent turn protocol"
```

## Task 1C: Streaming Turn Accumulator

### Interface

```python
class StreamingTurnAccumulator:
    def add(self, chunk: StreamChunk) -> None: ...
    def finalize(self) -> AssistantTurn: ...
```

### Steps

- [ ] Add tests for interleaved indexes, content accumulation, usage latest snapshot, calls with `finish_reason="stop"`, missing finish reason text, missing calls with `finish_reason="tool_calls"`, ID/name conflicts, and invalid JSON arguments.
- [ ] Run `python -m pytest tests/test_agent_protocol.py -k streaming -v`; expect failure before migration.
- [ ] Move the current pending-call merge logic into the protocol module. Sort by index in `finalize()`, reject conflicting ID/name, reject missing identity with `ModelRequestError(error_code="stream_protocol_error")`, and parse raw arguments through `ToolCall.from_raw()`.
- [ ] Do not synthesize `stop` for a stream with text and no finish reason.
- [ ] Run `python -m pytest tests/test_agent_protocol.py -k streaming tests/test_llm.py -k stream -v`; expect PASS.
- [ ] Commit:

```bash
git add general_mini_agent/agent_protocol.py general_mini_agent/llm.py tests/test_agent_protocol.py tests/test_llm.py
git commit -m "feat: centralize streaming turn accumulation"
```

## Handoff To Plan 02

Plan 02 may import only the interfaces documented above. It must not recreate a second accumulator, parse raw tool arguments independently, or define another stop-reason type.
