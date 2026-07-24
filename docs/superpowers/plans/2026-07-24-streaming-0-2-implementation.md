# General Mini Agent Framework 0.2.0 Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize synchronous-generator model and Agent streaming as the public `0.2.0` API with deterministic chunks, events, tool calls, errors, usage, and terminal states.

**Architecture:** Keep `Agent.run()` and `Agent.run_stream()` as separate control loops. Add explicit stream types in `core/llm.py`, parse OpenAI-compatible SSE strictly at the model boundary, and use a private indexed accumulator plus small event/usage helpers in `core/agent.py`; reuse the existing Agent-local `ToolRegistry` for sequential execution.

**Tech Stack:** Python 3.12, `dataclasses`, `TypedDict`, `Literal`, synchronous generators, `httpx.MockTransport`, pytest, Ruff.

## Global Constraints

- Stabilize synchronous-generator streaming only; do not add async APIs.
- Keep the stable `0.1.0` synchronous `Agent.run()` behavior and public call signatures compatible.
- Execute multiple tool calls sequentially in ascending tool-call index order.
- Keep Agent state, tools, stream buffers, context, and usage isolated per invocation and instance.
- Retry transport and retryable HTTP failures only before the first yielded stream chunk.
- Treat malformed SSE data and invalid tool-call metadata as sanitized protocol errors.
- Keep all automated tests offline; no test may read an API key or perform a network request.
- Keep memory, multi-Agent collaboration, and HTML trace export experimental.
- Commit each completed task locally so its changes remain independently traceable.
- Run focused RED/GREEN tests within Tasks 1-5 and defer the complete pytest, compileall, and Ruff
  verification matrix to Task 6.
- Do not push commits unless the user explicitly requests a remote update.

## Execution Override

On 2026-07-24 the user approved continuous execution without per-task review pauses. Each task now
ends with a local commit after its focused verification; Task 6 performs the complete regression
suite before the release commit.

## File Map

- `core/llm.py`: public model stream protocol, chunk types, exception classification, SSE parsing, and retry boundary.
- `core/agent.py`: public Agent event types, terminal flow, indexed tool-call reconstruction, trace, usage, and hooks.
- `core/__init__.py`: stable `0.2.0` public exports.
- `tests/conftest.py`: reusable scripted synchronous and streaming model fixtures.
- `tests/test_llm.py`: offline stream parser, error, retry, and usage fixtures.
- `tests/test_agent.py`: event ordering, terminal paths, tools, context, trace, usage, hooks, and isolation.
- `tests/test_package_metadata.py`: package version contract.
- `tests/test_docs_contract.py`: stable versus experimental documentation contract.
- `demo/reasoning_stream.py`: supported synchronous streaming example.
- `README.md`, `PLAN.md`, `ROADMAP.md`: current capability, architecture boundary, and next-version scope.
- `pyproject.toml`: package version `0.2.0`.

---

### Task 1: Add Public Model Streaming Types and Error Classification

**Files:**
- Modify: `core/llm.py`
- Modify: `core/__init__.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: existing `ChatModel`, `ModelRequestError`, and experimental `StreamChunk`.
- Produces: `ToolCallDelta(index, id, name, arguments)`, the new `StreamChunk.tool_calls`, `StreamingChatModel`, and `ModelRequestError.error_code`.

- [x] **Step 1: Write failing public-contract tests**

Add imports and tests that pin the new types and preserve old exception construction:

```python
from collections.abc import Iterator

from core import StreamChunk, StreamingChatModel, ToolCallDelta
from core.llm import LLMResponse


def test_model_request_error_defaults_to_request_error_code() -> None:
    error = ModelRequestError("request failed")
    assert error.error_code == "model_request_error"


def test_model_request_error_accepts_protocol_error_code() -> None:
    error = ModelRequestError(
        "invalid model stream",
        error_code="stream_protocol_error",
    )
    assert error.error_code == "stream_protocol_error"


def test_stream_chunk_exposes_indexed_tool_call_deltas() -> None:
    chunk = StreamChunk(
        content="thinking",
        tool_calls=[
            ToolCallDelta(index=1, id="call_2", name="add", arguments='{"a":'),
        ],
        finish_reason="tool_calls",
        usage={"total_tokens": 4},
    )

    assert chunk.tool_calls[0].index == 1
    assert chunk.tool_calls[0].arguments == '{"a":'


def test_streaming_chat_model_runtime_protocol_requires_both_paths() -> None:
    class CompleteModel:
        def chat(self, messages, *, tools=None) -> LLMResponse:
            return LLMResponse(content="ok", tool_calls=None)

        def chat_stream(self, messages, *, tools=None) -> Iterator[StreamChunk]:
            yield StreamChunk(content="ok", finish_reason="stop")

    assert isinstance(CompleteModel(), StreamingChatModel)
