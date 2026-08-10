"""Guarded subprocess execution for project tools.

The Phase 1 backend provides working-directory validation, environment
filtering, bounded output capture, timeout enforcement, and best-effort
process-tree cleanup. It is not an operating-system security sandbox: it does
not isolate the filesystem, network, CPU, or memory.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

NetworkPolicy = Literal["deny", "allow"]

DEFAULT_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USER",
    "PWD",
    "TEMP",
    "TMP",
)

if sys.platform == "win32":
    DEFAULT_ENV_ALLOWLIST += (
        "APPDATA",
        "LOCALAPPDATA",
        "SYSTEMROOT",
        "COMSPEC",
    )
elif sys.platform == "darwin":
    DEFAULT_ENV_ALLOWLIST += ("TMPDIR", "SHELL")
else:
    DEFAULT_ENV_ALLOWLIST += ("TMPDIR", "SHELL", "LANG", "TERM")


@dataclass(frozen=True)
class SandboxConfig:
    """Configuration for guarded command execution.

    ``network_policy="deny"`` fails closed because the Phase 1 subprocess
    backend cannot provide network isolation. Callers must explicitly choose
    ``"allow"`` when network access is acceptable.
    """

    enabled: bool = False
    filesystem_root: str | None = None
    network_policy: NetworkPolicy = "deny"
    timeout_seconds: float = 30.0
    max_output_bytes: int = 1024 * 1024
    env_allowlist: Sequence[str] | None = None

    def __post_init__(self) -> None:
        if self.network_policy not in ("deny", "allow"):
            raise ValueError("network_policy must be 'deny' or 'allow'")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        if self.filesystem_root == "":
            raise ValueError("filesystem_root must not be empty")
        if self.env_allowlist is not None:
            if isinstance(self.env_allowlist, (str, bytes)):
                raise ValueError("env_allowlist must be a sequence of variable names")
            allowlist = tuple(self.env_allowlist)
            if any(
                not isinstance(name, str) or not name or "=" in name or "\0" in name
                for name in allowlist
            ):
                raise ValueError("env_allowlist entries must be non-empty variable names")
            object.__setattr__(self, "env_allowlist", tuple(dict.fromkeys(allowlist)))


@dataclass(frozen=True)
class SandboxResult:
    """Structured result returned by :class:`CommandSandbox`."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timeout: bool
    sandbox_error: str | None
    output_truncated: bool = False


@dataclass
class _OutputCapture:
    data: bytes = b""
    truncated: bool = False


