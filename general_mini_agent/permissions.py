"""权限与安全边界系统。

提供结构化权限请求、风险分类和可扩展策略框架。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict

from .tools import ToolAuthorizationDecision, ToolAuthorizationRequest

# ─── 类型定义 ────────────────────────────────────────────────

RiskCategory = Literal["read", "write", "execute", "external"]
PermissionAction = Literal["allow", "deny", "ask"]


# ─── 权限请求与响应 ─────────────────────────────────────────────

@dataclass(frozen=True)
class ToolPermissionRequest:
    """结构化工具权限请求。

    包含工具调用的完整上下文，供权限策略评估使用。
    """

    tool_name: str
    arguments: dict[str, Any]
    risk_category: RiskCategory | None = None
    description: str | None = None
    context: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolPermissionResponse:
    """工具权限响应。

    权限策略的返回值，指示是否允许工具执行。
    """

    action: PermissionAction
    reason: str | None = None


# ─── 事件类型 ─────────────────────────────────────────────────

class PermissionRequestEvent(TypedDict):
    """权限请求事件类型。

    当工具需要权限决策时发射此事件。
    """

    type: Literal["permission_request"]
    tool_name: str
    arguments: dict[str, Any]
    risk_category: str | None
    description: str | None
    context: dict[str, Any] | None


class PermissionResponseEvent(TypedDict):
    """权限响应事件类型。

    当权限决策已做出时发射此事件。
    """

    type: Literal["permission_response"]
    tool_name: str
    action: str
    reason: str | None


# ─── 权限策略协议 ─────────────────────────────────────────────

class PermissionPolicy(Protocol):
    """权限策略协议。

    实现此协议来定义自定义权限规则。
    """

    def evaluate(self, request: ToolPermissionRequest) -> ToolPermissionResponse:
        """评估权限请求并返回决策。

        Args:
            request: 完整的工具权限请求

        Returns:
            包含动作和可选原因的响应
        """
        ...


# ─── 内置策略实现 ─────────────────────────────────────────────

class AllowAllPolicy:
    """总是允许所有工具调用的策略。"""

    def evaluate(self, request: ToolPermissionRequest) -> ToolPermissionResponse:
        return ToolPermissionResponse(action="allow")


class DenyAllPolicy:
    """总是拒绝所有工具调用的策略。"""

    def __init__(self, reason: str | None = "denied by policy"):
        self._reason = reason

    def evaluate(self, request: ToolPermissionRequest) -> ToolPermissionResponse:
        return ToolPermissionResponse(action="deny", reason=self._reason)


class AskPolicy:
    """总是询问的策略。

    发射权限请求事件，由外部监听器处理决策。
    """

    def __init__(self, reason: str | None = "requires user approval"):
        self._reason = reason

    def evaluate(self, request: ToolPermissionRequest) -> ToolPermissionResponse:
        return ToolPermissionResponse(action="ask", reason=self._reason)


class RiskBasedPolicy:
    """基于风险类别的策略。

    为每种风险类别配置不同的默认动作。
    """

    def __init__(
        self,
        read: PermissionAction = "allow",
        write: PermissionAction = "deny",
        execute: PermissionAction = "deny",
        external: PermissionAction = "deny",
    ):
        self.rules: dict[RiskCategory, PermissionAction] = {
            "read": read,
            "write": write,
            "execute": execute,
            "external": external,
        }

    def evaluate(self, request: ToolPermissionRequest) -> ToolPermissionResponse:
        category = request.risk_category or "read"
        action = self.rules.get(category, "deny")
        return ToolPermissionResponse(
            action=action,
            reason=f"{category} action {action} by risk-based policy",
        )


class ToolAllowlistPolicy:
    """基于工具名允许列表的策略。"""

    def __init__(self, allowed_tools: list[str]):
        self.allowed_tools = set(allowed_tools)

    def evaluate(self, request: ToolPermissionRequest) -> ToolPermissionResponse:
        if request.tool_name in self.allowed_tools:
            return ToolPermissionResponse(
                action="allow",
                reason=f"tool '{request.tool_name}' is in allowlist",
            )
        return ToolPermissionResponse(
            action="deny",
            reason=f"tool '{request.tool_name}' is not in allowlist",
        )


class ToolBlocklistPolicy:
    """基于工具名阻止列表的策略。"""

    def __init__(self, blocked_tools: list[str]):
        self.blocked_tools = set(blocked_tools)

    def evaluate(self, request: ToolPermissionRequest) -> ToolPermissionResponse:
        if request.tool_name in self.blocked_tools:
            return ToolPermissionResponse(
                action="deny",
                reason=f"tool '{request.tool_name}' is in blocklist",
            )
        return ToolPermissionResponse(
            action="allow",
            reason=f"tool '{request.tool_name}' is not in blocklist",
        )


class CompositePolicy:
    """组合多个策略的策略。

    策略按顺序评估，第一个非 "allow" 的结果立即返回。
    如果所有策略都允许，则最终允许。
    """

    def __init__(self, policies: list[PermissionPolicy]):
        self.policies = list(policies)

    def evaluate(self, request: ToolPermissionRequest) -> ToolPermissionResponse:
        for policy in self.policies:
            response = policy.evaluate(request)
            if response.action != "allow":
                return response
        return ToolPermissionResponse(
            action="allow",
            reason="allowed by all composite policies",
        )


class ConditionalPolicy:
    """条件策略。

    根据谓词选择使用哪个策略。
    """

    def __init__(
        self,
        predicate: callable[[ToolPermissionRequest], bool],
        then_policy: PermissionPolicy,
        else_policy: PermissionPolicy | None = None,
    ):
        self.predicate = predicate
        self.then_policy = then_policy
        self.else_policy = else_policy or AllowAllPolicy()

    def evaluate(self, request: ToolPermissionRequest) -> ToolPermissionResponse:
        if self.predicate(request):
            return self.then_policy.evaluate(request)
        return self.else_policy.evaluate(request)


# ─── 桥接适配器 ───────────────────────────────────────────────

class PermissionPolicyToAuthorizationAdapter:
    """将新 PermissionPolicy 适配到旧 ToolAuthorizationPolicy。

    保持与现有 ToolAuthorizationPolicy 协议的向后兼容。
    """

    def __init__(
        self,
        policy: PermissionPolicy,
        risk_category: RiskCategory | None = None,
        emitter: Any | None = None,
    ):
        self.policy = policy
        self.risk_category = risk_category
        self.emitter = emitter

    def authorize(self, request: ToolAuthorizationRequest) -> ToolAuthorizationDecision:
        permission_req = ToolPermissionRequest(
            tool_name=request.name,
            arguments=request.arguments,
            risk_category=self.risk_category,
        )

        # 发射权限请求事件
        if self.emitter:
            self.emitter.emit(
                "permission_request",
                {
                    "tool_name": permission_req.tool_name,
                    "arguments": permission_req.arguments,
                    "risk_category": permission_req.risk_category,
                    "description": permission_req.description,
                    "context": permission_req.context,
                },
            )

        response = self.policy.evaluate(permission_req)

        # 发射权限响应事件
        if self.emitter:
            self.emitter.emit(
                "permission_response",
                {
                    "tool_name": permission_req.tool_name,
                    "action": response.action,
                    "reason": response.reason,
                },
            )

        if response.action == "allow":
            return ToolAuthorizationDecision(allowed=True, reason=response.reason)
        # deny 或 ask 都拒绝（ask 模式需要上层异步处理）
        return ToolAuthorizationDecision(allowed=False, reason=response.reason)
