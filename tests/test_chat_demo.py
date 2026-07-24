"""Tests for the interactive chat demo's short-term memory helpers."""

from core.memory import SlidingWindowMemory
from demo.chat import clear_context, record_exchange


def test_record_exchange_adds_one_user_assistant_pair() -> None:
    memory = SlidingWindowMemory(window_size=4)

    record_exchange(memory, "first question", "first answer")

    assert memory.get_context() == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
    ]


def test_clear_context_removes_recorded_messages() -> None:
    memory = SlidingWindowMemory(window_size=4)
    memory.add("user", "old question")
    memory.add("assistant", "old answer")

    clear_context(memory)

    assert memory.get_context() == []
