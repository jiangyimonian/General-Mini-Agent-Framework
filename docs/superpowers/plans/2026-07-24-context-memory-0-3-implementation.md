# Context and Memory 0.3.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit request token budgets and transactional conversation-memory writeback to both Agent execution paths.

**Architecture:** A new `core/context.py` owns counting, grouping, trimming, overflow, and optional summarization. `core/memory.py` owns stored history, while `core/agent.py` only prepares each model request and commits successful user/assistant exchanges. Existing callers remain unchanged until they explicitly pass a context policy or writable conversation memory.

**Tech Stack:** Python 3.12, dataclasses and typing protocols, pytest, Ruff, existing scripted model test doubles.

## Global Constraints

- Keep `LLM` provider-neutral and do not add tokenizer or model-capacity dependencies.
- `context_window` and `reserved_output_tokens` are explicit positive integers.
- Count system messages, history, current messages, message metadata, and tool schemas.
- Preserve system messages, the current user turn, the previous complete user turn, and complete tool-call/result segments.
- Prepare context before every synchronous and streaming model request.
- Write exactly one user/assistant batch only after successful completion.
- Keep legacy `get_context()`-only memory readable and do not write to it.
- Keep external-service tests offline and never include real credentials.
- Run focused tests per task; defer the complete suite to Task 6.

---

## File Map

- Create `core/context.py`: public counting and context-policy contracts, deterministic budget policy, safe overflow error, optional summary wrapper.
- Modify `core/memory.py`: stable `ConversationMemory` protocol and `InMemoryConversation`; retain experimental compatibility classes.
- Modify `core/agent.py`: request preparation, context terminal mapping, and successful exchange commits.
- Modify `core/__init__.py`: export newly stable `0.3.0` interfaces.
- Modify `demo/chat.py`: explicit budget configuration and automatic memory writeback.
- Create `tests/test_context.py`: counting, trimming, overflow, mutation, and summary behavior.
- Modify `tests/test_memory.py`: stable in-memory store and atomic validation coverage.
- Modify `tests/test_agent.py`: sync/stream preparation, errors, writeback, cancellation, and compatibility.
- Modify `tests/test_chat_demo.py`: remove manual-recording expectations and retain clear behavior.
- Modify `README.md`, `PLAN.md`, `ROADMAP.md`, `pyproject.toml`: document and release `0.3.0`.

### Task 1: Token Counting and Budget Contracts

**Files:**
- Create: `core/context.py`
- Create: `tests/test_context.py`

**Interfaces:**
- Produces: `TokenCounter.count(messages, *, tools=None) -> int`
- Produces: `ApproximateTokenCounter(characters_per_token: int = 4)`
- Produces: `ContextPolicy.prepare(messages, *, tools=None) -> list[dict[str, Any]]`
- Produces: `ContextBudgetExceeded(input_tokens, input_budget)`
- Produces: `TokenBudgetContext(context_window, reserved_output_tokens, token_counter=None, oversized_content_handler=None)`

- [x] **Step 1: Write failing contract and estimator tests**

```python
def test_approximate_counter_is_deterministic_and_counts_tools() -> None:
    counter = ApproximateTokenCounter()
    messages = [{"role": "user", "content": "abcdefgh"}]
    without_tools = counter.count(messages)
    tools = [{"type": "function", "function": {"name": "lookup"}}]
    assert counter.count(messages) == without_tools
    assert counter.count(messages, tools=tools) > without_tools


@pytest.mark.parametrize(
    ("window", "reserve"), [(0, 1), (10, 0), (10, 10), (10, 11)]
)
def test_budget_configuration_rejects_invalid_values(window: int, reserve: int) -> None:
    with pytest.raises(ValueError):
        TokenBudgetContext(context_window=window, reserved_output_tokens=reserve)
```

- [x] **Step 2: Run the focused tests and confirm import failure**

Run: `python -m pytest tests/test_context.py -v`
Expected: FAIL because `core.context` does not exist.

