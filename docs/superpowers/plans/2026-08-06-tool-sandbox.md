# Guarded Command Execution Implementation Plan

**Version**: 1.9.0  
**Date**: 2026-08-10  
**Status**: Implemented

## Objective

Provide portable subprocess guardrails for `run_command` while keeping the legacy
path unchanged unless a caller explicitly enables `SandboxConfig`.

The implemented scope is intentionally narrower than an OS security sandbox. The
authoritative capability boundary is documented in the accompanying
[design](../specs/2026-08-06-tool-sandbox-design.md).

## Completed Work

1. Added immutable `SandboxConfig` and `SandboxResult` public data contracts.
2. Added working-directory boundary validation with relative roots resolved from
   the configured workspace.
3. Added default and custom environment allowlists, including exact empty-list
   behavior.
4. Added bounded stdout/stderr readers so captured output does not grow without
   limit in memory.
5. Added monotonic timeout tracking and best-effort process-tree cleanup.
6. Added fail-closed handling for unsupported network isolation requests.
7. Integrated enabled configs into `ToolRuntimeContext` and `run_command` while
   retaining the legacy default.
8. Added capability reporting and public package exports.
9. Added cross-platform tests based on the active Python interpreter.
10. Updated README, changelog, roadmap, and package version to 1.9.0.

## Compatibility

- `sandbox_config=None`: unchanged legacy behavior.
- `SandboxConfig(enabled=False)`: unchanged legacy behavior through project tools.
- Enabled configs use `timeout_seconds` and `max_output_bytes` from `SandboxConfig`.
- Enabled execution requires `network_policy="allow"` until network isolation exists.
- Existing public project-tool result fields remain; sandbox failures now expose a
  specific `error` code and successful truncation adds `output_truncated=True`.

## Deferred Work

- Filesystem and network isolation
- CPU, memory, disk, and process-count limits
- Strong containment for untrusted code
- Platform-specific capability backends or container integration

These are roadmap work and are not described as 1.9.0 behavior.

## Release Gate

```bash
python -m ruff check general_mini_agent tests demo
python -m compileall -q general_mini_agent demo tests
python -m pytest tests -v
git diff --check
python -m build
python -m twine check dist/*
```
