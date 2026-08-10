"""Tests for async long-term memory protocol and in-memory store."""

import asyncio

import pytest

from general_mini_agent.async_long_term_memory import (
    AsyncInMemoryLongTermStore,
    AsyncLongTermMemoryStore,
)
from general_mini_agent.long_term_memory import (
    MemoryNamespace,
    MemoryQuery,
    MemoryRecord,
    MemoryRecordNotFound,
)


@pytest.fixture
def namespace():
    return MemoryNamespace("user1", "conv1", "agent1")


@pytest.fixture
def another_namespace():
    return MemoryNamespace("user2", "conv2", "agent2")


@pytest.fixture
async def store():
    return AsyncInMemoryLongTermStore()


class TestAsyncInMemoryLongTermStore:
    """Contract tests for AsyncInMemoryLongTermStore."""

    @pytest.mark.asyncio
    async def test_store_returns_record_with_id(self, store, namespace):
        """Store operation returns a MemoryRecord with generated ID."""
        record = await store.store("test content", namespace)
        assert isinstance(record, MemoryRecord)
        assert record.id
        assert record.content == "test content"
        assert record.namespace == namespace

    @pytest.mark.asyncio
    async def test_store_with_metadata(self, store, namespace):
        """Store operation accepts optional metadata."""
        metadata = {"category": "test", "priority": 5}
        record = await store.store("content", namespace, metadata)
        assert record.metadata == metadata

    @pytest.mark.asyncio
    async def test_get_existing_record(self, store, namespace):
        """Get retrieves an existing record by ID."""
        stored = await store.store("content", namespace)
        retrieved = await store.get(stored.id, namespace)
        assert retrieved is not None
        assert retrieved.id == stored.id
        assert retrieved.content == stored.content

    @pytest.mark.asyncio
    async def test_get_nonexistent_record(self, store, namespace):
        """Get returns None for nonexistent record."""
        result = await store.get("nonexistent-id", namespace)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_wrong_namespace(self, store, namespace, another_namespace):
        """Get returns None when namespace doesn't match."""
        stored = await store.store("content", namespace)
        result = await store.get(stored.id, another_namespace)
        assert result is None

    @pytest.mark.asyncio
    async def test_query_empty_store(self, store, namespace):
        """Query returns empty list when store is empty."""
        query = MemoryQuery("test", namespace)
        results = await store.query(query)
        assert results == []

    @pytest.mark.asyncio
    async def test_query_finds_matching_content(self, store, namespace):
        """Query ranks records by term overlap."""
        await store.store("python programming", namespace)
        await store.store("java programming", namespace)
        await store.store("cooking recipes", namespace)

        query = MemoryQuery("programming", namespace, top_k=10)
        results = await store.query(query)
        # All 3 records returned, but "programming" matches ranked first
        assert len(results) == 3
        assert "programming" in results[0].content
        assert "programming" in results[1].content

    @pytest.mark.asyncio
    async def test_query_respects_top_k(self, store, namespace):
        """Query limits results to top_k."""
        for i in range(5):
            await store.store(f"test content {i}", namespace)

        query = MemoryQuery("test", namespace, top_k=3)
        results = await store.query(query)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_query_namespace_isolation_exact(self, store, namespace, another_namespace):
        """Query with exact scope only returns records from exact namespace."""
        await store.store("content1", namespace)
        await store.store("content2", another_namespace)

        query = MemoryQuery("content", namespace, scope="exact")
        results = await store.query(query)
        assert len(results) == 1
        assert results[0].namespace == namespace

    @pytest.mark.asyncio
    async def test_query_scope_user_agent(self, store):
        """Query with user_agent scope returns records across conversations."""
        ns1 = MemoryNamespace("user1", "conv1", "agent1")
        ns2 = MemoryNamespace("user1", "conv2", "agent1")
        ns3 = MemoryNamespace("user1", "conv3", "agent2")

        await store.store("content1", ns1)
        await store.store("content2", ns2)
        await store.store("content3", ns3)

        query = MemoryQuery("content", ns1, scope="user_agent")
        results = await store.query(query)
        assert len(results) == 2
        assert all(r.namespace.user_id == "user1" for r in results)
        assert all(r.namespace.agent_id == "agent1" for r in results)

    @pytest.mark.asyncio
    async def test_query_scope_user(self, store):
        """Query with user scope returns all records for user."""
        ns1 = MemoryNamespace("user1", "conv1", "agent1")
        ns2 = MemoryNamespace("user1", "conv2", "agent2")
        ns3 = MemoryNamespace("user2", "conv3", "agent1")

        await store.store("content1", ns1)
        await store.store("content2", ns2)
        await store.store("content3", ns3)

        query = MemoryQuery("content", ns1, scope="user")
        results = await store.query(query)
        assert len(results) == 2
        assert all(r.namespace.user_id == "user1" for r in results)

    @pytest.mark.asyncio
    async def test_query_with_metadata_filter(self, store, namespace):
        """Query respects metadata filter."""
        await store.store("content1", namespace, {"category": "tech"})
        await store.store("content2", namespace, {"category": "food"})

        query = MemoryQuery("content", namespace, metadata_filter={"category": "tech"})
        results = await store.query(query)
        assert len(results) == 1
        assert results[0].metadata["category"] == "tech"

    @pytest.mark.asyncio
    async def test_update_existing_record_content(self, store, namespace):
        """Update changes record content."""
        stored = await store.store("original", namespace)
        updated = await store.update(stored.id, namespace, content="modified")
        assert updated.content == "modified"
        assert updated.id == stored.id
        assert updated.created_at == stored.created_at
        assert updated.updated_at > stored.updated_at

    @pytest.mark.asyncio
    async def test_update_existing_record_metadata(self, store, namespace):
        """Update changes record metadata."""
        stored = await store.store("content", namespace, {"key": "value1"})
        updated = await store.update(stored.id, namespace, metadata={"key": "value2"})
        assert updated.metadata == {"key": "value2"}

    @pytest.mark.asyncio
    async def test_update_nonexistent_record_raises(self, store, namespace):
        """Update raises MemoryRecordNotFound for nonexistent record."""
        with pytest.raises(MemoryRecordNotFound) as exc_info:
            await store.update("nonexistent", namespace, content="new")
        assert exc_info.value.record_id == "nonexistent"

    @pytest.mark.asyncio
    async def test_update_wrong_namespace_raises(self, store, namespace, another_namespace):
        """Update raises MemoryRecordNotFound when namespace doesn't match."""
        stored = await store.store("content", namespace)
        with pytest.raises(MemoryRecordNotFound):
            await store.update(stored.id, another_namespace, content="new")

    @pytest.mark.asyncio
    async def test_delete_existing_record(self, store, namespace):
        """Delete removes existing record and returns True."""
        stored = await store.store("content", namespace)
        deleted = await store.delete(stored.id, namespace)
        assert deleted is True
        result = await store.get(stored.id, namespace)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_record(self, store, namespace):
        """Delete returns False for nonexistent record."""
        deleted = await store.delete("nonexistent", namespace)
        assert deleted is False

    @pytest.mark.asyncio
    async def test_delete_wrong_namespace(self, store, namespace, another_namespace):
        """Delete returns False when namespace doesn't match."""
        stored = await store.store("content", namespace)
        deleted = await store.delete(stored.id, another_namespace)
        assert deleted is False
        # Original record still exists
        result = await store.get(stored.id, namespace)
        assert result is not None

    @pytest.mark.asyncio
    async def test_clear_exact_scope(self, store):
        """Clear removes only exact namespace matches."""
        ns1 = MemoryNamespace("user1", "conv1", "agent1")
        ns2 = MemoryNamespace("user1", "conv2", "agent1")

        await store.store("content1", ns1)
        await store.store("content2", ns2)

        count = await store.clear(ns1, scope="exact")
        assert count == 1

        # ns2 record still exists
        query = MemoryQuery("content", ns2)
        results = await store.query(query)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_clear_user_agent_scope(self, store):
        """Clear with user_agent scope removes across conversations."""
        ns1 = MemoryNamespace("user1", "conv1", "agent1")
        ns2 = MemoryNamespace("user1", "conv2", "agent1")
        ns3 = MemoryNamespace("user1", "conv3", "agent2")

        await store.store("content1", ns1)
        await store.store("content2", ns2)
        await store.store("content3", ns3)

        count = await store.clear(ns1, scope="user_agent")
        assert count == 2

        # ns3 record still exists
        query = MemoryQuery("content", ns3)
        results = await store.query(query)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_clear_user_scope(self, store):
        """Clear with user scope removes all user records."""
        ns1 = MemoryNamespace("user1", "conv1", "agent1")
        ns2 = MemoryNamespace("user1", "conv2", "agent2")
        ns3 = MemoryNamespace("user2", "conv3", "agent1")

        await store.store("content1", ns1)
        await store.store("content2", ns2)
        await store.store("content3", ns3)

        count = await store.clear(ns1, scope="user")
        assert count == 2

        # user2 record still exists
        query = MemoryQuery("content", ns3, scope="user")
        results = await store.query(query)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_clear_invalid_scope_raises(self, store, namespace):
        """Clear raises ValueError for invalid scope."""
        with pytest.raises(ValueError, match="unsupported memory scope"):
            await store.clear(namespace, scope="invalid")  # type: ignore

    @pytest.mark.asyncio
    async def test_returns_defensive_copies(self, store, namespace):
        """Store operations return defensive copies."""
        stored = await store.store("content", namespace, {"key": "value"})
        stored.metadata["key"] = "modified"  # type: ignore

        retrieved = await store.get(stored.id, namespace)
        assert retrieved is not None
        assert retrieved.metadata["key"] == "value"

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, store, namespace):
        """Store handles concurrent operations safely."""
        async def store_record(i: int) -> MemoryRecord:
            return await store.store(f"content {i}", namespace)

        # Store 10 records concurrently
        records = await asyncio.gather(*[store_record(i) for i in range(10)])
        assert len(records) == 10
        assert len({r.id for r in records}) == 10  # All unique IDs

        # Query should find all
        query = MemoryQuery("content", namespace, top_k=20)
        results = await store.query(query)
        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_invalid_content_raises(self, store, namespace):
        """Store validates content before creating record."""
        with pytest.raises(ValueError, match="must be non-empty text"):
            await store.store("", namespace)

        with pytest.raises(ValueError, match="must be non-empty text"):
            await store.store("   ", namespace)

    @pytest.mark.asyncio
    async def test_invalid_metadata_raises(self, store, namespace):
        """Store validates metadata structure."""
        with pytest.raises(ValueError, match="reserved prefix"):
            await store.store("content", namespace, {"_gmf_invalid": "value"})

    @pytest.mark.asyncio
    async def test_protocol_compliance(self):
        """AsyncInMemoryLongTermStore conforms to AsyncLongTermMemoryStore protocol."""
        store_instance: AsyncLongTermMemoryStore = AsyncInMemoryLongTermStore()
        assert hasattr(store_instance, "store")
        assert hasattr(store_instance, "get")
        assert hasattr(store_instance, "query")
        assert hasattr(store_instance, "update")
        assert hasattr(store_instance, "delete")
        assert hasattr(store_instance, "clear")


