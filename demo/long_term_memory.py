"""Explicit persistent long-term memory without an LLM request."""

from core import ChromaMemoryStore, MemoryNamespace, MemoryQuery

namespace = MemoryNamespace(
    user_id="demo-user",
    conversation_id="demo-conversation",
    agent_id="demo-agent",
)
store = ChromaMemoryStore()

# Writes are always explicit; storing the same content again creates a new record.
stored = store.store(
    "The user prefers concise Python examples.",
    namespace,
    {"kind": "preference"},
)
print(f"Stored: {stored.id}")

query = MemoryQuery(
    "Python preference",
    namespace,
    metadata_filter={"kind": "preference"},
)
for record in store.query(query):
    print(f"Retrieved: {record.content}")
