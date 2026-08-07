# Async Debate and Parallel Participants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a stable sequential `AsyncDebate` foundation in `1.2.0`, then add opt-in parallel participants and stream multiplexing in `1.3.0` without changing the synchronous Debate API.

**Architecture:** Add `general_mini_agent/async_debate.py` beside the existing synchronous implementation instead of changing `Debate` behavior. `1.2.0` reuses the typed result objects from `debate.py` and implements isolated sequential async execution and streaming. `1.3.0` adds `asyncio.gather()` behind an explicit parallel mode; every participant in that mode receives the question plus completed prior rounds, never another participant's in-flight answer, and result turns remain in declared role order.

**Tech Stack:** Python 3.12+, `asyncio`, existing `AsyncAgent`, `RunEventEmitter`, pytest, pytest-asyncio, Ruff.

## Global Constraints

- Keep all existing public synchronous `Debate` APIs and behavior unchanged.
- Use a separate `AsyncDebateRole` and `AsyncDebateConfig`; do not widen the synchronous `DebateRole.agent` contract.
- Support both `run_async()` and `run_stream_async()` in `1.2.0`; `1.3.0` adds only their opt-in parallel behavior.
- Preserve per-invocation isolation for contexts, accumulated usage, events, and participant results.
- Let `asyncio.CancelledError` propagate and cancel unfinished participant work; never convert cancellation into a normal `DebateResult`.
- Run only offline scripted models in tests. Do not add API keys, network calls, or a required dependency.
- Keep errors structured, contextual, and free of secrets.
- Use TDD for each behavior: write a failing test, observe the expected failure, implement the smallest change, then rerun the focused test.
- `1.2.0` and `1.3.0` are minor releases. `1.2.1` and `1.3.1` are reserved for fixes and stabilization only.

---

## Release Decomposition

| Release | Scope | Exit criteria |
| --- | --- | --- |
| `1.2.0` | Async Debate contracts, sequential non-streaming and streaming paths, workflow adapter, public exports, offline demo, and release documentation. | Every async path has offline coverage, sequential context matches synchronous Debate, and the wheel installs outside the checkout. |
| `1.2.1` | Regression fixes only. | No new public API; all `1.2.0` quality gates remain green. |
| `1.3.0` | Explicit `participant_execution="parallel"`, immutable prior-round contexts, declared-order results, and parallel stream multiplexing. | Concurrency, failure, cancellation, event-attribution, and ordering tests pass. |
| `1.3.1` | Parallel-mode fixes only. | No new participant modes or memory APIs. |

The public contract below shows the final `1.3.0` shape. In `1.2.0`, `AsyncDebateConfig` contains only `max_rounds` and `convergence_check`, and all participants execute sequentially. `1.3.0` adds `AsyncParticipantExecution` and `participant_execution` with a `"sequential"` default, so upgrading from `1.2.x` does not change execution semantics.

## File Structure

| File | Responsibility |
| --- | --- |
| `general_mini_agent/async_debate.py` | Async role/config contracts, non-streaming and streaming execution, parallel scheduling, and convenience factory. |
| `general_mini_agent/workflow_adapters.py` | `AsyncDebateNode`, mapping an `AsyncDebate` verdict to `NodeResult` without mutating shared instance state. |
| `general_mini_agent/__init__.py` | Stable public exports for async Debate contracts and workflow adapter. |
| `tests/test_async_debate.py` | Offline contract, isolation, cancellation, sequential, parallel, and streaming regression coverage. |
| `tests/test_workflow.py` | `AsyncDebateNode` success, invalid-input, and event-context coverage. |
| `demo/async_debate_demo.py` | Offline executable example using scripted async models. |
| `README.md` | Public async Debate usage and parallel-round semantics. |
| `ROADMAP.md` | Move the delivered async Debate item out of planned work while retaining unimplemented async memory items. |
| `CHANGELOG.md` | User-facing `1.2.0` release entry. |
| `pyproject.toml` | Package version `1.2.0`. |

## Public Contract

