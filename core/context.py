"""Token counting and request context budget policies."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

_MESSAGE_ROLES = {"system", "user", "assistant", "tool"}


@dataclass
class _MessageUnit:
    messages: list[dict[str, Any]]
    starts_user_turn: bool = False
    protected: bool = False


class TokenCounter(Protocol):
    """Count tokens used by a complete model request input."""

    def count(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> int: ...


class ContextPolicy(Protocol):
    """Prepare a bounded message snapshot for one model request."""

    def prepare(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]: ...


class OversizedContentHandler(Protocol):
    """Replace protected content that cannot fit the configured budget."""

    def __call__(
        self,
        messages: Sequence[Mapping[str, Any]],
        input_budget: int,
    ) -> list[dict[str, Any]]: ...


class ApproximateTokenCounter:
    """Dependency-free deterministic estimate based on serialized characters."""

    def __init__(self, characters_per_token: int = 4) -> None:
        if characters_per_token <= 0:
            raise ValueError("characters_per_token must be positive")
        self.characters_per_token = characters_per_token

    def count(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> int:
        payload = {
            "messages": list(messages),
            "tools": list(tools or []),
        }
        characters = len(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        return max(1, math.ceil(characters / self.characters_per_token))


class ContextBudgetExceeded(Exception):
    """Raised when protected request content cannot fit the input budget."""

    def __init__(self, input_tokens: int, input_budget: int) -> None:
        self.input_tokens = input_tokens
        self.input_budget = input_budget
        super().__init__(
            f"request context requires {input_tokens} tokens; budget is {input_budget}"
        )


class TokenBudgetContext:
    """Enforce an explicit input budget for one model request."""

    def __init__(
        self,
        context_window: int,
        reserved_output_tokens: int,
        *,
        token_counter: TokenCounter | None = None,
        oversized_content_handler: OversizedContentHandler | None = None,
    ) -> None:
        if context_window <= 0:
            raise ValueError("context_window must be positive")
        if reserved_output_tokens <= 0:
            raise ValueError("reserved_output_tokens must be positive")
        if reserved_output_tokens >= context_window:
            raise ValueError("reserved_output_tokens must be smaller than context_window")
        self.context_window = context_window
        self.reserved_output_tokens = reserved_output_tokens
        self.input_budget = context_window - reserved_output_tokens
        self.token_counter = token_counter or ApproximateTokenCounter()
        self.oversized_content_handler = oversized_content_handler

    def prepare(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        prepared, _ = self._prepare_with_removed(messages, tools=tools)
        return prepared

    def _prepare_with_removed(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        prepared = _copy_and_validate_messages(messages)
        request_tools = copy.deepcopy(list(tools or []))
        units = _group_atomic_units(prepared)
        _mark_protected_units(units)
        removed: list[dict[str, Any]] = []

        while self._count(_flatten_units(units), request_tools) > self.input_budget:
            removable_index = next(
                (index for index, unit in enumerate(units) if not unit.protected),
                None,
            )
            if removable_index is None:
                protected = _flatten_units(units)
                return self._handle_protected_overflow(protected, request_tools), removed
            removed.extend(units.pop(removable_index).messages)

        return _flatten_units(units), removed

    def _handle_protected_overflow(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        input_tokens = self._count(messages, tools)
        if self.oversized_content_handler is None:
            raise ContextBudgetExceeded(input_tokens, self.input_budget)

        replacement = self.oversized_content_handler(
            copy.deepcopy(messages),
            self.input_budget,
        )
        prepared = _copy_and_validate_messages(replacement)
        replacement_tokens = self._count(prepared, tools)
        if replacement_tokens > self.input_budget:
            raise ContextBudgetExceeded(replacement_tokens, self.input_budget)
        return prepared

    def _count(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> int:
        count = self.token_counter.count(messages, tools=tools)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("token counter must return a non-negative integer")
        return count


def _copy_and_validate_messages(
    messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    pending_tool_ids: set[str] = set()

    for index, message in enumerate(messages):
        if not isinstance(message, Mapping):
            raise TypeError(f"message at index {index} must be a mapping")
        current = copy.deepcopy(dict(message))
        role = current.get("role")
        if role not in _MESSAGE_ROLES:
            raise ValueError(f"message at index {index} has invalid role")
        if "content" not in current:
            raise ValueError(f"message at index {index} is missing content")

        if role == "tool":
            tool_call_id = current.get("tool_call_id")
            if not isinstance(tool_call_id, str) or tool_call_id not in pending_tool_ids:
                raise ValueError(f"tool message at index {index} is orphaned")
            pending_tool_ids.remove(tool_call_id)
        else:
            if pending_tool_ids:
                raise ValueError("assistant tool calls are missing tool results")
            if role == "assistant" and "tool_calls" in current:
                pending_tool_ids = _validate_tool_calls(current["tool_calls"], index)

        copied.append(current)

    if pending_tool_ids:
        raise ValueError("assistant tool calls are missing tool results")
    return copied


def _validate_tool_calls(tool_calls: Any, message_index: int) -> set[str]:
    if not isinstance(tool_calls, list) or not tool_calls:
        raise ValueError(f"assistant message at index {message_index} has invalid tool_calls")
    call_ids: set[str] = set()
    for call in tool_calls:
        if not isinstance(call, Mapping):
            raise ValueError(f"assistant message at index {message_index} has invalid tool_calls")
        call_id = call.get("id")
        if not isinstance(call_id, str) or not call_id or call_id in call_ids:
            raise ValueError(f"assistant message at index {message_index} has invalid tool call id")
        call_ids.add(call_id)
    return call_ids


def _group_atomic_units(messages: list[dict[str, Any]]) -> list[_MessageUnit]:
    units: list[_MessageUnit] = []
    index = 0
    while index < len(messages):
        role = messages[index]["role"]
        if role == "system":
            units.append(_MessageUnit([messages[index]], protected=True))
            index += 1
            continue

        if role == "user":
            end = index + 1
            while end < len(messages) and messages[end]["role"] not in {"system", "user"}:
                end += 1
            units.append(_MessageUnit(messages[index:end], starts_user_turn=True))
            index = end
            continue

        if role == "assistant" and messages[index].get("tool_calls"):
            call_ids = {call["id"] for call in messages[index]["tool_calls"]}
            end = index + 1
            while end < len(messages):
                if messages[end].get("tool_call_id") not in call_ids:
                    break
                end += 1
            units.append(_MessageUnit(messages[index:end]))
            index = end
            continue

        units.append(_MessageUnit([messages[index]]))
        index += 1
    return units


def _mark_protected_units(units: list[_MessageUnit]) -> None:
    user_turns = [unit for unit in units if unit.starts_user_turn]
    for unit in user_turns[-2:]:
        unit.protected = True


def _flatten_units(units: Sequence[_MessageUnit]) -> list[dict[str, Any]]:
    return [message for unit in units for message in unit.messages]
