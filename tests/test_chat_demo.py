"""Tests for the interactive chat demo's stable memory integration."""

from pathlib import Path

from demo.chat import clear_context
from general_mini_agent.memory import InMemoryConversation


def test_chat_demo_uses_automatic_memory_writeback_and_context_budget() -> None:
    source = Path("demo/chat.py").read_text(encoding="utf-8")

    assert "InMemoryConversation" in source
    assert "TokenBudgetContext" in source
    assert "LLM_CONTEXT_WINDOW" in source
    assert "LLM_RESERVED_OUTPUT_TOKENS" in source
    assert 'os.environ.get("LLM_CONTEXT_WINDOW", "65536")' not in source
    assert 'os.environ.get("LLM_RESERVED_OUTPUT_TOKENS", "4096")' not in source
    assert "record_exchange(" not in source


def test_clear_context_removes_recorded_messages() -> None:
    memory = InMemoryConversation([
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
    ])

    clear_context(memory)

    assert memory.get_context() == []