```python
# general_mini_agent/async_debate.py
from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from .agent import StreamEvent
from .async_agent import AsyncAgent
from .debate import (
    ConvergenceCheck,
    DebateResult,
    DebateRound,
    DebateStopReason,
    DebateTurn,
)
from .events import EventSink, RunContext

AsyncParticipantExecution = Literal["sequential", "parallel"]


@dataclass
class AsyncDebateRole:
    name: str
    agent: AsyncAgent
    prompt: str
    role_context: str = ""


@dataclass
class AsyncDebateConfig:
    max_rounds: int = 3
    participant_execution: AsyncParticipantExecution = "sequential"
    convergence_check: ConvergenceCheck | None = None


class AsyncDebateRoundStartEvent(TypedDict):
    type: Literal["round_start"]
    round: int


class AsyncDebateSpeakerEvent(TypedDict):
    type: Literal["speaker"]
    role: str
    phase: Literal["participant", "judge"]
    round: int | None


class AsyncDebateAgentEvent(TypedDict):
    type: Literal["agent_event"]
    role: str
    event: StreamEvent


class AsyncDebateDoneEvent(TypedDict):
    type: Literal["debate_done"]
    verdict: str
    rounds: list[DebateRound]
    judge_turn: DebateTurn | None
    total_usage: dict[str, int]
    stop_reason: DebateStopReason
    converged: bool
    error: str | None


AsyncDebateStreamEvent = (
    AsyncDebateRoundStartEvent
    | AsyncDebateSpeakerEvent
    | AsyncDebateAgentEvent
    | AsyncDebateDoneEvent
)


class AsyncDebate:
    def __init__(
        self,
        participants: Sequence[AsyncDebateRole],
        *,
        judge: AsyncDebateRole | None = None,
        config: AsyncDebateConfig | None = None,
        event_sink: EventSink | None = None,
    ) -> None: ...

    async def run_async(
        self,
        question: str,
        *,
        run_context: RunContext | None = None,
        event_sink: EventSink | None = None,
    ) -> DebateResult: ...

    def run_stream_async(
        self,
        question: str,
        *,
        run_context: RunContext | None = None,
        event_sink: EventSink | None = None,
    ) -> AsyncIterator[AsyncDebateStreamEvent]: ...


def create_async_debate(
    solver: AsyncAgent,
    critic: AsyncAgent,
    judge: AsyncAgent,
    *,
    max_rounds: int = 3,
    participant_execution: AsyncParticipantExecution = "sequential",
    solver_context: str = "",
    critic_context: str = "",
) -> AsyncDebate: ...
```

`DebateResult`, `DebateRound`, and `DebateTurn` remain the shared result types. This keeps trace rendering, JSON serialization, and callers that inspect debate results compatible across sync and async modes.

### Parallel Round Rules

1. Launch every participant once for a parallel round.
2. Build every participant context from the immutable question and complete earlier rounds only.
3. Collect all terminal participant results before deciding the round outcome.
4. Store turns and accumulate usage in configured participant order, not completion order.
5. If any participant has a non-`completed` stop reason, return `participant_error`, preserve every collected turn, and do not call the judge.
6. A judge always runs after all successful rounds and receives every completed participant turn.
7. `sequential` remains available when a participant must read earlier responses from the same round; its behavior mirrors synchronous `Debate`.

### Streaming Rules

1. `run_stream_async()` yields exactly one terminal `debate_done` event unless cancelled.
2. In a sequential round, `speaker` and `agent_event` ordering matches participant declaration order.
3. In a parallel round, `speaker` events are emitted in declaration order before tasks start; subsequent `agent_event` values may interleave by arrival time and always include the source role.
4. The terminal event uses turns in declaration order even when streamed events arrived in a different order.
5. The stream must close all worker tasks before yielding its terminal event.

## Tasks

### Task 1: Add Async Debate Contracts and Validation (`1.2.0`)

**Files:**
- Create: `general_mini_agent/async_debate.py`
- Create: `tests/test_async_debate.py`

**Interfaces:**
- Consumes: `AsyncAgent`, `DebateRound`, `DebateTurn`, `DebateResult`, `ConvergenceCheck`, `RunEventEmitter`.
- Produces: `AsyncDebateRole`, `AsyncDebateConfig`, `AsyncDebate`, and the async stream event type aliases.

- [ ] **Step 1: Write failing contract tests**

