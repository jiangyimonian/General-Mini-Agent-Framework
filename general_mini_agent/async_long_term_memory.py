"""Async long-term memory protocol and in-memory implementation."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Mapping
from typing import Protocol

from .long_term_memory import (
    _MEMORY_SCOPES,
    MemoryNamespace,
    MemoryQuery,
    MemoryRecord,
    MemoryRecordNotFound,
    MemoryScope,
    MetadataValue,
    _copy_metadata,
    _namespace_matches,
    _tokenize,
    create_memory_record,
)


class AsyncLongTermMemoryStore(Protocol):
    """Async protocol for long-term memory operations."""

    async def store(
        self,
        content: str,
        namespace: MemoryNamespace,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> MemoryRecord: ...

    async def get(
        self,
        record_id: str,
        namespace: MemoryNamespace,
    ) -> MemoryRecord | None: ...

    async def query(self, query: MemoryQuery) -> list[MemoryRecord]: ...

    async def update(
        self,
        record_id: str,
        namespace: MemoryNamespace,
        *,
        content: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> MemoryRecord: ...

    async def delete(self, record_id: str, namespace: MemoryNamespace) -> bool: ...

    async def clear(
        self,
        namespace: MemoryNamespace,
        *,
        scope: MemoryScope = "exact",
    ) -> int: ...


class AsyncInMemoryLongTermStore:
    """Async in-memory store with same semantics as InMemoryLongTermStore."""

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._lock = asyncio.Lock()

    async def store(
        self,
        content: str,
        namespace: MemoryNamespace,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> MemoryRecord:
        record = create_memory_record(content, namespace, metadata)
        async with self._lock:
            self._records[record.id] = record
        return copy.deepcopy(record)

    async def get(
        self,
        record_id: str,
        namespace: MemoryNamespace,
    ) -> MemoryRecord | None:
        async with self._lock:
            record = self._records.get(record_id)
            if record is None or record.namespace != namespace:
                return None
            return copy.deepcopy(record)

    async def query(self, query: MemoryQuery) -> list[MemoryRecord]:
        query_terms = _tokenize(query.text)
        matches: list[tuple[int, int, MemoryRecord]] = []
        async with self._lock:
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

    async def update(
        self,
        record_id: str,
        namespace: MemoryNamespace,
        *,
        content: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> MemoryRecord:
        from datetime import UTC, datetime

        async with self._lock:
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

    async def delete(self, record_id: str, namespace: MemoryNamespace) -> bool:
        async with self._lock:
            current = self._records.get(record_id)
            if current is None or current.namespace != namespace:
                return False
            del self._records[record_id]
            return True

    async def clear(
        self,
        namespace: MemoryNamespace,
        *,
        scope: MemoryScope = "exact",
    ) -> int:
        if scope not in _MEMORY_SCOPES:
            raise ValueError(f"unsupported memory scope: {scope}")
        async with self._lock:
            matching_ids = [
                record_id
                for record_id, record in self._records.items()
                if _namespace_matches(record.namespace, namespace, scope)
            ]
            for record_id in matching_ids:
                del self._records[record_id]
            return len(matching_ids)
