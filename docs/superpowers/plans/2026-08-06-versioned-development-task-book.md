# Versioned Development Task Book

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement one release task at a time. Each task uses checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the post-`1.1.5` roadmap into independently releasable, testable work packages through `1.9.0` without changing public behavior outside an approved version scope.

**Architecture:** Each minor version has one bounded capability, a verification gate, and a documentation/release task. `1.2.0` and `1.3.0` share the existing Async Debate plan; every later subsystem begins with its own approved design and implementation plan before production code changes. Patch versions are reserved for corrective work and do not add public features.

**Tech Stack:** Python 3.12+, `asyncio`, `httpx`, optional ChromaDB and OpenTelemetry dependencies, pytest, pytest-asyncio, Ruff, build, and Twine.

## Global Constraints

- Preserve existing public APIs unless the version task explicitly introduces a backward-compatible API.
- Keep synchronous and streaming paths aligned, or state the intentionally unsupported path in the release documentation.
- Isolate state, tools, contexts, events, and mutable configuration between Agent invocations.
- Treat `asyncio.CancelledError` as control flow and propagate it without converting it into a normal result.
- Use lazy imports for ChromaDB and OpenTelemetry; neither may become a required install dependency.
- Do not put API keys, credentials, or real network calls in tests, demos, or documentation.
- Classify external errors, apply timeouts at external boundaries, and keep errors free of secret values.
- Write a focused failing test before every production behavior change, then run the focused test before and after the implementation.
- Run the release gate in this document before claiming a version is ready.

---

## Release Rules

| Rule | Requirement |
| --- | --- |
| Minor release | Introduces one backward-compatible capability with public documentation and tests. |
| Patch release | Fixes regressions, compatibility, packaging, or documentation only. No new public API, config field, or runtime mode. |
| Scope freeze | Stop adding work once every task in the version has an owner and acceptance condition. Newly discovered features move to the next minor release. |
| API review | Public dataclasses, protocols, config fields, and exports require a written interface section before code is started. |
| Release evidence | Ruff, compileall, full offline pytest, package build, Twine validation, and clean-wheel import must all succeed. |

## Version Dependency Map

```text
1.1.5 LoopNode
  -> 1.2.0 Async Debate foundation
  -> 1.2.1 stabilization
  -> 1.3.0 parallel Async Debate
  -> 1.3.1 stabilization
  -> 1.4.0 async memory protocol
  -> 1.5.0 async ChromaDB adapter
  -> 1.6.0 retry policy
  -> 1.7.0 dynamic workflow nodes
  -> 1.8.0 rate limiting and OpenTelemetry
  -> 1.9.0 tool sandbox isolation
```

## Shared Release Gate

Run this gate at the end of every minor or patch release. A failure creates a corrective task in the same release only when it blocks the declared scope; otherwise it becomes the first task of the next patch release.

```bash
python -m ruff check general_mini_agent tests demo
python -m compileall -q general_mini_agent demo tests
python -m pytest tests -v
git diff --check
rm -rf dist/
python -m build
python -m twine check dist/*
```

For clean-wheel verification, create a virtual environment outside the checkout, install `dist/*.whl`, change to a non-repository directory, and import the release's new public API. The installed distribution version must match `pyproject.toml` and `general_mini_agent.__version__`.

---

## 1.2.0: Async Debate Foundation

**Release objective:** Add an isolated, sequential `AsyncDebate` implementation with non-streaming and streaming paths. This version has no parallel participant mode.

**Dependency:** Existing `AsyncAgent`, `DebateResult` value types, `RunEventEmitter`, and workflow node protocol.

**Primary plan:** [Async Debate and Parallel Participants Implementation Plan](2026-08-06-async-debate-and-parallel-participants.md), Tasks 1, 2, the sequential portion of Task 4, Tasks 5, 6, and 7.

### Task 1.2-A: Async Debate Public Contract

**Files:**
- Create: `general_mini_agent/async_debate.py`
- Create: `tests/test_async_debate.py`
- Modify: `general_mini_agent/__init__.py`

**Deliverable:** `AsyncDebateRole`, `AsyncDebateConfig`, `AsyncDebate`, `AsyncDebateStreamEvent`, and `create_async_debate()`.