```

- [x] **Step 2: Run the contract tests to verify RED**

Run:

```powershell
python -m pytest tests/test_llm.py -k "error_code or indexed_tool_call or runtime_protocol" -v
```

Expected: collection or assertions fail because `ToolCallDelta`, `StreamingChatModel`, `StreamChunk.tool_calls`, and `ModelRequestError.error_code` do not exist.

- [x] **Step 3: Implement the public model contracts**

In `core/llm.py`, import `Iterator` from `collections.abc`, add the optional error code without changing existing callers, and define the stream protocol and dataclasses:

```python
from collections.abc import Iterator
from typing import Any, Literal, Protocol, runtime_checkable

ModelErrorCode = Literal["model_request_error", "stream_protocol_error"]


class ModelRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        endpoint: str = "",
        error_code: ModelErrorCode = "model_request_error",
    ) -> None:
        super().__init__(self._sanitize(message))
        self.status_code = status_code
        self.endpoint = endpoint
        self.error_code = error_code


@dataclass(frozen=True)
class ToolCallDelta:
    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class StreamChunk:
    content: str = ""
    tool_calls: list[ToolCallDelta] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)


@runtime_checkable
class StreamingChatModel(ChatModel, Protocol):
    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamChunk]: ...
```

Place `StreamingChatModel` after `StreamChunk` so the runtime protocol has concrete annotations. During Tasks 1-3, retain the three existing legacy stream fields on `StreamChunk` so the pre-existing Agent tests stay green; Task 4 removes them in the same change that migrates all Agent fixtures.

Export `ToolCallDelta`, `StreamChunk`, and `StreamingChatModel` from `core/__init__.py`. Keep the memory exports under the experimental compatibility comment.

- [x] **Step 4: Run focused and full regression tests**

Run:

```powershell
python -m pytest tests/test_llm.py tests/test_agent.py -v
python -m pytest tests -v
```

Expected: all tests pass, including existing synchronous Agent tests.

- [x] **Step 5: Stop for review**

Run `git diff --check` and summarize the new public types and compatibility behavior. Suggested commit message after approval: `feat: define stable streaming contracts`.

---

### Task 2: Parse OpenAI-Compatible SSE Strictly and Preserve Retry Safety

**Files:**
- Modify: `core/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `ToolCallDelta`, `StreamChunk`, `ModelRequestError.error_code`, and `LLMConfig.max_retries` from Task 1.
- Produces: `LLM.chat_stream(...) -> Iterator[StreamChunk]` with strict `data:` parsing, indexed tool deltas, usage-only chunks, and a no-duplication retry boundary.

- [ ] **Step 1: Add an offline stream-response helper and parser tests**

Add a helper using `httpx.MockTransport`:

```python
def make_streaming_llm(payload: bytes, *, max_retries: int = 1) -> LLM:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, request=request)

    llm = LLM(
        LLMConfig(
            api_key="test-key",
            base_url="https://example.test/v1",
            max_retries=max_retries,
        )
    )
    llm._client.close()
    llm._client = httpx.Client(
        base_url=llm.config.base_url,
        transport=httpx.MockTransport(handler),
    )
    return llm
```

Cover multiple deltas in one payload, interleaved indexes, optional SSE spacing, comments, usage-only payloads, and `[DONE]`:

```python
def test_chat_stream_parses_interleaved_tool_calls_and_usage() -> None:
    llm = make_streaming_llm(
        b": keep-alive\n\n"
        b'data:{"choices":[{"delta":{"tool_calls":['
        b'{"index":1,"id":"c2","function":{"name":"multiply","arguments":"{\\"a\\":"}},'
        b'{"index":0,"id":"c1","function":{"name":"add","arguments":"{\\"a\\":"}}'
        b']},"finish_reason":null}]}\n\n'
        b'data: {"choices":[{"delta":{"tool_calls":['
        b'{"index":0,"function":{"arguments":"1}"}},'
        b'{"index":1,"function":{"arguments":"2}"}}'
        b']},"finish_reason":"tool_calls"}]}\n\n'
        b'data: {"choices":[],"usage":{"prompt_tokens":3,"total_tokens":5}}\n\n'
        b"data: [DONE]\n\n"
    )

    chunks = list(llm.chat_stream([]))

    assert [delta.index for delta in chunks[0].tool_calls] == [1, 0]
    assert chunks[1].finish_reason == "tool_calls"
    assert chunks[2].usage == {"prompt_tokens": 3, "total_tokens": 5}
```

Also assert that the outgoing JSON body contains:

```python
request_body = json.loads(request.content)
assert request_body["stream_options"] == {"include_usage": True}
```

- [ ] **Step 2: Add malformed-data and retry-boundary tests**

Pin malformed JSON as a non-retryable protocol error:

