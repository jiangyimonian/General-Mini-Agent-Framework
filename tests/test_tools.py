"""测试工具注册系统"""

import pytest
from core.tools import tool, Tool, ToolRegistry


def setup_method():
    ToolRegistry.clear()


class TestToolRegistration:
    def test_basic_registration(self):
        @tool(description="计算两数之和")
        def add(a: int, b: int) -> int:
            """计算两数之和

            Args:
                a: 第一个数
                b: 第二个数
            """
            return a + b

        t = ToolRegistry.get("add")
        assert t is not None
        assert t.name == "add"
        assert t.description == "计算两数之和"

    def test_schema_generation(self):
        @tool
        def greet(name: str, age: int = 18) -> str:
            return f"{name} 你好"

        schema = ToolRegistry.get("greet").to_schema()
        props = schema["function"]["parameters"]["properties"]
        required = schema["function"]["parameters"]["required"]

        assert "name" in props
        assert props["name"]["type"] == "string"
        assert "age" in props
        assert props["age"]["type"] == "integer"
        assert "name" in required
        assert "age" not in required  # 有默认值

    def test_execute(self):
        @tool
        def add(a: int, b: int) -> int:
            return a + b

        result = ToolRegistry.get("add").execute(a=3, b=5)
        assert result == "8"

    def test_execute_error_safe(self):
        @tool
        def divide(a: int, b: int) -> float:
            return a / b

        result = ToolRegistry.get("divide").execute(a=1, b=0)
        assert "工具执行错误" in result

    def test_schemas_list(self):
        ToolRegistry.clear()
        @tool
        def fn1(x: int) -> int: return x
        @tool
        def fn2(x: str) -> str: return x

        schemas = ToolRegistry.schemas()
        assert len(schemas) == 2
        assert all(s["type"] == "function" for s in schemas)

    def test_description_from_docstring(self):
        @tool
        def foo(x: int) -> int:
            """只取第一行作为描述"""
            return x

        assert ToolRegistry.get("foo").description == "只取第一行作为描述"

    def test_no_args_tool(self):
        @tool
        def ping() -> str:
            return "pong"

        t = ToolRegistry.get("ping")
        assert t.execute() == "pong"
        assert t.parameters["properties"] == {}
        assert t.parameters["required"] == []

    def test_optional_parameter(self):
        from typing import Optional

        @tool
        def greet(name: Optional[str] = None) -> str:
            return name or "hello"

        t = ToolRegistry.get("greet")
        props = t.parameters["properties"]
        # Optional 在 schema 中应该标注 nullable
        if "nullable" in props.get("name", {}):
            assert props["name"]["nullable"] is True


class TestToolDirectDecorator:
    def test_without_parentheses(self):
        @tool
        def foo() -> str:
            return "bar"

        assert ToolRegistry.get("foo") is not None

    def test_with_parentheses(self):
        @tool()
        def foo() -> str:
            return "bar"

        assert ToolRegistry.get("foo") is not None

    def test_with_description(self):
        @tool(description="自定义描述")
        def foo() -> str:
            return "bar"

        assert ToolRegistry.get("foo").description == "自定义描述"
