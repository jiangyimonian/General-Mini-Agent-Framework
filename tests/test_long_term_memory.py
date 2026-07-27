"""Focused tests for stable long-term memory contracts and stores."""

from __future__ import annotations

import pytest

from core.long_term_memory import (
    InMemoryLongTermStore,
    MemoryNamespace,
    MemoryQuery,
    MemoryRecordNotFound,
    create_memory_record,
)

NAMESPACE = MemoryNamespace("user-1", "conversation-1", "agent-1")
OTHER_CONVERSATION = MemoryNamespace("user-1", "conversation-2", "agent-1")


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
