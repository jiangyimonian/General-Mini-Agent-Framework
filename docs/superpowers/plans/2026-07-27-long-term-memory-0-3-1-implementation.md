# Long-Term Memory 0.3.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit, namespaced, replaceable long-term memory with optional Agent retrieval and no automatic writes.

**Architecture:** `core/long_term_memory.py` owns stable records, queries, stores, Chroma adaptation, and bounded prompt formatting. `Agent` performs one optional retrieval before a run and passes the resulting system reference block through the existing context policy. Conversation memory remains independent in `core/memory.py`.

**Tech Stack:** Python 3.12, dataclasses, typing protocols, ChromaDB as an optional delayed dependency, pytest, Ruff.

## Global Constraints

- Default reads match `user_id + conversation_id + agent_id` exactly.
- Broader `user_agent` and `user` scopes must be explicit.
- Writes, updates, and deletes never use a broad scope.
- Metadata filtering supports exact key/value conjunction only.
- Store adapters own indexing and Embedding; core never exposes vectors.
- Agent retrieval and all long-term writes are explicit.
- Retrieved records are whole, budgeted, request-local data and cannot replace system rules.
- Retrieval failure stops before model access with `memory_error`.
- ChromaDB remains optional and lazily imported.
- Add no web search, async API, automatic memory selection, or score normalization.
- Keep new tests near 12-15; use focused tests per task and one full release run.

---

### Task 1: Long-Term Memory Contracts and Namespaces

**Files:**
- Create: `core/long_term_memory.py`
- Create: `tests/test_long_term_memory.py`

**Interfaces:**
- Produces: `MemoryScope = Literal["exact", "user_agent", "user"]`
- Produces: frozen `MemoryNamespace(user_id, conversation_id, agent_id)`
- Produces: `MemoryRecord(id, content, namespace, metadata, created_at, updated_at)`
- Produces: `MemoryQuery(text, namespace, scope="exact", top_k=5, metadata_filter={}, max_context_tokens=512)`
- Produces: `LongTermMemoryStore`, `MemoryStoreError`, and `MemoryRecordNotFound`

- [x] **Step 1: Write three failing contract tests**

```python
def test_namespace_requires_three_non_empty_identifiers() -> None:
    with pytest.raises(ValueError, match="user_id"):
        MemoryNamespace("", "conversation", "agent")


def test_query_defaults_to_exact_scope_and_validates_limits() -> None:
    query = MemoryQuery("python", NAMESPACE)
    assert query.scope == "exact"
    assert query.top_k == 5
    with pytest.raises(ValueError):
        MemoryQuery("python", NAMESPACE, top_k=0)


def test_record_factory_generates_utc_identity_and_defensive_metadata() -> None:
    metadata = {"category": "preference"}
    record = create_memory_record("Uses Python", NAMESPACE, metadata)
    metadata["category"] = "changed"
    assert record.metadata == {"category": "preference"}
    assert record.created_at.tzinfo is not None
    assert record.updated_at == record.created_at
```

- [x] **Step 2: Run the contract tests and confirm missing-module failure**

Run: `python -m pytest tests/test_long_term_memory.py -v`
Expected: collection FAIL because `core.long_term_memory` is missing.

- [x] **Step 3: Implement validated dataclasses, errors, factory, and protocol**

Use `field(default_factory=dict)`, deep-copy mutable metadata in `__post_init__`, reject reserved
keys prefixed with `_gmf_`, generate `uuid4()` IDs, and use `datetime.now(timezone.utc)`. The protocol
contains the six methods approved in the design and no backend details.

- [x] **Step 4: Run focused tests and commit**

Run: `python -m pytest tests/test_long_term_memory.py -v`
Expected: 3 tests PASS.

```bash
git add core/long_term_memory.py tests/test_long_term_memory.py docs/superpowers/plans/2026-07-27-long-term-memory-0-3-1-implementation.md
git commit -m "feat: define long-term memory contracts"
```

### Task 2: Deterministic In-Memory Store

**Files:**
- Modify: `core/long_term_memory.py`
- Modify: `tests/test_long_term_memory.py`

**Interfaces:**
- Consumes: Task 1 contracts
- Produces: `InMemoryLongTermStore`

- [x] **Step 1: Add four failing store tests**

