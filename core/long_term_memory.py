"""Stable contracts and stores for explicit long-term memory."""

from __future__ import annotations

import copy
import re
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


class InMemoryLongTermStore:
    """Deterministic process-local store suitable for tests and small apps."""

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def store(
        self,
        content: str,
        namespace: MemoryNamespace,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> MemoryRecord:
        record = create_memory_record(content, namespace, metadata)
        self._records[record.id] = record
        return copy.deepcopy(record)

    def get(
        self,
        record_id: str,
        namespace: MemoryNamespace,
    ) -> MemoryRecord | None:
        record = self._records.get(record_id)
        if record is None or record.namespace != namespace:
            return None
        return copy.deepcopy(record)

    def query(self, query: MemoryQuery) -> list[MemoryRecord]:
        query_terms = _tokenize(query.text)
        matches: list[tuple[int, int, MemoryRecord]] = []
        for insertion_order, record in enumerate(self._records.values()):
            if not _namespace_matches(record.namespace, query.namespace, query.scope):
                continue
            if not all(
                record.metadata.get(key) == value
                for key, value in query.metadata_filter.items()
            ):
                continue
            overlap = len(query_terms & _tokenize(record.content))
            matches.append((-overlap, insertion_order, record))

        matches.sort(key=lambda match: (match[0], match[1]))
        return [copy.deepcopy(match[2]) for match in matches[: query.top_k]]

    def update(
        self,
        record_id: str,
        namespace: MemoryNamespace,
        *,
        content: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> MemoryRecord:
        current = self._records.get(record_id)
        if current is None or current.namespace != namespace:
            raise MemoryRecordNotFound(record_id)

        updated = MemoryRecord(
            id=current.id,
            content=current.content if content is None else content.strip(),
            namespace=current.namespace,
            metadata=current.metadata if metadata is None else _copy_metadata(metadata),
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )
        self._records[record_id] = updated
        return copy.deepcopy(updated)

    def delete(self, record_id: str, namespace: MemoryNamespace) -> bool:
        current = self._records.get(record_id)
        if current is None or current.namespace != namespace:
            return False
        del self._records[record_id]
        return True

    def clear(
        self,
        namespace: MemoryNamespace,
        *,
        scope: MemoryScope = "exact",
    ) -> int:
        if scope not in _MEMORY_SCOPES:
            raise ValueError(f"unsupported memory scope: {scope}")
        matching_ids = [
            record_id
            for record_id, record in self._records.items()
            if _namespace_matches(record.namespace, namespace, scope)
        ]
        for record_id in matching_ids:
            del self._records[record_id]
        return len(matching_ids)


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


def _namespace_matches(
    candidate: MemoryNamespace,
    requested: MemoryNamespace,
    scope: MemoryScope,
) -> bool:
    if candidate.user_id != requested.user_id:
        return False
    if scope == "user":
        return True
    if candidate.agent_id != requested.agent_id:
        return False
    return scope == "user_agent" or candidate.conversation_id == requested.conversation_id


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold(), flags=re.UNICODE))
