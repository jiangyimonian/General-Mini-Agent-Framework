# Agent Runtime 1.1.0 Plan 02: Sync Agent

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Execute Plan 01 first and Plan 03 after this document.

**Goal:** 将 `Agent.run()` 和 `Agent.run_stream()` 迁移到共享回合协议，修复多工具消息、终止状态、空响应和同步流式行为。

**Architecture:** Agent 继续拥有生命周期、memory、context、hooks 和工具执行；`agent_protocol.py` 拥有规范回合和消息组装。每次模型响应先追加一条 assistant，再执行全部工具，最后追加全部 tool results。

**Tech Stack:** Python 3.12+, 现有同步 `LLM`、`ToolRegistry`、`pytest`。

## Global Constraints

- 只迁移同步非流式和同步流式 Agent；不修改异步路径、项目工具、权限或 CLI。
- 保持 `Agent(...)`、`run()`、`run_stream()`、`AgentResult` 和公开流事件签名。
- 工具按模型原始顺序执行；不引入并行工具执行。
- 所有消息组装和终止判断必须复用 Plan 01 的协议接口。
- 只有 `completed` 运行提交 memory 和调用 final hook。
- 测试离线运行，不新增依赖或真实 API Key。

## Prerequisites

- Plan 01 的 `ToolCall.from_raw()`、`AssistantTurn`、`ToolOutcome`、`TurnDecision`、消息 appenders、`classify_turn()` 和 `StreamingTurnAccumulator` 已合并。
- 现有 `Agent.run()`、`run_stream()` 公共签名不变。

## Files

- Modify: `general_mini_agent/agent.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_agent.py`
- Modify: `tests/test_memory.py` only for focused memory regression coverage

## Task 2A: Strict Transcript and Sync Tool Turns

### Steps

- [ ] Add this independent test validator to `tests/conftest.py`:

```python
def assert_valid_tool_transcript(messages):
    pending = set()
    for index, message in enumerate(messages):
        if message["role"] == "assistant":
            assert not pending, f"assistant interrupted pending tools at {index}"
            for call in message.get("tool_calls", []):
                assert call["id"] not in pending
                pending.add(call["id"])
        elif message["role"] == "tool":
            assert message["tool_call_id"] in pending
            pending.remove(message["tool_call_id"])
        else:
            assert not pending
    assert not pending


class StrictScriptedChatModel(ScriptedChatModel):
    def chat(self, messages, *, tools=None):
        assert_valid_tool_transcript(messages)
        return super().chat(messages, tools=tools)
```

- [ ] Add a two-tool test with `c1` and `c2`; the second model request must contain one assistant with two calls followed by two tool messages in order. Run the test and expect failure against current `Agent.run()`.
- [ ] Replace the current response branch in `Agent.run()` with this sequence:

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
            else self.registry.execute(call.name, call.arguments)
        )
        outcomes.append(ToolOutcome(call, execution))
        trace_event = build_tool_trace(iteration, turn, index, call, execution)
        trace.append(trace_event)
        self._call_hook("on_tool_call", dict(trace_event))
    append_tool_outcomes(messages, outcomes)
    continue
```

- [ ] Ensure all calls execute in original order, including after an earlier call returns an error. Do not append any assistant message inside the tool loop.
- [ ] Add `_result_from_decision(decision, turn, trace, usage, iterations, emitter) -> AgentResult` to centralize non-complete result and one `run_finished` event.
- [ ] Run `python -m pytest tests/test_agent.py -v`; expect old single-tool, chain, unknown-tool, exception, and max-iteration tests to pass.
- [ ] Commit:

```bash
git add general_mini_agent/agent.py tests/conftest.py tests/test_agent.py
git commit -m "fix: build canonical sync tool turns"
```

## Task 2B: Sync Terminal Behavior and Prompt

### Required behavior

| Response | Result |
|---|---|
| tool calls | execute and continue |
| text + `stop` | completed |
| text + `length`, `content_filter`, unknown reason | incomplete |
| no text/no calls | model_error, no fake follow-up |
| old response with text and empty reason | completed compatibility |

### Steps

- [ ] Add tests for `length`, `content_filter`, unknown finish reason, empty response, legacy response without finish reason, no memory commit on non-complete result, and final hook receiving a copy.
- [ ] Replace `DEFAULT_SYSTEM_PROMPT` with native-tool instructions. Keep tool descriptions, remove required `Thought:`, `Action:`, `Action Input:` and `Final Answer:` markers.
- [ ] Use `clean_final_content()` only for display compatibility with `[FINAL]` and old final prefixes.
- [ ] On `complete`, append final trace, call `on_final` with `dict(trace[-1])`, commit memory, emit `run_finished`, return `AgentResult`.
- [ ] On `stop_error`, return content and safe error text from `safe_error_message()`, do not call final hook, do not commit memory, and do not append a fake assistant message.
- [ ] Run:

```bash
python -m pytest tests/test_agent.py tests/test_memory.py -k "non_terminal or empty_response or legacy_model or default_prompt or final_hook or memory" -v
```

Expected: PASS.

- [ ] Commit:

```bash
git add general_mini_agent/agent.py tests/test_agent.py tests/test_memory.py
git commit -m "fix: classify sync terminal model responses"
```

## Task 2C: Sync Streaming Agent

### Steps

- [ ] Add tests for complete tool calls with `finish_reason="stop"`, text with no finish reason, multiple calls in one assistant message, invalid JSON arguments, incomplete response without memory commit, usage snapshot, and early consumer close.
- [ ] Run focused tests and record failures before implementation:

```bash
python -m pytest tests/test_agent.py -k "stream_executes_complete or stream_text_without or stream_multi_tool_request" -v
```

- [ ] Remove `_AccumulatedToolCall` and `_ToolCallAccumulator` from `agent.py`; import `StreamingTurnAccumulator`.
- [ ] For each stream request, add every chunk to the accumulator while yielding existing `thought_chunk` events. After stream completion, call `finalize()`, append one assistant turn, and classify it.
- [ ] Execute whenever `turn.tool_calls` is non-empty, regardless of finish reason. Build all `ToolOutcome` values in order, yield tool/observation events, then append all tool results.
- [ ] When no tools and `finish_reason` is empty, return `incomplete`; do not use the non-stream legacy text compatibility branch.
- [ ] Preserve existing event order: `iteration_start`, text chunks, tool events or final answer, then one `done`.
- [ ] Do not commit memory or fabricate `done` if the consumer closes the generator before completion.
- [ ] Run `python -m pytest tests/test_agent.py -k stream -v`; expect PASS.
- [ ] Commit:

```bash
git add general_mini_agent/agent.py tests/test_agent.py
git commit -m "fix: align sync streaming with turn protocol"
```

## Handoff To Plan 03

Plan 03 must reuse the same protocol imports and message assertions. It must not copy sync code into a new protocol implementation.
