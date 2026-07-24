# CI and Chat Memory Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore Python 3.12 CI and make the interactive chat demo retain and clear short-term conversation history.

**Architecture:** Extend the existing tool-schema parser to recognize both Python union origins without changing its output contract. Keep memory creation and writeback in `demo/chat.py`, using small demo helpers so behavior is testable without a real model or API key.

**Tech Stack:** Python 3.12+, pytest, Ruff, `types`, existing `SlidingWindowMemory`.

## Global Constraints

- Keep the stable `0.1.0` Agent contract unchanged.
- Keep memory ownership and writeback inside the interactive demo.
- Preserve existing synchronous and streaming Agent behavior.
- Do not add long-term memory, persistence, summarization, or commands.
- Do not commit or push until the user reviews the completed implementation.

---

### Task 1: Restore Python 3.12 Optional-Type Schema Support

**Files:**
- Modify: `core/tools.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: `typing.get_origin(tp)` and `typing.get_args(tp)`.
- Produces: `Tool._type_to_schema(str | None)` returning `{"type": "string", "nullable": True}` on Python 3.12 and newer.

- [x] **Step 1: Confirm the regression evidence**

Use GitHub Actions run `29987214362`, where
`TestToolRegistration.test_optional_parameter_is_nullable_and_not_required`
fails on Python 3.12 because the schema is missing `nullable: true`.

- [x] **Step 2: Implement the minimal compatibility fix**

Import `UnionType` from `types` and accept both union origins:

```python
from types import UnionType

if origin in (Union, UnionType) and type(None) in args:
    non_none = [arg for arg in args if arg is not type(None)]
    if non_none:
        schema = self._type_to_schema(non_none[0])
        schema["nullable"] = True
        return schema
```

- [x] **Step 3: Run the focused schema test**

Run:

```powershell
D:\python314\python.exe -m pytest tests/test_tools.py::TestToolRegistration::test_optional_parameter_is_nullable_and_not_required -v -p no:cacheprovider
```

Expected: `1 passed`. The authoritative Python 3.12 verification will be the next GitHub Actions run after user-approved commit and push.

### Task 2: Add Testable Chat Memory and Clear Behavior

**Files:**
- Modify: `demo/chat.py`
- Create: `tests/test_chat_demo.py`

**Interfaces:**
- Consumes: `SlidingWindowMemory.add(role, content)` and `SlidingWindowMemory.clear()`.
- Produces: `record_exchange(memory, user_input, assistant_content) -> None` and `clear_context(memory) -> None`.

- [x] **Step 1: Write failing helper tests**

```python
from core.memory import SlidingWindowMemory
from demo.chat import clear_context, record_exchange


def test_record_exchange_adds_one_user_assistant_pair() -> None:
    memory = SlidingWindowMemory(window_size=4)

    record_exchange(memory, "first question", "first answer")

    assert memory.get_context() == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
    ]


def test_clear_context_removes_recorded_messages() -> None:
    memory = SlidingWindowMemory(window_size=4)
    memory.add("user", "old question")
    memory.add("assistant", "old answer")

    clear_context(memory)

    assert memory.get_context() == []
```

- [x] **Step 2: Run tests to verify RED**

Run:

```powershell
D:\python314\python.exe -m pytest tests/test_chat_demo.py -v -p no:cacheprovider
```

Expected: collection fails because `clear_context` and `record_exchange` do not exist.

- [x] **Step 3: Implement the minimal demo behavior**

Move the optional `dotenv` import into `main()` so offline tests can import the demo without installing the demo extra. Add the helpers:

```python
from core.memory import SlidingWindowMemory


def record_exchange(
    memory: SlidingWindowMemory,
    user_input: str,
    assistant_content: str,
) -> None:
    memory.add("user", user_input)
    memory.add("assistant", assistant_content)


def clear_context(memory: SlidingWindowMemory) -> None:
    memory.clear()
```

In `main()`, create one `SlidingWindowMemory(window_size=20)`, pass it to the
Agent, call `clear_context(memory)` for `/clear`, and call
`record_exchange(memory, user_input, event["content"])` when a `done` event is
received.

- [x] **Step 4: Run focused tests to verify GREEN**

Run:

```powershell
D:\python314\python.exe -m pytest tests/test_chat_demo.py tests/test_tools.py::TestToolRegistration::test_optional_parameter_is_nullable_and_not_required -v -p no:cacheprovider
```

Expected: `3 passed`.

### Task 3: Full Verification and Review Handoff

**Files:**
- Review all files changed by Tasks 1 and 2.

**Interfaces:**
- Consumes: completed fixes from Tasks 1 and 2.
- Produces: an uncommitted, reviewed change set ready for user audit.

- [x] **Step 1: Run the complete offline verification**

```powershell
D:\python314\python.exe -m pytest tests -v -p no:cacheprovider
D:\python314\python.exe -m compileall -q core demo tests
D:\python314\python.exe -m ruff check core tests demo
git diff --check
```

Expected: all tests pass, compileall has no output, Ruff reports `All checks passed!`, and `git diff --check` reports no whitespace errors.

- [x] **Step 2: Review the diff and preserve unrelated work**

Run:

```powershell
git status --short
git diff -- core/tools.py demo/chat.py tests/test_chat_demo.py
```

Confirm `.env.example` remains unstaged and unchanged by this task. Do not commit or push; report the implementation and verification results for user audit.
