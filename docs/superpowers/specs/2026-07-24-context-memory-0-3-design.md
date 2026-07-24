# General Mini Agent Framework 0.3.0 Context and Memory Design

## Status

Approved for implementation on 2026-07-24.

## Goal

Make long-running Agent conversations predictable by applying an explicit token budget before
every model request and by defining when completed exchanges are written back to conversation
memory. The release must preserve the stable `0.2.0` model and Agent boundaries: the Agent owns
context policy and conversation state, while the model client sends the messages it receives.

## Scope

`0.3.0` stabilizes:

- a pluggable token-counting contract with a lightweight default estimator;
- an Agent-owned context policy configured with an explicit context window and output reserve;
- deterministic trimming that preserves complete conversation and tool-call units;
- context-budget enforcement before every synchronous and streaming model request;
- an in-memory conversation store with atomic exchange writeback;
- identical writeback and budget behavior for `Agent.run()` and `Agent.run_stream()`;
- an optional summarizing policy built on an explicitly supplied summarizer;
- offline tests and a budgeted multi-turn Demo.

The release does not stabilize vector storage, cross-process persistence, conversation namespaces,
metadata-filtered retrieval, async APIs, provider-specific tokenizers, or automatic model-capacity
lookup. Those storage concerns remain planned for `0.3.1`.

## Compatibility

`context_policy` remains optional on `Agent`. Omitting it preserves the `0.2.0` request behavior,
so existing callers are not forced into a guessed model capacity. Enabling budget management
requires an explicit `context_window` and `reserved_output_tokens`; the framework does not maintain
a model-name capacity table.

Existing objects that only provide `get_context()` remain supported as read-only legacy memory.
Automatic writeback requires the new conversation-memory contract. `SlidingWindowMemory` remains a
compatibility export, while the stable in-memory implementation separates history storage from the
request-time context policy.

## Public Contracts

### Token counting

Define a `TokenCounter` protocol that counts complete request inputs rather than plain message text:

```python
class TokenCounter(Protocol):
    def count(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> int: ...
```

`ApproximateTokenCounter` is the dependency-free default. It estimates serialized request content,
including message metadata and tool schemas, using a documented conservative character ratio and
fixed structural overhead. It is deterministic, but does not claim provider-exact counts. Callers
may inject a tokenizer-backed implementation through the same protocol.

### Context policy

Define a `ContextPolicy` protocol:

```python
class ContextPolicy(Protocol):
    def prepare(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]: ...
```

`TokenBudgetContext` is the default implementation. Its required configuration is:

- `context_window`: total model context capacity;
- `reserved_output_tokens`: capacity held back for model output.

It accepts optional `token_counter` and `oversized_content_handler` dependencies. Configuration is
rejected when values are non-positive or the output reserve is not smaller than the context window.
The usable input budget is always:

```text
context_window - reserved_output_tokens
```

The policy receives tool schemas separately and includes them in the count without inserting them
into the returned message list.

### Conversation memory

Define a `ConversationMemory` protocol with snapshot reads, atomic batch append, and clear:

```python
class ConversationMemory(Protocol):
    def get_context(self) -> list[dict[str, Any]]: ...
    def add_messages(self, messages: Sequence[Mapping[str, Any]]) -> None: ...
    def clear(self) -> None: ...
```

`InMemoryConversation` stores defensive copies and appends a batch only after every message has
been validated. Its context snapshots cannot mutate stored history. Memory instances are isolated
unless a caller deliberately shares one between Agents.

## Trimming Model

`TokenBudgetContext.prepare()` first copies and validates the input. It never mutates Agent working
messages or stored history. Messages are then grouped into atomic units:

1. system messages are protected individually;
2. each user message starts a conversation turn containing following assistant messages and their
   tool messages up to the next user message;
3. an assistant message with `tool_calls` and all matching tool results form one indivisible segment;
4. leading legacy messages that cannot be assigned to a user turn are treated as their own units.

The newest user turn is always protected. The immediately preceding complete user turn is also
protected when present. The policy repeatedly removes the oldest unprotected unit until the full
request fits. It preserves original message order and never slices message text or emits an orphaned
tool result.

If the protected minimum still exceeds the budget, the optional `oversized_content_handler` may
return a replacement for the oversized unit. The replacement is recounted and must preserve a valid
message structure. Without a handler, or when the replacement still does not fit, the policy raises
`ContextBudgetExceeded` with counts and limits but no message content.

## Agent Integration

`Agent` gains an optional `context_policy`. Both execution paths build their private working
messages as before. Immediately before every `chat()` or `chat_stream()` call, the Agent passes the
current messages and current tool schemas to the policy and sends the returned snapshot. This is
done on every ReAct iteration because tool observations can independently overflow the budget.

