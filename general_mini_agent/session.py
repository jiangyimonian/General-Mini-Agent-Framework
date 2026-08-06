"""会话存储与会话管理。

提供会话的保存、加载、列出和删除功能。
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .memory import ConversationMemory, InMemoryConversation


@dataclass
class SessionMetadata:
    """会话元数据。"""

    name: str
    created_at: str
    updated_at: str
    message_count: int
    summary: str = ""


@dataclass
class Session:
    """完整会话数据。"""

    metadata: SessionMetadata
    messages: list[dict[str, Any]]


def get_session_dir() -> Path:
    """获取会话存储目录。

    Returns:
        会话存储目录路径
    """
    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        if app_data:
            base_dir = Path(app_data) / "gmaf" / "sessions"
        else:
            base_dir = Path.home() / ".gmaf" / "sessions"
    else:
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_data_home:
            base_dir = Path(xdg_data_home) / "gmaf" / "sessions"
        else:
            base_dir = Path.home() / ".gmaf" / "sessions"

    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_session_path(name: str) -> Path:
    """获取会话文件路径。

    Args:
        name: 会话名称

    Returns:
        会话文件路径
    """
    safe_name = "".join(c for c in name if c.isalnum() or c in "._-")
    return get_session_dir() / f"{safe_name}.json"


def load_session(name: str) -> Session | None:
    """加载会话。

    Args:
        name: 会话名称

    Returns:
        会话对象，如果不存在则返回 None
    """
    path = get_session_path(name)
    if not path.exists():
        return None

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        metadata = SessionMetadata(
            name=data.get("metadata", {}).get("name", name),
            created_at=data.get("metadata", {}).get("created_at", ""),
            updated_at=data.get("metadata", {}).get("updated_at", ""),
            message_count=data.get("metadata", {}).get("message_count", 0),
            summary=data.get("metadata", {}).get("summary", ""),
        )

        messages = data.get("messages", [])
        return Session(metadata=metadata, messages=messages)
    except Exception:
        return None


def save_session(name: str, conversation: ConversationMemory, summary: str = "") -> Session:
    """保存会话。

    Args:
        name: 会话名称
        conversation: 对话记忆
        summary: 会话摘要

    Returns:
        保存后的会话对象
    """
    messages = list(conversation.get_context())

    created_at = datetime.now().isoformat()
    updated_at = created_at

    existing = load_session(name)
    if existing:
        created_at = existing.metadata.created_at

    metadata = SessionMetadata(
        name=name,
        created_at=created_at,
        updated_at=updated_at,
        message_count=len(messages),
        summary=summary,
    )

    session = Session(metadata=metadata, messages=messages)

    data = {
        "metadata": {
            "name": session.metadata.name,
            "created_at": session.metadata.created_at,
            "updated_at": session.metadata.updated_at,
            "message_count": session.metadata.message_count,
            "summary": session.metadata.summary,
        },
        "messages": session.messages,
    }

    path = get_session_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return session


def list_sessions() -> Iterator[SessionMetadata]:
    """列出所有会话。

    Yields:
        会话元数据
    """
    session_dir = get_session_dir()
    if not session_dir.exists():
        return

    for path in sorted(session_dir.glob("*.json"), key=lambda p: -p.stat().st_mtime):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            yield SessionMetadata(
                name=data.get("metadata", {}).get("name", path.stem),
                created_at=data.get("metadata", {}).get("created_at", ""),
                updated_at=data.get("metadata", {}).get("updated_at", ""),
                message_count=data.get("metadata", {}).get("message_count", 0),
                summary=data.get("metadata", {}).get("summary", ""),
            )
        except Exception:
            continue


def delete_session(name: str) -> bool:
    """删除会话。

    Args:
        name: 会话名称

    Returns:
        是否成功删除
    """
    path = get_session_path(name)
    if path.exists():
        try:
            path.unlink()
            return True
        except Exception:
            return False
    return False


def conversation_from_session(session: Session) -> InMemoryConversation:
    """从会话数据创建对话记忆。

    Args:
        session: 会话对象

    Returns:
        对话记忆对象
    """
    conv = InMemoryConversation()
    conv.add_messages(session.messages)
    return conv
