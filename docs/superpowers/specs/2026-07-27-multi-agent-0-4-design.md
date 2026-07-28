# General Mini Agent Framework 0.4.0 Multi-Agent Design

## Status

Approved for implementation on 2026-07-27.

## Goal

Stabilize a small, deterministic multi-Agent collaboration loop in which an ordered set of
participants can work for multiple rounds and one separate Judge produces the final verdict. Each
run must be isolated, observable, and consistent across synchronous and streaming execution.

## Scope

`0.4.0` stabilizes:

- ordered, configurable participant roles;
- a Judge configured separately from ordinary participants;
- effective `max_rounds` and optional explicit convergence checks;
- run-local shared context and repeat-run isolation;
- structured rounds, usage totals, stop reasons, and role failures;
- equivalent orchestration semantics for `run()` and `run_stream()`;
- an updated Debate Demo and HTML trace adapter.

The release does not add parallel execution, async APIs, voting, dynamic role creation, conditional
graphs, nested debates, automatic long-term-memory access, or provider-specific model behavior.

## Module Boundary

`core/debate.py` owns role configuration, turn ordering, shared run context, convergence decisions,
Judge invocation, usage aggregation, and Debate result/event types. It coordinates existing `Agent`
instances but does not execute tools, call model clients directly, or mutate Agent configuration.

`core/agent.py` remains responsible for each role's ReAct loop. `core/trace.py` only renders completed
Debate records and does not infer orchestration state. No generic workflow engine is introduced.

## Public Contracts

`DebateRole` contains a non-empty unique `name`, an `Agent`, a prompt template, and optional
`role_context`. Participant order is the sequence supplied to `Debate`; the Judge is supplied
separately and cannot share a participant name.

`DebateConfig` contains:

- `max_rounds: int = 3`, validated as at least one;
- `convergence_check: Callable[[DebateRound], bool] | None = None`.

No numeric confidence threshold is retained because an ordinary text response does not provide a
reliable normalized confidence value. Without a convergence callback, all configured participant
rounds run. A callback sees the completed current round and may only request an early transition to
the Judge.

The stable constructor is conceptually:

```python
Debate(
    participants: Sequence[DebateRole],
    *,
    judge: DebateRole | None = None,
    config: DebateConfig | None = None,
)
```

At least one participant is required. `create_debate(solver, critic, judge, ...)` remains as the
small three-role convenience factory and maps those Agents to the stable constructor.

## Result Model

`DebateTurn` records the role name, content, usage, Agent stop reason, and optional sanitized error.
`DebateRound` records a one-based round number and participant turns in execution order.

`DebateResult` contains:

- `verdict: str`, empty when no verdict was produced;
- `rounds: list[DebateRound]`;
- `judge_turn: DebateTurn | None`;
- `total_usage: dict[str, int]`;
- `stop_reason: DebateStopReason`;
- `converged: bool`;
- `error: str | None`.

`DebateStopReason` supports `completed`, `no_judge`, `participant_error`, and `judge_error`. A normal
Judge verdict is `completed` whether it follows convergence or exhaustion of `max_rounds`;
`converged` records which transition occurred.

## Execution Flow

Every call creates fresh local rounds, context messages, and usage totals. The `Debate` instance
stores configuration only and never stores conversation history from a run.

For each round:

1. Run every participant once in configured order.
2. Give each participant the original question plus all completed participant turns from this run,
   including earlier turns in the current round.
3. Record the turn and aggregate integer usage fields.
4. Stop immediately if a participant does not complete successfully.
5. After the complete round, call `convergence_check` when configured.

After convergence or `max_rounds`, invoke the Judge exactly once. The Judge receives the original
question and all completed participant rounds. The Judge is never run as an ordinary participant and
its output is stored separately as `judge_turn` and `verdict`.

If no Judge is configured, return `no_judge` after participant execution with the full rounds and an
empty verdict. The framework does not silently promote the last participant response to a verdict.

## Prompt and State Isolation

Role prompts are formatted for the current call and are never written back into `DebateRole` or
`Agent`. Context is rendered from structured run-local records. A second call on the same `Debate`
instance must produce the same input sequence as a call on a fresh equivalent instance.

The Debate layer does not automatically pass conversation-memory or long-term-memory queries. Any
memory configured inside an individual Agent retains that Agent's existing behavior and ownership;
Debate itself introduces no shared persistent state.

## Failure Semantics

An `AgentResult` whose `stop_reason` is not `completed` becomes a failed `DebateTurn`. Participant
failure returns `participant_error` before later participants or the Judge run. Judge failure returns
`judge_error` while preserving all completed rounds and Judge usage.

Expected Agent failures use the Agent's sanitized error text. Unexpected programming exceptions are
not converted into successful Debate results and continue to propagate. Convergence callback
exceptions also propagate because they indicate caller code defects, not model-service failures.

Usage aggregation includes every attempted role that returned an `AgentResult`, including a failed
participant or Judge. Only integer usage values are aggregated.

## Streaming Semantics

`run_stream()` follows the same participant rounds, convergence transition, single Judge call,
failure handling, and run-local isolation as `run()`. It emits Debate-level round and speaker events
around the existing Agent stream events, then emits one terminal Debate event carrying the same
fields as `DebateResult`.

The stream updates shared context only after a role emits its terminal `done` event. Closing a stream
early leaves no state on the `Debate` instance. A role's non-`completed` `done` event terminates the
Debate with the corresponding role error and does not invoke later roles.

## Compatibility

`core.debate` is experimental in `0.3.1`, so `0.4.0` may replace its loose dictionary records with
typed records. The `create_debate()` convenience factory remains available. Demo and trace code are
updated in the same release; no compatibility adapter for direct access to `shared_context` is
provided because persistent shared context is the state-leak bug being removed.

Stable Debate contracts are exported from `core.__init__` only after implementation and verification.

## Minimal Testing Strategy

Use scripted Agents or lightweight Agent fakes; no test contacts a real model service. Focus on:

- participant ordering and one Judge call after multiple rounds;
- early convergence after a complete round;
- `max_rounds` validation and enforcement;
- no-Judge behavior;
- participant and Judge terminal failures;
- usage aggregation;
- repeated synchronous and streaming run isolation;
- sync/stream orchestration equivalence;
- stable exports, Demo, and trace rendering.

Run focused tests while implementing each task and one full verification at release:

```bash
python -m pytest tests -v
python -m compileall -q core demo tests
ruff check core tests demo
git diff --check
```

## Documentation and Release

- update the Debate Demo to show at least two participant rounds and one final Judge verdict;
- document the stable multi-Agent boundary and non-goals in README and PLAN;
- remove completed `0.4` items from ROADMAP;
- bump the package version to `0.4.0` only after final verification passes.

## Acceptance Criteria

`0.4.0` is ready when the Judge is never treated as a participant, `max_rounds` and explicit
convergence both control real execution, one Debate instance can be reused without cross-run state,
role failures stop at a deterministic boundary, synchronous and streaming paths share the same
observable ordering and terminal meaning, the Demo and trace renderer consume the stable result
types, and all final verification commands pass.
