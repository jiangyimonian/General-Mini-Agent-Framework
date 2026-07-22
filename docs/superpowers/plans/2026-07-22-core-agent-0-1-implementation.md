# Core Agent 0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a publishable `0.1.0` Python package whose stable surface is a synchronous, single-Agent OpenAI-compatible tool-calling loop with isolated instance state and offline verification.

**Architecture:** `Agent` owns one `ToolRegistry`, the run-local message list, and a structured trace. `ChatModel` is a small synchronous protocol implemented by `LLM`; the concrete HTTP client only handles OpenAI-compatible requests. Existing memory, streaming, Debate, and HTML rendering modules remain importable but are explicitly experimental and do not participate in the stable `0.1.0` execution path.

**Tech Stack:** Python 3.12, `httpx`, `pytest`, `ruff`, GitHub Actions, Hatchling build backend.

## Global Constraints

- Support Python `>=3.12` and OpenAI Chat Completions-compatible model services only in `0.1.0`.
- The stable API is `Agent`, `AgentConfig`, `AgentResult`, `ChatModel`, `LLM`, `LLMConfig`, `Tool`, `ToolRegistry`, and `tool`.
- Preserve existing callable imports where practical; mark legacy streaming and memory entry points experimental instead of deleting them in this release.
- An Agent instance must never access another Agent instance's tools, messages, hooks, usage, or trace.
- Default tests must not require a real API key, network connection, ChromaDB, or model service.
- Do not place real API keys in code, docs, fixtures, CI, or generated artifacts.
- All new public interfaces use type annotations; optional dependencies remain lazily loaded.
- Do not add streaming, memory, multi-Agent, workflow, provider-adapter, permission, or HTML-rendering features to the synchronous core tasks.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `core/llm.py` | Public message type, `ChatModel` protocol, OpenAI-compatible `LLM`, sanitized request error. |
| `core/tools.py` | Tool schema construction, instance-local `ToolRegistry`, decorator metadata, structured tool execution outcome. |
| `core/agent.py` | Synchronous ReAct loop, run-local messages, structured trace, lifecycle and error outcomes. |
| `core/__init__.py` | Stable package exports and explicitly marked experimental compatibility exports. |
| `tests/conftest.py` | Offline `ScriptedChatModel` test double and reusable response helpers. |
| `tests/test_tools.py` | Tool schema, decorator metadata, registry isolation, argument and execution failures. |
| `tests/test_agent.py` | Synchronous lifecycle, tool isolation, trace, hooks, error, and iteration tests. |
| `tests/test_llm.py` | Response parsing, configuration validation, sanitized HTTP failure behavior. |
| `pyproject.toml` | Build metadata, dependencies, optional dev/demo/memory groups, pytest and Ruff configuration. |
| `.github/workflows/ci.yml` | Offline Python 3.12 test, compile, and lint checks. |
| `requirements.txt` | Compatibility installer that delegates to the package's runtime dependency set. |
| `README.md`, `PLAN.md`, `ROADMAP.md` | Published `0.1.0` contract, architecture and post-0.1 roadmap. |
| `demo/reasoning.py` | The supported minimal OpenAI-compatible tool-calling example. |

### Task 1: Define the stable synchronous model and result contracts

**Files:**
- Modify: `core/llm.py:1-181`
- Modify: `core/agent.py:16-33`
- Modify: `core/__init__.py:1-12`
- Create: `tests/conftest.py`
- Modify: `tests/test_llm.py:1-132`
- Modify: `tests/test_agent.py:1-207`

**Interfaces:**
- Consumes: existing `LLMResponse`, `ToolCall`, and `LLMConfig` dataclasses.
- Produces: `ChatModel`, `ModelRequestError`, `AgentStopReason`, `TraceEvent`, and the extended `AgentResult` used in Tasks 3-5.

- [ ] **Step 1: Bootstrap the test runner, then add failing protocol and result-contract tests**