```python
def test_chat_stream_rejects_non_json_data_without_retrying() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"data: not-json\n\n", request=request)

    llm = LLM(LLMConfig(api_key="test-key", max_retries=3))
    llm._client.close()
    llm._client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(ModelRequestError) as exc_info:
        list(llm.chat_stream([]))

    assert exc_info.value.error_code == "stream_protocol_error"
    assert str(exc_info.value) == "invalid JSON in model stream"
    assert calls == 1
```

Use a custom byte stream to prove a transport failure after output is not retried:

```python
class FailingAfterFirstChunk(httpx.SyncByteStream):
    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"first"},"finish_reason":null}]}\n\n'
        raise httpx.ReadError("sensitive transport detail")


def test_chat_stream_does_not_retry_after_yielding_output() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=FailingAfterFirstChunk(), request=request)

    llm = LLM(LLMConfig(api_key="test-key", max_retries=3))
    llm._client.close()
    llm._client = httpx.Client(transport=httpx.MockTransport(handler))
    stream = llm.chat_stream([])

    assert next(stream).content == "first"
    with pytest.raises(ModelRequestError, match="model streaming request failed"):
        next(stream)
    assert calls == 1
```

- [ ] **Step 3: Run new tests to verify RED**

Run:

```powershell
python -m pytest tests/test_llm.py -k "interleaved or non_json or after_yielding" -v
```

Expected: failures show missing indexed deltas, silently skipped malformed JSON, missing streamed usage, or an incorrect retry.

- [ ] **Step 4: Implement strict SSE parsing**

Make `tools` keyword-only in the concrete method so it matches `StreamingChatModel`:

```python
def chat_stream(
    self,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> Iterator[StreamChunk]:
```

Set `"stream_options": {"include_usage": True}` in the request body. Replace the line parser with this behavior:

```python
for line in resp.iter_lines():
    if not line or line.startswith(":") or not line.startswith("data:"):
        continue
    data_str = line[5:]
    if data_str.startswith(" "):
        data_str = data_str[1:]
    if data_str == "[DONE]":
        break
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError as exc:
        raise ModelRequestError(
            "invalid JSON in model stream",
            endpoint="/chat/completions",
            error_code="stream_protocol_error",
        ) from exc

    chunk = self._parse_stream_chunk(data)
    if chunk is not None:
        yielded_chunk = True
        yield chunk
```

Ensure `except ModelRequestError: raise` appears before the `httpx` handlers so protocol errors never enter retry logic. Parse usage-only chunks and every delta:

```python
def _parse_stream_chunk(self, data: dict[str, Any]) -> StreamChunk | None:
    usage = data.get("usage") or {}
    choices = data.get("choices") or []
    if not choices:
        return StreamChunk(usage=usage) if usage else None

    choice = choices[0]
    delta = choice.get("delta") or {}
    tool_calls: list[ToolCallDelta] = []
    for raw_call in delta.get("tool_calls") or []:
        index = raw_call.get("index")
        if not isinstance(index, int):
            raise ModelRequestError(
                "model stream tool call is missing an integer index",
                endpoint="/chat/completions",
                error_code="stream_protocol_error",
            )
        function = raw_call.get("function") or {}
        tool_calls.append(
            ToolCallDelta(
                index=index,
                id=raw_call.get("id") or "",
                name=function.get("name") or "",
                arguments=function.get("arguments") or "",
            )
        )

    return StreamChunk(
        content=delta.get("content") or "",
        tool_calls=tool_calls,
        finish_reason=choice.get("finish_reason") or "",
        usage=usage,
    )
```

Retain the existing HTTP status sanitization. Catch `httpx.HTTPError` after the yielded-chunk check and convert it to `ModelRequestError("model streaming request failed")` without embedding the original response or request text.

- [ ] **Step 5: Run focused and full regression tests**

Run:

```powershell
python -m pytest tests/test_llm.py -v
python -m pytest tests -v
```

Expected: all tests pass and every transport request is handled by an offline mock.

- [ ] **Step 6: Stop for review**

Run `git diff --check` and report parser behavior plus retry counts. Suggested commit message after approval: `feat: harden streaming SSE parsing`.

---

### Task 3: Stabilize Agent Event Types and Terminal Paths

**Files:**
- Modify: `core/agent.py`
- Modify: `core/__init__.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `StreamingChatModel`, `StreamChunk`, and classified `ModelRequestError` from Tasks 1-2.
- Produces: exported `StreamEvent`, seven literal event shapes, and deterministic `done.stop_reason` values.

- [ ] **Step 1: Add a reusable scripted streaming model**

Extend `tests/conftest.py` with a model that records deep-copied calls and can return chunks or raise an exception per request:

```python
class ScriptedStreamingChatModel(ScriptedChatModel):
    def __init__(
        self,
        responses: Sequence[LLMResponse],
        streams: Sequence[Sequence[StreamChunk] | Exception],
    ) -> None:
        super().__init__(responses)
        self._streams = list(streams)
        self.stream_calls: list[
            tuple[list[dict[str, Any]], list[dict[str, Any]] | None]
        ] = []

    def chat_stream(self, messages, *, tools=None):
        self.stream_calls.append((deepcopy(messages), deepcopy(tools)))
        if not self._streams:
            raise AssertionError("ScriptedStreamingChatModel has no remaining streams")
        response = self._streams.pop(0)
        if isinstance(response, Exception):
            raise response
        yield from response
