# Multi-Agent 0.4.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize isolated, deterministic multi-Agent rounds with ordered participants and one separate final Judge.

**Architecture:** `core/debate.py` owns typed Debate contracts and orchestration while delegating every role execution to the existing `Agent` API. Each call builds run-local context and records; synchronous and streaming paths expose the same participant ordering, convergence transition, Judge boundary, and terminal failures.

**Tech Stack:** Python 3.12, dataclasses, typed dictionaries and literals, pytest, Ruff.

## Global Constraints

- Keep participants ordered and configure the Judge separately.
- Require at least one participant, unique non-empty role names, and `max_rounds >= 1`.
- Invoke the Judge exactly once after convergence or maximum rounds.
- Keep all Debate history local to one `run()` or `run_stream()` call.
- Treat non-`completed` Agent results as terminal role failures.
- Keep synchronous and streaming orchestration semantics equivalent.
- Add no async API, parallelism, voting, workflow graph, dynamic roles, or automatic memory access.
- Run only focused tests per task; run the full suite once in the release task.

---

### Task 1: Design and Implementation Plan

**Files:**
- Create: `docs/superpowers/specs/2026-07-27-multi-agent-0-4-design.md`
- Create: `docs/superpowers/plans/2026-07-27-multi-agent-0-4-implementation.md`

**Interfaces:**
- Produces: approved `0.4.0` scope, contracts, execution semantics, and task boundaries.

- [x] **Step 1: Review the design for scope and contract consistency**

Run:

```powershell
rg -n "TBD|TODO|implement later|fill in details" docs/superpowers/specs/2026-07-27-multi-agent-0-4-design.md
```

Expected: no matches.

- [x] **Step 2: Check documentation whitespace**

Run: `git diff --check`

Expected: no output.

- [ ] **Step 3: Commit the design and plan as separately traceable documentation commits**

```powershell
git add docs/superpowers/specs/2026-07-27-multi-agent-0-4-design.md
git commit -m "docs: design stable multi-agent orchestration for 0.4.0"
git add docs/superpowers/plans/2026-07-27-multi-agent-0-4-implementation.md
git commit -m "docs: plan stable multi-agent orchestration for 0.4.0"
```

### Task 2: Stable Debate Contracts and Isolated Sync Runs

**Files:**
- Create: `tests/test_debate.py`
- Modify: `core/debate.py`

**Interfaces:**
- Produces: `DebateStopReason`, `ConvergenceCheck`, `DebateRole`, `DebateConfig`, `DebateTurn`, `DebateRound`, and `DebateResult`.
- Produces: `Debate(participants, *, judge=None, config=None)` and isolated `Debate.run(question)`.

- [x] **Step 1: Write focused failing contract and isolation tests**

Create a small `ScriptedAgent` in `tests/test_debate.py` that records inputs and returns queued
`AgentResult` values. Add tests asserting invalid rounds and duplicate role names are rejected, one
participant plus one Judge produces typed records, and two runs on one Debate do not include the
previous question in their prompts.

- [x] **Step 2: Run the tests and confirm the old constructor/record shape fails**

Run: `python -m pytest tests/test_debate.py -v`

Expected: FAIL because the stable participant constructor and typed records do not exist.

- [x] **Step 3: Implement contracts and one-run-local synchronous orchestration**

Replace persistent `shared_context` with local records. Validate role names, participant count, Judge
name uniqueness, and `max_rounds`. Render role context from the question and completed turns without
mutating role or Agent state. Aggregate integer usage values into `DebateResult.total_usage`.