If the environment does not already provide pytest, install the test runner before creating the first failing test:

```bash
python -m pip install "pytest>=8.0.0"
```

Task 4 moves this dependency into the checked-in `dev` extra; this bootstrap is only for starting the required red-green cycle in a fresh checkout.

Add `tests/conftest.py` with a real, deterministic test double rather than a mock:

```python
from collections.abc import Sequence
from typing import Any

from core.llm import LLMResponse


class ScriptedChatModel:
    def __init__(self, responses: Sequence[LLMResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools or []})
        return next(self._responses)
```

Add to `tests/test_agent.py`:

```python
from tests.conftest import ScriptedChatModel


def test_agent_accepts_structural_chat_model() -> None:
    model = ScriptedChatModel([LLMResponse(content="done", tool_calls=None)])

    result = Agent(llm=model, tools=[]).run("hello")

    assert result.content == "done"
    assert result.stop_reason == "completed"
    assert result.error is None
```

Add to `tests/test_llm.py`:

```python
def test_model_request_error_hides_authorization_value() -> None:
    error = ModelRequestError("request failed", status_code=401, endpoint="/chat/completions")

    assert error.status_code == 401
    assert "Authorization" not in str(error)
    assert "sk-" not in str(error)
```

- [ ] **Step 2: Run the new tests and verify the expected failure**

Run:

```bash
python -m pytest tests/test_agent.py::test_agent_accepts_structural_chat_model tests/test_llm.py::test_model_request_error_hides_authorization_value -v
```

Expected: collection or assertion failure because `ChatModel`, `AgentResult.stop_reason`, `AgentResult.error`, and `ModelRequestError` do not exist yet.

- [ ] **Step 3: Add the minimal public contracts**

At the top of `core/llm.py`, add the protocol and request error after the imports:

```python
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChatModel(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> "LLMResponse": ...


class ModelRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, endpoint: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint
```

Replace the `AgentResult` definition in `core/agent.py` with:

```python
from typing import Literal, NotRequired, TypedDict


AgentStopReason = Literal["completed", "max_iterations", "model_error"]


class TraceEvent(TypedDict):
    type: str
    iteration: int
    thought: NotRequired[str]
    tool: NotRequired[str]
    arguments: NotRequired[dict[str, Any]]
    observation: NotRequired[str]
    error_code: NotRequired[str]
    final_answer: NotRequired[str]
    message: NotRequired[str]


@dataclass
class AgentResult:
    content: str
    trace: list[TraceEvent] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    iterations: int = 0
    stop_reason: AgentStopReason = "completed"
    error: str | None = None
```

Change `Agent.__init__` to type its model as `ChatModel`, without adding a runtime `isinstance` check; structural test doubles are valid implementations:

```python
def __init__(self, llm: ChatModel, ...):
    self.llm = llm
```

Export `ChatModel`, `ModelRequestError`, `AgentStopReason`, and `TraceEvent` in `core/__init__.py` alongside the existing imports.

- [ ] **Step 4: Run the focused tests and the existing parsing tests**

Run:

```bash
python -m pytest tests/test_agent.py::test_agent_accepts_structural_chat_model tests/test_llm.py -v
```

Expected: PASS. Existing LLM parsing behavior remains unchanged.

- [ ] **Step 5: Commit the contract task**

```bash
git add core/llm.py core/agent.py core/__init__.py tests/conftest.py tests/test_llm.py tests/test_agent.py
git commit -m "feat: define core agent contracts"
```

### Task 2: Replace the global tool registry with instance-local tool ownership

**Files:**
- Modify: `core/tools.py:1-211`
- Modify: `core/agent.py:10-102`
- Modify: `tests/test_tools.py:1-123`
- Modify: `tests/test_agent.py:1-207`

**Interfaces:**
- Consumes: `Tool`, `ToolCall`, `TraceEvent`, and `ScriptedChatModel` from Task 1.
- Produces: `ToolRegistry(tools: Iterable[Tool | Callable] = ())`, `ToolRegistry.execute(name, arguments) -> ToolExecutionResult`, and decorator-attached `Tool` metadata consumed by `Agent`.

