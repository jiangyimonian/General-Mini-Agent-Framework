# General Mini Agent Framework 0.2.0 Streaming Design

## Status

Proposed design awaiting user review before implementation planning.

## Goal

Promote synchronous-generator streaming from an experimental compatibility path to a stable
`0.2.0` API. The release must make streamed text, tool calls, errors, usage, hooks, trace entries,
and terminal states predictable without changing the stable `0.1.0` synchronous execution loop.

## Scope

`0.2.0` stabilizes:

- `LLM.chat_stream()` for OpenAI-compatible SSE responses
- `Agent.run_stream()` as a synchronous Python generator
- indexed aggregation of multiple streamed tool calls
- typed public chunk and Agent event contracts
- structured terminal, tool-argument, request, and protocol errors
- offline regression coverage for all stable streaming behavior

The release does not add async APIs, concurrent tool execution, cancellation, reconnection,
automatic memory writeback, provider-specific adapters, or online CI.

## Compatibility Strategy

`Agent.run()` remains the `0.1.0` synchronous implementation and is not rebuilt on top of the
streaming path. The two entry points retain separate control loops and share only bounded helpers
for tool execution, trace construction, usage accumulation, and stop-reason mapping.

The existing streaming path was explicitly experimental in `0.1.0`. `0.2.0` may change the shape
of `StreamChunk` to establish a coherent stable contract. Agent events remain runtime dictionaries,
so consumers continue to branch on `event["type"]`.

## Model Streaming Contracts

Add a `StreamingChatModel` protocol without changing the existing `ChatModel` protocol.
`StreamingChatModel` extends the synchronous model requirement with:

```python
def chat_stream(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> Iterator[StreamChunk]: ...
```

A model passed to `Agent.run_stream()` must implement both synchronous and streaming model
protocols. Keeping the protocols separate avoids invalidating `0.1.0` custom synchronous models.

Represent each tool-call fragment explicitly:

```python
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
```

One SSE payload may therefore expose fragments for multiple tool-call indexes without overwriting
earlier entries.

## Tool-Call Aggregation

`Agent.run_stream()` uses a private accumulator keyed by `ToolCallDelta.index`. The accumulator:

1. accepts interleaved fragments from any index;
2. stores one stable id and name per index;
3. concatenates argument fragments in arrival order for that index;
4. rejects conflicting ids or names for the same index;
5. finalizes calls in ascending index order.

The accumulator only reconstructs calls. It does not execute tools or mutate Agent messages.

When `finish_reason` is `tool_calls`, every finalized call must have an index, id, and name. The
Agent appends one assistant message containing all finalized calls, then executes them sequentially
by index. Each result is appended as a corresponding tool message. Parallel execution is outside
this release.

Malformed argument JSON is recoverable when index, id, and name are complete. The Agent does not
execute the tool. It emits a `tool_call` event and an `observation` event carrying the
`invalid_arguments` error code, writes the raw call and error result back to the model, and allows
the next iteration to correct the arguments.

Missing identity fields, conflicting identity fragments, or a `tool_calls` finish reason with no
calls indicate a broken model protocol. These terminate the Agent as a model error before any tool
from that response is executed.

## Public Agent Events

Define each event as a dedicated `TypedDict` with a literal `type`, and export their union as
`StreamEvent`. Runtime values remain dictionaries.

### `iteration_start`

Required fields: `type`, `iteration`.

### `thought_chunk`

Required fields: `type`, `iteration`, `text`.

### `tool_call`

Required fields: `type`, `iteration`, `index`, `id`, `name`, `arguments`, `raw_arguments`.
`arguments` is a dictionary for valid JSON and `None` for malformed JSON. `error_code` is present
for invalid arguments.

### `observation`

Required fields: `type`, `iteration`, `index`, `tool_call_id`, `name`, `text`. `error_code` is
present for argument validation, unknown tools, invalid tool parameters, and execution failures.

### `final_answer`

Required fields: `type`, `iteration`, `text`.

### `model_error`

Required fields: `type`, `iteration`, `error_code`, `error`. An HTTP status code is optional. Error
text is sanitized and never includes response bodies, authorization values, or API keys.

Stable model error codes are `model_request_error` for transport and HTTP failures, and
`stream_protocol_error` for malformed SSE or tool-call metadata.

`ModelRequestError` gains a public `error_code` attribute whose default remains
`model_request_error`, preserving existing construction and catch behavior. Malformed SSE payloads
raise the same exception type with `error_code="stream_protocol_error"`; Agent-side tool-call
metadata failures use that code directly. This lets low-level and Agent consumers distinguish the
two categories without parsing error text or adding a second public exception hierarchy.

### `done`

Required fields: `type`, `content`, `trace`, `usage`, `iterations`, `stop_reason`. Optional fields
are `finish_reason` and `error`.

`stop_reason` is one of:

