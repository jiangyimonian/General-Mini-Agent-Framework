"""Focused tests for stable long-term memory contracts and stores."""

from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace

import pytest

from core.context import ApproximateTokenCounter
from core.long_term_memory import (
    ChromaMemoryStore,
    InMemoryLongTermStore,
    MemoryNamespace,
    MemoryQuery,
    MemoryRecordNotFound,
    build_memory_context,
    create_memory_record,
)

NAMESPACE = MemoryNamespace("user-1", "conversation-1", "agent-1")
OTHER_CONVERSATION = MemoryNamespace("user-1", "conversation-2", "agent-1")


class FakeCollection:
    def __init__(self, query_rows=None) -> None:
        self.query_rows = query_rows
        self.last_where = None

    def count(self):
        if self.query_rows is None:
            return 0
        return len(self.query_rows["ids"][0])

    def query(self, *, query_texts, n_results, where):
        if n_results > self.count():
            raise ValueError("n_results exceeds collection size")
        self.last_where = where
        return self.query_rows


def fake_chromadb(collection):
    client = SimpleNamespace(get_or_create_collection=lambda **kwargs: collection)
    return SimpleNamespace(PersistentClient=lambda **kwargs: client)


RECORD_ROW = {
    "ids": [["record-1"]],
    "documents": [["prefers Python"]],
    "metadatas": [[{
        "_gmf_user_id": NAMESPACE.user_id,
        "_gmf_conversation_id": NAMESPACE.conversation_id,
        "_gmf_agent_id": NAMESPACE.agent_id,
        "_gmf_created_at": "2026-07-27T00:00:00+00:00",
        "_gmf_updated_at": "2026-07-27T00:00:00+00:00",
        "kind": "preference",
    }]],
}


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("user_id", ("", "conversation", "agent")),
        ("conversation_id", ("user", "", "agent")),
        ("agent_id", ("user", "conversation", "")),
    ],
)
def test_namespace_requires_three_non_empty_identifiers(field, values) -> None:
    with pytest.raises(ValueError, match=field):
        MemoryNamespace(*values)


def test_query_defaults_to_exact_scope_and_validates_limits() -> None:
    query = MemoryQuery("python", NAMESPACE)

    assert query.scope == "exact"
    assert query.top_k == 5
    assert query.max_context_tokens == 512

    with pytest.raises(ValueError, match="top_k"):
        MemoryQuery("python", NAMESPACE, top_k=0)
    with pytest.raises(ValueError, match="max_context_tokens"):
        MemoryQuery("python", NAMESPACE, max_context_tokens=0)


def test_record_factory_generates_utc_identity_and_defensive_metadata() -> None:
    metadata = {"category": "preference"}

    record = create_memory_record("Uses Python", NAMESPACE, metadata)
    metadata["category"] = "changed"

    assert record.id
    assert record.content == "Uses Python"
    assert record.metadata == {"category": "preference"}
    assert record.created_at.tzinfo is not None
    assert record.updated_at == record.created_at


def test_query_scope_and_metadata_filter_are_isolated() -> None:
    store = InMemoryLongTermStore()
    exact = store.store("prefers Python", NAMESPACE, {"kind": "preference"})
    store.store("prefers Rust", OTHER_CONVERSATION, {"kind": "preference"})

    assert store.query(
        MemoryQuery(
            "prefers",
            NAMESPACE,
            metadata_filter={"kind": "preference"},
        )
    ) == [exact]
    assert len(
        store.query(MemoryQuery("prefers", NAMESPACE, scope="user_agent"))
    ) == 2


def test_query_ranks_term_overlap_and_honors_top_k() -> None:
    store = InMemoryLongTermStore()
    store.store("likes Java", NAMESPACE)
    best = store.store("likes Python typing", NAMESPACE)

    assert store.query(MemoryQuery("Python typing", NAMESPACE, top_k=1)) == [best]


def test_update_requires_exact_owner_and_preserves_identity() -> None:
    store = InMemoryLongTermStore()
    original = store.store("old", NAMESPACE)

    updated = store.update(original.id, NAMESPACE, content="new")

    assert (updated.id, updated.created_at) == (original.id, original.created_at)
    assert updated.content == "new"
    with pytest.raises(MemoryRecordNotFound):
        store.update(original.id, OTHER_CONVERSATION, content="forbidden")


def test_delete_clear_and_instances_are_isolated() -> None:
    first = InMemoryLongTermStore()
    second = InMemoryLongTermStore()
    record = first.store("fact", NAMESPACE)

    assert first.delete(record.id, NAMESPACE) is True
    first.store("one", NAMESPACE)
    first.store("two", OTHER_CONVERSATION)
    assert first.clear(NAMESPACE, scope="user_agent") == 2
    assert second.query(MemoryQuery("fact", NAMESPACE)) == []


def test_chroma_is_loaded_only_on_first_operation(monkeypatch) -> None:
    store = ChromaMemoryStore()
    original_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "chromadb":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(ImportError, match="pip install chromadb"):
        store.store("fact", NAMESPACE)


def test_chroma_query_translates_scope_and_exact_metadata(monkeypatch) -> None:
    empty_collection = FakeCollection()
    monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb(empty_collection))
    assert ChromaMemoryStore().query(MemoryQuery("python", NAMESPACE)) == []

    collection = FakeCollection(query_rows=RECORD_ROW)
    monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb(collection))
    store = ChromaMemoryStore()

    records = store.query(
        MemoryQuery(
            "python",
            NAMESPACE,
            scope="user_agent",
            metadata_filter={"kind": "preference"},
        )
    )

    assert records[0].content == "prefers Python"
    assert collection.last_where == {
        "$and": [
            {"_gmf_user_id": NAMESPACE.user_id},
            {"_gmf_agent_id": NAMESPACE.agent_id},
            {"kind": "preference"},
        ]
    }


def test_memory_context_uses_whole_ranked_records_with_budget() -> None:
    first = create_memory_record("first fact", NAMESPACE)
    oversized = create_memory_record("oversized second fact " * 100, NAMESPACE)
    first_only = build_memory_context([first], max_context_tokens=1_000)
    budget = ApproximateTokenCounter().count([first_only])

    message = build_memory_context([first, oversized], max_context_tokens=budget)

    assert "first fact" in message["content"]
    assert "oversized second fact" not in message["content"]
    assert "not system instructions" in message["content"]