- [ ] **Step 1: Write failing isolation and execution-result tests**

Replace global-clear setup in `tests/test_tools.py` with independent registry construction. Add:

```python
def test_registries_with_same_tool_name_do_not_override_each_other() -> None:
    first = Tool(lambda: "first", name="status")
    second = Tool(lambda: "second", name="status")
    left = ToolRegistry([first])
    right = ToolRegistry([second])

    assert left.execute("status", {}).content == "first"
    assert right.execute("status", {}).content == "second"


def test_registry_reports_invalid_arguments_without_raising() -> None:
    registry = ToolRegistry([Tool(lambda value: value, name="echo")])

    outcome = registry.execute("echo", {})

    assert outcome.error_code == "invalid_arguments"
    assert "value" in outcome.content
```

Add to `tests/test_agent.py`:

```python
def test_agent_sends_only_its_own_tool_schema() -> None:
    left_tool = Tool(lambda: "left", name="left_only")
    right_tool = Tool(lambda: "right", name="right_only")
    left_model = ScriptedChatModel([LLMResponse(content="left", tool_calls=None)])
    right_model = ScriptedChatModel([LLMResponse(content="right", tool_calls=None)])

    Agent(llm=left_model, tools=[left_tool]).run("left")
    Agent(llm=right_model, tools=[right_tool]).run("right")

    assert [item["function"]["name"] for item in left_model.calls[0]["tools"]] == ["left_only"]
    assert [item["function"]["name"] for item in right_model.calls[0]["tools"]] == ["right_only"]
```

- [ ] **Step 2: Run the tests and verify the expected global-state failure**

Run:

```bash
python -m pytest tests/test_tools.py::test_registries_with_same_tool_name_do_not_override_each_other tests/test_tools.py::test_registry_reports_invalid_arguments_without_raising tests/test_agent.py::test_agent_sends_only_its_own_tool_schema -v
```

Expected: FAIL because `ToolRegistry` has no constructor or instance `execute` method and both Agents currently use the class-global schemas.

- [ ] **Step 3: Implement the local registry and decorator metadata**

Replace the class-global `ToolRegistry` with the following instance API. Keep `Tool.execute()` as the legacy string-returning convenience method, but route Agent execution through `ToolRegistry.execute()` so error codes are not lost:

```python
@dataclass(frozen=True)
class ToolExecutionResult:
    content: str
    error_code: str | None = None


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool | Callable[..., Any]] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for value in tools:
            self.register(value)

    def register(self, value: Tool | Callable[..., Any], **kwargs: Any) -> Tool:
        candidate = value if isinstance(value, Tool) else getattr(value, "__agent_tool__", None)
        item = candidate if isinstance(candidate, Tool) else Tool(value, **kwargs)
        if item.name in self._tools:
            raise ValueError(f"duplicate tool name: {item.name}")
        self._tools[item.name] = item
        return item

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [item.to_schema() for item in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        item = self.get(name)
        if item is None:
            return ToolExecutionResult(f"错误: 未找到工具 '{name}'", "unknown_tool")
        try:
            return ToolExecutionResult(str(item.func(**arguments)))
        except TypeError as exc:
            return ToolExecutionResult(f"工具参数错误: {exc}", "invalid_arguments")
        except Exception as exc:
            return ToolExecutionResult(f"工具执行错误: {type(exc).__name__}: {exc}", "execution_failed")
```

Use a normal overload-free decorator implementation that attaches metadata but does not register process-global state:

```python
def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Callable[..., Any]:
    def decorate(target: Callable[..., Any]) -> Callable[..., Any]:
        setattr(target, "__agent_tool__", Tool(target, name=name, description=description))
        return target

    return decorate(func) if func is not None else decorate
```

In `Agent.__init__`, replace class registration with:

