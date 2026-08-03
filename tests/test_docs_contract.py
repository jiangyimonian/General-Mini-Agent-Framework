"""Documentation contract tests for the published stable scope."""

from pathlib import Path

import pytest


def test_readme_publishes_stable_multi_agent_scope() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "1.1.0 稳定能力" in readme
    assert "单 Agent 同步工具调用" in readme
    assert "OpenAI 兼容" in readme
    assert "Agent.run_stream()" in readme
    assert "StreamingChatModel" in readme
    assert "ToolCallDelta" in readme
    assert "StreamEvent" in readme
    assert "TokenBudgetContext" in readme
    assert "InMemoryConversation" in readme
    assert "context_budget_exceeded" in readme
    assert "Judge" in readme
    assert "max_rounds" in readme
    assert "Debate.run_stream()" in readme
    assert "HTML 报告" in readme
    assert "结构化工具结果" in readme
    assert "工具授权" in readme
    assert "原生工具调用" in readme or "工具调用协议" in readme


def test_readme_documents_async_limitations() -> None:
    """README 必须说明同步工具取消限制。"""
    readme = Path("README.md").read_text(encoding="utf-8")

    # 0.6.0 异步能力
    assert "AsyncAgent" in readme or "异步 Agent" in readme
    # 同步工具取消限制说明
    assert "同步工具" in readme or "sync callable" in readme.lower()


def test_core_exports_stable_streaming_contracts() -> None:
    from general_mini_agent import StreamChunk, StreamEvent, StreamingChatModel, ToolCallDelta

    assert StreamChunk is not None
    assert StreamEvent is not None
    assert StreamingChatModel is not None
    assert ToolCallDelta is not None


def test_core_exports_stable_context_and_memory_contracts() -> None:
    from general_mini_agent import (
        ApproximateTokenCounter,
        ChromaMemoryStore,
        ContextBudgetExceeded,
        ContextPolicy,
        ConversationMemory,
        InMemoryConversation,
        InMemoryLongTermStore,
        LongTermMemoryStore,
        MemoryNamespace,
        MemoryQuery,
        MemoryRecord,
        MemoryRecordNotFound,
        MemoryStoreError,
        SummarizingContext,
        TokenBudgetContext,
        TokenCounter,
        build_memory_context,
        create_memory_record,
    )

    assert ApproximateTokenCounter is not None
    assert ContextBudgetExceeded is not None
    assert ContextPolicy is not None
    assert ConversationMemory is not None
    assert InMemoryConversation is not None
    assert InMemoryLongTermStore is not None
    assert LongTermMemoryStore is not None
    assert MemoryNamespace is not None
    assert MemoryQuery is not None
    assert MemoryRecord is not None
    assert MemoryRecordNotFound is not None
    assert MemoryStoreError is not None
    assert SummarizingContext is not None
    assert TokenBudgetContext is not None
    assert TokenCounter is not None
    assert ChromaMemoryStore is not None
    assert build_memory_context is not None
    assert create_memory_record is not None


def test_core_exports_stable_tool_contracts() -> None:
    from general_mini_agent import (
        JSONValue,
        ToolAuthorizationDecision,
        ToolAuthorizationPolicy,
        ToolAuthorizationRequest,
        ToolExecutionResult,
    )
    from general_mini_agent.tools import JSONValue as ToolJSONValue

    assert JSONValue is ToolJSONValue
    assert ToolAuthorizationDecision is not None
    assert ToolAuthorizationPolicy is not None
    assert ToolAuthorizationRequest is not None
    assert ToolExecutionResult is not None


def test_core_exports_stable_async_contracts() -> None:
    """测试异步符号导出。"""
    from general_mini_agent import (
        AsyncAgent,
        AsyncChatModel,
        AsyncLLM,
        AsyncStreamingChatModel,
        AsyncToolRegistry,
    )

    assert AsyncAgent is not None
    assert AsyncChatModel is not None
    assert AsyncLLM is not None
    assert AsyncStreamingChatModel is not None
    assert AsyncToolRegistry is not None


def test_core_exports_stable_event_contracts() -> None:
    """测试事件符号导出。"""
    from general_mini_agent import (
        EventCollector,
        EventSink,
        RunContext,
        RunEvent,
        RunEventEmitter,
    )

    assert RunContext is not None
    assert RunEvent is not None
    assert EventSink is not None
    assert EventCollector is not None
    assert RunEventEmitter is not None


def test_core_exports_stable_trace_json_contracts() -> None:
    """测试 JSON trace 符号导出。"""
    from general_mini_agent import (
        TraceDocument,
        export_trace_json,
        trace_from_json,
        trace_to_json,
    )

    assert TraceDocument is not None
    assert trace_to_json is not None
    assert trace_from_json is not None
    assert export_trace_json is not None


def test_core_exports_stable_trace_html_contracts() -> None:
    import general_mini_agent
    from general_mini_agent import (
        compare_traces_to_html,
        debate_to_html,
        export_trace,
        export_trace_html,
        render_html,
        trace_to_html,
    )

    expected_exports = {
        "compare_traces_to_html",
        "debate_to_html",
        "export_trace",
        "export_trace_html",
        "render_html",
        "trace_to_html",
    }
    assert expected_exports <= set(general_mini_agent.__all__)
    assert export_trace is export_trace_html
    assert all(
        (
            compare_traces_to_html,
            debate_to_html,
            render_html,
            trace_to_html,
        )
    )


@pytest.mark.parametrize(
    ("path", "required_text"),
    [
        ("pyproject.toml", ('version = "1.1.0"',)),
        ("README.md", ("显式检索", "不会自动写入")),
        (
            "demo/long_term_memory.py",
            ("ChromaMemoryStore", "MemoryNamespace", "MemoryQuery"),
        ),
    ],
)
def test_long_term_memory_release_contract(path, required_text) -> None:
    content = Path(path).read_text(encoding="utf-8")

    for text in required_text:
        assert text in content


def test_changelog_exists_and_contains_versions() -> None:
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")

    assert "## [0.4.1]" in changelog
    assert "## [0.4.0]" in changelog
    assert "### 新增" in changelog
    assert "release" in changelog.lower() or "发行" in changelog


def test_releasing_manual_exists_and_contains_key_steps() -> None:
    releasing = Path("docs/RELEASING.md").read_text(encoding="utf-8")

    assert "python -m pytest tests -v" in releasing
    assert "python -m build" in releasing
    assert "twine check" in releasing
    assert "git tag" in releasing
    assert "CI 失败" in releasing or "CI失败" in releasing


def test_live_smoke_is_explicit_and_contains_no_real_key() -> None:
    """Live smoke 脚本必须显式启用且不包含真实密钥。"""
    smoke = Path("demo/live_agent_smoke.py").read_text(encoding="utf-8")

    # 必须从环境变量读取密钥
    assert "GMAF_API_KEY" in smoke
    # 必须使用 Agent 和工具
    assert "Agent(" in smoke
    assert "@tool" in smoke
    assert "calculator" in smoke
    # 不能包含硬编码密钥
    assert "sk-" not in smoke
