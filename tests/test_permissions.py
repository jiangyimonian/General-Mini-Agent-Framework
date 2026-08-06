"""Tests for permission and security boundary system."""

import tempfile
from pathlib import Path

from general_mini_agent.permissions import (
    AllowAllPolicy,
    AskPolicy,
    CompositePolicy,
    ConditionalPolicy,
    DenyAllPolicy,
    PermissionPolicyToAuthorizationAdapter,
    RiskBasedPolicy,
    ToolAllowlistPolicy,
    ToolBlocklistPolicy,
    ToolPermissionRequest,
    ToolPermissionResponse,
)
from general_mini_agent.tools import ToolRegistry
from general_mini_agent.tools_project import (
    ProjectToolBoundaryPolicy,
    ToolRuntimeContext,
    create_project_tool_policy,
    get_risk_category_for_tool,
)


class TestPermissionRequestAndResponse:
    """Tests for permission request and response data classes."""

    def test_permission_request_creation(self) -> None:
        request = ToolPermissionRequest(
            tool_name="read_file",
            arguments={"path": "test.txt"},
            risk_category="read",
            description="Read a file",
            context={"workspace": "/tmp"},
        )

        assert request.tool_name == "read_file"
        assert request.arguments == {"path": "test.txt"}
        assert request.risk_category == "read"
        assert request.description == "Read a file"
        assert request.context == {"workspace": "/tmp"}

    def test_permission_response_creation(self) -> None:
        response = ToolPermissionResponse(
            action="allow",
            reason="looks safe",
        )

        assert response.action == "allow"
        assert response.reason == "looks safe"


class TestBuiltinPolicies:
    """Tests for built-in permission policies."""

    def test_allow_all_policy(self) -> None:
        policy = AllowAllPolicy()
        request = ToolPermissionRequest(
            tool_name="any_tool",
            arguments={},
        )

        response = policy.evaluate(request)

        assert response.action == "allow"
        assert response.reason is None

    def test_deny_all_policy_default_reason(self) -> None:
        policy = DenyAllPolicy()
        request = ToolPermissionRequest(
            tool_name="any_tool",
            arguments={},
        )

        response = policy.evaluate(request)

        assert response.action == "deny"
        assert response.reason == "denied by policy"

    def test_deny_all_policy_custom_reason(self) -> None:
        policy = DenyAllPolicy(reason="blocked by admin")
        request = ToolPermissionRequest(
            tool_name="any_tool",
            arguments={},
        )

        response = policy.evaluate(request)

        assert response.action == "deny"
        assert response.reason == "blocked by admin"

    def test_ask_policy(self) -> None:
        policy = AskPolicy()
        request = ToolPermissionRequest(
            tool_name="any_tool",
            arguments={},
        )

        response = policy.evaluate(request)

        assert response.action == "ask"
        assert response.reason == "requires user approval"

    def test_risk_based_policy_defaults(self) -> None:
        policy = RiskBasedPolicy()

        read_request = ToolPermissionRequest(
            tool_name="read_file",
            arguments={},
            risk_category="read",
        )
        write_request = ToolPermissionRequest(
            tool_name="write_file",
            arguments={},
            risk_category="write",
        )
        execute_request = ToolPermissionRequest(
            tool_name="run_command",
            arguments={},
            risk_category="execute",
        )
        external_request = ToolPermissionRequest(
            tool_name="api_call",
            arguments={},
            risk_category="external",
        )

        assert policy.evaluate(read_request).action == "allow"
        assert policy.evaluate(write_request).action == "deny"
        assert policy.evaluate(execute_request).action == "deny"
        assert policy.evaluate(external_request).action == "deny"

    def test_risk_based_policy_custom_config(self) -> None:
        policy = RiskBasedPolicy(
            read="allow",
            write="allow",
            execute="ask",
            external="deny",
        )

        read_request = ToolPermissionRequest(
            tool_name="read_file",
            arguments={},
            risk_category="read",
        )
        write_request = ToolPermissionRequest(
            tool_name="write_file",
            arguments={},
            risk_category="write",
        )
        execute_request = ToolPermissionRequest(
            tool_name="run_command",
            arguments={},
            risk_category="execute",
        )

        assert policy.evaluate(read_request).action == "allow"
        assert policy.evaluate(write_request).action == "allow"
        assert policy.evaluate(execute_request).action == "ask"

    def test_risk_based_policy_fallback_to_read(self) -> None:
        policy = RiskBasedPolicy()
        request = ToolPermissionRequest(
            tool_name="unknown_tool",
            arguments={},
            risk_category=None,
        )

        response = policy.evaluate(request)

        assert response.action == "allow"

    def test_tool_allowlist_policy(self) -> None:
        policy = ToolAllowlistPolicy(["safe_read", "safe_write"])

        allowed_request = ToolPermissionRequest(
            tool_name="safe_read",
            arguments={},
        )
        blocked_request = ToolPermissionRequest(
            tool_name="dangerous_tool",
            arguments={},
        )

        assert policy.evaluate(allowed_request).action == "allow"
        assert policy.evaluate(blocked_request).action == "deny"

    def test_tool_blocklist_policy(self) -> None:
        policy = ToolBlocklistPolicy(["dangerous_tool", "risky_call"])

        blocked_request = ToolPermissionRequest(
            tool_name="dangerous_tool",
            arguments={},
        )
        allowed_request = ToolPermissionRequest(
            tool_name="safe_read",
            arguments={},
        )

        assert policy.evaluate(blocked_request).action == "deny"
        assert policy.evaluate(allowed_request).action == "allow"


