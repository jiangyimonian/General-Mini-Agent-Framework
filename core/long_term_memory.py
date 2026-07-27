"""Stable contracts and stores for explicit long-term memory."""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

MemoryScope = Literal["exact", "user_agent", "user"]
MetadataValue = str | int | float | bool
_MEMORY_SCOPES = {"exact", "user_agent", "user"}
_RESERVED_METADATA_PREFIX = "_gmf_"


@dataclass(frozen=True)
class MemoryNamespace:
    user_id: str
    conversation_id: str
    agent_id: str

    def __post_init__(self) -> None:
        for field_name in ("user_id", "conversation_id", "agent_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty text")
            object.__setattr__(self, field_name, value.strip())


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    content: str
    namespace: MemoryNamespace
    metadata: dict[str, MetadataValue] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("id must be non-empty text")
        _validate_content(self.content)
        object.__setattr__(self, "metadata", _copy_metadata(self.metadata))
        for field_name in ("created_at", "updated_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class MemoryQuery:
    text: str
    namespace: MemoryNamespace
    scope: MemoryScope = "exact"
    top_k: int = 5
    metadata_filter: dict[str, MetadataValue] = field(default_factory=dict)
    max_context_tokens: int = 512

    def __post_init__(self) -> None:
        _validate_content(self.text, field_name="query text")
        if self.scope not in _MEMORY_SCOPES:
            raise ValueError(f"unsupported memory scope: {self.scope}")
        if not isinstance(self.top_k, int) or isinstance(self.top_k, bool) or self.top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        if (
            not isinstance(self.max_context_tokens, int)
            or isinstance(self.max_context_tokens, bool)
            or self.max_context_tokens <= 0
        ):
            raise ValueError("max_context_tokens must be a positive integer")
        object.__setattr__(self, "metadata_filter", _copy_metadata(self.metadata_filter))


class MemoryStoreError(Exception):
    """Sanitized failure from a long-term memory backend."""

    def __init__(self, operation: str, *, backend: str = "memory") -> None:
        self.operation = operation
        self.backend = backend
        super().__init__(f"{backend} memory operation failed: {operation}")


class MemoryRecordNotFound(MemoryStoreError):
    def __init__(self, record_id: str) -> None:
        self.record_id = record_id
        super().__init__("update missing record")


class LongTermMemoryStore(Protocol):
    def store(
        self,
        content: str,
        namespace: MemoryNamespace,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> MemoryRecord: ...

    def get(
        self,
        record_id: str,
        namespace: MemoryNamespace,
    ) -> MemoryRecord | None: ...

    def query(self, query: MemoryQuery) -> list[MemoryRecord]: ...

    def update(
        self,
        record_id: str,
        namespace: MemoryNamespace,
        *,
        content: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> MemoryRecord: ...

    def delete(self, record_id: str, namespace: MemoryNamespace) -> bool: ...

    def clear(
        self,
        namespace: MemoryNamespace,
        *,
        scope: MemoryScope = "exact",
    ) -> int: ...


def create_memory_record(
    content: str,
    namespace: MemoryNamespace,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> MemoryRecord:
    _validate_content(content)
    now = datetime.now(UTC)
    return MemoryRecord(
        id=str(uuid.uuid4()),
        content=content.strip(),
        namespace=namespace,
        metadata=_copy_metadata(metadata or {}),
        created_at=now,
        updated_at=now,
    )


def _validate_content(content: str, *, field_name: str = "content") -> None:
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"{field_name} must be non-empty text")


def _copy_metadata(
    metadata: Mapping[str, MetadataValue],
) -> dict[str, MetadataValue]:
    if not isinstance(metadata, Mapping):
        raise TypeError("metadata must be a mapping")
    copied = copy.deepcopy(dict(metadata))
    for key, value in copied.items():
        if not isinstance(key, str) or not key:
            raise ValueError("metadata keys must be non-empty strings")
        if key.startswith(_RESERVED_METADATA_PREFIX):
            raise ValueError(f"metadata key uses reserved prefix: {key}")
        if not isinstance(value, (str, int, float, bool)):
            raise TypeError(f"metadata value for '{key}' must be scalar")
    return copied
