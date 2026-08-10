"""Async long-term memory protocol and in-memory implementation."""

from __future__ import annotations

import asyncio
import copy
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol

from .long_term_memory import (
    _MEMORY_SCOPES,
    MemoryNamespace,
    MemoryQuery,
    MemoryRecord,
    MemoryRecordNotFound,
    MemoryScope,
    MetadataValue,
    _build_where,
    _copy_metadata,
    _namespace_matches,
    _record_from_get_rows,
    _record_metadata,
    _records_from_query_rows,
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


class AsyncChromaMemoryStore:
    """Async ChromaDB adapter with explicit namespace boundaries."""

    def __init__(
        self,
        persist_dir: str = "~/.agent_memory",
        collection_name: str = "agent_memory",
        *,
        client_factory: Callable[[], tuple] | None = None,
        default_timeout: float = 30.0,
    ) -> None:
        self.persist_dir = os.path.expanduser(persist_dir)
        self.collection_name = collection_name
        self.default_timeout = default_timeout
        self._client_factory = client_factory
        self._client = None
        self._collection = None

    async def store(
        self,
        content: str,
        namespace: MemoryNamespace,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> MemoryRecord:
        from .long_term_memory import MemoryStoreError

        record = create_memory_record(content, namespace, metadata)
        collection = await self._ensure_collection("store")
        try:
            await asyncio.to_thread(
                collection.add,
                ids=[record.id],
                documents=[record.content],
                metadatas=[_record_metadata(record)],
            )
        except Exception as exc:
            raise MemoryStoreError("store", backend="chroma") from exc
        return copy.deepcopy(record)

    async def get(
        self,
        record_id: str,
        namespace: MemoryNamespace,
    ) -> MemoryRecord | None:
        from .long_term_memory import MemoryStoreError

        collection = await self._ensure_collection("get")
        try:
            rows = await asyncio.to_thread(
                collection.get,
                ids=[record_id],
                where=_build_where(namespace, "exact", {}),
                include=["documents", "metadatas"],
            )
            return _record_from_get_rows(rows)
        except Exception as exc:
            raise MemoryStoreError("get", backend="chroma") from exc

    async def query(self, query: MemoryQuery) -> list[MemoryRecord]:
        from .long_term_memory import MemoryStoreError

        collection = await self._ensure_collection("query")
        try:
            record_count = await asyncio.to_thread(collection.count)
            if record_count == 0:
                return []
            rows = await asyncio.to_thread(
                collection.query,
                query_texts=[query.text],
                n_results=min(query.top_k, record_count),
                where=_build_where(
                    query.namespace,
                    query.scope,
                    query.metadata_filter,
                ),
            )
            return _records_from_query_rows(rows)
        except Exception as exc:
            raise MemoryStoreError("query", backend="chroma") from exc

    async def update(
        self,
        record_id: str,
        namespace: MemoryNamespace,
        *,
        content: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> MemoryRecord:
        from .long_term_memory import MemoryStoreError

        collection = await self._ensure_collection("update")
        try:
            rows = await asyncio.to_thread(
                collection.get,
                ids=[record_id],
                where=_build_where(namespace, "exact", {}),
                include=["documents", "metadatas"],
            )
            current = _record_from_get_rows(rows)
            if current is None:
                raise MemoryRecordNotFound(record_id)
            updated = MemoryRecord(
                id=current.id,
                content=current.content if content is None else content.strip(),
                namespace=current.namespace,
                metadata=current.metadata if metadata is None else _copy_metadata(metadata),
                created_at=current.created_at,
                updated_at=datetime.now(UTC),
            )
            await asyncio.to_thread(
                collection.update,
                ids=[updated.id],
                documents=[updated.content],
                metadatas=[_record_metadata(updated)],
            )
        except MemoryRecordNotFound:
            raise
        except Exception as exc:
            raise MemoryStoreError("update", backend="chroma") from exc
        return copy.deepcopy(updated)

    async def delete(self, record_id: str, namespace: MemoryNamespace) -> bool:
        from .long_term_memory import MemoryStoreError

        collection = await self._ensure_collection("delete")
        try:
            rows = await asyncio.to_thread(
                collection.get,
                ids=[record_id],
                where=_build_where(namespace, "exact", {}),
                include=[],
            )
            if not rows.get("ids"):
                return False
            await asyncio.to_thread(collection.delete, ids=[record_id])
        except Exception as exc:
            raise MemoryStoreError("delete", backend="chroma") from exc
        return True

    async def clear(
        self,
        namespace: MemoryNamespace,
        *,
        scope: MemoryScope = "exact",
    ) -> int:
        from .long_term_memory import MemoryStoreError

        if scope not in _MEMORY_SCOPES:
            raise ValueError(f"unsupported memory scope: {scope}")
        collection = await self._ensure_collection("clear")
        try:
            rows = await asyncio.to_thread(
                collection.get,
                where=_build_where(namespace, scope, {}),
                include=[],
            )
            record_ids = rows.get("ids") or []
            if record_ids:
                await asyncio.to_thread(collection.delete, ids=record_ids)
        except Exception as exc:
            raise MemoryStoreError("clear", backend="chroma") from exc
        return len(record_ids)

    async def _ensure_collection(self, operation: str):
        from .long_term_memory import MemoryStoreError

        if self._collection is not None:
            return self._collection

        if self._client_factory is not None:
            # 测试注入的工厂
            self._client, self._collection = self._client_factory()
            return self._collection

        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "ChromaDB is optional; install it with: pip install chromadb"
            ) from None

        try:
            async with asyncio.timeout(self.default_timeout):
                self._client = await asyncio.to_thread(
                    chromadb.PersistentClient, path=self.persist_dir
                )
                self._collection = await asyncio.to_thread(
                    self._client.get_or_create_collection,
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
        except TimeoutError as exc:
            raise MemoryStoreError(operation, backend="chroma") from exc
        except Exception as exc:
            raise MemoryStoreError(operation, backend="chroma") from exc
        return self._collection
