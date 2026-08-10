# Guarded Command Execution Design

**Version**: 1.9.0  
**Status**: Implemented (Phase 1)  
**Date**: 2026-08-10

## Objective

Add portable guardrails to project-tool command execution without presenting a
plain subprocess as an operating-system security sandbox.

## Enforced Behavior

Phase 1 enforces:

1. The child working directory must stay under `filesystem_root`.
2. Enabled execution receives only allowlisted environment variables.
3. A timeout triggers best-effort process-group or process-tree cleanup.
4. stdout and stderr are continuously drained while captured content is bounded.
5. Unsupported `network_policy="deny"` requests fail before process creation.

## Explicit Non-Goals

Phase 1 does not enforce:

- filesystem isolation for paths passed to or constructed by the command;
- network isolation;
- CPU, memory, process-count, or disk quotas;
- containment suitable for malicious or otherwise untrusted code;
- protection against child processes that deliberately detach from the process group.

These capabilities require platform-specific isolation or a container boundary and
remain roadmap items.

## Public Contract

```python
@dataclass(frozen=True)
class SandboxConfig:
    enabled: bool = False
    filesystem_root: str | None = None
    network_policy: Literal["deny", "allow"] = "deny"
    timeout_seconds: float = 30.0
    max_output_bytes: int = 1024 * 1024
    env_allowlist: Sequence[str] | None = None


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timeout: bool
    sandbox_error: str | None
    output_truncated: bool = False
```

`sandbox_error` is a stable machine-readable code. Human-readable details are
returned in `stderr` and propagated as the project tool's `message`.

## Configuration Semantics

- `enabled=False`: `ToolRuntimeContext` retains the legacy command path.
- `filesystem_root=None`: the workspace is the working-directory boundary.
- Relative `filesystem_root` values resolve from the workspace.
- `env_allowlist=None`: use the portable default allowlist.
- `env_allowlist=[]`: pass no parent environment variables.
- A custom allowlist replaces, rather than extends, the default.
- `network_policy="deny"`: return `network_isolation_unavailable` without executing.
- `network_policy="allow"`: explicitly accept the lack of network isolation.

## Platform Contract

| Platform | Process cleanup | Other enforced guardrails |
|----------|-----------------|---------------------------|
| Linux | New session/process group | cwd, environment, timeout, bounded capture |
| Windows | New process group plus `taskkill /T` | cwd, environment, timeout, bounded capture |
| macOS | New session/process group | cwd, environment, timeout, bounded capture |

`get_platform_info()` reports capabilities individually and labels process-tree cleanup
as `best_effort`. `sandbox_available=True`
only means the portable Phase 1 subprocess backend is available; it does not imply
filesystem, network, or resource isolation.

## Authorization Order

Authorization and execution guardrails are separate layers. When a command tool is
invoked through a `ToolRegistry` with an authorization policy, the registry denies
the call before the tool function creates a subprocess. Directly calling the tool
function does not add an authorization layer.

## Error Codes

- `network_isolation_unavailable`
- `invalid_filesystem_root`
- `path_escape`
- `invalid_working_directory`
- `command_not_found`
- `permission_denied`
- `execution_failed`

## Verification Contract

Tests cover configuration validation, fail-closed network requests, working-directory
escape rejection, exact environment allowlists, timeout cleanup, bounded stdout and
stderr capture, structured error propagation, and authorization-before-execution.