```python
# tests/test_async_debate.py
import asyncio
from collections import deque

import pytest

from general_mini_agent.agent import AgentResult
from general_mini_agent.async_debate import AsyncDebate, AsyncDebateConfig, AsyncDebateRole


class ScriptedAsyncAgent:
    def __init__(self, *responses: AgentResult) -> None:
        self._responses = deque(responses)
        self.inputs: list[str] = []

    async def run_async(self, user_input: str, *, run_context=None) -> AgentResult:
        self.inputs.append(user_input)
        return self._responses.popleft()


def completed(content: str, tokens: int = 1) -> AgentResult:
    return AgentResult(
        content=content,
        usage={"total_tokens": tokens},
        stop_reason="completed",
    )


def failed(content: str, error: str, tokens: int = 1) -> AgentResult:
    return AgentResult(
        content=content,
        usage={"total_tokens": tokens},
        stop_reason="model_error",
        error=error,
    )


def async_role(name: str, agent: ScriptedAsyncAgent | None = None) -> AsyncDebateRole:
    return AsyncDebateRole(
        name=name,
        agent=agent or ScriptedAsyncAgent(completed("unused")),  # type: ignore[arg-type]
        prompt=f"You are {name}.\n{{role_context}}",
    )


def test_async_debate_config_rejects_non_positive_max_rounds() -> None:
    with pytest.raises(ValueError, match="max_rounds"):
        AsyncDebateConfig(max_rounds=0)


# Add this assertion only in the 1.3.0 change set, after the new field exists.
def test_async_debate_config_rejects_unknown_participant_execution() -> None:
    with pytest.raises(ValueError, match="participant_execution"):
        AsyncDebateConfig(participant_execution="fanout")  # type: ignore[arg-type]


def test_async_debate_rejects_missing_and_duplicate_roles(async_role) -> None:
    with pytest.raises(ValueError, match="at least one participant"):
        AsyncDebate([])
    with pytest.raises(ValueError, match="unique"):
        AsyncDebate([async_role("Solver"), async_role("Solver")])
    with pytest.raises(ValueError, match="distinct"):
        AsyncDebate([async_role("Judge")], judge=async_role("Judge"))
```

- [ ] **Step 2: Run the focused test and verify it fails because the module does not exist**

Run: `python -m pytest tests/test_async_debate.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'general_mini_agent.async_debate'`.

- [ ] **Step 3: Add the contracts and validation**

```python
# general_mini_agent/async_debate.py
@dataclass
class AsyncDebateRole:
    name: str
    agent: AsyncAgent
    prompt: str
    role_context: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("role name must be non-empty")
        if not self.prompt.strip():
            raise ValueError(f"prompt for role {self.name!r} must be non-empty")


@dataclass
class AsyncDebateConfig:
    max_rounds: int = 3
    convergence_check: ConvergenceCheck | None = None

    def __post_init__(self) -> None:
        if self.max_rounds < 1:
            raise ValueError("max_rounds must be at least 1")


# Add this exact extension in Task 3 for the 1.3.0 release.
AsyncParticipantExecution = Literal["sequential", "parallel"]


@dataclass
class AsyncDebateConfig:
    max_rounds: int = 3
    convergence_check: ConvergenceCheck | None = None
    participant_execution: AsyncParticipantExecution = "sequential"

    def __post_init__(self) -> None:
        if self.max_rounds < 1:
            raise ValueError("max_rounds must be at least 1")
        if self.participant_execution not in ("sequential", "parallel"):
            raise ValueError("participant_execution must be 'sequential' or 'parallel'")


class AsyncDebate:
    def __init__(self, participants, *, judge=None, config=None, event_sink=None) -> None:
        self.participants = list(participants)
        self.judge = judge
        self.config = config or AsyncDebateConfig()
        self.event_sink = event_sink
        self._validate_roles()

    def _validate_roles(self) -> None:
        if not self.participants:
            raise ValueError("at least one participant is required")
        names = [role.name for role in self.participants]
        if len(set(names)) != len(names):
            raise ValueError("participant role names must be unique")
        if self.judge is not None and self.judge.name in names:
            raise ValueError("Judge role name must be distinct from participant names")
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `python -m pytest tests/test_async_debate.py -q`

Expected: the contract tests pass.

- [ ] **Step 5: Commit the contract boundary**

```bash
git add general_mini_agent/async_debate.py tests/test_async_debate.py
git commit -m "feat: add async debate contracts"
```

### Task 2: Implement Sequential Async Debate Parity (`1.2.0`)

**Files:**
- Modify: `general_mini_agent/async_debate.py`
- Modify: `tests/test_async_debate.py`

**Interfaces:**
- Consumes: `AsyncDebateRole.agent.run_async(context, run_context=...) -> AgentResult`.
- Produces: `AsyncDebate.run_async()` with `sequential` behavior, `DebateResult`, and hierarchical run IDs.

- [ ] **Step 1: Write failing sequential execution tests**

```python
@pytest.mark.asyncio
async def test_sequential_async_debate_preserves_same_round_context_and_runs_judge() -> None:
    solver = ScriptedAsyncAgent(completed("proposal", 2))
    critic = ScriptedAsyncAgent(completed("review", 3))
    judge = ScriptedAsyncAgent(completed("verdict", 5))
    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1, participant_execution="sequential"),
    )

    result = await debate.run_async("question")

    assert result.stop_reason == "completed"
    assert result.verdict == "verdict"
    assert result.total_usage == {"total_tokens": 10}
    assert "[Solver]: proposal" in critic.inputs[0]
    assert "[Critic]: review" in judge.inputs[0]
    assert [turn.role for turn in result.rounds[0].turns] == ["Solver", "Critic"]
    assert result.run_id and all(turn.run_id for turn in result.rounds[0].turns)


