"""工具注册、JSON Schema 生成与安全执行封装。"""

from __future__ import annotations

import inspect
import re
from typing import Any, Callable, get_origin, get_args, Union

TYPE_MAP = {
    int: "integer",
    float: "number",
    str: "string",
    bool: "boolean",
    list: "array",
    dict: "object",
}


# ─── Tool 类 ────────────────────────────────────────────────


class Tool:
    """单个工具的封装"""

    def __init__(
        self,
        func: Callable,
        name: str | None = None,
        description: str | None = None,
    ):
        self.func = func
        self.name = name or func.__name__
        self.description = description or self._extract_description()
        self.parameters = self._build_schema()

    def execute(self, **kwargs: Any) -> str:
        """执行工具，异常安全，统一返回字符串"""
        try:
            result = self.func(**kwargs)
            return str(result)
        except Exception as e:
            return f"工具执行错误: {type(e).__name__}: {e}"

    def to_schema(self) -> dict:
        """生成 LLM function calling 用的 JSON Schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    # ── 内部 ────────────────────────────────────────────

    def _extract_description(self) -> str:
        """从文档字符串中提取简短描述（第一行）"""
        doc = self.func.__doc__
        if not doc:
            return ""
        return doc.strip().split("\n")[0]

    def _build_schema(self) -> dict:
        """从函数签名 + 类型注解 → JSON Schema"""
        sig = inspect.signature(self.func)
        hints = self._get_type_hints()
        param_descs = self._parse_param_descriptions()

        properties = {}
        required = []

        for name, param in sig.parameters.items():
            if name == "self" or name == "cls":
                continue

            if param.kind == inspect.Parameter.VAR_KEYWORD:
                continue

            schema = self._type_to_schema(hints.get(name, str))
            desc = param_descs.get(name, "")
            if desc:
                schema["description"] = desc

            properties[name] = schema

            # 没有默认值 → required
            if param.default is inspect.Parameter.empty:
                required.append(name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def _get_type_hints(self) -> dict:
        try:
            return inspect.get_annotations(self.func)
        except Exception:
            return {}

    def _parse_param_descriptions(self) -> dict[str, str]:
        """从 Args: 段落提取参数描述"""
        doc = self.func.__doc__
        if not doc:
            return {}

        descs: dict[str, str] = {}
        # 匹配 Args: 下的 参数名: 描述 行
        in_args = False
        for line in doc.split("\n"):
            stripped = line.strip()
            if stripped.startswith("Args:") or stripped.startswith("Args:"):
                in_args = True
                continue
            if in_args:
                if stripped == "" or not stripped[0].isalpha():
                    in_args = False
                    continue
                match = re.match(r"(\w+)\s*:\s*(.+)", stripped)
                if match:
                    descs[match.group(1)] = match.group(2)
        return descs

    def _type_to_schema(self, tp: type) -> dict:
        """Python 类型 → JSON Schema type"""
        origin = get_origin(tp)
        args = get_args(tp)

        # Optional[X] → X + nullable
        if origin is Union and type(None) in args:
            non_none = [a for a in args if a is not type(None)]
            if non_none:
                schema = self._type_to_schema(non_none[0])
                schema["nullable"] = True
                return schema

        # list[X]
        if origin is list:
            item_schema = self._type_to_schema(args[0]) if args else {}
            return {"type": "array", "items": item_schema}

        # dict[str, X]
        if origin is dict:
            value_schema = self._type_to_schema(args[1]) if len(args) > 1 else {}
            return {"type": "object", "additionalProperties": value_schema}

        if tp in TYPE_MAP:
            return {"type": TYPE_MAP[tp]}

        return {"type": "string"}  # fallback


# ─── 全局注册表 ──────────────────────────────────────────────


class ToolRegistry:
    """全局工具注册表（单例）"""
    _tools: dict[str, Tool] = {}

    @classmethod
    def register(cls, func: Callable | None = None, **kwargs) -> Tool:
        """注册一个工具，返回 Tool 实例"""
        tool = Tool(func, **kwargs)  # type: ignore
        cls._tools[tool.name] = tool
        return tool

    @classmethod
    def get(cls, name: str) -> Tool | None:
        return cls._tools.get(name)

    @classmethod
    def list(cls) -> list[Tool]:
        return list(cls._tools.values())

    @classmethod
    def schemas(cls) -> list[dict]:
        """获取所有工具 schema（给 LLM 用）"""
        return [t.to_schema() for t in cls._tools.values()]

    @classmethod
    def clear(cls) -> None:
        cls._tools.clear()


# ─── 装饰器 ─────────────────────────────────────────────────


def tool(name: str | None = None, description: str | None = None):
    """装饰器：将函数注册为工具

    Usage:
        @tool
        def my_func(x: int) -> str: ...

        @tool(description="做某事")
        def my_func(x: int) -> str: ...
    """
    def decorator(func: Callable) -> Callable:
        ToolRegistry.register(func, name=name, description=description)
        return func
    return decorator


# 兼容无参数调用 @tool
def _tool_direct(func: Callable) -> Callable:
    ToolRegistry.register(func)
    return func

# 让 @tool 同时支持 @tool 和 @tool() 两种写法
_tool_wrapper = tool
tool = lambda *a, **kw: _tool_direct(*a, **kw) if (a and callable(a[0])) else _tool_wrapper(*a, **kw)