- [ ] Define `AsyncDebateRole` with a non-empty name and prompt, an `AsyncAgent`, and optional role context.
- [ ] Define `AsyncDebateConfig(max_rounds: int = 3, convergence_check: ConvergenceCheck | None = None)` and reject values below one.
- [ ] Implement `await AsyncDebate.run_async(question, *, run_context=None, event_sink=None) -> DebateResult` with a fresh event emitter, usage map, round list, and judge turn for every invocation.
- [ ] Add `run_stream_async()` that yields role-labelled stream events and exactly one terminal event on normal completion.
- [ ] Add offline tests for invalid roles, invalid rounds, result structure, total usage, no-judge behavior, participant failure, judge failure, and two independent invocations.

**Acceptance:** A sequential Async Debate result has the same `DebateResult`, `DebateRound`, `DebateTurn`, stop reason, usage accumulation, and error semantics as its synchronous equivalent.

### Task 1.2-B: Sequential Context and Streaming Parity

**Files:**
- Modify: `general_mini_agent/async_debate.py`
- Modify: `tests/test_async_debate.py`

**Deliverable:** Later participants receive complete turns from earlier participants in the same round; the judge receives all successful rounds.

- [ ] Write a failing test where the Critic receives the Solver response in the same round and the Judge receives both responses.
- [ ] Write a failing stream test that asserts `speaker` events occur as `Solver`, `Critic`, `Judge`, and exactly one `debate_done` event contains the verdict.
- [ ] Implement sequential role execution with one child `RunEventEmitter` per role and copy each terminal `AgentResult` into a `DebateTurn` with the child run ID.
- [ ] Propagate cancellation while closing any active asynchronous stream; do not emit `debate_done` after cancellation.
- [ ] Run `python -m pytest tests/test_async_debate.py -q` before and after implementation.

**Acceptance:** A sequential streaming execution has declared-role order, isolated contexts, one terminal event, and cancellation propagation.

### Task 1.2-C: Workflow, Demo, and Release Surface