@pytest.mark.asyncio
async def test_sequential_async_debate_stops_before_later_roles_after_failure() -> None:
    solver = ScriptedAsyncAgent(failed("partial", "unavailable", 2))
    critic = ScriptedAsyncAgent(completed("must not run"))
    judge = ScriptedAsyncAgent(completed("must not run"))
    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(participant_execution="sequential"),
    )

    result = await debate.run_async("question")

    assert result.stop_reason == "participant_error"
    assert result.error == "unavailable"
    assert critic.inputs == []
    assert judge.inputs == []
```

- [ ] **Step 2: Run the focused tests and verify they fail because `run_async` is absent**

Run: `python -m pytest tests/test_async_debate.py -k sequential -q`

Expected: failure reports that `AsyncDebate` has no `run_async` method.

- [ ] **Step 3: Implement isolated sequential execution**

```python
async def _run_role(
    self,
    role: AsyncDebateRole,
    context: str,
    child_emitter: RunEventEmitter,
) -> DebateTurn:
    result = await role.agent.run_async(context, run_context=child_emitter.context())
    return DebateTurn(
        role=role.name,
        content=result.content,
        usage=result.usage,
        stop_reason=result.stop_reason,
        error=result.error,
        run_id=child_emitter.run_id,
    )


async def _run_sequential_round(self, question, rounds, emitter):
    turns: list[DebateTurn] = []
    for role in self.participants:
        turn = await self._run_role(
            role,
            self._build_context(role, question, rounds, turns),
            emitter.child(),
        )
        turns.append(turn)
        if turn.stop_reason != "completed":
            return turns, turn
    return turns, None
```

Implement `run_async()` around this helper with fresh `rounds`, `total_usage`, and `RunEventEmitter` values per invocation. Emit `debate_started` before work and `debate_finished` on each terminal path. Reuse `_build_context`, `_turn_error`, and `_accumulate_usage` semantics from `debate.py`; copy these private helpers into `async_debate.py` rather than importing private functions.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python -m pytest tests/test_async_debate.py -k sequential -q`

Expected: both sequential tests pass.

- [ ] **Step 5: Commit sequential parity**

```bash
git add general_mini_agent/async_debate.py tests/test_async_debate.py
git commit -m "feat: add sequential async debate"
```

### Task 3: Add Deterministic Parallel Rounds (`1.3.0`)

**Files:**
- Modify: `general_mini_agent/async_debate.py`
- Modify: `tests/test_async_debate.py`

**Interfaces:**
- Consumes: a stable snapshot of complete `list[DebateRound]` and `AsyncDebateRole.agent.run_async()`.
- Produces: `participant_execution="parallel"` with concurrent launch, declared-order results, and complete failure accounting.

Before this task's tests, apply the `AsyncParticipantExecution` and `AsyncDebateConfig` extension shown in Task 1, Step 3. Its default must remain `"sequential"`; `"parallel"` is an explicit opt-in added only in `1.3.0`.

- [ ] **Step 1: Write failing parallel round tests**