```python
self.registry = ToolRegistry(tools or [])
self.tools = self.registry.list()
```

Remove all runtime imports of `ToolRegistry` inside `run()` and `run_stream()`. Replace their class calls with `self.registry.schemas()`, `self.registry.get()`, and `self.registry.execute()`.

- [ ] **Step 4: Extend the existing tool tests for decorator behavior**

Update old `ToolRegistry.get()` assertions to inspect the decorator metadata instead:

```python
@tool(description="计算两数之和")
def add(a: int, b: int) -> int:
    return a + b

registered = getattr(add, "__agent_tool__")
assert registered.name == "add"
assert registered.description == "计算两数之和"
```

Keep tests for `@tool` and `@tool()` forms. Add a duplicate-name test asserting that `ToolRegistry([Tool(...), Tool(...)])` raises `ValueError` rather than silently replacing a tool.

- [ ] **Step 5: Run all tool and focused Agent tests**

Run:

```bash
python -m pytest tests/test_tools.py tests/test_agent.py::test_agent_sends_only_its_own_tool_schema -v
```

Expected: PASS. No test should call `ToolRegistry.clear()` or read class-level state.

- [ ] **Step 6: Commit the registry task**

```bash
git add core/tools.py core/agent.py tests/test_tools.py tests/test_agent.py
git commit -m "fix: isolate tools per agent instance"
```

### Task 3: Make the synchronous Agent lifecycle explicit and fully testable

**Files:**
- Modify: `core/agent.py:1-311`
- Modify: `tests/test_agent.py:1-207`
- Modify: `core/__init__.py:1-12`

**Interfaces:**
- Consumes: `ChatModel`, `ModelRequestError`, `ToolRegistry.execute()`, `ToolExecutionResult`, `TraceEvent`, and `AgentResult` from Tasks 1-2.
- Produces: a stable synchronous `Agent.run(user_input: str) -> AgentResult` with `completed`, `max_iterations`, and `model_error` stop reasons.

- [ ] **Step 1: Add failing lifecycle tests**

Add these tests to `tests/test_agent.py`:

```python
def test_unknown_tool_is_recorded_as_a_structured_error() -> None:
    model = ScriptedChatModel([
        LLMResponse(content="try", tool_calls=[ToolCall("c1", "missing", {})]),
        LLMResponse(content="done", tool_calls=None),
    ])

    result = Agent(llm=model, tools=[]).run("question")

    assert result.stop_reason == "completed"
    assert result.trace[0]["type"] == "tool_call"
    assert result.trace[0]["error_code"] == "unknown_tool"
    assert "未找到工具" in result.trace[0]["observation"]


def test_tool_exception_is_recorded_and_model_can_finish() -> None:
    def explode() -> str:
        raise RuntimeError("boom")

    model = ScriptedChatModel([
        LLMResponse(content="call", tool_calls=[ToolCall("c1", "explode", {})]),
        LLMResponse(content="recovered", tool_calls=None),
    ])

    result = Agent(llm=model, tools=[Tool(explode)]).run("question")

    assert result.content == "recovered"
    assert result.trace[0]["error_code"] == "execution_failed"


def test_model_error_returns_trace_and_does_not_expose_secret() -> None:
    class FailingModel:
        def chat(self, messages, *, tools=None):
            raise ModelRequestError("request failed", status_code=503, endpoint="/chat/completions")

    result = Agent(llm=FailingModel(), tools=[]).run("question")

    assert result.stop_reason == "model_error"
    assert result.error == "model request failed"
    assert result.trace[-1]["type"] == "model_error"
```

Also update the existing maximum-iteration test to assert `result.stop_reason == "max_iterations"`, and update direct-answer tests to assert the final trace event has `type == "final"`.

- [ ] **Step 2: Run the tests and verify the expected lifecycle failures**

Run:

```bash
python -m pytest tests/test_agent.py::test_unknown_tool_is_recorded_as_a_structured_error tests/test_agent.py::test_tool_exception_is_recorded_and_model_can_finish tests/test_agent.py::test_model_error_returns_trace_and_does_not_expose_secret -v
```

Expected: FAIL because current traces have no `type` or `error_code`, and `Agent.run()` propagates model request errors.

- [ ] **Step 3: Implement one synchronous execution path**

Refactor `Agent.run()` so it builds its message list locally for every call and routes every tool call through `self.registry.execute()`. The core loop must use this shape:

```python
try:
    response = self.llm.chat(messages, tools=self.registry.schemas())
except ModelRequestError:
    trace.append({"type": "model_error", "iteration": iteration, "message": "model request failed"})
    return AgentResult(
        content="",
        trace=trace,
        usage=total_usage,
        iterations=iteration,
        stop_reason="model_error",
        error="model request failed",
    )

for call in response.tool_calls or []:
    outcome = self.registry.execute(call.name, call.arguments)
    event: TraceEvent = {
        "type": "tool_call",
        "iteration": iteration,
        "thought": response.content or "",
        "tool": call.name,
        "arguments": call.arguments,
        "observation": outcome.content,
    }
    if outcome.error_code is not None:
        event["error_code"] = outcome.error_code
    trace.append(event)
```

For a text-only response, append `{"type": "final", "iteration": iteration, "final_answer": clean_content}` and return an `AgentResult` with `stop_reason="completed"`. For iteration exhaustion, append `{"type": "max_iterations", "iteration": self.max_iterations, "message": "maximum iterations reached"}` and return `stop_reason="max_iterations"`.

Retain the `memory` and `run_stream` parameters only as experimental compatibility paths in this release. Remove the unconditional `SlidingWindowMemory()` construction and the top-level import from `core.agent`; if a supplied legacy memory object has `get_context()`, append only that returned list. Do not mention either capability in the stable README quickstart.

- [ ] **Step 4: Verify hooks and message continuity**

Add a regression test that checks the second scripted model call contains the prior assistant tool-call message and its tool result:

```python
def test_second_model_call_receives_tool_result() -> None:
    model = ScriptedChatModel([
        LLMResponse(content="use add", tool_calls=[ToolCall("c1", "add", {"a": 2, "b": 3})]),
        LLMResponse(content="5", tool_calls=None),
    ])
    result = Agent(llm=model, tools=[Tool(lambda a, b: a + b, name="add")]).run("2+3")

    assert result.content == "5"
    assert model.calls[1]["messages"][-1] == {"role": "tool", "tool_call_id": "c1", "content": "5"}
```

Run:

```bash
python -m pytest tests/test_agent.py -v
```

Expected: PASS, including existing direct-answer, multi-tool, hook, empty-response, usage, and maximum-iteration tests updated for the new trace fields.

- [ ] **Step 5: Commit the Agent lifecycle task**

```bash
git add core/agent.py core/__init__.py tests/test_agent.py
git commit -m "feat: stabilize synchronous agent lifecycle"
```

### Task 4: Package the core and add repeatable local and CI verification

**Files:**
- Create: `pyproject.toml`
- Create: `.github/workflows/ci.yml`
- Modify: `requirements.txt:1-5`
- Modify: `.gitignore:1-637`
- Modify: `tests/test_llm.py:1-132`

**Interfaces:**
- Consumes: the offline test suite from Tasks 1-3.
- Produces: `pip install .`, `pip install ".[dev]"`, `python -m pytest tests -v`, `python -m compileall -q core demo tests`, and `ruff check core tests demo` as repeatable verification commands.

- [ ] **Step 1: Add failing packaging metadata tests**

Create `tests/test_package_metadata.py`:

```python
from pathlib import Path


def test_pyproject_declares_core_runtime_and_dev_extra() -> None:
    content = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'name = "general-mini-agent-framework"' in content
    assert '"httpx>=0.27.0"' in content
    assert 'dev = [' in content
    assert '"pytest>=8.0.0"' in content
    assert '"ruff>=' in content
```