- [x] **Step 3: Implement protocols, estimator, configuration, and safe error metadata**

```python
class ApproximateTokenCounter:
    def __init__(self, characters_per_token: int = 4) -> None:
        if characters_per_token <= 0:
            raise ValueError("characters_per_token must be positive")
        self.characters_per_token = characters_per_token

    def count(self, messages, *, tools=None) -> int:
        payload = {"messages": list(messages), "tools": list(tools or [])}
        characters = len(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return max(1, math.ceil(characters / self.characters_per_token))


class ContextBudgetExceeded(Exception):
    def __init__(self, input_tokens: int, input_budget: int) -> None:
        self.input_tokens = input_tokens
        self.input_budget = input_budget
        super().__init__(
            f"request context requires {input_tokens} tokens; budget is {input_budget}"
        )
```

Define runtime-checkable typing protocols and validate `TokenBudgetContext` constructor arguments.
For this task, `prepare()` returns defensive message copies when they fit and raises
`ContextBudgetExceeded` when the complete input does not fit; trimming is Task 2.

- [x] **Step 4: Run Task 1 tests**

Run: `python -m pytest tests/test_context.py -v`
Expected: all Task 1 tests PASS.

- [x] **Step 5: Commit Task 1**

```bash
git add core/context.py tests/test_context.py
git commit -m "feat: define context budget contracts"
```

### Task 2: Deterministic Conversation Trimming

**Files:**
- Modify: `core/context.py`
- Modify: `tests/test_context.py`

**Interfaces:**
- Consumes: Task 1 `TokenCounter`, `TokenBudgetContext`, and `ContextBudgetExceeded`
- Produces: atomic turn grouping and `OversizedContentHandler(messages, input_budget) -> list[dict[str, Any]]`

- [x] **Step 1: Add failing grouping and trimming tests with an exact fake counter**

```python
class MessageCostCounter:
    def count(self, messages, *, tools=None):
        return sum(message.get("cost", 1) for message in messages) + len(tools or [])


def test_trimming_removes_oldest_turn_and_preserves_recent_turns() -> None:
    policy = TokenBudgetContext(6, 1, token_counter=MessageCostCounter())
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]
    assert policy.prepare(messages) == [messages[0], *messages[3:]]


def test_trimming_never_orphans_tool_results() -> None:
    # Build three turns where the oldest assistant tool call and tool result must disappear together.
    prepared = policy.prepare(messages)
    assert not any(message.get("tool_call_id") == "old-call" for message in prepared)
    assert not any(
        call.get("id") == "old-call"
        for message in prepared
        for call in message.get("tool_calls", [])
    )
```

Also add tests for protected overflow, tools included in exact counts, input immutability, returned
copy isolation, malformed tool chains, and successful/failed oversized-content handling.

- [x] **Step 2: Run the new tests and confirm unimplemented trimming failures**

Run: `python -m pytest tests/test_context.py -v`
Expected: new trimming tests FAIL while Task 1 tests remain green.

- [x] **Step 3: Implement atomic grouping and oldest-removable-unit selection**

```python
def prepare(self, messages, *, tools=None):
    copied = _copy_and_validate_messages(messages)
    units = _group_atomic_units(copied)
    protected = _protected_unit_indexes(units)
    while self.token_counter.count(_flatten(units), tools=tools) > self.input_budget:
        removable = next((i for i in range(len(units)) if i not in protected), None)
        if removable is None:
            return self._handle_protected_overflow(_flatten(units), tools)
        units.pop(removable)
        protected = {i - (i > removable) for i in protected if i != removable}
    return _flatten(units)
```

Validate roles, `tool_calls`, and matching `tool_call_id` relationships before trimming. Copy nested
message data with `copy.deepcopy`. The overflow handler receives copied protected messages, its
result is validated and recounted, and failure raises the original safe error type.

- [x] **Step 4: Run all context tests**