**Files:**
- Modify: `general_mini_agent/workflow_adapters.py`
- Modify: `general_mini_agent/__init__.py`
- Modify: `tests/test_workflow.py`
- Create: `demo/async_debate_demo.py`
- Modify: `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `pyproject.toml`

**Deliverable:** `AsyncDebateNode` maps a string workflow value to an Async Debate verdict without mutating an instance-level event sink.

- [ ] Add a failing workflow test for a successful `AsyncDebateNode` and a separate test for a non-string input returning `invalid_node_input`.
- [ ] Pass the workflow's run context and event sink as per-run arguments to `AsyncDebate.run_async()`; do not temporarily assign `debate.event_sink`.
- [ ] Create an offline scripted demo using sequential participants and document the same-round context rule in the README.
- [ ] Bump both version locations to `1.2.0`, add a changelog entry, and leave parallel participation marked as planned.
- [ ] Execute the Shared Release Gate and verify an installed wheel imports `AsyncDebate` and `AsyncDebateNode` outside the checkout.

**Acceptance:** `AsyncDebateNode` has no shared mutable event-sink mutation, the demo is network-free, and the public package export test passes.

## 1.2.1: Async Debate Stabilization

**Release objective:** Correct verified `1.2.0` regressions only.

### Task 1.2.1-A: Triage and Scope Control

**Files:**
- Modify only files named by a failing regression test.
- Test: the smallest existing or new `tests/test_async_debate.py` or `tests/test_workflow.py` case reproducing the defect.

- [ ] Record the observed failure, supported Python version, event sequence, and minimal reproduction in the issue or pull request description.
- [ ] Add one failing regression test that identifies the broken `1.2.0` behavior.
- [ ] Make one minimal corrective change; do not add `participant_execution`, asynchronous memory APIs, or additional configuration fields.
- [ ] Run the focused regression test and then the Shared Release Gate.
- [ ] Release only after `CHANGELOG.md` describes the fixed regression and the version is `1.2.1`.

**Acceptance:** The diff contains no new exported API or capability mode.

---

## 1.3.0: Parallel Async Debate

**Release objective:** Add a deliberate, opt-in parallel participant mode to `AsyncDebate`; sequential remains the default.

**Dependency:** `1.2.0` Async Debate foundation and its isolated event/result contracts.

**Primary plan:** [Async Debate and Parallel Participants Implementation Plan](2026-08-06-async-debate-and-parallel-participants.md), Task 3, the parallel portion of Task 4, and the `1.3.0` release updates in Tasks 5 through 7.

### Task 1.3-A: Parallel Configuration and Immutable Round Context

**Files:**
- Modify: `general_mini_agent/async_debate.py`
- Modify: `tests/test_async_debate.py`
- Modify: `general_mini_agent/__init__.py`

**Deliverable:** `AsyncParticipantExecution = Literal["sequential", "parallel"]` and `AsyncDebateConfig.participant_execution`, defaulting to `"sequential"`.

- [ ] Add a failing validation test for an unsupported mode and a compatibility test proving an omitted mode remains sequential.
- [ ] Add a barrier-based test proving all parallel participants start before any is released.
- [ ] Add a context test proving parallel participants do not receive same-round answers while the Judge receives all completed turns.
- [ ] Implement parallel rounds with `asyncio.gather()` over contexts built from the immutable completed-round snapshot.
- [ ] Store turns and accumulate usage in role declaration order rather than task completion order.

**Acceptance:** Parallel scheduling is opt-in, deterministic in stored results, and never leaks an in-flight answer to another participant.

### Task 1.3-B: Parallel Failure, Cancellation, and Stream Multiplexing

**Files:**
- Modify: `general_mini_agent/async_debate.py`
- Modify: `tests/test_async_debate.py`

**Deliverable:** Role-labelled interleaved stream events and complete accounting of a failed parallel round.

- [ ] Add a test with one successful and one failed participant; assert both terminal turns are retained, all usage is included, and the Judge is skipped.
- [ ] Add a cancellation test that verifies every blocked participant task receives cancellation and no terminal debate event is emitted.
- [ ] Add a stream test with interleaved chunks; assert every `agent_event` identifies the originating role and the final rounds retain declaration order.
- [ ] Implement a bounded `asyncio.Queue` for participant events and close or cancel all worker tasks in a `finally` block.
- [ ] Run `python -m pytest tests/test_async_debate.py -k "parallel or cancellation or stream" -q` before the Shared Release Gate.

**Acceptance:** No participant task outlives a closed stream, and an ordinary participant error is represented as `participant_error`, not an uncaught task exception.

### Task 1.3-C: Documentation and Compatibility Release

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `pyproject.toml`
- Modify: `demo/async_debate_demo.py`
- Modify: `tests/test_docs_contract.py`, `tests/test_package_metadata.py`

- [ ] Update the demo to explicitly pass `participant_execution="parallel"`.
- [ ] Document that parallel participants receive only prior completed rounds and that `"sequential"` preserves same-round visibility.
- [ ] Add contract tests for the README language and `1.3.0` package metadata.
- [ ] Bump both version locations to `1.3.0`, add the changelog entry, and run the Shared Release Gate.

**Acceptance:** Upgrading from `1.2.x` preserves sequential behavior unless the caller explicitly opts into parallel execution.

## 1.3.1: Parallel Stabilization

**Release objective:** Fix only post-release defects in parallel scheduling, cancellation cleanup, event attribution, or packaging.

- [ ] Start from a focused failing regression test.
- [ ] Confirm the corrective diff does not add a new participant mode, memory protocol, or workflow API.
- [ ] Run the Shared Release Gate and release `1.3.1` only with a concrete changelog entry.

---

## 1.4.0: Async Long-Term Memory Protocol

**Release objective:** Let `AsyncAgent` retrieve long-term memory without blocking the event loop, using an in-memory backend that is deterministic in offline tests.

**Dependency:** Existing `MemoryNamespace`, `MemoryRecord`, `MemoryQuery`, `MemoryStoreError`, and `build_memory_context()` in `general_mini_agent/long_term_memory.py`.

### Task 1.4-A: Define the Async Store Contract

**Files:**
- Create: `general_mini_agent/async_long_term_memory.py`
- Create: `tests/test_async_long_term_memory.py`
- Modify: `general_mini_agent/__init__.py`

**Public contract:**

```python
class AsyncLongTermMemoryStore(Protocol):
    async def store(self, content: str, namespace: MemoryNamespace, metadata=None) -> MemoryRecord: ...
    async def get(self, record_id: str, namespace: MemoryNamespace) -> MemoryRecord | None: ...
    async def query(self, query: MemoryQuery) -> list[MemoryRecord]: ...
    async def update(self, record_id: str, namespace: MemoryNamespace, *, content=None, metadata=None) -> MemoryRecord: ...
    async def delete(self, record_id: str, namespace: MemoryNamespace) -> bool: ...
    async def clear(self, namespace: MemoryNamespace, *, scope: MemoryScope = "exact") -> int: ...