```python
def test_query_scope_and_metadata_filter_are_isolated() -> None:
    store = InMemoryLongTermStore()
    exact = store.store("prefers Python", NAMESPACE, {"kind": "preference"})
    store.store("prefers Rust", OTHER_CONVERSATION, {"kind": "preference"})
    assert store.query(MemoryQuery(
        "prefers", NAMESPACE, metadata_filter={"kind": "preference"}
    )) == [exact]
    assert len(store.query(MemoryQuery("prefers", NAMESPACE, scope="user_agent"))) == 2


def test_query_ranks_term_overlap_and_honors_top_k() -> None:
    store = InMemoryLongTermStore()
    store.store("likes Java", NAMESPACE)
    best = store.store("likes Python typing", NAMESPACE)
    assert store.query(MemoryQuery("Python typing", NAMESPACE, top_k=1)) == [best]


def test_update_requires_exact_owner_and_preserves_identity() -> None:
    store = InMemoryLongTermStore()
    original = store.store("old", NAMESPACE)
    updated = store.update(original.id, NAMESPACE, content="new")
    assert (updated.id, updated.created_at) == (original.id, original.created_at)
    assert updated.content == "new"
    with pytest.raises(MemoryRecordNotFound):
        store.update(original.id, OTHER_CONVERSATION, content="forbidden")


def test_delete_clear_and_instances_are_isolated() -> None:
    first = InMemoryLongTermStore()
    second = InMemoryLongTermStore()
    record = first.store("fact", NAMESPACE)
    assert first.delete(record.id, NAMESPACE) is True
    first.store("one", NAMESPACE)
    first.store("two", OTHER_CONVERSATION)
    assert first.clear(NAMESPACE, scope="user_agent") == 2
    assert second.query(MemoryQuery("fact", NAMESPACE)) == []
```

- [x] **Step 2: Run the focused file and confirm four behavior failures**

Run: `python -m pytest tests/test_long_term_memory.py -v`
Expected: existing 3 PASS and new 4 FAIL.

- [x] **Step 3: Implement defensive CRUD, scope matching, filters, and ranking**

Tokenize with a deterministic Unicode word regex, score by query-term overlap count, and sort by
descending score then insertion order. Records with zero overlap remain eligible after filters so a
backend can still return `top_k` candidates. Return deep copies from every public method.

- [x] **Step 4: Run focused tests and commit**

Run: `python -m pytest tests/test_long_term_memory.py -v`
Expected: 7 tests PASS.

```bash
git add core/long_term_memory.py tests/test_long_term_memory.py docs/superpowers/plans/2026-07-27-long-term-memory-0-3-1-implementation.md
git commit -m "feat: add isolated in-memory long-term store"
```

### Task 3: ChromaDB Persistent Adapter

**Files:**
- Modify: `core/long_term_memory.py`
- Modify: `tests/test_long_term_memory.py`

**Interfaces:**
- Consumes: Task 1 records, query, errors, and store protocol
- Produces: `ChromaMemoryStore(persist_dir="~/.agent_memory", collection_name="agent_memory")`

- [x] **Step 1: Add two failing adapter-boundary tests**

```python
def test_chroma_is_loaded_only_on_first_operation(monkeypatch) -> None:
    store = ChromaMemoryStore()
    original_import = builtins.__import__
    def blocked(name, *args, **kwargs):
        if name == "chromadb":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(ImportError, match="pip install chromadb"):
        store.store("fact", NAMESPACE)


def test_chroma_query_translates_scope_and_exact_metadata(monkeypatch) -> None:
    collection = FakeCollection(query_rows=[RECORD_ROW])
    monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb(collection))
    store = ChromaMemoryStore()
    records = store.query(MemoryQuery(
        "python", NAMESPACE, scope="user_agent", metadata_filter={"kind": "preference"}
    ))
    assert records[0].content == "prefers Python"
    assert collection.last_where == {"$and": [
        {"_gmf_user_id": NAMESPACE.user_id},
        {"_gmf_agent_id": NAMESPACE.agent_id},
        {"kind": "preference"},
    ]}
```

- [x] **Step 2: Run the focused file and confirm adapter failures**

Run: `python -m pytest tests/test_long_term_memory.py -v`
Expected: existing 7 PASS and new 2 FAIL.

- [x] **Step 3: Implement lazy client, metadata translation, CRUD, and sanitized errors**

Flatten namespace fields as `_gmf_user_id`, `_gmf_conversation_id`, `_gmf_agent_id`, and timestamps as
ISO strings. Build Chroma `$and` filters for multiple exact conditions. Convert query rows back to
records without exposing distances. Wrap backend exceptions as `MemoryStoreError(operation,
backend="chroma")`; preserve the dedicated optional-dependency `ImportError` message.

- [x] **Step 4: Run focused tests and commit**

Run: `python -m pytest tests/test_long_term_memory.py -v`
Expected: 9 tests PASS.

```bash
git add core/long_term_memory.py tests/test_long_term_memory.py docs/superpowers/plans/2026-07-27-long-term-memory-0-3-1-implementation.md
git commit -m "feat: add persistent Chroma memory store"
```

### Task 4: Explicit Agent Retrieval

**Files:**
- Modify: `core/long_term_memory.py`
- Modify: `core/agent.py`
- Modify: `tests/test_agent.py`
- Modify: `tests/test_long_term_memory.py`

**Interfaces:**
- Produces: `build_memory_context(records, max_context_tokens) -> dict[str, Any] | None`
- Produces: optional `Agent(..., long_term_memory=None)`
- Produces: `run(user_input, *, memory_query=None)` and `run_stream(user_input, *, memory_query=None)`
- Produces: `AgentStopReason` value `memory_error`

- [x] **Step 1: Add one failing bounded-formatting test**