- [ ] **Step 2: Run the test and verify the missing metadata failure**

Run:

```bash
python -m pytest tests/test_package_metadata.py -v
```

Expected: FAIL with `FileNotFoundError` because `pyproject.toml` does not exist.

- [ ] **Step 3: Add package, tool, and CI configuration**

Create `pyproject.toml` with exactly these sections:

```toml
[build-system]
requires = ["hatchling>=1.25.0"]
build-backend = "hatchling.build"

[project]
name = "general-mini-agent-framework"
version = "0.1.0"
description = "A lightweight, composable Python Agent core for OpenAI-compatible tool calling."
readme = "README.md"
requires-python = ">=3.12"
dependencies = ["httpx>=0.27.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0.0", "ruff>=0.6.0"]
demo = ["python-dotenv>=1.0.0"]
memory = ["chromadb>=0.5.0"]

[tool.hatch.build.targets.wheel]
packages = ["core"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]
```

Replace `requirements.txt` with the runtime compatibility dependency only:

```text
httpx>=0.27.0
```

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install --upgrade pip
      - run: python -m pip install ".[dev]"
      - run: python -m pytest tests -v
      - run: python -m compileall -q core demo tests
      - run: ruff check core tests demo
```

Add `.ruff_cache/`, `.pytest_cache/`, `*.egg-info/`, and `dist/` to `.gitignore` if absent. Do not add a lock file without choosing a repository-wide dependency tool.

In `core/llm.py`, replace raw final request failures with `ModelRequestError` while preserving retryable status handling:

```python
except httpx.HTTPStatusError as exc:
    if exc.response.status_code not in (429, 502, 503, 504):
        raise ModelRequestError(
            "model request returned an HTTP error",
            status_code=exc.response.status_code,
            endpoint="/chat/completions",
        ) from exc
```

After retry exhaustion, raise `ModelRequestError("model request failed after retries", endpoint="/chat/completions") from last_error`. Never include `exc.request.headers`, response bodies, or the configured API key in the new error text.

- [ ] **Step 4: Install the local development extra and run packaging checks**

Run:

```bash
python -m pip install ".[dev]"
python -m pytest tests/test_package_metadata.py tests/test_llm.py -v
python -m compileall -q core demo tests
ruff check core tests demo
```

Expected: all commands exit `0`. Address Ruff findings by editing code or using existing compatible style; do not suppress rules globally.

- [ ] **Step 5: Commit the packaging task**

```bash
git add pyproject.toml requirements.txt .gitignore .github/workflows/ci.yml core/llm.py tests/test_llm.py tests/test_package_metadata.py
git commit -m "build: add package metadata and CI"
```

### Task 5: Publish the 0.1.0 contract and preserve experimental modules honestly

**Files:**
- Modify: `README.md:1-200`
- Modify: `PLAN.md:1-105`
- Modify: `ROADMAP.md:1-96`
- Modify: `core/__init__.py:1-12`
- Modify: `demo/reasoning.py:1-150`
- Modify: `demo/reasoning_stream.py:1-100`
- Modify: `demo/chat.py:1-170`
- Modify: `demo/debate_demo.py:1-120`
- Modify: `demo/export_demo.py:1-100`

**Interfaces:**
- Consumes: the stable API and commands from Tasks 1-4.
- Produces: documentation and examples whose published claims match `0.1.0`, while retaining non-core code behind explicit experimental labels.

- [ ] **Step 1: Add failing documentation-contract tests**

Create `tests/test_docs_contract.py`:

```python
from pathlib import Path


def test_readme_describes_only_the_stable_core_as_current_capability() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "单 Agent 同步工具调用" in readme
    assert "OpenAI 兼容" in readme
    assert "实验性" in readme
    assert "流式、多 Agent、记忆和 HTML 轨迹导出不属于 0.1.0 稳定 API" in readme