- `completed`
- `max_iterations`
- `model_error`
- `incomplete`

Unless the consumer explicitly closes the generator, every invocation produces exactly one `done`
event.

## Event and Terminal Flow

Normal final response:

```text
iteration_start -> thought_chunk* -> final_answer -> done(completed)
```

Tool response:

```text
iteration_start -> thought_chunk* -> aggregate calls
  -> tool_call -> observation
  -> tool_call -> observation
  -> next iteration
```

Model request or protocol failure:

```text
iteration_start -> model_error -> done(model_error)
```

Iteration exhaustion:

```text
iteration_start* -> done(max_iterations)
```

`stop` is the only finish reason that permits a final answer. `tool_calls` requires complete calls.
`length`, `content_filter`, unknown finish reasons, and a clean transport close without a finish
reason produce `done(incomplete)` and do not invoke the final hook. The incomplete event retains the
raw finish reason and any partial generated content.

Tool execution failures remain recoverable observations and do not terminate the Agent. The
`on_tool_call` hook runs once for each attempted complete call, including calls rejected for invalid
arguments. The `on_final` hook runs only for `completed` final answers.

## SSE Parsing and Retry Rules

`LLM.chat_stream()` follows the OpenAI-compatible one-JSON-object-per-`data:`-line format:

- ignore blank lines, SSE comments, and non-`data:` fields;
- accept `data:` with the optional SSE space;
- stop transport parsing at `data: [DONE]`;
- treat non-JSON `data:` payloads as sanitized stream protocol errors;
- preserve usage-only payloads that contain no choices;
- request streamed usage with `stream_options.include_usage=true`;
- leave usage empty when a compatible service does not provide it.

Temporary HTTP and connection errors are retried only before the first yielded chunk. Once any
chunk has been yielded, retrying could duplicate text or tool calls, so a later failure is surfaced
immediately. Protocol errors are never retried. Low-level `LLM.chat_stream()` raises
`ModelRequestError` with the appropriate error code; `Agent.run_stream()` converts it into the
terminal event sequence.

## Context, Trace, Usage, and Hooks

For multiple tool calls in one model turn, Agent context contains exactly one assistant message with
all tool calls followed by one tool message per call. Raw argument text is retained in the assistant
message so an invalid call can be shown back to the model accurately.

Trace events preserve iteration, thought, tool identity, parsed or raw arguments, observation, and
error code. Model errors and incomplete finishes receive explicit trace entries. Within one model
request, the Agent retains the latest value for each usage key and adds that request usage to the
run total exactly once when the request ends. This avoids double-counting cumulative usage repeated
across chunks. Missing usage remains an empty dictionary rather than being estimated.

## Testing Strategy

All automated tests are offline and use `httpx.MockTransport`, SSE byte fixtures, or scripted model
objects. No test reads a real API key or performs a network request.

### LLM tests

- multiple tool deltas in one SSE payload;
- interleaved fragments for multiple indexes;
- content, finish reason, and usage-only payload parsing;
- blank lines, comments, optional SSE spacing, and `[DONE]`;
- malformed JSON data as a protocol error with the stable error code;
- transport and HTTP failures retaining the default request error code;
- retry before the first chunk;
- no retry after output has started;
- sanitization of all surfaced errors.

### Agent tests

- required keys and ordering for every public event;
- exactly one `done` for every non-cancelled terminal path;
- multiple tools reconstructed and executed in index order;
- one assistant message containing all calls and correctly ordered tool results;
- split argument JSON and interleaved calls;
- invalid arguments written back for model correction;
- missing or conflicting call metadata as protocol errors;
- request failures as `model_error` events;
- `length`, `content_filter`, unknown, and missing finish reasons as `incomplete`;
- cumulative usage chunks counted once per model request;
- trace and hooks aligned with synchronous semantics;
- tool and stream state isolated between Agent instances.

The required verification commands remain:

```bash
python -m pytest tests -v
python -m compileall -q core demo tests
ruff check core tests demo
git diff --check
```

## Documentation and Release Changes

- bump the package version to `0.2.0`;
- list synchronous streaming as a stable README capability;
- promote `demo/reasoning_stream.py` to a stable example;
- export `ToolCallDelta`, `StreamChunk`, `StreamingChatModel`, and `StreamEvent` as stable API;
- update `PLAN.md` with the `0.2.0` streaming boundary;
- remove completed streaming work from `ROADMAP.md`, making `0.3` memory the next version;
- keep memory, multi-Agent, and HTML trace export explicitly experimental.

## Acceptance Criteria

`0.2.0` is ready for review when all confirmed event shapes and terminal paths are covered by offline
tests, multiple streamed tools work with interleaved argument fragments, malformed streams cannot
silently continue, the synchronous `0.1.0` suite remains unchanged and passing, documentation
matches the public exports, and every verification command exits successfully.
