"""Documentation contract tests for the published stable scope."""

from pathlib import Path


def test_readme_publishes_context_and_keeps_other_modules_experimental() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "0.3.0 稳定能力" in readme
    assert "单 Agent 同步工具调用" in readme
    assert "OpenAI 兼容" in readme
    assert "Agent.run_stream()" in readme
    assert "StreamingChatModel" in readme
    assert "ToolCallDelta" in readme
    assert "StreamEvent" in readme
    assert "TokenBudgetContext" in readme
    assert "InMemoryConversation" in readme
    assert "context_budget_exceeded" in readme
    assert "长期向量记忆、多 Agent 和 HTML 轨迹导出仍为实验性" in readme


def test_core_exports_stable_streaming_contracts() -> None:
    from core import StreamChunk, StreamEvent, StreamingChatModel, ToolCallDelta

    assert StreamChunk is not None
    assert StreamEvent is not None
    assert StreamingChatModel is not None
    assert ToolCallDelta is not None


def test_core_exports_stable_context_and_memory_contracts() -> None:
    from core import (
        ApproximateTokenCounter,
        ContextBudgetExceeded,
        ContextPolicy,
        ConversationMemory,
        InMemoryConversation,
        SummarizingContext,
        TokenBudgetContext,
        TokenCounter,
    )

    assert ApproximateTokenCounter is not None
    assert ContextBudgetExceeded is not None
    assert ContextPolicy is not None
    assert ConversationMemory is not None
    assert InMemoryConversation is not None
    assert SummarizingContext is not None
    assert TokenBudgetContext is not None
    assert TokenCounter is not None
