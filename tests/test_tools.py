"""Tests for local tool registration, schemas, and execution."""

from typing import Any

import pytest

from core.tools import ToolRegistry, tool


class TestToolRegistration:
    def test_decorated_function_metadata_is_snapshotted_per_registry(self):
        @tool(name="add_numbers", description="Add two values")
        def add(a: int, b: int) -> int:
            return a + b

        first_registry = ToolRegistry([add])
        second_registry = ToolRegistry([add])

        first_tool = first_registry.get("add_numbers")
        second_tool = second_registry.get("add_numbers")
        attached_tool = getattr(add, "__agent_tool__")

        assert first_tool is not None
        assert second_tool is not None
        assert first_tool is not attached_tool
        assert second_tool is not attached_tool
        assert first_tool is not second_tool

        first_tool.parameters["properties"]["a"]["type"] = "string"
        first_schema = first_registry.schemas()[0]
        first_schema["function"]["parameters"]["properties"]["b"]["type"] = "boolean"

        second_schema = second_registry.schemas()[0]
        assert second_tool.parameters["properties"]["a"]["type"] == "integer"
        assert second_schema["function"]["parameters"]["properties"]["a"]["type"] == "integer"
        assert second_schema["function"]["parameters"]["properties"]["b"]["type"] == "integer"
        first_schema_after_second_registry = first_registry.schemas()[0]
        first_parameters = first_schema_after_second_registry["function"]["parameters"]
        first_properties = first_parameters["properties"]
        assert first_properties["b"]["type"] == "integer"

    def test_schema_contains_parameter_types(self):
        def configure(name: str, count: int, ratio: float, enabled: bool) -> str:
            return name

        properties = ToolRegistry([configure]).schemas()[0]["function"]["parameters"]["properties"]

        assert properties == {
            "name": {"type": "string"},
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
            "enabled": {"type": "boolean"},
        }

    def test_schema_marks_only_parameters_without_defaults_as_required(self):
        def configure(required: str, optional: int = 1, also_optional: bool = False) -> str:
            return required

        parameters = ToolRegistry([configure]).schemas()[0]["function"]["parameters"]

        assert parameters["required"] == ["required"]
        assert set(parameters["properties"]) == {"required", "optional", "also_optional"}

    def test_schema_extracts_description_and_parameter_descriptions(self):
        def add(a: int, b: int) -> int:
            """Add two integers.

            Args:
                a: First integer.
                b: Second integer.
            """
            return a + b

        schema = ToolRegistry([add]).schemas()[0]
        parameters = schema["function"]["parameters"]

        assert schema["function"]["description"] == "Add two integers."
        assert parameters["properties"]["a"]["description"] == "First integer."
        assert parameters["properties"]["b"]["description"] == "Second integer."

    def test_optional_parameter_is_nullable_and_not_required(self):
        def greet(name: str | None = None) -> str:
            return name or "hello"

        parameters = ToolRegistry([greet]).schemas()[0]["function"]["parameters"]

        assert parameters["properties"]["name"] == {
            "type": "string",
            "nullable": True,
        }
        assert parameters["required"] == []

    def test_no_argument_tool_has_empty_parameter_schema(self):
        def ping() -> str:
            return "pong"

        parameters = ToolRegistry([ping]).schemas()[0]["function"]["parameters"]

        assert parameters == {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def test_registries_with_same_name_keep_independent_implementations(self):
        @tool(name="same")
        def first() -> str:
            return "first"

        @tool(name="same")
        def second() -> str:
            return "second"

        first_registry = ToolRegistry([first])
        second_registry = ToolRegistry([second])

        assert first_registry.execute("same", {}).content == "first"
        assert second_registry.execute("same", {}).content == "second"

    def test_invalid_arguments_return_structured_failure(self):
        def add(a: int, b: int) -> int:
            return a + b

        result = ToolRegistry([add]).execute("add", {"a": 1})

        assert result.error_code == "invalid_arguments"
        assert result.content

    def test_unknown_tool_returns_structured_failure(self):
        result = ToolRegistry().execute("missing", {})

        assert result.error_code == "unknown_tool"
        assert "missing" in result.content

    def test_tool_exception_returns_structured_failure(self):
        def explode() -> str:
            raise RuntimeError("boom")

        result = ToolRegistry([explode]).execute("explode", {})

        assert result.error_code == "execution_failed"
        assert "boom" in result.content

    def test_type_error_inside_tool_body_is_execution_failure(self):
        def explode() -> str:
            raise TypeError("body failure")

        result = ToolRegistry([explode]).execute("explode", {})

        assert result.error_code == "execution_failed"
        assert "body failure" in result.content

    def test_duplicate_names_in_one_registry_raise(self):
        def first() -> str:
            return "first"

        def second() -> str:
            return "second"

        first.__name__ = "same"
        second.__name__ = "same"

        with pytest.raises(ValueError, match=r"^duplicate tool name: same$"):
            ToolRegistry([first, second])

    def test_successful_execution_stringifies_result(self):
        def answer() -> int:
            return 42

        result = ToolRegistry([answer]).execute("answer", {})

        assert result.content == "42"
        assert result.error_code is None

    def test_tool_execute_keeps_legacy_string_behavior(self):
        def add(a: int, b: int) -> int:
            return a + b

        registered = ToolRegistry([add]).get("add")

        assert registered is not None
        assert registered.execute(a=3, b=5) == "8"

    def test_schemas_and_list_are_registry_local(self):
        def first(value: int) -> int:
            return value

        def second(value: str) -> str:
            return value

        first_registry = ToolRegistry([first])
        second_registry = ToolRegistry([second])

        assert [item.name for item in first_registry.list()] == ["first"]
        assert [item.name for item in second_registry.list()] == ["second"]
        assert first_registry.schemas()[0]["function"]["name"] == "first"


class TestStructuredToolResult:
    """Tests for JSON-preserving tool results and serialization failures."""

    def test_dict_result_preserves_value_and_deterministic_json(self) -> None:
        def fetch() -> dict[str, Any]:
            return {"items": [1, True, None], "status": "ok"}

        result = ToolRegistry([fetch]).execute("fetch", {})

        assert result.error_code is None
        assert result.content == '{"items":[1,true,null],"status":"ok"}'
        assert result.value == {"items": [1, True, None], "status": "ok"}

    def test_string_result_remains_unmodified(self) -> None:
        def greet() -> str:
            return "hello world"

        result = ToolRegistry([greet]).execute("greet", {})

        assert result.error_code is None
        assert result.content == "hello world"
        assert result.value is None

    @pytest.mark.parametrize(
        "invalid_value",
        [
            object(),
            float("nan"),
            {1: "value"},
        ],
        ids=["object", "nan", "non_string_key"],
    )
    def test_non_json_result_returns_serialization_failed(
        self, invalid_value: Any
    ) -> None:
        def broken() -> Any:
            return invalid_value

        result = ToolRegistry([broken]).execute("broken", {})

        assert result.error_code == "serialization_failed"
        assert result.content == "tool result is not valid JSON"
        assert result.value is None


class TestToolDecorator:
    def test_decorator_forms_attach_metadata_without_global_registration(self):
        empty_registry = ToolRegistry()

        @tool
        def direct() -> str:
            return "direct"

        @tool()
        def wrapped() -> str:
            return "wrapped"

        @tool(name="renamed", description="custom")
        def configured() -> str:
            return "configured"

        assert empty_registry.list() == []
        assert direct.__agent_tool__.name == "direct"
        assert wrapped.__agent_tool__.name == "wrapped"
        assert configured.__agent_tool__.name == "renamed"
        assert configured.__agent_tool__.description == "custom"
