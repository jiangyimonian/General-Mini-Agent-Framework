"""测试记忆系统"""

import pytest

from general_mini_agent.memory import InMemoryConversation, SlidingWindowMemory


class TestInMemoryConversation:
    def test_appends_batch_atomically(self):
        memory = InMemoryConversation()

        memory.add_messages([
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ])

        assert memory.get_context() == [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]

    def test_invalid_batch_does_not_partially_append(self):
        memory = InMemoryConversation([
            {"role": "user", "content": "existing"},
        ])

        with pytest.raises(ValueError, match="role"):
            memory.add_messages([
                {"role": "assistant", "content": "valid"},
                {"role": "invalid", "content": "bad"},
            ])

        assert memory.get_context() == [
            {"role": "user", "content": "existing"},
        ]

    def test_constructor_and_snapshots_are_defensive_copies(self):
        initial = [{
            "role": "assistant",
            "content": "answer",
            "metadata": {"source": "initial"},
        }]
        memory = InMemoryConversation(initial)

        initial[0]["metadata"]["source"] = "mutated input"
        snapshot = memory.get_context()
        snapshot[0]["metadata"]["source"] = "mutated snapshot"

        assert memory.get_context()[0]["metadata"]["source"] == "initial"

    def test_preserves_structured_message_fields(self):
        memory = InMemoryConversation()
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }],
        }

        memory.add_messages([message])

        assert memory.get_context() == [message]

    def test_clear_and_instance_state_are_isolated(self):
        first = InMemoryConversation([{"role": "user", "content": "one"}])
        second = InMemoryConversation([{"role": "user", "content": "two"}])

        first.clear()

        assert first.get_context() == []
        assert second.get_context() == [{"role": "user", "content": "two"}]


class TestSlidingWindowMemory:
    def test_add_and_get(self):
        m = SlidingWindowMemory(window_size=10)
        m.add("user", "你好")
        m.add("assistant", "你好！有什么可以帮助你的？")

        ctx = m.get_context()
        assert len(ctx) == 2
        assert ctx[0]["role"] == "user"
        assert ctx[0]["content"] == "你好"

    def test_window_trimming(self):
        m = SlidingWindowMemory(window_size=4)
        m.add("system", "你是助手")
        for i in range(6):
            m.add("user", f"消息{i}")
            m.add("assistant", f"回复{i}")

        ctx = m.get_context()
        assert len(ctx) <= 4

        # system 消息应保留
        assert ctx[0]["role"] == "system"

    def test_window_too_small(self):
        with pytest.raises(ValueError, match="至少为 2"):
            SlidingWindowMemory(window_size=1)

    def test_clear(self):
        m = SlidingWindowMemory(window_size=10)
        m.add("user", "你好")
        m.clear()
        assert len(m.get_context()) == 0

    def test_len(self):
        m = SlidingWindowMemory(window_size=10)
        assert len(m) == 0
        m.add("user", "你好")
        assert len(m) == 1

    def test_add_message_dict(self):
        m = SlidingWindowMemory(window_size=10)
        m.add_message({"role": "user", "content": "dict 消息"})
        ctx = m.get_context()
        assert ctx[0]["role"] == "user"


class TestSlidingWindowEdgeCases:
    def test_exact_window_size(self):
        """消息数刚好等于窗口大小时不丢弃"""
        m = SlidingWindowMemory(window_size=4)
        m.add("system", "sys")
        m.add("user", "u1")
        m.add("assistant", "a1")
        m.add("user", "u2")

        ctx = m.get_context()
        assert len(ctx) == 4

    def test_window_exceeded_by_one(self):
        """超出一条时，丢弃最早的非 system 消息"""
        m = SlidingWindowMemory(window_size=3)
        m.add("system", "sys")
        m.add("user", "u1")
        m.add("assistant", "a1")
        m.add("user", "u2")  # 超出 1 条

        ctx = m.get_context()
        assert len(ctx) == 3
        assert ctx[0]["role"] == "system"
        assert ctx[0]["content"] == "sys"