class TestCompositePolicy:
    """Tests for combining multiple policies."""

    def test_composite_allows_when_all_allow(self) -> None:
        policy = CompositePolicy([AllowAllPolicy(), AllowAllPolicy()])
        request = ToolPermissionRequest(
            tool_name="test",
            arguments={},
        )

        response = policy.evaluate(request)

        assert response.action == "allow"

    def test_composite_first_deny_wins(self) -> None:
        policy = CompositePolicy([AllowAllPolicy(), DenyAllPolicy()])
        request = ToolPermissionRequest(
            tool_name="test",
            arguments={},
        )

        response = policy.evaluate(request)

        assert response.action == "deny"

    def test_composite_order_matters(self) -> None:
        first_deny = CompositePolicy([DenyAllPolicy(), AllowAllPolicy()])
        first_allow = CompositePolicy([AllowAllPolicy(), DenyAllPolicy()])
        request = ToolPermissionRequest(
            tool_name="test",
            arguments={},
        )

        assert first_deny.evaluate(request).action == "deny"
        assert first_allow.evaluate(request).action == "deny"


class TestConditionalPolicy:
    """Tests for conditional policy routing."""

    def test_conditional_policy_then_branch(self) -> None:
        policy = ConditionalPolicy(
            predicate=lambda req: req.tool_name == "safe",
            then_policy=AllowAllPolicy(),
            else_policy=DenyAllPolicy(),
        )

        safe_request = ToolPermissionRequest(
            tool_name="safe",
            arguments={},
        )
        unsafe_request = ToolPermissionRequest(
            tool_name="unsafe",
            arguments={},
        )

        assert policy.evaluate(safe_request).action == "allow"
        assert policy.evaluate(unsafe_request).action == "deny"

    def test_conditional_policy_default_else(self) -> None:
        policy = ConditionalPolicy(
            predicate=lambda req: req.tool_name == "safe",
            then_policy=DenyAllPolicy(),
        )

        unsafe_request = ToolPermissionRequest(
            tool_name="unsafe",
            arguments={},
        )

        assert policy.evaluate(unsafe_request).action == "allow"


class TestRiskCategoryHelper:
    """Tests for risk category detection."""

    def test_read_tools(self) -> None:
        assert get_risk_category_for_tool("read_file") == "read"
        assert get_risk_category_for_tool("list_files") == "read"
        assert get_risk_category_for_tool("glob_files") == "read"
        assert get_risk_category_for_tool("search_text") == "read"

    def test_write_tools(self) -> None:
        assert get_risk_category_for_tool("write_file") == "write"
        assert get_risk_category_for_tool("edit_file") == "write"

    def test_execute_tools(self) -> None:
        assert get_risk_category_for_tool("run_command") == "execute"

    def test_unknown_tool_defaults_to_external(self) -> None:
        assert get_risk_category_for_tool("unknown") == "external"
        assert get_risk_category_for_tool("custom_api") == "external"


