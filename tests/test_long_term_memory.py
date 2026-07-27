"""Focused tests for stable long-term memory contracts and stores."""

from __future__ import annotations

import pytest

from core.long_term_memory import (
    MemoryNamespace,
    MemoryQuery,
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