```

- [ ] Write contract tests for each method signature, namespace isolation, defensive copies, invalid content, invalid scope, and sanitized `MemoryStoreError` behavior.
- [ ] Implement `AsyncInMemoryLongTermStore` with the same value semantics as `InMemoryLongTermStore`; use an `asyncio.Lock` around record mutation and return copies.
- [ ] Export `AsyncLongTermMemoryStore` and `AsyncInMemoryLongTermStore` without modifying the synchronous protocol.
- [ ] Run `python -m pytest tests/test_async_long_term_memory.py -q` before and after implementation.

**Acceptance:** All six store operations are awaitable, isolated by namespace, deterministic, and do not change synchronous store behavior.

### Task 1.4-B: Integrate Non-Blocking Retrieval into AsyncAgent

**Files:**
- Modify: `general_mini_agent/async_agent.py`
- Modify: `tests/test_async_agent.py`
- Modify: `tests/test_runtime_contract.py`

- [ ] Add a failing test with a blocking fake async store to prove `run_async()` awaits query completion without running synchronous store code on the event loop.
- [ ] Change `AsyncAgent.long_term_memory` to accept `AsyncLongTermMemoryStore | None` and await `query(memory_query)` in `_initial_messages()`.
- [ ] Preserve the existing `memory_error` terminal result and its sanitized error message when query fails.
- [ ] Add a streaming-path test that sees the same retrieval result and failure stop reason as `run_async()`.
- [ ] Run the async agent and runtime contract test files before the Shared Release Gate.

**Acceptance:** Sync and async memory store protocols remain separate, and both AsyncAgent paths have matching retrieval and failure semantics.

### Task 1.4-C: Documentation and Release

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `pyproject.toml`
- Modify: `tests/test_docs_contract.py`, `tests/test_package_metadata.py`

- [ ] Add an offline `AsyncInMemoryLongTermStore` example with `MemoryQuery`.
- [ ] State that ChromaDB is not yet available through the async protocol.
- [ ] Bump the package to `1.4.0`, add the changelog entry, and run the Shared Release Gate.

---

## 1.5.0: Async ChromaDB Adapter

**Release objective:** Provide optional persistent async memory while preserving lazy dependency loading and a fully testable replacement boundary.

**Dependency:** `1.4.0` async memory protocol. Do not introduce a ChromaDB import at package import time.

### Task 1.5-A: Adapter Boundary and Lazy Loading

**Files:**
- Modify: `general_mini_agent/async_long_term_memory.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_async_long_term_memory.py`

- [ ] Add a failing test proving `import general_mini_agent` succeeds when ChromaDB is absent.
- [ ] Add a failing test that a missing ChromaDB dependency raises a sanitized `MemoryStoreError` only when constructing or first using `AsyncChromaMemoryStore`.
- [ ] Implement `AsyncChromaMemoryStore` with delayed client creation and an injectable synchronous client factory for tests.
- [ ] Run synchronous ChromaDB operations through `asyncio.to_thread()` behind `asyncio.timeout()`; propagate cancellation and map backend failures to `MemoryStoreError(operation, backend="chroma")`.
- [ ] Add the optional dependency under the existing `memory` extra rather than the base dependency list.

**Acceptance:** The core package remains importable without ChromaDB, and the adapter never blocks the event loop while invoking a synchronous client.

### Task 1.5-B: Persistence Semantics and Failure Coverage

**Files:**
- Modify: `general_mini_agent/async_long_term_memory.py`
- Modify: `tests/test_async_long_term_memory.py`
- Modify: `tests/test_async_agent.py`

- [ ] Reuse the synchronous namespace metadata encoding and filtering rules; add tests for exact, user-agent, and user scope queries.
- [ ] Add fake-client tests for store, get, query, update, delete, clear, client timeout, and client exception paths.
- [ ] Add AsyncAgent tests using the fake persistent store for success and `memory_error` paths.
- [ ] Verify ChromaDB import is still deferred by executing the targeted test under an environment without the dependency.

**Acceptance:** Persistent behavior matches the existing ChromaDB namespace rules and does not expose backend exception text.

### Task 1.5-C: Documentation and Release

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `pyproject.toml`
- Modify: `tests/test_docs_contract.py`, `tests/test_package_metadata.py`

- [ ] Document `pip install ".[memory]"` as optional and show one offline fake-client test scenario rather than a live service requirement.
- [ ] Bump the package to `1.5.0`, add the changelog entry, and run the Shared Release Gate.

---

## 1.6.0: Retry Policy for Orchestration Boundaries

**Release objective:** Replace ad hoc retry loops with a single explicit policy that is safe for reads and model requests, observable, deterministic in tests, and conservative for side-effecting tools.

**Dependency:** Existing `LLMConfig.max_retries`, `ModelRequestError`, `AsyncToolRegistry`, `ToolRegistry`, and memory error types.

### Task 1.6-A: Retry Contract and Test Clock

**Files:**
- Create: `general_mini_agent/retry.py`
- Create: `tests/test_retry.py`
- Modify: `general_mini_agent/__init__.py`

**Public contract:**

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    initial_delay_seconds: float
    max_delay_seconds: float
    multiplier: float = 2.0

    def delay_for_attempt(self, attempt: int) -> float: ...
    def should_retry(self, error: Exception, attempt: int) -> bool: ...
```

