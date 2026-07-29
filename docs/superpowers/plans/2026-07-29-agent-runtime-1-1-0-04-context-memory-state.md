# Agent Runtime 1.1.0 Plan 04: Context, Memory, and State Contracts

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Execute Plans 01–03 first and Plan 05 after this document.

**Goal:** 锁定 canonical assistant/tool 消息在上下文裁剪中的原子性，并验证成功、失败、取消和并发运行的 memory 与状态隔离。

**Architecture:** `context.py` 继续作为请求视图策略，不拥有 canonical transcript。assistant tool call 和其全部 tool results 是不可拆分 `_MessageUnit`。Agent 实例不保存单次运行状态，记忆只在正常完成后提交。

**Tech Stack:** Python 3.12+, 现有 `ContextPolicy`、`TokenBudgetContext`、`InMemoryConversation`、pytest/pytest-asyncio。

## Global Constraints

- 本计划只验证和修正上下文原子组、memory 条件、事件和状态隔离，不重新设计 Agent 循环。
- `canonical_messages` 是运行事实；context policy 只能返回请求副本。
- assistant tool call 与其全部 tool results 是不可拆分单元。
- 只有正常完成提交 user/assistant 两条短期记忆；工具 trace 不写入对话记忆。
- 单次运行状态只能存在于方法局部变量，不能新增到 Agent 实例字段。
- 不新增自动摘要、会话存储、项目工具、权限交互或 CLI。

## Files

- Modify: `general_mini_agent/context.py` only if regression tests fail
- Test: `tests/test_context.py`
- Test: `tests/test_agent.py`
- Test: `tests/test_async_agent.py`
- Test: `tests/test_runtime_contract.py`

## Task 4A: Atomic Multi-Tool Context Group

- [ ] Add a `TokenBudgetContext` test with one assistant containing `c1` and `c2`, followed by both tool results. Force an old turn to be removed and assert the whole assistant/results group is either present or absent.

```python
def test_trimming_keeps_multi_tool_group_intact():
    policy = TokenBudgetContext(
        context_window=8,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
    )
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "checking", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "one"},
        {"role": "tool", "tool_call_id": "c2", "content": "two"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "current"},
    ]
    prepared = policy.prepare(messages)
    calls = [m for m in prepared if m.get("role") == "assistant" and m.get("tool_calls")]
    results = [m for m in prepared if m.get("role") == "tool"]
    assert bool(calls) == bool(results)
    if calls:
        assert {c["id"] for c in calls[0]["tool_calls"]} == {
            r["tool_call_id"] for r in results
        }
```

- [ ] Run `python -m pytest tests/test_context.py -k "multi_tool_group" -v`; expect PASS if existing grouping already satisfies the protocol, otherwise fail before the minimal `_group_atomic_units()` correction.
- [ ] If it fails, update `_group_atomic_units()` so an assistant tool-call unit consumes all immediately following tool messages whose IDs belong to that assistant call set; retain existing orphan validation.
- [ ] Run the complete context suite: `python -m pytest tests/test_context.py -v`.
- [ ] Commit only the test if production behavior already passes:

```bash
git add tests/test_context.py
git commit -m "test: lock multi-tool context atomicity"
```

If production changes are required, include `general_mini_agent/context.py` and use `git commit -m "fix: keep multi-tool messages atomic during trimming"`.

## Task 4B: Memory Commit Matrix

- [ ] Add tests for each execution path asserting memory contains exactly user and assistant messages only after `completed`.
- [ ] Assert memory remains empty after `length`, `content_filter`, empty response, model error, context budget exceeded, max iterations, tool loop cancellation, and stream consumer close.
- [ ] Assert a final hook mutation does not mutate stored trace or stored assistant content.
- [ ] Run:

```bash
python -m pytest tests/test_agent.py tests/test_async_agent.py tests/test_runtime_contract.py -k "memory or incomplete or max_iterations or cancellation or abandoned" -v
```

Expected: PASS; no production change is allowed if the existing lifecycle already satisfies these conditions.

- [ ] Commit:

```bash
git add tests/test_agent.py tests/test_async_agent.py tests/test_runtime_contract.py
git commit -m "test: lock agent memory commit conditions"
```

## Task 4C: Run-State Isolation and Events

- [ ] Add or retain tests that call one `Agent` twice and one `AsyncAgent` concurrently, asserting traces, usage, messages and final content do not leak between runs.
- [ ] Assert every completed/error run has one terminal result, `on_final` only runs for completed, each tool call has one observation, and error strings do not contain `sk-` or authorization values.
- [ ] Inspect constructors and reject adding instance fields for `messages`, `trace`, `usage`, `iteration`, pending calls or current tool results.
- [ ] Run:

```bash
python -m pytest tests/test_agent.py tests/test_async_agent.py tests/test_events.py tests/test_logging.py -v
```

- [ ] Run `python -m compileall -q general_mini_agent demo tests`; expect PASS.
- [ ] Commit:

```bash
git add tests/test_agent.py tests/test_async_agent.py tests/test_events.py tests/test_logging.py
git commit -m "test: verify agent run isolation and terminal events"
```

## Handoff To Plan 05

Plan 05 must not change Agent protocol behavior. It only updates package metadata, current documentation, CI namespace paths, and release verification after the runtime contract is green.