```

- [ ] **Step 2: Run the test and verify the documentation mismatch**

Run:

```bash
python -m pytest tests/test_docs_contract.py -v
```

Expected: FAIL because the current README presents streaming, memory, Debate, and HTML export as current framework capabilities without an experimental boundary.

- [ ] **Step 3: Rewrite the published contract and examples**

Rewrite `README.md` around this exact capability statement:

```markdown
General Mini Agent Framework 是一个轻量、可组合的 Python Agent 内核。`0.1.0` 稳定支持 OpenAI 兼容模型上的单 Agent 同步工具调用，并提供实例隔离和结构化运行轨迹。

## 0.1.0 稳定能力

- OpenAI 兼容 Chat Completions 客户端
- Python 函数到 JSON Schema 的工具定义
- 单 Agent 同步 ReAct 循环
- Agent 实例级工具隔离
- 结构化执行结果、轨迹和明确的停止原因

## 实验性模块

流式、多 Agent、记忆和 HTML 轨迹导出不属于 0.1.0 稳定 API。它们保留在仓库中用于实验，不保证接口或行为兼容性。
```

Use only this stable quickstart shape, including a real `Tool` object or `@tool` function and no memory/streaming options:

```python
from core import Agent, LLM, LLMConfig, tool


@tool(description="计算两个整数的和")
def add(a: int, b: int) -> int:
    return a + b


agent = Agent(
    llm=LLM(LLMConfig(api_key="<your-api-key>", model="<your-model>")),
    tools=[add],
)
result = agent.run("计算 17 + 25")
print(result.content)
```

Document installation as `python -m pip install .` for runtime and `python -m pip install ".[dev]"` for contributors. State the three CI commands exactly as defined in Task 4.

Update `PLAN.md` to point to the `0.1.0` module boundaries from the approved scope specification. Update `ROADMAP.md` so `0.2` is streaming, `0.3` is memory, `0.4` is multi-Agent, and workflow/observability follows; do not list these as implemented.

Keep non-core demos but add the first line after their module docstring:

```python
# Experimental example: not covered by the 0.1.0 stable API.
```

Leave `demo/reasoning.py` as the supported example and remove any streaming, memory, or Debate claims from it. In `core/__init__.py`, retain compatibility imports for `StreamChunk`, `SlidingWindowMemory`, and `LongTermMemory`, but place them below a comment reading `# Experimental compatibility exports; not part of the 0.1.0 stable API.`

- [ ] **Step 4: Run the full verification suite**

Run:

```bash
python -m pytest tests -v
python -m compileall -q core demo tests
ruff check core tests demo
git diff --check
```

Expected: all commands exit `0`; the test suite performs no network calls and no test uses a real key.

- [ ] **Step 5: Commit the documentation task**

```bash
git add README.md PLAN.md ROADMAP.md core/__init__.py demo tests/test_docs_contract.py
git commit -m "docs: define the 0.1 core contract"
```

## Plan Self-Review

### Spec coverage

- OpenAI-compatible client, timeout, sanitized errors: Tasks 1 and 4.
- Function tools, JSON Schema, isolated registration, tool errors: Task 2.
- Synchronous single-Agent ReAct loop, result, trace, iteration limits: Task 3.
- Stable public API, offline testing, installation, CI: Tasks 1, 4, and 5.
- Exclusion and honest treatment of streaming, memory, multi-Agent, workflow, providers, and HTML rendering: Tasks 3 and 5.
- Ordered post-0.1 releases: Task 5.

### Placeholder scan

No task contains placeholders, unspecified validation, or unnamed APIs. Each production change names the target files, public contract, tests, and verification command.

### Type consistency

`ChatModel.chat()` consistently returns `LLMResponse`. `ToolRegistry.execute()` consistently returns `ToolExecutionResult`. `Agent.run()` consistently returns `AgentResult`, whose `trace` uses `TraceEvent` and whose `stop_reason` is an `AgentStopReason` literal.