Run: `python -m pytest tests/test_context.py -v`
Expected: all tests PASS.

- [x] **Step 5: Commit Task 2**

```bash
git add core/context.py tests/test_context.py
git commit -m "feat: trim context by atomic conversation turns"
```

### Task 3: Stable In-Memory Conversation Store

**Files:**
- Modify: `core/memory.py`
- Modify: `tests/test_memory.py`

**Interfaces:**
- Produces: `ConversationMemory.get_context()`, `add_messages(messages)`, and `clear()` protocol
- Produces: `InMemoryConversation(initial_messages=None)`

- [x] **Step 1: Add failing atomicity and defensive-copy tests**

```python
def test_in_memory_conversation_appends_batch_atomically() -> None:
    memory = InMemoryConversation()
    memory.add_messages([
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ])
    assert memory.get_context() == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]


def test_invalid_batch_does_not_partially_append() -> None:
    memory = InMemoryConversation([{"role": "user", "content": "existing"}])
    with pytest.raises(ValueError):
        memory.add_messages([
            {"role": "assistant", "content": "valid"},
            {"role": "invalid", "content": "bad"},
        ])
    assert memory.get_context() == [{"role": "user", "content": "existing"}]
```

Add tests that constructor input and snapshots are deep-copied, `clear()` works, and separate
instances do not share state. Keep all existing `SlidingWindowMemory` tests.

- [x] **Step 2: Run memory tests and confirm missing implementation**

Run: `python -m pytest tests/test_memory.py -v`
Expected: FAIL because `InMemoryConversation` is not defined.

- [x] **Step 3: Implement protocol and validated batch storage**

```python
class InMemoryConversation:
    def __init__(self, initial_messages=None) -> None:
        self._messages: list[dict[str, Any]] = []
        if initial_messages:
            self.add_messages(initial_messages)

    def add_messages(self, messages) -> None:
        copied = [_validate_conversation_message(message) for message in messages]
        self._messages.extend(copied)

    def get_context(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._messages)

    def clear(self) -> None:
        self._messages.clear()
```

The validator accepts OpenAI chat roles and preserves structured assistant/tool metadata. It never
stores caller-owned nested dictionaries.

- [x] **Step 4: Run memory tests**

Run: `python -m pytest tests/test_memory.py -v`
Expected: all memory tests PASS.

- [x] **Step 5: Commit Task 3**

```bash
git add core/memory.py tests/test_memory.py
git commit -m "feat: add transactional conversation memory"
```

### Task 4: Agent Budget Enforcement and Writeback

**Files:**
- Modify: `core/agent.py`
- Modify: `tests/test_agent.py`

**Interfaces:**
- Consumes: `ContextPolicy.prepare()` and `ConversationMemory.add_messages()`
- Produces: optional `Agent(..., context_policy: ContextPolicy | None = None)`
- Produces: `AgentStopReason` value `context_budget_exceeded`

- [ ] **Step 1: Add failing synchronous preparation and writeback tests**

```python
def test_run_prepares_every_model_request_and_commits_completed_exchange() -> None:
    policy = RecordingPolicy()
    memory = InMemoryConversation()
    model = ScriptedModel([tool_response, final_response])
    result = Agent(model, tools=[lookup], memory=memory, context_policy=policy).run("q")
    assert result.stop_reason == "completed"
    assert len(policy.calls) == 2
    assert memory.get_context() == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": result.content},
    ]
```

Add tests that context overflow prevents model access, tool observations are present in the next
policy call, model errors and max iterations do not write, and `get_context()`-only legacy memory is
still read without write attempts.

- [ ] **Step 2: Add failing streaming preparation, terminal, and cancellation tests**