```python
class BlockingAsyncAgent(ScriptedAsyncAgent):
    def __init__(
        self,
        name: str,
        started: list[str],
        gate: asyncio.Event,
        response: AgentResult,
    ) -> None:
        super().__init__(response)
        self.name = name
        self.started = started
        self.gate = gate

    async def run_async(self, user_input: str, *, run_context=None) -> AgentResult:
        self.inputs.append(user_input)
        self.started.append(self.name)
        await self.gate.wait()
        return self._responses.popleft()


class CancellableAsyncAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def run_async(self, user_input: str, *, run_context=None) -> AgentResult:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


async def wait_until(predicate) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not reached")


@pytest.mark.asyncio
async def test_parallel_round_starts_all_participants_and_keeps_declared_turn_order() -> None:
    gate = asyncio.Event()
    started: list[str] = []
    solver = BlockingAsyncAgent("Solver", started, gate, completed("proposal", 2))
    critic = BlockingAsyncAgent("Critic", started, gate, completed("review", 3))
    judge = ScriptedAsyncAgent(completed("verdict", 5))
    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    task = asyncio.create_task(debate.run_async("question"))
    await wait_until(lambda: len(started) == 2)
    gate.set()
    result = await task

    assert set(started) == {"Solver", "Critic"}
    assert [turn.role for turn in result.rounds[0].turns] == ["Solver", "Critic"]
    assert "[Solver]: proposal" not in critic.inputs[0]
    assert "[Critic]: review" not in solver.inputs[0]
    assert "[Solver]: proposal" in judge.inputs[0]
    assert "[Critic]: review" in judge.inputs[0]


@pytest.mark.asyncio
async def test_parallel_round_collects_all_turns_and_skips_judge_when_a_role_fails() -> None:
    solver = ScriptedAsyncAgent(completed("proposal", 2))
    critic = ScriptedAsyncAgent(failed("partial", "unavailable", 3))
    judge = ScriptedAsyncAgent(completed("must not run"))
    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(participant_execution="parallel"),
    )

    result = await debate.run_async("question")

    assert result.stop_reason == "participant_error"
    assert result.total_usage == {"total_tokens": 5}
    assert [turn.role for turn in result.rounds[0].turns] == ["Solver", "Critic"]
    assert judge.inputs == []
```

- [ ] **Step 2: Run the focused tests and verify they fail because parallel scheduling is not implemented**

Run: `python -m pytest tests/test_async_debate.py -k parallel -q`

Expected: the first test observes only one participant started, or the second test returns after the first failure rather than retaining both turns.

- [ ] **Step 3: Implement one immutable-context parallel round**

```python
async def _run_parallel_round(
    self,
    question: str,
    rounds: list[DebateRound],
    emitter: RunEventEmitter,
) -> tuple[list[DebateTurn], DebateTurn | None]:
    contexts = [
        self._build_context(role, question, rounds, [])
        for role in self.participants
    ]
    turns = await asyncio.gather(
        *[
            self._run_role(role, context, emitter.child())
            for role, context in zip(self.participants, contexts, strict=True)
        ]
    )
    failed_turn = next((turn for turn in turns if turn.stop_reason != "completed"), None)
    return turns, failed_turn
```

Call `_run_parallel_round()` only when `self.config.participant_execution == "parallel"`. Append the complete round before returning `participant_error`, accumulate every turn's usage in participant order, and never call the judge after a failed parallel round. Do not catch `asyncio.CancelledError` around `asyncio.gather()`.

- [ ] **Step 4: Add and run cancellation coverage**

```python
@pytest.mark.asyncio
async def test_parallel_async_debate_propagates_cancellation_to_participants() -> None:
    participant = CancellableAsyncAgent()
    debate = AsyncDebate([async_role("Solver", participant)])

    task = asyncio.create_task(debate.run_async("question"))
    await participant.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert participant.cancelled.is_set()
```

Run: `python -m pytest tests/test_async_debate.py -k "parallel or cancellation" -q`

Expected: all parallel, ordering, failure, and cancellation tests pass.

- [ ] **Step 5: Commit parallel round execution**

```bash
git add general_mini_agent/async_debate.py tests/test_async_debate.py
git commit -m "feat: add parallel async debate rounds"
```

### Task 4: Add Async Streaming with Role-Aware Multiplexing (`1.2.0` sequential; `1.3.0` parallel)

**Files:**
- Modify: `general_mini_agent/async_debate.py`
- Modify: `tests/test_async_debate.py`

**Interfaces:**
- Consumes: `AsyncAgent.run_stream_async(context) -> AsyncIterator[StreamEvent]`.
- Produces: `AsyncDebate.run_stream_async() -> AsyncIterator[AsyncDebateStreamEvent]`.

- [ ] **Step 1: Write failing streaming tests**

