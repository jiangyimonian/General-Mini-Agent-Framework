"""测试会话管理和压缩。"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from general_mini_agent.compression import (
    AutoCompressingConversation,
    SimpleTruncationStrategy,
)
from general_mini_agent.memory import InMemoryConversation
from general_mini_agent.session import (
    Session,
    SessionMetadata,
    conversation_from_session,
    delete_session,
    get_session_dir,
    get_session_path,
    list_sessions,
    load_session,
    save_session,
)


def test_session_metadata() -> None:
    """测试会话元数据。"""
    m = SessionMetadata(
        name="test",
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-02T00:00:00",
        message_count=10,
        summary="test summary",
    )
    assert m.name == "test"
    assert m.message_count == 10


def test_session_roundtrip() -> None:
    """测试会话保存和加载。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 模拟用户目录
        with patch("general_mini_agent.session.Path.home", return_value=Path(tmpdir)):
            # 创建对话
            conv = InMemoryConversation()
            conv.add_messages([
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ])

            # 保存会话
            session = save_session("test-session", conv, "test summary")

            assert session.metadata.name == "test-session"
            assert session.metadata.message_count == 2
            assert len(session.messages) == 2

            # 加载会话
            loaded = load_session("test-session")
            assert loaded is not None
            assert loaded.metadata.name == "test-session"
            assert len(loaded.messages) == 2


def test_list_sessions() -> None:
    """测试列出会话。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("general_mini_agent.session.Path.home", return_value=Path(tmpdir)):
            # 确保会话目录空
            session_dir = get_session_dir()
            for f in session_dir.glob("*.json"):
                f.unlink()

            # 保存几个会话
            for i in range(3):
                conv = InMemoryConversation()
                conv.add_messages([{"role": "user", "content": f"test {i}"}])
                save_session(f"session-{i}", conv)

            # 列出会话
            sessions = list(list_sessions())
            assert len(sessions) == 3
            names = {s.name for s in sessions}
            assert names == {"session-0", "session-1", "session-2"}


def test_delete_session() -> None:
    """测试删除会话。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("general_mini_agent.session.Path.home", return_value=Path(tmpdir)):
            conv = InMemoryConversation()
            save_session("to-delete", conv)

            # 确认存在
            assert load_session("to-delete") is not None

            # 删除
            success = delete_session("to-delete")
            assert success is True

            # 确认已删除
            assert load_session("to-delete") is None


def test_conversation_from_session() -> None:
    """测试从会话创建对话。"""
    session = Session(
        metadata=SessionMetadata(
            name="test",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-02T00:00:00",
            message_count=2,
            summary="",
        ),
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )

    conv = conversation_from_session(session)
    context = conv.get_context()
    assert len(context) == 2


def test_simple_truncation() -> None:
    """测试简单截断策略。"""
    conv = InMemoryConversation()
    conv.add_messages([
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "msg 1"},
        {"role": "assistant", "content": "reply 1"},
        {"role": "user", "content": "msg 2"},
        {"role": "assistant", "content": "reply 2"},
        {"role": "user", "content": "msg 3"},
        {"role": "assistant", "content": "reply 3"},
    ])

    # 只保留 2 条最新消息（加上系统消息）
    strategy = SimpleTruncationStrategy(keep_recent=2)
    result = strategy.compress(conv.get_context(), 1)

    # 应该会触发压缩
    # 期望保留系统消息和最后 2 条消息
    assert result.compressed > 0
    assert len(result.messages) == 3  # 系统 + 最后 2 条用户/助理消息
    assert result.messages[-2]["content"] == "msg 3"
    assert result.messages[-1]["content"] == "reply 3"


def test_auto_compressing_conversation() -> None:
    """测试自动压缩对话。"""
    conv = AutoCompressingConversation()

    conv.add_messages([
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ])

    assert len(conv.get_context()) == 2

    # 手动压缩
    compressed = conv.compress_to(1000)
    assert len(compressed) >= 2  # 消息少，可能不需要压缩


def test_get_session_path() -> None:
    """测试会话路径生成。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("general_mini_agent.session.Path.home", return_value=Path(tmpdir)):
            path = get_session_path("test-session")
            assert "test-session" in path.name
            assert path.suffix == ".json"


def test_get_session_dir() -> None:
    """测试会话目录。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("general_mini_agent.session.Path.home", return_value=Path(tmpdir)):
            d = get_session_dir()
            assert d.exists()
            assert d.is_dir()