```

Import `StreamChunk` in the fixture module.

- [ ] **Step 2: Write failing event and terminal-flow tests**

Add table-driven assertions for the four terminal categories:

```python
@pytest.mark.parametrize("finish_reason", ["length", "content_filter", "future_reason", ""])
def test_run_stream_maps_non_terminal_finishes_to_incomplete(finish_reason: str) -> None:
    model = ScriptedStreamingChatModel(
        [],
        [[StreamChunk(content="partial", finish_reason=finish_reason)]],
    )

    events = list(Agent(llm=model, tools=[]).run_stream("question"))

    assert [event["type"] for event in events] == [
        "iteration_start",
        "thought_chunk",
        "done",
    ]
    assert events[-1]["stop_reason"] == "incomplete"
    assert events[-1]["content"] == "partial"
    assert events[-1]["finish_reason"] == finish_reason
```

Add normal and error sequences:

```python
def test_run_stream_completed_event_keys_and_order() -> None:
    model = ScriptedStreamingChatModel(
        [],
        [[StreamChunk(content="answer", finish_reason="stop")]],
    )

    events = list(Agent(llm=model, tools=[]).run_stream("question"))

    assert [event["type"] for event in events] == [
        "iteration_start",
        "thought_chunk",
        "final_answer",
        "done",
    ]
    assert events[1] == {"type": "thought_chunk", "iteration": 0, "text": "answer"}
    assert events[-1]["stop_reason"] == "completed"
    assert events[-1]["iterations"] == 1


def test_run_stream_converts_model_error_to_terminal_events() -> None:
    error = ModelRequestError(
        "invalid model stream sk-secret",
        status_code=502,
        error_code="stream_protocol_error",
    )
    model = ScriptedStreamingChatModel([], [error])

    events = list(Agent(llm=model, tools=[]).run_stream("question"))

    assert [event["type"] for event in events] == [
        "iteration_start",
        "model_error",
        "done",
    ]
    assert events[1]["error_code"] == "stream_protocol_error"
    assert events[1]["status_code"] == 502
    assert "sk-secret" not in str(events)
    assert events[-1]["stop_reason"] == "model_error"
```

Also assert exactly one `done` for completed, incomplete, model-error, and max-iteration flows, and assert `on_final` is called only for `stop`.

- [ ] **Step 3: Run terminal tests to verify RED**

Run:

```powershell
python -m pytest tests/test_agent.py -k "run_stream and (completed or incomplete or model_error or done)" -v
```

Expected: failures show missing `iteration`, missing stop reasons, uncaught model errors, and incorrect final handling.

- [ ] **Step 4: Define strict event types**

In `core/agent.py`, define dedicated `TypedDict` classes with literal `type` values. Use `NotRequired` only for the documented optional keys:

```python
AgentStopReason = Literal["completed", "max_iterations", "model_error", "incomplete"]


class IterationStartEvent(TypedDict):
    type: Literal["iteration_start"]
    iteration: int


class ThoughtChunkEvent(TypedDict):
    type: Literal["thought_chunk"]
    iteration: int
    text: str


class ToolCallEvent(TypedDict):
    type: Literal["tool_call"]
    iteration: int
    index: int
    id: str
    name: str
    arguments: dict[str, Any] | None
    raw_arguments: str
    error_code: NotRequired[str]


class ObservationEvent(TypedDict):
    type: Literal["observation"]
    iteration: int
    index: int
    tool_call_id: str
    name: str
    text: str
    error_code: NotRequired[str]


class FinalAnswerEvent(TypedDict):
    type: Literal["final_answer"]
    iteration: int
    text: str


class ModelErrorEvent(TypedDict):
    type: Literal["model_error"]
    iteration: int
    error_code: str
    error: str
    status_code: NotRequired[int]


class DoneEvent(TypedDict):
    type: Literal["done"]
    content: str
    trace: list[TraceEvent]
    usage: dict[str, int]
    iterations: int
    stop_reason: AgentStopReason
    finish_reason: NotRequired[str]
    error: NotRequired[str]