```python
class StreamingAsyncAgent(ScriptedAsyncAgent):
    def __init__(self, chunks: list[str], response: AgentResult) -> None:
        super().__init__(response)
        self.chunks = chunks

    async def run_stream_async(self, user_input: str):
        self.inputs.append(user_input)
        for chunk in self.chunks:
            await asyncio.sleep(0)
            yield {"type": "thought_chunk", "iteration": 0, "text": chunk}
        result = self._responses.popleft()
        yield {
            "type": "done",
            "content": result.content,
            "trace": result.trace,
            "usage": result.usage,
            "iterations": result.iterations,
            "stop_reason": result.stop_reason,
        }


class BlockingStreamingAsyncAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def run_stream_async(self, user_input: str):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        yield {"type": "done", "content": "", "trace": [], "usage": {}, "iterations": 0,
               "stop_reason": "completed"}


@pytest.mark.asyncio
async def test_sequential_async_stream_keeps_speaker_order_and_emits_one_terminal_result() -> None:
    solver = StreamingAsyncAgent(["solver"], completed("proposal", 2))
    critic = StreamingAsyncAgent(["critic"], completed("review", 3))
    judge = StreamingAsyncAgent(["judge"], completed("verdict", 5))
    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
    )

    events = [event async for event in debate.run_stream_async("question")]

    assert [event["role"] for event in events if event["type"] == "speaker"] == [
        "Solver", "Critic", "Judge"
    ]
    assert [event for event in events if event["type"] == "debate_done"][0]["verdict"] == "verdict"


# Add the remaining parallel stream tests only after Task 3 in the 1.3.0 change set.
@pytest.mark.asyncio
async def test_parallel_async_stream_identifies_interleaved_role_events_and_emits_one_terminal_result() -> None:
    solver = StreamingAsyncAgent(["solver-a", "solver-b"], completed("proposal", 2))
    critic = StreamingAsyncAgent(["critic-a", "critic-b"], completed("review", 3))
    judge = StreamingAsyncAgent(["judge"], completed("verdict", 5))
    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(participant_execution="parallel"),
    )

    events = [event async for event in debate.run_stream_async("question")]

    speakers = [event["role"] for event in events if event["type"] == "speaker"]
    role_events = [event for event in events if event["type"] == "agent_event"]
    done = [event for event in events if event["type"] == "debate_done"]
    assert speakers == ["Solver", "Critic", "Judge"]
    assert {event["role"] for event in role_events} == {"Solver", "Critic", "Judge"}
    assert len(done) == 1
    assert [turn.role for turn in done[0]["rounds"][0].turns] == ["Solver", "Critic"]
    assert done[0]["verdict"] == "verdict"


@pytest.mark.asyncio
async def test_async_stream_propagates_cancellation_without_terminal_event() -> None:
    participant = BlockingStreamingAsyncAgent()
    debate = AsyncDebate([async_role("Solver", participant)])
    stream = debate.run_stream_async("question")
    task = asyncio.create_task(anext(stream))
    await participant.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert participant.cancelled.is_set()
```

- [ ] **Step 2: Run the focused tests and verify they fail because the stream API is absent**

Run: `python -m pytest tests/test_async_debate.py -k stream -q`

Expected: failure reports that `AsyncDebate` has no `run_stream_async` method.

- [ ] **Step 3: Implement role pumping and stream multiplexing**

```python
async def _pump_stream_role(
    self,
    role: AsyncDebateRole,
    context: str,
    child_emitter: RunEventEmitter,
    events: asyncio.Queue[AsyncDebateAgentEvent],
) -> DebateTurn:
    done_event: StreamEvent | None = None
    async for event in role.agent.run_stream_async(context):
        await events.put({"type": "agent_event", "role": role.name, "event": event})
        if event["type"] == "done":
            done_event = event
    if done_event is None:
        return DebateTurn(
            role=role.name,
            content="",
            stop_reason="incomplete",
            error=f"role {role.name!r} stream ended without a done event",
            run_id=child_emitter.run_id,
        )
    return DebateTurn(
        role=role.name,
        content=done_event["content"],
        usage=done_event["usage"],
        stop_reason=done_event["stop_reason"],
        error=done_event.get("error"),
        run_id=child_emitter.run_id,
    )
```

For `1.2.0`, implement the sequential path by awaiting one `_pump_stream_role()` at a time and using its terminal turn to build the next participant context. For `1.3.0`, create one task per `_pump_stream_role()` and drain the queue while any task is unfinished. Once every task has completed, call `await asyncio.gather(*tasks)` to obtain turns in task creation order. Use `try`/`finally` to cancel and await unfinished tasks when the outer async generator is closed or cancelled. Yield `AsyncDebateDoneEvent` only after all round and judge tasks have settled normally.

- [ ] **Step 4: Run the focused streaming suite and verify it passes**

Run: `python -m pytest tests/test_async_debate.py -k stream -q`

Expected: streaming, role identification, terminal-event, and cancellation tests pass.

- [ ] **Step 5: Commit streaming support**

```bash
git add general_mini_agent/async_debate.py tests/test_async_debate.py
git commit -m "feat: stream async debate events"
```

### Task 5: Add Workflow Adapter and Public Exports (`1.2.0`; extend exports for parallel mode in `1.3.0`)

**Files:**
- Modify: `general_mini_agent/workflow_adapters.py`
- Modify: `general_mini_agent/__init__.py`
- Modify: `tests/test_workflow.py`
- Modify: `tests/test_async_debate.py`