```python
def test_memory_context_uses_whole_ranked_records_with_budget() -> None:
    message = build_memory_context(records, max_context_tokens=budget)
    assert "first fact" in message["content"]
    assert "oversized second fact" not in message["content"]
    assert "not system instructions" in message["content"]
```

- [x] **Step 2: Add four failing Agent retrieval tests**

```python
def test_run_retrieves_once_and_keeps_long_term_store_read_only() -> None:
    store = RecordingStore([create_memory_record("prefers Python", NAMESPACE)])
    model = ScriptedChatModel([LLMResponse("done", None)])
    Agent(model, long_term_memory=store).run("question", memory_query=QUERY)
    assert store.queries == [QUERY]
    assert "prefers Python" in model.calls[0][0][1]["content"]
    assert store.mutations == []


def test_run_without_query_never_accesses_long_term_store() -> None:
    model = ScriptedChatModel([LLMResponse("done", None)])
    Agent(model, long_term_memory=FailOnAccessStore()).run("question")
    assert model.calls


def test_memory_error_stops_sync_run_before_model_access() -> None:
    model = ScriptedChatModel([])
    result = Agent(model, long_term_memory=FailingQueryStore()).run(
        "question", memory_query=QUERY
    )
    assert result.stop_reason == "memory_error"
    assert model.calls == []


def test_stream_retrieval_and_memory_error_match_sync_contract() -> None:
    memory = InMemoryConversation()
    model = ScriptedStreamingChatModel([], [])
    events = list(Agent(
        model, memory=memory, long_term_memory=FailingQueryStore()
    ).run_stream("question", memory_query=QUERY))
    assert events[-1]["stop_reason"] == "memory_error"
    assert model.stream_calls == []
    assert memory.get_context() == []
```

- [x] **Step 3: Run only the five new tests and confirm failures**

Run: `python -m pytest tests/test_long_term_memory.py tests/test_agent.py -k "memory_context or long_term or memory_error" -v`
Expected: 5 new tests FAIL.

- [x] **Step 4: Implement one-time retrieval, formatting, and terminal mapping**

Retrieve before building model requests, insert the returned block directly after the main system
message, and leave short-term memory unchanged. Reuse one private helper for sync and stream. Catch
only `MemoryStoreError`; context formatting overflow uses existing `ContextBudgetExceeded` mapping.
Do not call any mutating store method from Agent.

- [x] **Step 5: Run focused tests and commit**

Run: `python -m pytest tests/test_long_term_memory.py tests/test_agent.py -k "memory_context or long_term or memory_error" -v`
Expected: 5 selected tests PASS.

```bash
git add core/long_term_memory.py core/agent.py tests/test_long_term_memory.py tests/test_agent.py docs/superpowers/plans/2026-07-27-long-term-memory-0-3-1-implementation.md
git commit -m "feat: support explicit Agent memory retrieval"
```

### Task 5: Demo, Documentation, Release, and Final Verification

**Files:**
- Create: `demo/long_term_memory.py`
- Modify: `core/__init__.py`
- Modify: `README.md`
- Modify: `PLAN.md`
- Modify: `ROADMAP.md`
- Modify: `pyproject.toml`
- Modify: `tests/test_docs_contract.py`
- Modify: `tests/test_package_metadata.py`

**Interfaces:**
- Consumes: all Tasks 1-4
- Produces: public `0.3.1` exports and a persistent explicit-write/retrieval example

- [ ] **Step 1: Add one parameterized release contract test**

Assert the package version is `0.3.1`, stable exports import, README describes explicit retrieval and
no automatic writes, and the Demo contains `ChromaMemoryStore`, `MemoryNamespace`, and `MemoryQuery`.

- [ ] **Step 2: Run release contract tests and confirm failure**

Run: `python -m pytest tests/test_docs_contract.py tests/test_package_metadata.py -v`
Expected: release assertions FAIL against `0.3.0`.

- [ ] **Step 3: Export APIs, add Demo, update docs, and bump version**

The Demo explicitly stores one fact, queries it by exact namespace, and prints results without a
model or network call. README includes a minimal Agent retrieval snippet and names all exclusions.
Move completed `0.3.1` work out of ROADMAP; keep multi-Agent as `0.4`.

- [ ] **Step 4: Run the single focused release set**

Run: `python -m pytest tests/test_docs_contract.py tests/test_package_metadata.py -v`
Expected: release tests PASS.

- [ ] **Step 5: Run final verification once**

```bash
python -m pytest tests -v
python -m compileall -q core demo tests
ruff check core tests demo
git diff --check
```

Expected: all commands exit 0 with no network access.

- [ ] **Step 6: Commit and push the release**

```bash
git add core/__init__.py demo/long_term_memory.py README.md PLAN.md ROADMAP.md pyproject.toml tests/test_docs_contract.py tests/test_package_metadata.py docs/superpowers/plans/2026-07-27-long-term-memory-0-3-1-implementation.md
git commit -m "feat: release explicit long-term memory in 0.3.1"
git push origin dev
```