class TestProjectToolBoundaryPolicy:
    """Tests for project tool path and capability boundaries."""

    def test_allow_read_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_read=True)
            policy = ProjectToolBoundaryPolicy(context)

            request = ToolPermissionRequest(
                tool_name="read_file",
                arguments={"path": "test.txt"},
            )

            response = policy.evaluate(request)
            assert response.action == "allow"

    def test_deny_read_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_read=False)
            policy = ProjectToolBoundaryPolicy(context)

            request = ToolPermissionRequest(
                tool_name="read_file",
                arguments={"path": "test.txt"},
            )

            response = policy.evaluate(request)
            assert response.action == "deny"
            assert "read operations are disabled" in response.reason

    def test_allow_write_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_write=True)
            policy = ProjectToolBoundaryPolicy(context)

            request = ToolPermissionRequest(
                tool_name="write_file",
                arguments={"path": "test.txt", "content": "test"},
            )

            response = policy.evaluate(request)
            assert response.action == "allow"

    def test_deny_write_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_write=False)
            policy = ProjectToolBoundaryPolicy(context)

            request = ToolPermissionRequest(
                tool_name="write_file",
                arguments={"path": "test.txt", "content": "test"},
            )

            response = policy.evaluate(request)
            assert response.action == "deny"
            assert "write operations are disabled" in response.reason

    def test_allow_execute_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_execute=True)
            policy = ProjectToolBoundaryPolicy(context)

            request = ToolPermissionRequest(
                tool_name="run_command",
                arguments={"command": "echo", "args": ["hello"]},
            )

            response = policy.evaluate(request)
            assert response.action == "allow"

    def test_deny_execute_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_execute=False)
            policy = ProjectToolBoundaryPolicy(context)

            request = ToolPermissionRequest(
                tool_name="run_command",
                arguments={"command": "echo", "args": ["hello"]},
            )

            response = policy.evaluate(request)
            assert response.action == "deny"
            assert "command execution is disabled" in response.reason

    def test_deny_path_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_read=True)
            policy = ProjectToolBoundaryPolicy(context)

            request = ToolPermissionRequest(
                tool_name="read_file",
                arguments={"path": "../outside_workspace.txt"},
            )

            response = policy.evaluate(request)
            assert response.action == "deny"
            assert "outside workspace boundary" in response.reason

    def test_allow_path_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "subdir").mkdir()
            context = ToolRuntimeContext(workspace=workspace, allow_read=True)
            policy = ProjectToolBoundaryPolicy(context)

            request = ToolPermissionRequest(
                tool_name="read_file",
                arguments={"path": "subdir/file.txt"},
            )

            response = policy.evaluate(request)
            assert response.action == "allow"


class TestCreateProjectToolPolicy:
    """Tests for create_project_tool_policy helper."""

    def test_creates_boundary_policy_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_write=False)
            policy = create_project_tool_policy(context)

            request = ToolPermissionRequest(
                tool_name="write_file",
                arguments={"path": "test.txt"},
            )

            response = policy.evaluate(request)
            assert response.action == "deny"

    def test_composes_with_base_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_write=True)
            base_policy = ToolBlocklistPolicy(["write_file"])
            policy = create_project_tool_policy(context, base_policy=base_policy)

            request = ToolPermissionRequest(
                tool_name="write_file",
                arguments={"path": "test.txt"},
            )

            response = policy.evaluate(request)
            # Boundary allows, but blocklist denies
            assert response.action == "deny"


class TestPermissionPolicyToAuthorizationAdapter:
    """Tests for adapting new PermissionPolicy to old ToolAuthorizationPolicy."""

    def test_adapter_allow_passes_through(self) -> None:
        call_count = 0

        def test_tool() -> str:
            nonlocal call_count
            call_count += 1
            return "executed"

        adapter = PermissionPolicyToAuthorizationAdapter(AllowAllPolicy())
        registry = ToolRegistry([test_tool], authorization_policy=adapter)

        result = registry.execute("test_tool", {})

        assert result.error_code is None
        assert call_count == 1

    def test_adapter_deny_blocks_execution(self) -> None:
        call_count = 0

        def test_tool() -> str:
            nonlocal call_count
            call_count += 1
            return "executed"

        adapter = PermissionPolicyToAuthorizationAdapter(DenyAllPolicy())
        registry = ToolRegistry([test_tool], authorization_policy=adapter)

        result = registry.execute("test_tool", {})

        assert result.error_code == "permission_denied"
        assert call_count == 0

    def test_adapter_ask_blocks_execution(self) -> None:
        call_count = 0

        def test_tool() -> str:
            nonlocal call_count
            call_count += 1
            return "executed"

        adapter = PermissionPolicyToAuthorizationAdapter(AskPolicy())
        registry = ToolRegistry([test_tool], authorization_policy=adapter)

        result = registry.execute("test_tool", {})

        assert result.error_code == "permission_denied"
        assert call_count == 0
