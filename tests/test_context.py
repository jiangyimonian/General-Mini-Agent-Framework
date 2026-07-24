"""Tests for request context budgeting."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from core.context import (
    ApproximateTokenCounter,
    ContextBudgetExceeded,
    TokenBudgetContext,
)


class FixedTokenCounter:
    def __init__(self, tokens: int) -> None:
        self.tokens = tokens
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []

    def count(self, messages, *, tools=None) -> int:
        self.calls.append(copy.deepcopy((list(messages), list(tools or []))))
        return self.tokens


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