```python
def test_abandoned_stream_does_not_write_memory() -> None:
    memory = InMemoryConversation()
    stream = Agent(streaming_model, memory=memory).run_stream("q")
    next(stream)
    stream.close()
    assert memory.get_context() == []


def test_stream_context_overflow_yields_terminal_done_without_model_call() -> None:
    events = list(Agent(failing_if_called_model, context_policy=rejecting).run_stream("q"))
    assert events[-1]["type"] == "done"
    assert events[-1]["stop_reason"] == "context_budget_exceeded"
```

Also cover incomplete and model-error streams leaving memory unchanged, successful streams writing
once, and memory write failures escaping instead of being reported as model failures.

- [ ] **Step 3: Run focused Agent tests and confirm failures**

Run: `python -m pytest tests/test_agent.py -k "context or memory or writeback or abandoned" -v`
Expected: new tests FAIL before Agent integration.

- [ ] **Step 4: Implement bounded helpers shared by both execution loops**

```python
def _prepare_request(self, messages):
    if self.context_policy is None:
        return messages
    return self.context_policy.prepare(messages, tools=self.registry.schemas())


def _commit_exchange(self, user_input: str, assistant_content: str) -> None:
    add_messages = getattr(self.memory, "add_messages", None)
    if callable(add_messages):
        add_messages([
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": assistant_content},
        ])
```

Call `_prepare_request()` immediately before every model invocation. Catch only
`ContextBudgetExceeded`, append a safe trace event, and return/yield the new terminal state. Call
`_commit_exchange()` after final-answer hooks succeed and immediately before returning
`AgentResult` or yielding successful `done`.

- [ ] **Step 5: Run focused Agent and existing memory compatibility tests**

Run: `python -m pytest tests/test_agent.py tests/test_memory.py -v`
Expected: all tests in both files PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add core/agent.py tests/test_agent.py
git commit -m "feat: enforce Agent context budgets and writeback"
```

### Task 5: Optional Summarizing Context Policy

**Files:**
- Modify: `core/context.py`
- Modify: `tests/test_context.py`

**Interfaces:**
- Consumes: Task 2 grouping and `TokenBudgetContext`
- Produces: `SummarizingContext(base_policy, summarizer)`
- Produces: `Summarizer(turns: Sequence[Mapping[str, Any]]) -> str` protocol

- [ ] **Step 1: Add failing summary behavior tests**

```python
def test_summary_replaces_only_turns_that_base_policy_would_remove() -> None:
    seen = []
    policy = SummarizingContext(base_policy, lambda turns: seen.extend(turns) or "old summary")
    prepared = policy.prepare(messages)
    assert seen == old_removable_turns
    assert {"role": "system", "content": "Conversation summary: old summary"} in prepared
    assert prepared[-2:] == latest_turn


@pytest.mark.parametrize("failure", [RuntimeError("failed"), "oversized"])
def test_summary_failure_falls_back_to_deterministic_trimming(failure) -> None:
    assert summarizing.prepare(messages) == base_policy.prepare(messages)
```

Add tests that no summarizer call occurs when input already fits, summaries do not mutate or write
history, tool-call units given to the summarizer remain complete, and tools are included in recounts.

- [ ] **Step 2: Run context tests and confirm missing summary wrapper**

Run: `python -m pytest tests/test_context.py -v`
Expected: new summary tests FAIL.

- [ ] **Step 3: Implement request-local summarization with deterministic fallback**

```python
def prepare(self, messages, *, tools=None):
    trimmed, removed = self.base_policy._prepare_with_removed(messages, tools=tools)
    if not removed:
        return trimmed
    try:
        summary = self.summarizer(copy.deepcopy(removed))
        candidate = [_summary_message(summary), *trimmed]
        return self.base_policy.prepare(candidate, tools=tools)
    except (ContextBudgetExceeded, TypeError, ValueError, RuntimeError):
        return trimmed