**Interfaces:**
- Consumes: `AsyncDebate.run_async(question, run_context=..., event_sink=...) -> DebateResult`.
- Produces: `AsyncDebateNode` and stable top-level imports.

- [ ] **Step 1: Write failing adapter and namespace tests**

```python
def async_debate_with_completed_roles() -> AsyncDebate:
    return AsyncDebate(
        [async_role("Solver", ScriptedAsyncAgent(completed("proposal")))],
        judge=async_role("Judge", ScriptedAsyncAgent(completed("verdict"))),
    )


@pytest.mark.asyncio
async def test_async_debate_node_returns_verdict_and_keeps_event_sink_per_run() -> None:
    collector = EventCollector()
    debate = async_debate_with_completed_roles()
    node = AsyncDebateNode(debate=debate)
    result = await Workflow(root=node, event_sink=collector).run("question")

    assert result.stop_reason == "completed"
    assert result.value == "verdict"
    assert debate.event_sink is None
    assert any(event.type == "debate_started" for event in collector.snapshot())


def test_package_exports_async_debate_contracts() -> None:
    from general_mini_agent import AsyncDebate, AsyncDebateConfig, AsyncDebateNode, AsyncDebateRole

    assert all((AsyncDebate, AsyncDebateConfig, AsyncDebateNode, AsyncDebateRole))
```

- [ ] **Step 2: Run the focused tests and verify they fail because the adapter and exports are absent**

Run: `python -m pytest tests/test_workflow.py -k async_debate -q`

Expected: collection fails with missing `AsyncDebateNode`.

- [ ] **Step 3: Implement the adapter without mutable sink swapping**

```python
@dataclass
class AsyncDebateNode:
    debate: AsyncDebate

    async def run(
        self,
        value: JSONValue,
        *,
        run_context: RunContext,
        emitter: RunEventEmitter,
    ) -> NodeResult:
        if not isinstance(value, str):
            return NodeResult(
                value=None,
                run_id=run_context.run_id,
                error_code="invalid_node_input",
                error="AsyncDebateNode requires string input",
            )
        result = await self.debate.run_async(
            value,
            run_context=run_context,
            event_sink=emitter._sink,
        )
        if result.stop_reason == "completed":
            return NodeResult(value=result.verdict, run_id=result.run_id)
        return NodeResult(
            value=None,
            run_id=result.run_id,
            error_code=f"debate_{result.stop_reason}",
            error=f"AsyncDebate stopped with: {result.stop_reason}",
        )
```

For `1.2.0`, add imports and `__all__` entries for `AsyncDebate`, `AsyncDebateConfig`, `AsyncDebateRole`, `AsyncDebateStreamEvent`, `AsyncDebateRoundStartEvent`, `AsyncDebateSpeakerEvent`, `AsyncDebateAgentEvent`, `AsyncDebateDoneEvent`, `create_async_debate`, and `AsyncDebateNode`. In `1.3.0`, add `AsyncParticipantExecution` and the `participant_execution` parameter to the public factory.

- [ ] **Step 4: Run focused adapter and export tests**

Run: `python -m pytest tests/test_workflow.py -k async_debate -q; python -m pytest tests/test_async_debate.py -k exports -q`

Expected: all selected tests pass and `debate.event_sink` retains its original value.

- [ ] **Step 5: Commit workflow integration**

```bash
git add general_mini_agent/workflow_adapters.py general_mini_agent/__init__.py tests/test_workflow.py tests/test_async_debate.py
git commit -m "feat: add async debate workflow node"
```

### Task 6: Add Offline Demo, Documentation, and Release Metadata (`1.2.0`; amend for parallel mode in `1.3.0`)

**Files:**
- Create: `demo/async_debate_demo.py`
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml`
- Modify: `general_mini_agent/__init__.py`
- Modify: `tests/test_docs_contract.py`
- Modify: `tests/test_package_metadata.py`

**Interfaces:**
- Consumes: public `AsyncDebate` API and existing scripted/offline model patterns.
- Produces: runnable offline demonstration, current documentation, and `1.2.0` metadata.

- [ ] **Step 1: Write failing documentation and metadata tests**

```python
def test_readme_documents_async_debate() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "AsyncDebate" in readme
    assert "run_stream_async" in readme


# Add this assertion only to the 1.3.0 documentation change set.
def test_readme_documents_parallel_async_debate() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "participant_execution" in readme
    assert "parallel" in readme.lower()


