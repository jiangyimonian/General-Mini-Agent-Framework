"""Tests for guarded project-tool command execution."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

import general_mini_agent
from general_mini_agent.sandbox import (
    DEFAULT_ENV_ALLOWLIST,
    CommandSandbox,
    SandboxConfig,
    SandboxResult,
    get_platform_info,
    is_sandbox_available,
)
from general_mini_agent.tools import (
    ToolAuthorizationDecision,
    ToolAuthorizationRequest,
    ToolRegistry,
)
from general_mini_agent.tools_project import ToolRuntimeContext, create_run_command


def _enabled_config(**kwargs: object) -> SandboxConfig:
    return SandboxConfig(enabled=True, network_policy="allow", **kwargs)


class TestSandboxConfig:
    def test_default_values(self) -> None:
        config = SandboxConfig()

        assert config.enabled is False
        assert config.filesystem_root is None
        assert config.network_policy == "deny"
        assert config.timeout_seconds == 30.0
        assert config.max_output_bytes == 1024 * 1024
        assert config.env_allowlist is None

    def test_custom_values_are_normalized(self) -> None:
        config = SandboxConfig(
            enabled=True,
            filesystem_root="sandbox",
            network_policy="allow",
            timeout_seconds=60.0,
            max_output_bytes=2048,
            env_allowlist=["PATH", "HOME", "PATH"],
        )

        assert config.filesystem_root == "sandbox"
        assert config.network_policy == "allow"
        assert config.env_allowlist == ("PATH", "HOME")

    @pytest.mark.parametrize("timeout", [0, -1])
    def test_invalid_timeout(self, timeout: float) -> None:
        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            SandboxConfig(timeout_seconds=timeout)

    @pytest.mark.parametrize("max_output", [0, -1])
    def test_invalid_max_output(self, max_output: int) -> None:
        with pytest.raises(ValueError, match="max_output_bytes must be positive"):
            SandboxConfig(max_output_bytes=max_output)

    @pytest.mark.parametrize("name", ["", "A=B", "A\0B", 1])
    def test_invalid_environment_name(self, name: object) -> None:
        with pytest.raises(ValueError, match="env_allowlist entries"):
            SandboxConfig(env_allowlist=[name])  # type: ignore[list-item]

    def test_environment_allowlist_rejects_a_single_string(self) -> None:
        with pytest.raises(ValueError, match="sequence of variable names"):
            SandboxConfig(env_allowlist="PATH")

    def test_invalid_network_policy(self) -> None:
        with pytest.raises(ValueError, match="network_policy"):
            SandboxConfig(network_policy="block")  # type: ignore[arg-type]


class TestCommandSandbox:
    def test_disabled_config_retains_parent_environment(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GMAF_LEGACY_ENV", "visible")
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = CommandSandbox(SandboxConfig(enabled=False), Path(tmpdir))
            result = sandbox.execute(
                sys.executable,
                args=["-c", "import os; print(os.environ.get('GMAF_LEGACY_ENV', ''))"],
            )

        assert result.exit_code == 0
        assert result.stdout.strip() == "visible"

    def test_enabled_command_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = CommandSandbox(_enabled_config(), Path(tmpdir))
            result = sandbox.execute(sys.executable, args=["-c", "print('hello')"])

        assert result.exit_code == 0
        assert result.stdout.strip() == "hello"
        assert result.timeout is False
        assert result.sandbox_error is None

    def test_network_deny_fails_closed_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            marker = workspace / "executed"
            sandbox = CommandSandbox(SandboxConfig(enabled=True), workspace)
            result = sandbox.execute(
                sys.executable,
                args=["-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
            )

            assert result.sandbox_error == "network_isolation_unavailable"
            assert not marker.exists()

    def test_path_escape_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = CommandSandbox(_enabled_config(), Path(tmpdir))
            result = sandbox.execute(sys.executable, cwd="..")

        assert result.sandbox_error == "path_escape"
        assert "outside the working-directory boundary" in result.stderr
        assert result.exit_code == -1

    def test_absolute_path_outside_boundary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            sandbox = CommandSandbox(_enabled_config(), workspace)
            result = sandbox.execute(sys.executable, cwd=str(workspace.parent))

        assert result.sandbox_error == "path_escape"

    def test_missing_working_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = CommandSandbox(_enabled_config(), Path(tmpdir))
            result = sandbox.execute(sys.executable, cwd="missing")

        assert result.sandbox_error == "invalid_working_directory"

    def test_missing_filesystem_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = CommandSandbox(
                _enabled_config(filesystem_root="missing"),
                Path(tmpdir),
            )
            result = sandbox.execute(sys.executable)

        assert result.sandbox_error == "invalid_filesystem_root"

    def test_timeout_cleans_up_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = CommandSandbox(
                _enabled_config(timeout_seconds=0.2),
                Path(tmpdir),
            )
            result = sandbox.execute(
                sys.executable,
                args=["-c", "import time; time.sleep(10)"],
            )

        assert result.timeout is True
        assert result.duration_ms < 5000

    def test_output_capture_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = CommandSandbox(
                _enabled_config(max_output_bytes=100),
                Path(tmpdir),
            )
            result = sandbox.execute(
                sys.executable,
                args=["-c", "import sys; print('x' * 1000); print('y' * 1000, file=sys.stderr)"],
            )

        assert result.output_truncated is True
        assert "[output truncated]" in result.stdout
        assert "[output truncated]" in result.stderr
        assert len(result.stdout.encode()) <= 100
        assert len(result.stderr.encode()) <= 100

    def test_custom_environment_allowlist_replaces_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GMAF_ALLOWED", "yes")
        monkeypatch.setenv("GMAF_SECRET", "hidden")
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = CommandSandbox(
                _enabled_config(env_allowlist=["GMAF_ALLOWED"]),
                Path(tmpdir),
            )
            result = sandbox.execute(
                sys.executable,
                args=["-c", "import json, os; print(json.dumps(dict(os.environ)))"],
            )

        environment = json.loads(result.stdout)
        assert environment["GMAF_ALLOWED"] == "yes"
        assert "GMAF_SECRET" not in environment
        assert "PATH" not in environment

    def test_empty_environment_allowlist_passes_no_parent_variables(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GMAF_SECRET", "hidden")
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = CommandSandbox(
                _enabled_config(env_allowlist=[]),
                Path(tmpdir),
            )
            result = sandbox.execute(
                sys.executable,
                args=["-c", "import os; print(os.environ.get('GMAF_SECRET', 'missing'))"],
            )

        assert result.stdout.strip() == "missing"

    def test_default_allowlist_contains_portable_variables(self) -> None:
        assert {"PATH", "HOME", "USER", "TEMP", "TMP"} <= set(DEFAULT_ENV_ALLOWLIST)

    def test_relative_filesystem_root_is_resolved_from_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            expected = workspace / "subdir"
            expected.mkdir()
            sandbox = CommandSandbox(
                _enabled_config(filesystem_root="subdir"),
                workspace,
            )
            result = sandbox.execute(
                sys.executable,
                args=["-c", "from pathlib import Path; print(Path.cwd())"],
            )

        assert result.exit_code == 0
        assert Path(result.stdout.strip()).resolve() == expected.resolve()

    def test_command_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = CommandSandbox(_enabled_config(), Path(tmpdir))
            result = sandbox.execute("gmaf-command-that-does-not-exist")

        assert result.sandbox_error == "command_not_found"

    def test_shell_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = CommandSandbox(_enabled_config(), Path(tmpdir))
            result = sandbox.execute("echo hello", shell=True)

        assert result.exit_code == 0
        assert "hello" in result.stdout.lower()


class TestPublicContracts:
    def test_sandbox_types_are_exported_from_package_namespace(self) -> None:
        expected = {
            "CommandSandbox",
            "SandboxConfig",
            "SandboxResult",
            "get_platform_info",
            "is_sandbox_available",
        }

        assert expected <= set(general_mini_agent.__all__)
        assert general_mini_agent.CommandSandbox is CommandSandbox
        assert general_mini_agent.SandboxConfig is SandboxConfig
        assert general_mini_agent.SandboxResult is SandboxResult

    def test_result_defaults_and_immutability(self) -> None:
        result = SandboxResult(
            exit_code=0,
            stdout="test",
            stderr="",
            duration_ms=100.0,
            timeout=False,
            sandbox_error=None,
        )

        assert result.output_truncated is False
        with pytest.raises(AttributeError):
            result.exit_code = 1  # type: ignore[misc]

    def test_config_is_deeply_immutable_for_allowlist(self) -> None:
        source = ["PATH"]
        config = SandboxConfig(enabled=True, env_allowlist=source)
        source.append("HOME")

        assert config.env_allowlist == ("PATH",)
        with pytest.raises(AttributeError):
            config.enabled = False  # type: ignore[misc]

    def test_platform_info_reports_only_enforced_capabilities(self) -> None:
        assert is_sandbox_available() is True
        info = get_platform_info()

        assert info["sandbox_available"] is True
        assert info["working_directory_boundary"] is True
        assert info["environment_filtering"] is True
        assert info["process_tree_cleanup"] == "best_effort"
        assert info["filesystem_isolation"] is False
        assert info["network_isolation"] is False
        assert info["resource_limits"] is False


class _DenyPolicy:
    def authorize(self, request: ToolAuthorizationRequest) -> ToolAuthorizationDecision:
        return ToolAuthorizationDecision(allowed=False, reason="test policy")


class TestProjectToolIntegration:
    def test_project_tool_returns_specific_sandbox_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ToolRuntimeContext(
                workspace=Path(tmpdir),
                allow_execute=True,
                sandbox_config=SandboxConfig(enabled=True),
            )
            result = create_run_command(context)(sys.executable)

        assert isinstance(result, dict)
        assert result["error"] == "network_isolation_unavailable"

    def test_authorization_denial_happens_before_command_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            marker = workspace / "executed"
            context = ToolRuntimeContext(
                workspace=workspace,
                allow_execute=True,
                sandbox_config=_enabled_config(),
            )
            registry = ToolRegistry(
                [create_run_command(context)],
                authorization_policy=_DenyPolicy(),
            )
            result = registry.execute(
                "run_command",
                {
                    "command": sys.executable,
                    "args": [
                        "-c",
                        f"from pathlib import Path; Path({str(marker)!r}).touch()",
                    ],
                },
            )

            assert result.error_code == "permission_denied"
            assert not marker.exists()