class CommandSandbox:
    """Execute commands with portable Phase 1 subprocess guardrails."""

    def __init__(self, config: SandboxConfig, workspace: Path):
        self.config = config
        self.workspace = workspace.resolve()
        configured_root = Path(config.filesystem_root) if config.filesystem_root else None
        if configured_root is None:
            self._filesystem_root = self.workspace
        elif configured_root.is_absolute():
            self._filesystem_root = configured_root.resolve()
        else:
            self._filesystem_root = (self.workspace / configured_root).resolve()

    def _build_env(self, work_dir: Path) -> dict[str, str]:
        if not self.config.enabled:
            return dict(os.environ)

        allowlist = (
            DEFAULT_ENV_ALLOWLIST
            if self.config.env_allowlist is None
            else self.config.env_allowlist
        )
        env = {
            name: value
            for name in allowlist
            if (value := os.environ.get(name)) is not None
        }
        if os.name != "nt" and "PWD" in allowlist:
            env["PWD"] = str(work_dir)
        return env

    def _validate_work_dir(self, path: str) -> Path:
        resolved = (self._filesystem_root / path).resolve()
        try:
            resolved.relative_to(self._filesystem_root)
        except ValueError as exc:
            raise ValueError(f"'{path}' resolves outside the working-directory boundary") from exc
        return resolved

    def _error_result(
        self,
        code: str,
        message: str,
        *,
        started_at: float | None = None,
    ) -> SandboxResult:
        duration_ms = 0.0
        if started_at is not None:
            duration_ms = (time.monotonic() - started_at) * 1000
        return SandboxResult(
            exit_code=-1,
            stdout="",
            stderr=message,
            duration_ms=duration_ms,
            timeout=False,
            sandbox_error=code,
        )

    def _capture_stream(self, stream: BinaryIO, capture: _OutputCapture) -> None:
        buffer = bytearray()
        limit = self.config.max_output_bytes
        try:
            while chunk := stream.read(64 * 1024):
                remaining = limit - len(buffer)
                if remaining > 0:
                    buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    capture.truncated = True
        except (OSError, ValueError):
            capture.truncated = True
        finally:
            capture.data = bytes(buffer)
            stream.close()

    def _decode_capture(self, capture: _OutputCapture) -> str:
        data = capture.data
        if capture.truncated:
            marker = b"\n...[output truncated]..."
            if len(marker) >= self.config.max_output_bytes:
                data = marker[: self.config.max_output_bytes]
            else:
                keep = self.config.max_output_bytes - len(marker)
                data = data[:keep] + marker
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _terminate_process_tree(proc: subprocess.Popen[bytes]) -> None:
        if os.name == "nt":
            if proc.poll() is not None:
                return
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5.0,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                proc.kill()
            return

        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            if proc.poll() is None:
                proc.kill()

    def execute(
        self,
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        shell: bool = False,
    ) -> SandboxResult:
        """Execute a command using the configured subprocess guardrails."""
        args = [] if args is None else list(args)

        if self.config.enabled and self.config.network_policy == "deny":
            return self._error_result(
                "network_isolation_unavailable",
                "network_policy='deny' is unavailable in the Phase 1 subprocess backend",
            )

        if not self._filesystem_root.is_dir():
            return self._error_result(
                "invalid_filesystem_root",
                f"filesystem_root is not an existing directory: {self._filesystem_root}",
            )

        if cwd is None:
            work_dir = self._filesystem_root
        else:
            try:
                work_dir = self._validate_work_dir(cwd)
            except ValueError as exc:
                return self._error_result("path_escape", str(exc))
            if not work_dir.is_dir():
                return self._error_result(
                    "invalid_working_directory",
                    f"working directory is not an existing directory: {cwd}",
                )

        cmd: str | list[str]
        if shell:
            rendered_args = (
                subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)
            )
            cmd = command + (" " + rendered_args if rendered_args else "")
        else:
            cmd = [command, *args]

        started_at = time.monotonic()
        proc: subprocess.Popen[bytes] | None = None
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(work_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._build_env(work_dir),
                text=False,
                shell=shell,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                ),
                start_new_session=os.name != "nt",
            )
            assert proc.stdout is not None
            assert proc.stderr is not None

            stdout_capture = _OutputCapture()
            stderr_capture = _OutputCapture()
            readers = (
                threading.Thread(
                    target=self._capture_stream,
                    args=(proc.stdout, stdout_capture),
                    daemon=True,
                ),
                threading.Thread(
                    target=self._capture_stream,
                    args=(proc.stderr, stderr_capture),
                    daemon=True,
                ),
            )
            for reader in readers:
                reader.start()

            timed_out = False
            try:
                proc.wait(timeout=self.config.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate_process_tree(proc)
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

            for reader in readers:
                reader.join(timeout=5.0)
            for capture, reader in zip(
                (stdout_capture, stderr_capture),
                readers,
                strict=True,
            ):
                if reader.is_alive():
                    # A deliberately detached descendant may retain an inherited pipe.
                    # Do not block this call while closing a stream another thread is reading.
                    capture.truncated = True

            output_truncated = stdout_capture.truncated or stderr_capture.truncated
            return SandboxResult(
                exit_code=proc.returncode if proc.returncode is not None else -1,
                stdout=self._decode_capture(stdout_capture),
                stderr=self._decode_capture(stderr_capture),
                duration_ms=(time.monotonic() - started_at) * 1000,
                timeout=timed_out,
                sandbox_error=None,
                output_truncated=output_truncated,
            )
        except FileNotFoundError as exc:
            return self._error_result(
                "command_not_found",
                f"command not found: {exc}",
                started_at=started_at,
            )
        except PermissionError as exc:
            return self._error_result(
                "permission_denied",
                f"permission denied: {exc}",
                started_at=started_at,
            )
        except Exception as exc:
            if proc is not None:
                self._terminate_process_tree(proc)
            return self._error_result(
                "execution_failed",
                f"execution failed: {type(exc).__name__}: {exc}",
                started_at=started_at,
            )


def is_sandbox_available() -> bool:
    """Return whether the portable Phase 1 subprocess backend is available."""
    return True


def get_platform_info() -> dict[str, str | bool]:
    """Return the capabilities actually enforced by the current backend."""
    return {
        "platform": sys.platform,
        "os": os.name,
        "sandbox_available": is_sandbox_available(),
        "working_directory_boundary": True,
        "environment_filtering": True,
        "timeout_enforcement": True,
        "bounded_output_capture": True,
        "process_tree_cleanup": "best_effort",
        "filesystem_isolation": False,
        "network_isolation": False,
        "resource_limits": False,
    }
