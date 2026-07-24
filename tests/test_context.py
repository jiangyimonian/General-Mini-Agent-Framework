"""Tests for request context budgeting."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from core.context import (
    ApproximateTokenCounter,
    ContextBudgetExceeded,
    SummarizingContext,
    TokenBudgetContext,
)


class FixedTokenCounter:
    def __init__(self, tokens: int) -> None:
        self.tokens = tokens
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []

    def count(self, messages, *, tools=None) -> int:
        self.calls.append(copy.deepcopy((list(messages), list(tools or []))))
        return self.tokens


class MessageCostCounter:
    def count(self, messages, *, tools=None) -> int:
        return sum(message.get("cost", 1) for message in messages) + len(tools or [])


class OversizedSummaryCounter(MessageCostCounter):
    def count(self, messages, *, tools=None) -> int:
        total = super().count(messages, tools=tools)
        if any(
            str(message.get("content", "")).startswith("Conversation summary:")
            for message in messages
        ):
            total += 10
        return total


def test_approximate_counter_is_deterministic_and_counts_tools() -> None:
    counter = ApproximateTokenCounter()
    messages = [{"role": "user", "content": "abcdefgh"}]

    without_tools = counter.count(messages)
    tools = [{"type": "function", "function": {"name": "lookup"}}]

    assert counter.count(messages) == without_tools
    assert counter.count(messages, tools=tools) > without_tools


def test_approximate_counter_counts_structured_message_fields() -> None:
    counter = ApproximateTokenCounter()
    plain = [{"role": "assistant", "content": "calling"}]
    structured = [{
        "role": "assistant",
        "content": "calling",
        "tool_calls": [{
            "id": "call-1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"q":"python"}'},
        }],
    }]

    assert counter.count(structured) > counter.count(plain)


def test_approximate_counter_rejects_invalid_character_ratio() -> None:
    with pytest.raises(ValueError, match="characters_per_token"):
        ApproximateTokenCounter(characters_per_token=0)


@pytest.mark.parametrize(
    ("window", "reserve"),
    [(0, 1), (10, 0), (10, 10), (10, 11)],
)
def test_budget_configuration_rejects_invalid_values(
    window: int,
    reserve: int,
) -> None:
    with pytest.raises(ValueError):
        TokenBudgetContext(
            context_window=window,
            reserved_output_tokens=reserve,
        )


def test_budget_policy_uses_injected_counter_and_returns_copies() -> None:
    counter = FixedTokenCounter(tokens=4)
    policy = TokenBudgetContext(
        context_window=10,
        reserved_output_tokens=5,
        token_counter=counter,
    )
    messages = [{"role": "user", "content": "question", "metadata": {"n": 1}}]
    tools = [{"type": "function", "function": {"name": "lookup"}}]

    prepared = policy.prepare(messages, tools=tools)
    prepared[0]["metadata"]["n"] = 2

    assert messages[0]["metadata"]["n"] == 1
    assert counter.calls == [(messages, tools)]
    assert policy.input_budget == 5


def test_budget_error_exposes_only_safe_size_metadata() -> None:
    secret = "sensitive user message"
    policy = TokenBudgetContext(
        context_window=10,
        reserved_output_tokens=5,
        token_counter=FixedTokenCounter(tokens=6),
    )

    with pytest.raises(ContextBudgetExceeded) as caught:
        policy.prepare([{"role": "user", "content": secret}])

    assert caught.value.input_tokens == 6
    assert caught.value.input_budget == 5
    assert secret not in str(caught.value)


def test_trimming_removes_oldest_turn_and_preserves_recent_turns() -> None:
    policy = TokenBudgetContext(
        context_window=6,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
    )
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]

    assert policy.prepare(messages) == [messages[0], *messages[3:]]


def test_trimming_never_orphans_tool_results() -> None:
    policy = TokenBudgetContext(
        context_window=7,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
    )
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "old question"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "old-call",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "old-call", "content": "old result"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "recent question"},
        {"role": "assistant", "content": "recent answer"},
        {"role": "user", "content": "current question"},
    ]

    prepared = policy.prepare(messages)

    assert prepared == [messages[0], *messages[5:]]
    assert not any(message.get("tool_call_id") == "old-call" for message in prepared)


def test_tool_schemas_can_force_an_old_turn_to_be_trimmed() -> None:
    policy = TokenBudgetContext(
        context_window=7,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
    )
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u0"},
        {"role": "assistant", "content": "a0"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
    ]
    tools = [{"type": "function"}, {"type": "function"}]

    assert policy.prepare(messages, tools=tools) == [messages[0], *messages[3:]]


def test_protected_turns_raise_when_they_cannot_fit() -> None:
    policy = TokenBudgetContext(
        context_window=4,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
    )
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "previous"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "current"},
    ]

    with pytest.raises(ContextBudgetExceeded) as caught:
        policy.prepare(messages)

    assert caught.value.input_tokens == 4
    assert caught.value.input_budget == 3


def test_oversized_handler_is_recounted_before_returning() -> None:
    seen: list[list[dict[str, Any]]] = []

    def compress(messages, input_budget):
        seen.append(copy.deepcopy(list(messages)))
        assert input_budget == 3
        return [
            {"role": "system", "content": "compressed"},
            {"role": "user", "content": "current"},
        ]

    policy = TokenBudgetContext(
        context_window=4,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
        oversized_content_handler=compress,
    )
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "previous"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "current"},
    ]

    prepared = policy.prepare(messages)

    assert seen == [messages]
    assert prepared == [
        {"role": "system", "content": "compressed"},
        {"role": "user", "content": "current"},
    ]


def test_oversized_handler_cannot_return_an_oversized_replacement() -> None:
    policy = TokenBudgetContext(
        context_window=3,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
        oversized_content_handler=lambda messages, budget: list(messages),
    )

    with pytest.raises(ContextBudgetExceeded):
        policy.prepare([
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
        ])


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "invalid", "content": "bad"}],
        [{"role": "tool", "tool_call_id": "orphan", "content": "bad"}],
        [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "missing-result",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }],
            },
        ],
    ],
)
def test_policy_rejects_invalid_message_or_tool_boundaries(messages) -> None:
    policy = TokenBudgetContext(
        context_window=100,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
    )

    with pytest.raises(ValueError):
        policy.prepare(messages)


def test_summary_replaces_only_turns_deterministic_policy_removes() -> None:
    seen: list[list[dict[str, Any]]] = []

    def summarize(turns):
        seen.append(copy.deepcopy(list(turns)))
        return "old facts"

    base_policy = TokenBudgetContext(
        context_window=6,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
    )
    policy = SummarizingContext(base_policy, summarize)
    messages = [
        {"role": "system", "content": "instructions"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "recent question"},
        {"role": "assistant", "content": "recent answer"},
        {"role": "user", "content": "current question"},
    ]

    prepared = policy.prepare(messages)

    assert seen == [messages[1:3]]
    assert prepared == [
        {"role": "system", "content": "Conversation summary: old facts"},
        messages[0],
        *messages[3:],
    ]


def test_summary_is_not_called_when_context_already_fits() -> None:
    calls = 0

    def summarize(turns):
        nonlocal calls
        calls += 1
        return "unused"

    base_policy = TokenBudgetContext(
        context_window=10,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
    )
    policy = SummarizingContext(base_policy, summarize)
    messages = [{"role": "user", "content": "question"}]

    assert policy.prepare(messages) == messages
    assert calls == 0


@pytest.mark.parametrize("failure", [RuntimeError("failed"), ValueError("bad")])
def test_summary_failure_falls_back_to_deterministic_trimming(failure) -> None:
    def summarize(turns):
        raise failure

    base_policy = TokenBudgetContext(
        context_window=6,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
    )
    policy = SummarizingContext(base_policy, summarize)
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]

    assert policy.prepare(messages) == [messages[0], *messages[3:]]


def test_oversized_summary_falls_back_to_deterministic_trimming() -> None:
    base_policy = TokenBudgetContext(
        context_window=6,
        reserved_output_tokens=1,
        token_counter=OversizedSummaryCounter(),
    )
    policy = SummarizingContext(base_policy, lambda turns: "too large")
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]

    assert policy.prepare(messages) == [messages[0], *messages[3:]]


def test_summary_receives_complete_removed_tool_call_unit() -> None:
    seen: list[list[dict[str, Any]]] = []
    base_policy = TokenBudgetContext(
        context_window=6,
        reserved_output_tokens=1,
        token_counter=MessageCostCounter(),
    )
    policy = SummarizingContext(
        base_policy,
        lambda turns: seen.append(copy.deepcopy(list(turns))) or "tool facts",
    )
    old_turn = [
        {"role": "user", "content": "old question"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "result"},
        {"role": "assistant", "content": "old answer"},
    ]
    messages = [
        {"role": "system", "content": "s"},
        *old_turn,
        {"role": "user", "content": "recent"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "current"},
    ]

    policy.prepare(messages)

    assert seen == [old_turn]
