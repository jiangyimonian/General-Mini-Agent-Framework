# Agent Runtime 1.1.0 Plan 03: Async Agent and Cross-Path Parity

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Execute Plans 01 and 02 first and Plan 04 after this document.

**Goal:** 将异步非流式、异步流式和跨路径契约统一到 Plan 01 的回合协议，确保工具顺序、终止状态、usage、trace 和取消语义一致。

**Architecture:** `AsyncAgent` 只负责 await 模型和异步工具；所有 assistant/tool 消息和终止判断复用 `agent_protocol.py`。同步工具仍由现有异步工具注册表处理，不在本计划引入并发工具调度。

**Tech Stack:** Python 3.12+, `asyncio`, 现有 `AsyncLLM`、`AsyncToolRegistry`、`pytest-asyncio`。

## Global Constraints

- 保持 `AsyncAgent`、`run_async()` 和 `run_stream_async()` 现有公共签名。
- 异步路径必须复用 Plan 01 的协议，不复制消息组装、参数解析或终止矩阵。
- 多工具顺序 `await`；本版不使用 `asyncio.gather()` 并行执行模型工具调用。
- `CancelledError` 必须传播，取消、流关闭和非成功结果不得提交 memory。
- 同步和异步最终语义必须通过同一个离线契约场景。
- 不新增运行时依赖、项目工具、权限交互或 CLI。

## Prerequisites and Files

- Plan 01 and Plan 02 are merged.
- Modify: `general_mini_agent/async_agent.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_async_agent.py`
- Create: `tests/test_runtime_contract.py`

## Task 3A: Async Script Model and Non-Streaming Agent

### Test fixture

- [ ] Add this model to `tests/conftest.py`; it records request copies and never stores Agent state:

```python
class ScriptedAsyncChatModel:
    def __init__(self, responses, streams=()):
        self.responses = list(responses)
        self.streams = list(streams)
        self.calls = []
        self.stream_calls = []

    async def chat_async(self, messages, *, tools=None):
        self.calls.append((deepcopy(messages), deepcopy(tools)))
        if not self.responses:
            raise AssertionError("no remaining async response")
        return self.responses.pop(0)

    async def chat_stream_async(self, messages, *, tools=None):
        self.stream_calls.append((deepcopy(messages), deepcopy(tools)))
        if not self.streams:
            raise AssertionError("no remaining async stream")
        stream = self.streams.pop(0)
        if isinstance(stream, Exception):
            raise stream
        for chunk in stream:
            yield chunk
```

### Steps

- [ ] Add async tests for two tool calls in one assistant message, `length` without memory commit, empty response, legacy text response, tool failure recovery, and cancellation without memory commit.
- [ ] Run `python -m pytest tests/test_async_agent.py -k "multiple_tool_calls or incomplete_response or empty_response" -v`; expect failure before migration.
- [ ] In `AsyncAgent.run_async()`, mirror the sync order exactly:

```python
turn = AssistantTurn.from_response(response)
self._accumulate_usage(total_usage, turn.usage)
append_assistant_turn(messages, turn)
decision = classify_turn(turn)

if decision.action == "continue":
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
```

- [ ] Implement `_finish_completed_run(...) -> AgentResult` and `_finish_stopped_run(...) -> AgentResult` so only completed runs call final hook and memory commit.
- [ ] Preserve `CancelledError`; do not catch it as a model error and do not write memory after cancellation.
- [ ] Run `python -m pytest tests/test_async_agent.py -v`; expect PASS.
- [ ] Commit:

```bash
git add general_mini_agent/async_agent.py tests/test_async_agent.py tests/conftest.py
git commit -m "fix: align async agent with turn protocol"
```

## Task 3B: Async Streaming Agent

### Steps

- [ ] Add tests for interleaved multi-tool chunks, calls with `finish_reason="stop"`, invalid JSON arguments, missing finish reason text, stream protocol errors, usage snapshots, and early async generator close.
- [ ] Run `python -m pytest tests/test_async_agent.py -k stream -v`; expect failures in the old duplicated accumulator path.
- [ ] Replace the local accumulator with `StreamingTurnAccumulator`.
- [ ] Consume chunks with `async for`, yield existing text events, add each chunk to the accumulator, finalize once, append one assistant message, and classify.
- [ ] Execute `turn.tool_calls` in order using `await self.registry.execute_async()`, build all outcomes, yield public tool events, then append all tool results.
- [ ] Keep text with no finish reason as `incomplete`; use tool presence, not `finish_reason == "tool_calls"`, as the continuation signal.
- [ ] Preserve one final `done`; do not commit memory when the async generator is closed or cancelled.
- [ ] Run `python -m pytest tests/test_async_agent.py -k stream -v`; expect PASS.
- [ ] Commit:

```bash
git add general_mini_agent/async_agent.py tests/test_async_agent.py
git commit -m "fix: align async streaming with turn protocol"
```

## Task 3C: Cross-Path Contract

### Steps

- [ ] Create `tests/test_runtime_contract.py` with the same logical scenario for sync non-stream, sync stream, async non-stream and async stream: model calls `first` and `second`, both return, model answers `done`.
- [ ] Assert for every path:

```python
assert result.content == "done"
assert result.stop_reason == "completed"
assert result.iterations == 2
assert [event["tool"] for event in result.trace if event["type"] == "tool_call"] == [
    "first", "second",
]
```

- [ ] Inspect the second request and assert exactly one assistant message with call IDs `c1`, `c2`, followed by tool IDs `c1`, `c2`.
- [ ] Add parity assertions for `length`, empty response, unknown tool, invalid arguments, usage accumulation, hook copy, and memory commit condition.
- [ ] Run `python -m pytest tests/test_runtime_contract.py tests/test_agent.py tests/test_async_agent.py -v`; expect PASS.
- [ ] Run `ruff check general_mini_agent tests`; expect PASS.
- [ ] Commit:

```bash
git add tests/test_runtime_contract.py general_mini_agent/agent.py general_mini_agent/async_agent.py
git commit -m "test: enforce sync and async agent parity"
```

## Handoff To Plan 04

Plan 04 may assume all four execution paths generate valid canonical messages. It should focus on context grouping, memory commit conditions and run-state isolation rather than changing the loop again.
