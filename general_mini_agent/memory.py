"""滑动窗口上下文与 ChromaDB 长期记忆组件。"""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

_MESSAGE_ROLES = {"system", "user", "assistant", "tool"}


class ConversationMemory(Protocol):
    """Stored conversation history used by an Agent."""

    def get_context(self) -> list[dict[str, Any]]: ...

    def add_messages(
        self,
        messages: Sequence[Mapping[str, Any]],
    ) -> None: ...

    def clear(self) -> None: ...


class InMemoryConversation:
    """Conversation history with validated atomic batch writes."""

    def __init__(
        self,
        initial_messages: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self._messages: list[dict[str, Any]] = []
        if initial_messages:
            self.add_messages(initial_messages)

    def add_messages(
        self,
        messages: Sequence[Mapping[str, Any]],
    ) -> None:
        copied = [
            _copy_conversation_message(message, index)
            for index, message in enumerate(messages)
        ]
        self._messages.extend(copied)

    def get_context(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)


def _copy_conversation_message(
    message: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    if not isinstance(message, Mapping):
        raise TypeError(f"message at index {index} must be a mapping")
    copied = copy.deepcopy(dict(message))
    role = copied.get("role")
    if role not in _MESSAGE_ROLES:
        raise ValueError(f"message at index {index} has invalid role")
    if "content" not in copied:
        raise ValueError(f"message at index {index} is missing content")
    if not isinstance(copied["content"], str) and copied["content"] is not None:
        raise TypeError(f"message at index {index} has invalid content")
    return copied

# ─── 消息模型 ───────────────────────────────────────────────


@dataclass
class Message:
    role: str       # system / user / assistant / tool
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


# ─── 短期记忆：滑动窗口 ─────────────────────────────────────


class SlidingWindowMemory:
    """短期记忆：维护消息列表，超出窗口大小时丢弃最早的非 system 消息

    当超出窗口时，丢弃最早的 user/assistant/tool 消息对（保留 system 提示词）
    """

    def __init__(self, window_size: int = 20):
        if window_size < 2:
            raise ValueError("window_size 至少为 2")
        self.window_size = window_size
        self.messages: list[dict] = []

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self._trim()

    def add_message(self, msg: dict) -> None:
        """直接添加 dict 格式的消息"""
        self.messages.append(msg)
        self._trim()

    def get_context(self) -> list[dict]:
        """获取当前上下文消息列表"""
        return list(self.messages)

    def clear(self) -> None:
        self.messages.clear()

    def _trim(self) -> None:
        """超出窗口时，丢弃最早的非 system 消息"""
        if len(self.messages) <= self.window_size:
            return

        # 找到第一个非 system 消息的位置
        non_system_start = 0
        for i, m in enumerate(self.messages):
            if m["role"] != "system":
                non_system_start = i
                break

        # 从非 system 开始丢弃
        to_remove = len(self.messages) - self.window_size
        if non_system_start < len(self.messages):
            remove_end = min(non_system_start + to_remove, len(self.messages))
            self.messages = (
                self.messages[:non_system_start]
                + self.messages[remove_end:]
            )

    def __len__(self) -> int:
        return len(self.messages)


# ─── 长期记忆：ChromaDB ────────────────────────────────────


class LongTermMemory:
    """长期记忆：基于 ChromaDB 的向量检索

    存储重要信息，支持语义检索。ChromaDB 为可选依赖。
    """

    def __init__(self, persist_dir: str = "~/.agent_memory"):
        self.persist_dir = os.path.expanduser(persist_dir)
        self._collection = None
        self._client = None

    def _ensure_db(self):
        """延迟初始化 ChromaDB"""
        if self._collection is not None:
            return

        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "ChromaDB 未安装。请执行: pip install chromadb"
            )

        self._client = chromadb.PersistentClient(path=self.persist_dir)
        self._collection = self._client.get_or_create_collection(
            name="agent_memory",
            metadata={"hnsw:space": "cosine"},
        )

    def store(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        """存储一条记忆，返回 ID"""
        self._ensure_db()
        import uuid

        doc_id = str(uuid.uuid4())
        self._collection.add(
            documents=[content],
            metadatas=[metadata or {}],
            ids=[doc_id],
        )
        return doc_id

    def query(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """检索与 query 最相关的记忆"""
        self._ensure_db()
        if self._collection.count() == 0:
            return []

        results = self._collection.query(
            query_texts=[query],
            n_results=min(top_k, self._collection.count()),
        )

        output = []
        for i in range(len(results["ids"][0])):
            output.append({
                "id": results["ids"][0][i],
                "content": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i] if results.get("distances") else 0,
            })
        return output

    def count(self) -> int:
        """记忆总数"""
        if self._collection is None:
            return 0
        return self._collection.count()

    def clear(self) -> None:
        if self._collection is not None:
            self._collection.delete(where={})
