"""Tool metadata, JSON schema generation, and Agent-local execution."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass
from types import UnionType
from typing import Any, Protocol, Union, get_args, get_origin

TYPE_MAP = {
    int: "integer",
    float: "number",
    str: "string",
    bool: "boolean",
    list: "array",
    dict: "object",
}

type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]


@dataclass(frozen=True)
class ToolExecutionResult:
    content: str
    value: JSONValue | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class ToolAuthorizationRequest:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolAuthorizationDecision:
    allowed: bool
    reason: str | None = None


class ToolAuthorizationPolicy(Protocol):
    def authorize(
        self,
        request: ToolAuthorizationRequest,
    ) -> ToolAuthorizationDecision: ...


def _is_json_value(value: Any) -> bool:
    """Recursively validate that value conforms to JSONValue."""
    if value is None:
        return True
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        try:
            json.dumps(value, allow_nan=False)
            return True
        except ValueError:
            return False
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(val)
            for key, val in value.items()
        )
    return False


def _serialize_result(value: Any) -> ToolExecutionResult:
    """Serialize tool result with deterministic JSON or fail closed."""
    if isinstance(value, str):
        return ToolExecutionResult(content=value, value=None)
    if _is_json_value(value):
        try:
            content = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
                separators=(",", ":"),
            )
            return ToolExecutionResult(content=content, value=value)
        except (TypeError, ValueError):
            pass
    return ToolExecutionResult(
        content="tool result is not valid JSON",
        value=None,
        error_code="serialization_failed",
    )


class Tool:
    """Description and legacy execution wrapper for one callable tool."""

    def __init__(
        self,
        func: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        self.func = func
        self.name = name or func.__name__
        self.description = description or self._extract_description()
        self.parameters = self._build_schema()

    def execute(self, **kwargs: Any) -> str:
        """Execute the tool and retain the legacy string-only result."""
        try:
            result = self.func(**kwargs)
            return str(result)
        except Exception as exc:
            return f"工具执行错误: {type(exc).__name__}: {exc}"

    def to_schema(self) -> dict[str, Any]:
        """Return the OpenAI function-calling schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": deepcopy(self.parameters),
            },
        }

    def _snapshot(self) -> Tool:
        snapshot = Tool(
            self.func,
            name=self.name,
            description=self.description,
        )
        snapshot.parameters = deepcopy(self.parameters)
        return snapshot

    def _extract_description(self) -> str:
        doc = self.func.__doc__
        if not doc:
            return ""
        return doc.strip().split("\n")[0]

    def _build_schema(self) -> dict[str, Any]:
        sig = inspect.signature(self.func)
        hints = self._get_type_hints()
        param_descs = self._parse_param_descriptions()

        properties: dict[str, dict[str, Any]] = {}
        required: list[str] = []

        for name, param in sig.parameters.items():
            if name == "self" or name == "cls":
                continue
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                continue

            schema = self._type_to_schema(hints.get(name, str))
            description = param_descs.get(name, "")
            if description:
                schema["description"] = description
            properties[name] = schema

            if param.default is inspect.Parameter.empty:
                required.append(name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def _get_type_hints(self) -> dict[str, Any]:
        try:
            return inspect.get_annotations(self.func)
        except Exception:
            return {}

    def _parse_param_descriptions(self) -> dict[str, str]:
        doc = self.func.__doc__
        if not doc:
            return {}

        descriptions: dict[str, str] = {}
        in_args = False
        for line in doc.split("\n"):
            stripped = line.strip()
            if stripped.startswith("Args:"):
                in_args = True
                continue
            if in_args:
                if stripped == "" or not stripped[0].isalpha():
                    in_args = False
                    continue
                match = re.match(r"(\w+)\s*:\s*(.+)", stripped)
                if match:
                    descriptions[match.group(1)] = match.group(2)
        return descriptions

    def _type_to_schema(self, tp: Any) -> dict[str, Any]:
        origin = get_origin(tp)
        args = get_args(tp)

        if origin in (Union, UnionType) and type(None) in args:
            non_none = [arg for arg in args if arg is not type(None)]
            if non_none:
                schema = self._type_to_schema(non_none[0])
                schema["nullable"] = True
                return schema

        if origin is list:
            item_schema = self._type_to_schema(args[0]) if args else {}
            return {"type": "array", "items": item_schema}

        if origin is dict:
            value_schema = self._type_to_schema(args[1]) if len(args) > 1 else {}
            return {"type": "object", "additionalProperties": value_schema}

        if tp in TYPE_MAP:
            return {"type": TYPE_MAP[tp]}

        return {"type": "string"}


class ToolRegistry:
    """A private registry owned by one Agent or caller."""

    def __init__(
        self,
        tools: Iterable[Tool | Callable[..., Any]] = (),
        *,
        authorization_policy: ToolAuthorizationPolicy | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._policy = authorization_policy
        for value in tools:
            self.register(value)

    def register(self, value: Tool | Callable[..., Any], **kwargs: Any) -> Tool:
        """Register a tool, reusing metadata attached by ``@tool``."""
        if isinstance(value, Tool):
            registered = value._snapshot()
        else:
            metadata = getattr(value, "__agent_tool__", None)
            if isinstance(metadata, Tool) and not kwargs:
                registered = metadata._snapshot()
            else:
                registered = Tool(value, **kwargs)

        if registered.name in self._tools:
            raise ValueError(f"duplicate tool name: {registered.name}")
        self._tools[registered.name] = registered
        return registered

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [registered.to_schema() for registered in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        registered = self.get(name)
        if registered is None:
            return ToolExecutionResult(
                content=f"unknown tool: {name}",
                error_code="unknown_tool",
            )

        try:
            inspect.signature(registered.func).bind(**arguments)
        except TypeError as exc:
            return ToolExecutionResult(
                content=f"invalid arguments for tool '{name}': {exc}",
                error_code="invalid_arguments",
            )

        if self._policy is not None:
            request = ToolAuthorizationRequest(
                name=name,
                arguments=dict(arguments),
            )
            try:
                decision = self._policy.authorize(request)
            except Exception:
                return ToolExecutionResult(
                    content="authorization error",
                    error_code="authorization_error",
                )
            if not decision.allowed:
                return ToolExecutionResult(
                    content="permission denied",
                    error_code="permission_denied",
                )

        try:
            result = registered.func(**arguments)
        except Exception as exc:
            return ToolExecutionResult(
                content=f"tool execution failed: {type(exc).__name__}: {exc}",
                error_code="execution_failed",
            )
        return _serialize_result(result)


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Callable[..., Any]:
    """Attach tool metadata without process-global registration."""

    def decorate(target: Callable[..., Any]) -> Callable[..., Any]:
        setattr(
            target,
            "__agent_tool__",
            Tool(target, name=name, description=description),
        )
        return target

    return decorate(func) if func is not None else decorate
