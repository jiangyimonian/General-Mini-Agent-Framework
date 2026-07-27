"""Documentation contract tests for the published stable scope."""

from pathlib import Path

import pytest


def test_readme_publishes_stable_multi_agent_scope() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "0.4.0 稳定能力" in readme
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
    assert "HTML 轨迹导出仍为实验性" in readme


def test_core_exports_stable_streaming_contracts() -> None:
    from core import StreamChunk, StreamEvent, StreamingChatModel, ToolCallDelta

    assert StreamChunk is not None
    assert StreamEvent is not None
    assert StreamingChatModel is not None
    assert ToolCallDelta is not None


def test_core_exports_stable_context_and_memory_contracts() -> None:
    from core import (
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


@pytest.mark.parametrize(
    ("path", "required_text"),
    [
        ("pyproject.toml", ('version = "0.4.0"',)),
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