- [x] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_debate.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/debate.py tests/test_debate.py
git commit -m "feat: isolate stable multi-agent debate runs"
```

### Task 3: Effective Multi-Round and Convergence Semantics

**Files:**
- Modify: `tests/test_debate.py`
- Modify: `core/debate.py`

**Interfaces:**
- Consumes: Task 2 typed contracts and local synchronous runner.
- Produces: effective `max_rounds`, `ConvergenceCheck`, and one post-round Judge transition.
- Preserves: `create_debate(solver, critic, judge, *, max_rounds=3, ...)` convenience API.

- [x] **Step 1: Add two failing orchestration tests**

Test that two participants each run for all three configured rounds before the Judge runs once. Test
that a callback returning true for round one transitions to the Judge after that complete round and
sets `result.converged` without running round two.

- [x] **Step 2: Run only the two new tests and verify their expected failures**

Run: `python -m pytest tests/test_debate.py -k "multiple_rounds or convergence" -v`

Expected: FAIL because the old Judge-in-role-loop behavior cannot satisfy the ordering.

- [x] **Step 3: Implement complete-round convergence and the compatibility factory**

Loop participants for `max_rounds`, evaluate the callback only after a full round, then invoke the
separate Judge once. Keep Solver/Critic prompts in `create_debate()` but build ordinary participant
roles and a separate Judge role.

- [x] **Step 4: Run focused Debate tests**

Run: `python -m pytest tests/test_debate.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/debate.py tests/test_debate.py
git commit -m "feat: enforce multi-agent rounds and convergence"
```

### Task 4: Role Failures and Streaming Equivalence

**Files:**
- Modify: `tests/test_debate.py`
- Modify: `core/debate.py`

**Interfaces:**
- Produces: `participant_error`, `judge_error`, and `no_judge` Debate terminal results.
- Produces: typed Debate stream events and `Debate.run_stream(question)` with sync-equivalent order.

- [x] **Step 1: Add minimal failure and stream tests**

Add one parameterized test for participant/Judge non-`completed` results, one no-Judge test, and one
stream test asserting two runs are isolated and emit a single terminal event after the same role
order as synchronous execution.

- [x] **Step 2: Run the new test subset and verify failures**

Run: `python -m pytest tests/test_debate.py -k "error or no_judge or stream" -v`

Expected: FAIL because stable Debate failures and stream termination are not implemented.

- [x] **Step 3: Implement terminal boundaries and streaming orchestration**

Convert returned Agent failures into failed turns and Debate stop reasons, retain returned usage, and
skip all later roles. Mirror round/convergence/Judge decisions in streaming, adding shared context
only after each role's terminal `done` event. Do not retain stream state on the Debate instance.

- [x] **Step 4: Run focused Debate tests**

Run: `python -m pytest tests/test_debate.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/debate.py tests/test_debate.py
git commit -m "feat: align multi-agent failure and stream behavior"
```

### Task 5: Stable Exports, Demo, and Trace Rendering

**Files:**
- Modify: `core/__init__.py`
- Modify: `core/trace.py`
- Modify: `demo/debate_demo.py`
- Modify: `demo/export_demo.py`
- Modify: `tests/test_debate.py`
- Modify: `tests/test_trace.py`
- Modify: `tests/test_docs_contract.py`

**Interfaces:**
- Exports: all stable Debate contracts from `core`.
- Consumes: typed `DebateRound`, `DebateTurn`, and separate `judge_turn` in Demo and trace output.

- [x] **Step 1: Add failing export and trace adapter tests**

Assert stable Debate types import from `core`. Construct one typed result and assert its participant
and Judge content are present in rendered HTML.

- [x] **Step 2: Run the narrow adapter tests and verify failures**

Run: `python -m pytest tests/test_debate.py tests/test_trace.py tests/test_docs_contract.py -v`

Expected: FAIL on missing exports and old dictionary rendering.

- [x] **Step 3: Update exports, Demo, and trace conversion**

Export stable contracts, convert dataclasses to JSON-safe dictionaries inside `debate_to_html()`, and
update both demos to use participant roles plus a separate Judge and typed round access.

- [x] **Step 4: Run the same adapter tests**

Run: `python -m pytest tests/test_debate.py tests/test_trace.py tests/test_docs_contract.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/__init__.py core/trace.py demo/debate_demo.py demo/export_demo.py tests/test_debate.py tests/test_trace.py tests/test_docs_contract.py
git commit -m "feat: publish stable multi-agent interfaces"
```

### Task 6: Documentation and 0.4.0 Release Verification

**Files:**
- Modify: `README.md`
- Modify: `PLAN.md`
- Modify: `ROADMAP.md`
- Modify: `pyproject.toml`
- Modify: `tests/test_package_metadata.py`
- Modify: `tests/test_docs_contract.py`
- Modify: `docs/superpowers/plans/2026-07-27-multi-agent-0-4-implementation.md`

**Interfaces:**
- Produces: package version `0.4.0` and documentation matching the verified stable API.

- [x] **Step 1: Update release contract tests first**

Change metadata and docs assertions from `0.3.1` to `0.4.0` and require the stable Debate boundary.

- [x] **Step 2: Run release contract tests and verify failure**

Run: `python -m pytest tests/test_package_metadata.py tests/test_docs_contract.py -v`

Expected: FAIL until metadata and documentation are updated.

- [x] **Step 3: Update release metadata and documentation**

Set `pyproject.toml` to `0.4.0`, describe current multi-Agent behavior in README and PLAN, and remove
the completed `0.4` section from ROADMAP without claiming deferred orchestration features.

- [x] **Step 4: Run the single full release verification**

```powershell
python -m pytest tests -v
python -m compileall -q core demo tests
ruff check core tests demo
git diff --check
```

Expected: all tests PASS and all other commands exit zero with no errors.

- [ ] **Step 5: Commit the release**

```powershell
git add README.md PLAN.md ROADMAP.md pyproject.toml tests/test_package_metadata.py tests/test_docs_contract.py docs/superpowers/plans/2026-07-27-multi-agent-0-4-implementation.md
git commit -m "feat: release stable multi-agent orchestration in 0.4.0"
```