```

Refactor `TokenBudgetContext.prepare()` through a private `_prepare_with_removed()` helper returning
the validated prepared messages and complete removed units. A protected overflow still raises before
the summarizer is called. The wrapper catches failures from the supplied summarizer or from recounting
its candidate and falls back to the already validated deterministic result; malformed original input
is validated before this fallback boundary and remains visible to the caller.

- [ ] **Step 4: Run context tests**

Run: `python -m pytest tests/test_context.py -v`
Expected: all context tests PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add core/context.py tests/test_context.py
git commit -m "feat: add optional context summarization"
```

### Task 6: Stable Exports, Demo, Documentation, and Release Verification

**Files:**
- Modify: `core/__init__.py`
- Modify: `demo/chat.py`
- Modify: `tests/test_chat_demo.py`
- Modify: `tests/test_docs_contract.py`
- Modify: `README.md`
- Modify: `PLAN.md`
- Modify: `ROADMAP.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: all Tasks 1-5 public APIs
- Produces: documented `0.3.0` package surface and runnable budgeted chat Demo

- [ ] **Step 1: Add failing export, version, and Demo contract tests**

```python
def test_chat_demo_uses_automatic_memory_writeback() -> None:
    source = Path("demo/chat.py").read_text(encoding="utf-8")
    assert "InMemoryConversation" in source
    assert "TokenBudgetContext" in source
    assert "record_exchange(" not in source


def test_release_documents_context_api() -> None:
    assert project_version() == "0.3.0"
    assert "TokenBudgetContext" in readme
    assert "context_budget_exceeded" in readme
```

- [ ] **Step 2: Run focused release tests and confirm failures**

Run: `python -m pytest tests/test_chat_demo.py tests/test_docs_contract.py -v`
Expected: FAIL against `0.2.0` exports, Demo, and documentation.

- [ ] **Step 3: Export APIs and migrate the Demo**

Export `TokenCounter`, `ApproximateTokenCounter`, `ContextPolicy`, `TokenBudgetContext`,
`SummarizingContext`, `ContextBudgetExceeded`, `ConversationMemory`, and `InMemoryConversation`.
Configure the Demo explicitly:

```python
memory = InMemoryConversation()
context_policy = TokenBudgetContext(
    context_window=int(os.environ.get("LLM_CONTEXT_WINDOW", "65536")),
    reserved_output_tokens=int(os.environ.get("LLM_RESERVED_OUTPUT_TOKENS", "4096")),
)
agent = Agent(..., memory=memory, context_policy=context_policy)
```

Remove `record_exchange()` and its call. Only display successful content already committed by Agent;
all other terminal reasons display their safe `error` without changing memory.

- [ ] **Step 4: Update release documents and version**

Set `pyproject.toml` version to `0.3.0`. Update README examples and limitations, promote context and
conversation memory to stable APIs in `PLAN.md`, remove completed deterministic context work from
`ROADMAP.md`, and add a `0.3.1` section for persistent namespaced vector memory. Do not describe
provider-exact counting or automatic long-term retrieval as shipped.

- [ ] **Step 5: Run focused release tests**

Run: `python -m pytest tests/test_chat_demo.py tests/test_docs_contract.py -v`
Expected: all focused release tests PASS.

- [ ] **Step 6: Run complete automated tests**

Run: `python -m pytest tests -v`
Expected: all tests PASS with no network access.

- [ ] **Step 7: Run compilation, lint, and whitespace verification**

Run: `python -m compileall -q core demo tests`
Expected: exit code 0.

Run: `ruff check core tests demo`
Expected: `All checks passed!`

Run: `git diff --check`
Expected: no output and exit code 0.

- [ ] **Step 8: Commit the release**

```bash
git add core/__init__.py demo/chat.py tests/test_chat_demo.py tests/test_docs_contract.py README.md PLAN.md ROADMAP.md pyproject.toml docs/superpowers/plans/2026-07-24-context-memory-0-3-implementation.md
git commit -m "feat: release bounded context in 0.3.0"
```

- [ ] **Step 9: Push the completed task series**

Run: `git push origin dev`
Expected: remote `dev` advances through all `0.3.0` commits.