class TestAsyncChromaMemoryStore:
    """Contract tests for AsyncChromaMemoryStore with fake client."""

    def _fake_collection(self, records=None):
        """Create a fake ChromaDB collection for testing."""
        records = records or {}

        class FakeCollection:
            def __init__(self):
                self._records = dict(records)

            def add(self, ids, documents, metadatas):
                for i, doc_id in enumerate(ids):
                    self._records[doc_id] = {
                        "id": doc_id,
                        "document": documents[i],
                        "metadata": metadatas[i],
                    }

            def get(self, ids=None, where=None, include=None):
                result_ids = []
                result_docs = []
                result_metas = []

                if ids:
                    for doc_id in ids:
                        if doc_id in self._records:
                            rec = self._records[doc_id]
                            # 检查 where 条件
                            if where is None or self._matches_where(rec["metadata"], where):
                                result_ids.append(doc_id)
                                result_docs.append(rec["document"])
                                result_metas.append(rec["metadata"])
                else:
                    # 无 ids 时，按 where 过滤
                    for doc_id, rec in self._records.items():
                        if where is None or self._matches_where(rec["metadata"], where):
                            result_ids.append(doc_id)
                            result_docs.append(rec["document"])
                            result_metas.append(rec["metadata"])

                return {"ids": result_ids, "documents": result_docs, "metadatas": result_metas}

            def query(self, query_texts, n_results, where=None):
                # 简化查询：返回所有匹配的记录
                rows = self.get(where=where)
                ids = rows["ids"][:n_results]
                docs = rows["documents"][:n_results]
                metas = rows["metadatas"][:n_results]
                return {"ids": [ids], "documents": [docs], "metadatas": [metas]}

            def count(self):
                return len(self._records)

            def update(self, ids, documents, metadatas):
                for i, doc_id in enumerate(ids):
                    if doc_id in self._records:
                        self._records[doc_id]["document"] = documents[i]
                        self._records[doc_id]["metadata"] = metadatas[i]

            def delete(self, ids):
                for doc_id in ids:
                    self._records.pop(doc_id, None)

            def _matches_where(self, metadata, where):
                """检查元数据是否匹配 where 条件。"""
                if "$and" in where:
                    return all(self._matches_where(metadata, cond) for cond in where["$and"])
                for key, value in where.items():
                    if key == "$and":
                        continue
                    if metadata.get(key) != value:
                        return False
                return True

        return FakeCollection()

    def _create_store(self, records=None):
        """Create an AsyncChromaMemoryStore with injected fake client."""
        from general_mini_agent.async_long_term_memory import AsyncChromaMemoryStore

        collection = self._fake_collection(records)

        def client_factory():
            return (None, collection)

        return AsyncChromaMemoryStore(client_factory=client_factory)

    @pytest.mark.asyncio
    async def test_store_returns_record_with_id(self):
        """Store operation returns a MemoryRecord with generated ID."""
        store = self._create_store()
        namespace = MemoryNamespace("user1", "conv1", "agent1")
        record = await store.store("test content", namespace)
        assert isinstance(record, MemoryRecord)
        assert record.id
        assert record.content == "test content"

    @pytest.mark.asyncio
    async def test_get_existing_record(self):
        """Get retrieves an existing record by ID."""
        store = self._create_store()
        namespace = MemoryNamespace("user1", "conv1", "agent1")
        stored = await store.store("content", namespace)
        retrieved = await store.get(stored.id, namespace)
        assert retrieved is not None
        assert retrieved.id == stored.id

    @pytest.mark.asyncio
    async def test_query_finds_matching_content(self):
        """Query finds records with matching content."""
        store = self._create_store()
        namespace = MemoryNamespace("user1", "conv1", "agent1")
        await store.store("python programming", namespace)
        await store.store("java programming", namespace)

        query = MemoryQuery("programming", namespace, top_k=10)
        results = await store.query(query)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_update_existing_record(self):
        """Update changes record content."""
        store = self._create_store()
        namespace = MemoryNamespace("user1", "conv1", "agent1")
        stored = await store.store("original", namespace)
        updated = await store.update(stored.id, namespace, content="modified")
        assert updated.content == "modified"

    @pytest.mark.asyncio
    async def test_delete_existing_record(self):
        """Delete removes existing record."""
        store = self._create_store()
        namespace = MemoryNamespace("user1", "conv1", "agent1")
        stored = await store.store("content", namespace)
        deleted = await store.delete(stored.id, namespace)
        assert deleted is True

    @pytest.mark.asyncio
    async def test_clear_removes_records(self):
        """Clear removes records by namespace."""
        store = self._create_store()
        namespace = MemoryNamespace("user1", "conv1", "agent1")
        await store.store("content1", namespace)
        await store.store("content2", namespace)
        count = await store.clear(namespace)
        assert count == 2

    @pytest.mark.asyncio
    async def test_missing_chromadb_raises_import_error(self):
        """Missing ChromaDB raises ImportError on first use."""
        from general_mini_agent.async_long_term_memory import AsyncChromaMemoryStore

        # 不注入工厂，会尝试导入 chromadb
        store = AsyncChromaMemoryStore()
        namespace = MemoryNamespace("user1", "conv1", "agent1")

        # 如果 ChromaDB 已安装，这个测试会跳过
        # 如果未安装，应抛出 ImportError
        import importlib.util
        if importlib.util.find_spec("chromadb") is not None:
            pytest.skip("ChromaDB is installed, skipping missing dependency test")

        with pytest.raises(ImportError, match="ChromaDB is optional"):
            await store.store("content", namespace)


class TestImportWithoutChromaDB:
    """Test that general_mini_agent imports without ChromaDB."""

    def test_import_succeeds_without_chromadb(self):
        """import general_mini_agent succeeds when ChromaDB is absent."""
        # 这个测试在 CI 环境中验证包可以在没有 ChromaDB 的情况下导入
        import general_mini_agent
        assert general_mini_agent.__version__
        assert hasattr(general_mini_agent, "AsyncChromaMemoryStore")
        # 类存在，但使用时会检查依赖