- [ ] Write failing tests for invalid policy values, exponential delay capping, retryable timeout/connection/temporary-server failures, and non-retryable authentication/validation failures.
- [ ] Inject a sleeper callable into the execution helper so tests record delays without wall-clock waiting.
- [ ] Ensure `CancelledError` is never caught by the helper.
- [ ] Export only the policy and a narrowly typed helper; do not export provider-specific exception internals.

**Acceptance:** Retry timing is deterministic in tests and error classification is explicit rather than inferred from exception text.

### Task 1.6-B: Model and Memory Read Integration

**Files:**
- Modify: `general_mini_agent/llm.py`, `general_mini_agent/async_llm.py`
- Modify: `general_mini_agent/async_long_term_memory.py`
- Modify: `tests/test_llm.py`, `tests/test_async_llm.py`, `tests/test_async_long_term_memory.py`

- [ ] Add focused failing tests showing a retryable model error succeeds on a later attempt and an error after first streamed output is not retried.
- [ ] Replace duplicated LLM retry loops with the shared policy while preserving current `LLMConfig.max_retries` compatibility.
- [ ] Apply the policy only to idempotent memory reads (`get` and `query`), not `store`, `update`, `delete`, or `clear`.
- [ ] Emit a structured retry event through the existing run event boundary without including request content or credentials.
- [ ] Run all LLM, async LLM, and async memory tests before the Shared Release Gate.

**Acceptance:** A retry never duplicates a tool mutation, memory write, or streamed model output.

### Task 1.6-C: Explicit Tool Opt-In

**Files:**
- Modify: `general_mini_agent/tools.py`, `general_mini_agent/async_tools.py`
- Modify: `tests/test_tools.py`, `tests/test_async_agent.py`

- [ ] Add a metadata field that identifies a tool as retry-safe; its default is false.
- [ ] Add tests proving an unmarked tool executes once even when it fails transiently.
- [ ] Add tests proving a marked read-only tool follows the retry policy and reports its final structured result.
- [ ] Document the retry-safe contract next to the tool decorator and release the version as `1.6.0` after the Shared Release Gate.

**Acceptance:** Side-effecting tools are never retried by default.

---

## 1.7.0: Dynamic Workflow Nodes

**Release objective:** Permit constrained runtime graph expansion while keeping the workflow graph valid, observable, bounded, and reproducible.

**Dependency:** `WorkflowNode`, `Workflow`, `NodeResult`, `RunContext`, `RunEventEmitter`, and the established `SequenceNode`, `ParallelNode`, `ConditionalNode`, and `LoopNode` contracts.

### Task 1.7-A: Design Gate and Public API Review

**Files:**
- Create: `docs/superpowers/specs/2026-08-06-dynamic-workflow-nodes-design.md`
- Create: `docs/superpowers/plans/2026-08-06-dynamic-workflow-nodes.md`