StreamEvent = (
    IterationStartEvent
    | ThoughtChunkEvent
    | ToolCallEvent
    | ObservationEvent
    | FinalAnswerEvent
    | ModelErrorEvent
    | DoneEvent
)
```

Export `StreamEvent` from `core/__init__.py` and annotate `run_stream()` as
`Iterator[StreamEvent]`. Task 4 fills the already-defined tool event shapes without changing the
public type union.

- [ ] **Step 5: Implement deterministic non-tool terminal flow**

Track the latest non-empty `finish_reason` for each request. Do not break the Agent chunk loop when
that reason appears: continue consuming until `LLM.chat_stream()` ends so a usage-only chunk after
the final choice is retained. Emit `thought_chunk` with `iteration`; after the stream closes:

```python
if chunk.finish_reason:
    finish_reason = chunk.finish_reason
```

Then select the terminal path:

```python
if finish_reason == "stop":
    clean = thought.replace("[FINAL]", "").replace("Final Answer:", "").strip()
    final_event: FinalAnswerEvent = {
        "type": "final_answer",
        "iteration": iteration,
        "text": clean,
    }
    yield final_event
    trace.append({
        "type": "final_answer",
        "iteration": iteration,
        "thought": thought,
        "final_answer": clean,
    })
    self._call_hook("on_final", trace[-1])
    yield self._done_event(
        content=clean,
        trace=trace,
        usage=total_usage,
        iterations=iteration + 1,
        stop_reason="completed",
        finish_reason=finish_reason,
    )
    return

if finish_reason != "tool_calls":
    trace.append({
        "type": "incomplete",
        "iteration": iteration,
        "thought": thought,
        "finish_reason": finish_reason,
    })
    yield self._done_event(
        content=thought,
        trace=trace,
        usage=total_usage,
        iterations=iteration + 1,
        stop_reason="incomplete",
        finish_reason=finish_reason,
    )
    return
```

Catch `ModelRequestError` around stream iteration, append a sanitized `model_error` trace entry,
emit `model_error`, then emit `done(model_error)` and return. Add this private done helper so every
terminal path uses the same required fields and optional-key rule:

```python
@staticmethod
def _done_event(
    *,
    content: str,
    trace: list[TraceEvent],
    usage: dict[str, int],
    iterations: int,
    stop_reason: AgentStopReason,
    finish_reason: str | None = None,
    error: str | None = None,
) -> DoneEvent:
    event: DoneEvent = {
        "type": "done",
        "content": content,
        "trace": trace,
        "usage": usage,
        "iterations": iterations,
        "stop_reason": stop_reason,
    }
    if finish_reason is not None:
        event["finish_reason"] = finish_reason
    if error is not None:
        event["error"] = error
    return event
```

Keep the existing tool branch operational through its legacy fields until Task 4 performs the indexed migration.

- [ ] **Step 6: Run focused and full regression tests**

Run:

```powershell
python -m pytest tests/test_agent.py -v
python -m pytest tests -v
```

Expected: all tests pass and every non-cancelled tested path contains exactly one final `done` event.

- [ ] **Step 7: Stop for review**

Run `git diff --check` and report each terminal sequence. Suggested commit message after approval: `feat: stabilize streaming agent events`.

---

### Task 4: Reconstruct and Execute Multiple Streamed Tool Calls

**Files:**
- Modify: `core/llm.py`
- Modify: `core/agent.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: indexed `ToolCallDelta` chunks and terminal events from Tasks 1-3.
- Produces: private `_ToolCallAccumulator`, populated `ToolCallEvent` and `ObservationEvent` values, one assistant context message per model tool turn, and ordered tool result messages.

- [ ] **Step 1: Migrate existing Agent stream fixtures to indexed deltas**

Replace every legacy stream constructor in `tests/test_agent.py` with the stable shape:

```python
StreamChunk(
    tool_calls=[
        ToolCallDelta(
            index=0,
            id="call_1",
            name="add",
            arguments='{"a": 1, "b": 2}',
        )
    ],
    finish_reason="tool_calls",
)
```

Import `ToolCallDelta` from `core.llm`. Remove the three legacy fields from `StreamChunk` in `core/llm.py` only after all fixtures and Agent code in this task use `tool_calls`.

- [ ] **Step 2: Write failing multi-tool and context tests**

Use interleaved fragments and indexes arriving out of order:

```python
def test_run_stream_reconstructs_multiple_tools_and_executes_by_index() -> None:
    calls: list[str] = []

    @tool
    def first(value: int) -> str:
        calls.append("first")
        return str(value)

    @tool
    def second(value: int) -> str:
        calls.append("second")
        return str(value)

    model = ScriptedStreamingChatModel([], [
        [
            StreamChunk(tool_calls=[
                ToolCallDelta(1, "c2", "second", '{"value":'),
                ToolCallDelta(0, "c1", "first", '{"value":'),
            ]),
            StreamChunk(tool_calls=[
                ToolCallDelta(0, arguments="1}"),
                ToolCallDelta(1, arguments="2}"),
            ], finish_reason="tool_calls"),
        ],
        [StreamChunk(content="done", finish_reason="stop")],
    ])

    events = list(Agent(llm=model, tools=[first, second]).run_stream("question"))

    assert calls == ["first", "second"]
    assert [event["name"] for event in events if event["type"] == "tool_call"] == [
        "first",
        "second",
    ]
    second_request = model.stream_calls[1][0]
    assistant = second_request[-3]
    assert assistant["role"] == "assistant"
    assert [call["id"] for call in assistant["tool_calls"]] == ["c1", "c2"]
    assert [message["tool_call_id"] for message in second_request[-2:]] == ["c1", "c2"]
```

- [ ] **Step 3: Write failing recovery and protocol-error tests**

Verify malformed JSON is returned to the model without executing the tool:

```python
def test_run_stream_returns_invalid_json_to_model_for_correction() -> None:
    executions = 0

    @tool
    def add(a: int, b: int) -> int:
        nonlocal executions
        executions += 1
        return a + b

    model = ScriptedStreamingChatModel([], [
        [StreamChunk(
            tool_calls=[ToolCallDelta(0, "c1", "add", '{"a":1')],
            finish_reason="tool_calls",
        )],
        [StreamChunk(content="corrected", finish_reason="stop")],
    ])

    events = list(Agent(llm=model, tools=[add]).run_stream("question"))
    tool_event = next(event for event in events if event["type"] == "tool_call")
    observation = next(event for event in events if event["type"] == "observation")

    assert executions == 0
    assert tool_event["arguments"] is None
    assert tool_event["raw_arguments"] == '{"a":1'
    assert tool_event["error_code"] == "invalid_arguments"
    assert observation["error_code"] == "invalid_arguments"
    assert model.stream_calls[1][0][-1]["tool_call_id"] == "c1"
```

Parameterize missing id, missing name, conflicting ids, conflicting names, and `finish_reason="tool_calls"` with no calls. Assert each path emits `model_error(error_code="stream_protocol_error")`, then `done(model_error)`, and executes zero tools.

- [ ] **Step 4: Run tool tests to verify RED**

Run:

```powershell
python -m pytest tests/test_agent.py -k "reconstructs_multiple or invalid_json or protocol" -v
```

Expected: failures expose the one-tool index assumption, `{}` fallback for malformed JSON, repeated assistant messages, and absent metadata validation.

- [ ] **Step 5: Implement the private accumulator**

Add private records in `core/agent.py`:

```python
@dataclass
class _AccumulatedToolCall:
    index: int
    id: str = ""
    name: str = ""
    argument_parts: list[str] = field(default_factory=list)

    @property
    def raw_arguments(self) -> str:
        return "".join(self.argument_parts)


class _ToolCallAccumulator:
    def __init__(self) -> None:
        self._calls: dict[int, _AccumulatedToolCall] = {}

    def add(self, delta: ToolCallDelta) -> None:
        call = self._calls.setdefault(delta.index, _AccumulatedToolCall(delta.index))
        if delta.id:
            if call.id and call.id != delta.id:
                raise self._protocol_error(delta.index, "id")
            call.id = delta.id
        if delta.name:
            if call.name and call.name != delta.name:
                raise self._protocol_error(delta.index, "name")
            call.name = delta.name
        if delta.arguments:
            call.argument_parts.append(delta.arguments)

    def finalize(self) -> list[_AccumulatedToolCall]:
        calls = [self._calls[index] for index in sorted(self._calls)]
        if not calls:
            raise ModelRequestError(
                "model ended with tool_calls but supplied no calls",
                error_code="stream_protocol_error",
            )
        for call in calls:
            if not call.id or not call.name:
                raise ModelRequestError(
                    f"model tool call at index {call.index} is missing identity metadata",
                    error_code="stream_protocol_error",
                )
        return calls

    @staticmethod
    def _protocol_error(index: int, field_name: str) -> ModelRequestError:
        return ModelRequestError(
            f"model tool call at index {index} has conflicting {field_name}",
            error_code="stream_protocol_error",
        )
```

The accumulator lives inside each `run_stream()` invocation, never on `Agent`.

- [ ] **Step 6: Implement ordered execution with the stable event types**

Import `ToolExecutionResult` from `core.tools`. After `finish_reason == "tool_calls"`, finalize all
calls before executing any call. Route a `ModelRequestError` raised by `add()` or `finalize()`
through the Task 3 `model_error -> done(model_error)` helper before any tool executes. Append one
assistant message whose `tool_calls` contain each raw argument string. For every finalized call,
parse JSON and require a dictionary:

```python
try:
    parsed = json.loads(call.raw_arguments)
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must be a JSON object")
    arguments: dict[str, Any] | None = parsed
    execution = self.registry.execute(call.name, parsed)
except (json.JSONDecodeError, ValueError) as exc:
    arguments = None
    execution = ToolExecutionResult(
        content=f"invalid arguments for tool '{call.name}': {exc}",
        error_code="invalid_arguments",
    )
```

Construct `tool_call` and `observation` events with every required identity field, attach `execution.error_code` to both when present, append one trace entry, invoke `on_tool_call` once, and append one tool message. Continue to the next model iteration after all calls complete.

- [ ] **Step 7: Run focused and full regression tests**

Run:

```powershell
python -m pytest tests/test_agent.py -v
python -m pytest tests -v
```

Expected: all tests pass; multi-tool execution and context order are deterministic; synchronous tests remain unchanged.

- [ ] **Step 8: Stop for review**

Run `git diff --check` and report call ordering, invalid-argument recovery, and protocol failure coverage. Suggested commit message after approval: `feat: support streamed multi-tool calls`.

---

### Task 5: Align Usage, Trace, Hooks, and Invocation Isolation

**Files:**
- Modify: `core/agent.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: stable events and indexed tool execution from Tasks 3-4.
- Produces: once-per-request usage accumulation, complete streaming trace metadata, hook parity, and per-run state isolation.

- [ ] **Step 1: Write failing usage tests**

Prove repeated cumulative usage chunks are counted once per request and separate requests are added:

```python
def test_run_stream_counts_latest_usage_once_per_request() -> None:
    @tool
    def noop() -> str:
        return "ok"

    model = ScriptedStreamingChatModel([], [
        [
            StreamChunk(usage={"prompt_tokens": 3, "total_tokens": 3}),
            StreamChunk(
                tool_calls=[ToolCallDelta(0, "c1", "noop", "{}")],
                finish_reason="tool_calls",
            ),
            StreamChunk(
                usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
            ),
        ],
        [
            StreamChunk(content="done", finish_reason="stop"),
            StreamChunk(
                usage={"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}
            ),
        ],
    ])

    done = list(Agent(llm=model, tools=[noop]).run_stream("question"))[-1]

    assert done["usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
    }
```

Add a model-error-after-usage test and require the latest usage seen before failure to appear in `done`.

- [ ] **Step 2: Write failing trace, hook, and isolation tests**

Assert tool traces contain `iteration`, `tool_call_id`, `index`, `tool`, parsed or raw arguments, observation, and error code. Assert incomplete and model-error paths add explicit trace entries. Assert `on_tool_call` receives one trace event for malformed JSON, unknown tools, parameter validation failure, and tool exceptions; assert `on_final` is absent for incomplete and model-error paths.

Run the same Agent twice with separate scripted streams and assert the second `done` contains no content, usage, calls, or trace from the first run:

```python
def test_run_stream_state_is_isolated_between_invocations() -> None:
    model = ScriptedStreamingChatModel([], [
        [StreamChunk(content="first", finish_reason="stop", usage={"total_tokens": 2})],
        [StreamChunk(content="second", finish_reason="stop", usage={"total_tokens": 3})],
    ])
    agent = Agent(llm=model, tools=[])

    first_done = list(agent.run_stream("one"))[-1]
    second_done = list(agent.run_stream("two"))[-1]

    assert first_done["content"] == "first"
    assert second_done["content"] == "second"
    assert second_done["usage"] == {"total_tokens": 3}
    assert len(second_done["trace"]) == 1
```

- [ ] **Step 3: Run cross-cutting tests to verify RED**

Run:

```powershell
python -m pytest tests/test_agent.py -k "usage or trace or hook or isolated" -v
```

Expected: cumulative usage is double-counted or incomplete metadata assertions fail.

- [ ] **Step 4: Accumulate the latest usage once per model request**

Create a request-local dictionary at the start of each iteration:

```python
request_usage: dict[str, int] = {}

for chunk in self.llm.chat_stream(messages, tools=self.registry.schemas()):
    for key, value in chunk.usage.items():
        if isinstance(value, int):
            request_usage[key] = value
    # emit content and collect tool deltas

self._accumulate_usage(total_usage, request_usage)
```

In the `ModelRequestError` handler, call `_accumulate_usage(total_usage, request_usage)` before creating terminal events. Do not add usage to totals inside the chunk loop.

- [ ] **Step 5: Complete trace and hook metadata**

Extend `TraceEvent` with optional `index`, `tool_call_id`, `raw_arguments`, and `finish_reason`. Build tool traces from the same local values used by public events, and use one private helper for optional error-code insertion:

```python
@staticmethod
def _with_error_code(event: dict[str, Any], error_code: str | None) -> None:
    if error_code is not None:
        event["error_code"] = error_code
```

Call `on_tool_call` only after the complete trace event has been appended. Call `on_final` only after the completed final trace exists. Keep hook exceptions unchanged from the existing synchronous behavior.

- [ ] **Step 6: Run focused and full regression tests**

Run:

```powershell
python -m pytest tests/test_agent.py -v
python -m pytest tests -v
python -m compileall -q core demo tests
```

Expected: all tests pass and `compileall` exits with no output.

- [ ] **Step 7: Stop for review**

Run `git diff --check` and report usage totals, hook counts, trace fields, and isolation assertions. Suggested commit message after approval: `test: complete streaming behavior coverage`.

---

### Task 6: Publish the 0.2.0 Contract, Demo, and Documentation

**Files:**
- Modify: `pyproject.toml`
- Modify: `core/__init__.py`
- Modify: `demo/reasoning_stream.py`
- Modify: `README.md`
- Modify: `PLAN.md`
- Modify: `ROADMAP.md`
- Modify: `tests/test_package_metadata.py`
- Modify: `tests/test_docs_contract.py`

**Interfaces:**
- Consumes: all stable stream APIs and behavior from Tasks 1-5.
- Produces: package version `0.2.0`, accurate stable exports, a supported stream demo, and documentation that names memory as the `0.3` focus.

- [ ] **Step 1: Write failing release contract tests**

Update metadata and documentation tests:

```python
def test_pyproject_declares_version_0_2_0() -> None:
    content = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.2.0"' in content


def test_readme_publishes_streaming_and_keeps_other_modules_experimental() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "0.2.0" in readme
    assert "Agent.run_stream()" in readme
    assert "StreamingChatModel" in readme
    assert "ToolCallDelta" in readme
    assert "StreamEvent" in readme
    assert "memory" in readme.lower()
    assert "experimental" in readme.lower() or "实验性" in readme
```

Add a stable-export test:

```python
def test_core_exports_stable_streaming_contracts() -> None:
    from core import StreamChunk, StreamEvent, StreamingChatModel, ToolCallDelta

    assert StreamChunk is not None
    assert StreamEvent is not None
    assert StreamingChatModel is not None
    assert ToolCallDelta is not None
```

- [ ] **Step 2: Run release tests to verify RED**

Run:

```powershell
python -m pytest tests/test_package_metadata.py tests/test_docs_contract.py -v
```

Expected: failures show version `0.1.0` and documentation that still labels streaming experimental.

- [ ] **Step 3: Update package metadata and stable exports**

Set:

```toml
[project]
version = "0.2.0"
```

Ensure `core.__all__` contains these stable stream names alongside the `0.1.0` API:

```python
"StreamChunk",
"StreamEvent",
"StreamingChatModel",
"ToolCallDelta",
```

Leave only `SlidingWindowMemory` and `LongTermMemory` under the experimental compatibility export comment.

- [ ] **Step 4: Promote the streaming demo**

Remove the `0.1.0` experimental warning from `demo/reasoning_stream.py`. Handle all seven stable event types, including terminal errors and incomplete responses:

```python
elif etype == "model_error":
    print(f"\nModel error [{event['error_code']}]: {event['error']}")

elif etype == "done":
    if event["stop_reason"] == "incomplete":
        print(f"\nIncomplete response ({event.get('finish_reason') or 'missing finish reason'})")
    elif event["stop_reason"] == "model_error":
        print("\nThe model request did not complete.")
```

Read event fields directly according to `StreamEvent`; do not add provider-specific branches or online checks.

- [ ] **Step 5: Update current-state documentation**

In `README.md`:

- identify `0.2.0` as the current stable scope;
- list `LLM.chat_stream()` and `Agent.run_stream()` as synchronous-generator APIs;
- document the seven event types and four stop reasons;
- list `ToolCallDelta`, `StreamChunk`, `StreamingChatModel`, and `StreamEvent` as stable exports;
- list `demo/reasoning_stream.py` with the supported demos;
- keep memory, multi-Agent, and HTML export explicitly experimental.

In `PLAN.md`, describe the separate synchronous and streaming control loops plus their bounded shared helpers. In `ROADMAP.md`, remove completed streaming work and make `0.3` memory semantics and tests the next release target.

- [ ] **Step 6: Run release tests and required verification**

Run exactly:

```powershell
python -m pytest tests -v
python -m compileall -q core demo tests
ruff check core tests demo
git diff --check
```

Expected: pytest reports zero failures, `compileall` has no output, Ruff reports `All checks passed!`, and `git diff --check` reports no whitespace errors.

- [ ] **Step 7: Review the complete release diff**

Run:

```powershell
git status --short
git diff --stat
git diff -- core tests demo pyproject.toml README.md PLAN.md ROADMAP.md
```

Confirm no real API key, online test, async API, concurrent execution, memory writeback, or unrelated file change is present. Stop for user review. Suggested commit message after approval: `feat: release stable streaming API in 0.2.0`.
