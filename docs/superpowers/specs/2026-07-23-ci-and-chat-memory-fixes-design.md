# CI Compatibility and Chat Memory Fix Design

## Goal

Restore the Python 3.12 CI build and make the `/clear` command in
`demo/chat.py` clear real short-term conversation history.

## Scope

- Keep the stable `0.1.0` Agent contract unchanged.
- Keep memory ownership and writeback inside the interactive demo.
- Preserve the existing synchronous and streaming Agent behavior.
- Do not add long-term memory, persistence, summarization, or new commands.

## CI Compatibility Fix

Python 3.12 reports the origin of a PEP 604 annotation such as `str | None`
as `types.UnionType`, while the current schema builder only recognizes
`typing.Union`. The schema builder will recognize both origins and retain the
existing nullable schema shape.

The existing optional-parameter test is the regression test: it fails in the
current Python 3.12 CI run and must pass after the fix.

## Chat Memory Fix

`demo/chat.py` will create a `SlidingWindowMemory` instance and pass it to the
Agent. After a streamed run reaches its `done` event, the demo will append the
user input and final assistant content to that memory. The next run can then
include the prior conversation through the Agent's existing compatibility
hook.

The `/clear` command will clear this memory. Memory remains process-local and
is lost when the demo exits.

To keep the behavior testable without a model request, small demo-level
helpers will record and clear a completed conversation. Tests will verify that
recording stores one user/assistant pair and clearing removes all stored
messages.

## Verification

- Run the focused tool-schema and chat-memory tests.
- Run the full offline test suite.
- Run `python -m compileall -q core demo tests`.
- Run `ruff check core tests demo`.
- After approval, commit and push so GitHub Actions verifies Python 3.12.