- [ ] Define the exact expansion boundary: which node may request additions, where additions are attached, and when the graph snapshot becomes immutable.
- [ ] Define maximum dynamic-node count, maximum depth, duplicate-node policy, and behavior after a node fails or the workflow is cancelled.
- [ ] Define event types and payload fields for node-requested, node-accepted, node-rejected, and graph-frozen transitions.
- [ ] Obtain approval for the API and plan before editing `general_mini_agent/workflow.py`.

**Acceptance:** The approved design states one unambiguous graph mutation model and has an explicit bound on growth.

### Task 1.7-B: Bounded Runtime Expansion

**Files:**
- Modify: `general_mini_agent/workflow.py`, `general_mini_agent/events.py`
- Modify: `tests/test_workflow.py`, `tests/test_events.py`

- [ ] Write failing tests for a valid runtime addition, duplicate rejection, maximum-node rejection, failure propagation, cancellation, and stable event parent/child IDs.
- [ ] Implement only the API approved in Task 1.7-A; retain immutable copies for previously emitted `NodeResult` values.
- [ ] Ensure a dynamically added node validates input and returns the existing structured `NodeResult` error shape.
- [ ] Add a repeat-run test proving two executions do not share additions from a prior run.

**Acceptance:** Dynamic expansion cannot escape its configured graph and never leaks state across Workflow runs.

### Task 1.7-C: Documentation and Release

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `pyproject.toml`
- Modify: `tests/test_docs_contract.py`, `tests/test_package_metadata.py`

- [ ] Add an offline bounded-expansion example and document the configured limits.
- [ ] Bump to `1.7.0`, add the changelog entry, and run the Shared Release Gate.

---

## 1.8.0: Rate Limiting and OpenTelemetry

**Release objective:** Add per-instance request governance and optional distributed tracing without changing default request behavior when neither capability is configured.

**Dependency:** Model request paths in `llm.py` and `async_llm.py`, framework configuration, and run events.

### Task 1.8-A: Rate-Limit Policy

**Files:**
- Create: `general_mini_agent/rate_limit.py`
- Create: `tests/test_rate_limit.py`
- Modify: `general_mini_agent/config.py`, `general_mini_agent/llm.py`, `general_mini_agent/async_llm.py`

**Public contract:**

```python
@dataclass(frozen=True)
class RateLimitPolicy:
    requests_per_minute: int
    burst: int

    def acquire_sync(self) -> None: ...
    async def acquire_async(self) -> None: ...
```

- [ ] Write failing fake-clock tests for burst allowance, waiting until a token becomes available, independent policy instances, and cancellation while awaiting a token.
- [ ] Inject monotonic clock and sleep functions; do not use wall-clock time to calculate tokens.
- [ ] Apply the policy at the model request boundary before each outbound request, including retry attempts.
- [ ] Keep the default policy unset so existing callers experience no new delay.

**Acceptance:** Rate limits are local to the configured LLM instance and use deterministic fake-clock tests.

### Task 1.8-B: Optional OpenTelemetry Bridge

**Files:**
- Create: `general_mini_agent/telemetry.py`
- Create: `tests/test_telemetry.py`
- Modify: `pyproject.toml`, `general_mini_agent/events.py`, `general_mini_agent/__init__.py`

- [ ] Add an optional `telemetry` extra containing OpenTelemetry API packages; keep imports inside the bridge factory.
- [ ] Write a fake-tracer test that asserts spans include run ID, parent run ID, event type, stop reason, and elapsed time but omit prompt content, tool arguments, and secrets.
- [ ] Write a missing-dependency test that confirms normal framework execution continues when telemetry is not installed or not configured.
- [ ] Bridge `RunEvent` emissions to spans without changing `EventSink` ordering or failure behavior.

**Acceptance:** Observability is opt-in, non-blocking, and incapable of exposing model inputs or credentials through default span attributes.

### Task 1.8-C: Configuration, Documentation, and Release