The original working messages remain intact between iterations. Trimming is a request view, not a
destructive edit to history or the current trace.

`ContextBudgetExceeded` is converted into a terminal Agent result with
`stop_reason="context_budget_exceeded"`. The synchronous path returns an `AgentResult`; the streaming
path yields one terminal `done` event. No model request is attempted after the policy rejects the
context, and error text contains only safe size metadata.

## Writeback Contract

For a configured `ConversationMemory`, a completed run atomically appends exactly two messages:

```text
user(original input) -> assistant(clean final answer)
```

Tool calls, observations, intermediate thoughts, and trace entries are not conversation history.
They remain available through `AgentResult.trace` or the streaming `done` event.

There is no writeback for `model_error`, `max_iterations`, `incomplete`,
`context_budget_exceeded`, hook failures, or an exception escaping the execution path. The user
message is therefore never persisted without its final assistant reply.

For `run_stream()`, writeback occurs immediately before the generator yields its successful `done`
event. Reaching that point requires the caller to consume the generator through the final-answer
path. Closing or abandoning the generator earlier performs no writeback. This gives synchronous and
fully consumed streaming runs the same stored result.

Legacy memory with only `get_context()` remains readable but receives no automatic writes. The Demo
stops manually recording exchanges once it uses `InMemoryConversation`, preventing duplicates.

## Optional Summary Policy

Summary generation is explicit and cannot silently reuse the Agent's primary model client.
`SummarizingContext` wraps a `TokenBudgetContext` and receives a caller-supplied synchronous
summarizer callable. It is invoked only when deterministic trimming would otherwise discard one or
more old complete turns.

The summarizer receives only those removable turns and returns plain summary text. The wrapper
stores that text in a clearly marked context message, then asks the underlying budget policy to
validate the final request. Summary failure or an oversized summary falls back to deterministic
trimming; it does not fail an otherwise valid Agent run. Summaries are request-local in `0.3.0` and
are not written back to conversation memory.

## Error Handling

- invalid policy configuration raises `ValueError` at construction;
- malformed message or memory input raises a contextual `TypeError` or `ValueError` before a model
  request;
- an unsatisfied protected budget raises `ContextBudgetExceeded`;
- Agent maps that exception to the stable `context_budget_exceeded` stop reason;
- custom counter, compressor, summarizer, and memory exceptions are not mislabeled as model errors;
- no surfaced error includes system prompts, user content, tool results, schemas, or credentials.

## Testing Strategy

Focused tests cover each task before its commit. Final verification remains offline and runs after
all implementation tasks.

### Context tests

- default estimator is deterministic and includes tools and structured message fields;
- injected counters control budget decisions;
- invalid capacities and reserves fail at construction;
- oldest complete turns are removed first;
- system messages, current turn, and the previous complete turn are protected;
- assistant tool calls and matching tool results are never split;
- policy output and memory snapshots cannot mutate their inputs;
- oversized protected content reports safe metadata only;
- optional content handling is recounted and validated;
- summary runs only for removable history and safely falls back.

### Agent and memory tests

- every synchronous and streaming model request is prepared by the policy;
- large tool observations trigger a new budget decision on the next iteration;
- context rejection makes no model request and returns the new stop reason;
- only completed runs append one atomic user/assistant batch;
- every non-success terminal state leaves memory unchanged;
- an abandoned stream leaves memory unchanged;
- legacy read-only memory remains compatible;
- separate Agent and memory instances remain isolated;
- the Demo no longer double-writes completed exchanges.

Required final verification:

```bash
python -m pytest tests -v
python -m compileall -q core demo tests
ruff check core tests demo
git diff --check
```

## Documentation and Release

- export stable context, counter, memory, and error contracts from `core`;
- document explicit context-window configuration and approximate-count limitations;
- update the chat Demo to use automatic writeback and a configured budget;
- add a small custom-counter example without requiring provider-specific packages;
- update `PLAN.md`, `README.md`, and `ROADMAP.md` to describe only shipped behavior;
- bump package and module versions to `0.3.0` after the full suite passes;
- leave long-term vector memory and namespaced retrieval on the `0.3.1` roadmap.

## Acceptance Criteria

`0.3.0` is ready when callers can explicitly cap every Agent model request, trimming never breaks a
conversation or tool-call unit, protected overflow fails before network access, completed sync and
fully consumed stream runs write the same two-message exchange exactly once, unsuccessful runs do
not change memory, old `Agent` construction remains valid without a policy, documentation matches
public exports, and all final verification commands pass.