def test_package_version_is_1_2_0() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["version"] == "1.2.0"
```

- [ ] **Step 2: Run the focused tests and verify they fail against the pre-release documentation**

Run: `python -m pytest tests/test_docs_contract.py tests/test_package_metadata.py -q`

Expected: failures identify the missing API documentation and old version number.

- [ ] **Step 3: Implement documentation and release artifacts**

For `1.2.0`, add an offline `asyncio.run(main())` demo that constructs three scripted `AsyncAgent` instances, creates a sequential `AsyncDebate`, and prints the verdict. Add this README example:

```python
import asyncio

from general_mini_agent import AsyncDebate, AsyncDebateConfig, AsyncDebateRole


async def main() -> None:
    debate = AsyncDebate(
        [
            AsyncDebateRole("Solver", solver, "Solve the problem.\n{role_context}"),
            AsyncDebateRole("Critic", critic, "Review the proposal.\n{role_context}"),
        ],
        judge=AsyncDebateRole("Judge", judge, "Produce the final answer.\n{role_context}"),
        config=AsyncDebateConfig(max_rounds=1),
    )
    result = await debate.run_async("What is the trade-off?")
    print(result.verdict)


asyncio.run(main())
```

For `1.2.0`, document the sequential same-round context behavior and move only the async Debate foundation item from `ROADMAP.md` to the completed release section. Retain parallel participants, async long-term memory, and async ChromaDB as future work. Add a `1.2.0` changelog section and update both `pyproject.toml` and `general_mini_agent.__version__` to `1.2.0`.

For `1.3.0`, change the demo and README to use `participant_execution="parallel"`, document the immutable prior-round context rule, move the parallel-participant item to completed work, add a `1.3.0` changelog section, and update both version locations to `1.3.0`.

- [ ] **Step 4: Run documentation, metadata, and demo checks**

Run: `python -m pytest tests/test_docs_contract.py tests/test_package_metadata.py -q; python demo/async_debate_demo.py`

Expected: contract tests pass and the demo prints a scripted final verdict without network access.

- [ ] **Step 5: Commit release-facing artifacts**

```bash
git add demo/async_debate_demo.py README.md ROADMAP.md CHANGELOG.md pyproject.toml general_mini_agent/__init__.py tests/test_docs_contract.py tests/test_package_metadata.py
git commit -m "docs: document async debate release"
```

### Task 7: Run the Full Release Verification (once for `1.2.0`, again for `1.3.0`)

**Files:**
- Modify: no source files unless a verification failure identifies a defect.

**Interfaces:**
- Consumes: the completed `1.2.0` or `1.3.0` source tree.
- Produces: evidence that the package, linting, compilation, tests, build artifact, and installed wheel are valid.

- [ ] **Step 1: Run all offline quality gates**

```bash
python -m ruff check general_mini_agent tests demo
python -m compileall -q general_mini_agent demo tests
python -m pytest tests -v
git diff --check
```

Expected: Ruff reports no violations, compileall exits zero, pytest has no failures, and diff check reports no whitespace errors.

- [ ] **Step 2: Build and validate the distribution**

```bash
rm -rf dist/
python -m build
python -m twine check dist/*
```

Expected: one source distribution and one wheel are created, and Twine validates both artifacts.

- [ ] **Step 3: Verify an installed wheel outside the repository**

```bash
python -m venv /tmp/gmaf-async-debate-smoke
/tmp/gmaf-async-debate-smoke/bin/python -m pip install dist/*.whl
cd /tmp
/tmp/gmaf-async-debate-smoke/bin/python -c "from importlib.metadata import version; from general_mini_agent import AsyncDebate, AsyncDebateNode; assert version('general-mini-agent-framework') == '1.2.0'; assert AsyncDebate and AsyncDebateNode"
```

Expected: the installed wheel imports `AsyncDebate` and `AsyncDebateNode`, reports version `1.2.0`, and does not import the checkout. Repeat this exact check after `1.3.0`, changing the expected version to `1.3.0` and additionally importing `AsyncParticipantExecution`.

- [ ] **Step 4: Commit any verification-only corrections, then create the release commit**

```bash
git add -A
git commit -m "release: prepare 1.2.0"
```

## Deferred Work

Do not add these capabilities to the `1.2.0` implementation:

- Async long-term memory protocol and ChromaDB adapter.
- Dynamic workflow nodes.
- Retry/backoff policy for model, tool, and memory boundaries.
- Rate limiting, OpenTelemetry, and process-level tool sandboxing.

Each is a separate subsystem with different public contracts and must receive its own approved design and implementation plan after this release.