**Files:**
- Modify: `general_mini_agent/config.py`, `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `pyproject.toml`
- Modify: `tests/test_config.py`, `tests/test_docs_contract.py`, `tests/test_package_metadata.py`

- [ ] Add validation tests for rate limit values and environment/config precedence.
- [ ] Document the opt-in configuration, default-off behavior, and data-redaction rule for telemetry.
- [ ] Bump to `1.8.0`, add the changelog entry, and run the Shared Release Gate.

---

## 1.9.0: Tool Sandbox Isolation

**Release objective:** Isolate project-tool command execution with explicit platform support, resource limits, and a fail-closed security boundary.

**Dependency:** `ToolRuntimeContext`, `ProjectToolBoundaryPolicy`, `create_run_command()`, structured permission policy, and the existing command timeout/output cap behavior.

### Task 1.9-A: Threat Model and Platform Contract

**Files:**
- Create: `docs/superpowers/specs/2026-08-06-tool-sandbox-design.md`
- Create: `docs/superpowers/plans/2026-08-06-tool-sandbox.md`

- [ ] Enumerate supported host platforms and the isolation mechanism available on each.
- [ ] Define sandbox filesystem roots, network policy, process lifetime, CPU/memory limits, environment-variable allowlist, and behavior when isolation is unavailable.
- [ ] Define the compatibility policy for the existing `run_command` tool: sandbox-disabled legacy behavior, sandbox-enabled enforcement, and a future major-version path if the default must become more restrictive.
- [ ] Obtain security review and explicit approval before production changes to `tools_project.py`.

**Acceptance:** The design gives a testable answer for every requested execution capability and does not claim isolation that the selected platform cannot provide.

### Task 1.9-B: Sandboxed Command Runner

**Files:**
- Create: `general_mini_agent/sandbox.py`
- Modify: `general_mini_agent/tools_project.py`, `general_mini_agent/permissions.py`
- Create: `tests/test_sandbox.py`
- Modify: `tests/test_tools_project.py`, `tests/test_permissions.py`

- [ ] Write failing tests for disabled sandbox behavior, path escape rejection, network-denied behavior, timeout cleanup, output caps, environment filtering, and unavailable-sandbox failure.
- [ ] Define a `CommandSandbox` protocol returning a structured result with exit code, stdout, stderr, duration, timeout state, and sandbox error code.
- [ ] Route `create_run_command()` through the sandbox only when `ToolRuntimeContext` explicitly selects it; default to denial if sandbox mode is requested but unavailable.
- [ ] Keep authorization evaluation before sandbox process creation and return sanitized structured errors for all setup failures.
- [ ] Execute Linux and Windows test jobs for every sandbox-enabled release candidate.

**Acceptance:** A sandboxed command cannot access a path, environment value, network capability, or process lifetime outside the approved contract.

### Task 1.9-C: Security Documentation and Release

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `pyproject.toml`, `.github/workflows/ci.yml`
- Modify: `tests/test_docs_contract.py`, `tests/test_package_metadata.py`

- [ ] Document supported platforms, configuration defaults, known limitations, and the distinction between authorization and isolation.
- [ ] Add CI coverage for each supported sandbox platform or mark unsupported combinations as excluded with a documented reason.
- [ ] Bump to `1.9.0`, add the changelog entry, and run the Shared Release Gate plus sandbox platform checks.

**Acceptance:** The release notes do not represent a permission check as a sandbox, and CI evidence covers every supported isolation implementation.

---

## Planning Outputs Required Before Each Future Version

| Version | Required design artifact | Required implementation plan | Existing status |
| --- | --- | --- | --- |
| `1.2.0` | Async Debate contract in the linked plan | Linked Async Debate plan | Written |
| `1.3.0` | Parallel execution rules in the linked plan | Linked Async Debate plan | Written |
| `1.4.0` | Async memory contract design | `async-long-term-memory` plan | Create before coding |
| `1.5.0` | Async Chroma adapter design | `async-chroma-memory` plan | Create before coding |
| `1.6.0` | Retry classification design | `retry-policy` plan | Create before coding |
| `1.7.0` | Dynamic graph mutation design | `dynamic-workflow-nodes` plan | Design task included above |
| `1.8.0` | Rate-limit and telemetry data policy | `runtime-governance` plan | Create before coding |
| `1.9.0` | Sandbox threat model and platform contract | `tool-sandbox` plan | Design task included above |

## Out of Scope for This Task Book

- No production code is changed by this document.
- No version is claimed as released until its Shared Release Gate has fresh passing evidence.
- No live model provider, ChromaDB server, telemetry collector, or external command host is required for the default offline test suite.
