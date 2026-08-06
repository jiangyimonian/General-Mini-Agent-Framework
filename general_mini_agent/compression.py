"""上下文压缩策略。

当对话历史超过 Token 预算时，自动压缩旧消息。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .context import (
    ApproximateTokenCounter,
    ContextBudgetExceeded,
    ContextPolicy,
    TokenCounter,
)
from .memory import ConversationMemory


@dataclass
class CompressionResult:
    """压缩结果。"""

    messages: list[dict[str, Any]]
    compressed: int  # 压缩掉的消息数
    token_savings: int  # 估算节省的 Token 数


class CompressionStrategy:
    """压缩策略协议。"""

    def compress(self, messages: list[dict[str, Any]], target_tokens: int) -> CompressionResult:
        """压缩消息列表到目标 Token 数。

        Args:
            messages: 原始消息列表
            target_tokens: 目标 Token 数

        Returns:
            压缩结果
        """
        ...


class SimpleTruncationStrategy:
    """简单截断策略。

    保留：
    - 系统消息（始终保留）
    - 最近的消息

    截断中间的消息。
    """

    def __init__(
        self,
        counter: TokenCounter | None = None,
        keep_recent: int = 10,
        skip_system: bool = True,
    ):
        self.counter = counter or ApproximateTokenCounter()
        self.keep_recent = keep_recent
        self.skip_system = skip_system

    def compress(self, messages: list[dict[str, Any]], target_tokens: int) -> CompressionResult:
        """压缩消息列表。"""
        if not messages:
            return CompressionResult(messages=[], compressed=0, token_savings=0)

        # 分离系统消息和普通消息
        system_messages: list[dict[str, Any]] = []
        user_messages: list[dict[str, Any]] = []

        for msg in messages:
            if self.skip_system and msg.get("role") == "system":
                system_messages.append(msg.copy())
            else:
                user_messages.append(msg.copy())

        if not user_messages:
            return CompressionResult(messages=system_messages, compressed=0, token_savings=0)

        # 计算 token 数的辅助函数
        def count_tokens(msgs: list[dict[str, Any]]) -> int:
            combined = system_messages + msgs
            return self.counter.count(combined, tools=[])

        original_tokens = count_tokens(user_messages)
        compressed = 0

        # 保留的消息：先假设全部保留
        kept = user_messages

        # 第一步：如果消息数超过 keep_recent，先截断到 keep_recent 条
        # (这是硬限制，不管 token 是否足够)
        if len(kept) > self.keep_recent:
            compressed = len(kept) - self.keep_recent
            kept = kept[-self.keep_recent :]

        # 第二步：检查 token，如果还超过目标，并且消息数 > keep_recent，才继续截断
        # 但这里因为第一步已经截断到 keep_recent 了，所以实际上不会再截断
        # (我们不把消息截断到 keep_recent 以下)

        # 构建结果
        result = system_messages + kept
        new_tokens = count_tokens(kept)

        return CompressionResult(
            messages=result,
            compressed=compressed,
            token_savings=original_tokens - new_tokens,
        )


class SummarizationStrategy:
    """摘要策略。

    将旧消息压缩成一条摘要消息。
    """

    def __init__(
        self,
        counter: TokenCounter | None = None,
        summarizer: Callable[[list[dict[str, Any]]], str] | None = None,
        keep_recent: int = 5,
    ):
        self.counter = counter or ApproximateTokenCounter()
        self.summarizer = summarizer or self._default_summarizer
        self.keep_recent = keep_recent

    @staticmethod
    def _default_summarizer(messages: list[dict[str, Any]]) -> str:
        """默认摘要生成器（只用于占位）。"""
        count = len(messages)
        return f"[之前 {count} 条消息的摘要]"

    def compress(self, messages: list[dict[str, Any]], target_tokens: int) -> CompressionResult:
        """压缩消息列表。"""
        if not messages:
            return CompressionResult(messages=[], compressed=0, token_savings=0)

        # 分离系统消息
        system_messages: list[dict[str, Any]] = []
        user_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.get("role") == "system":
                system_messages.append(msg.copy())
            else:
                user_messages.append(msg.copy())

        if len(user_messages) <= self.keep_recent:
            return CompressionResult(messages=list(messages), compressed=0, token_savings=0)

        # 计算当前 Token
        def count_tokens(msgs: list[dict[str, Any]]) -> int:
            combined = system_messages + msgs
            return self.counter.count(combined, tools=[])

        current_tokens = count_tokens(user_messages)

        if current_tokens <= target_tokens:
            return CompressionResult(messages=list(messages), compressed=0, token_savings=0)

        # 保留最近的消息，压缩前面的
        old_messages = user_messages[: -self.keep_recent]
        recent_messages = user_messages[-self.keep_recent :]

        if not old_messages:
            return CompressionResult(messages=list(messages), compressed=0, token_savings=0)

        # 生成摘要
        summary = self.summarizer(old_messages)
        summary_msg = {
            "role": "system",
            "content": f"历史对话摘要: {summary}",
        }

        # 构建结果
        result = system_messages + [summary_msg] + recent_messages

        # 计算节省
        result_tokens = count_tokens([summary_msg] + recent_messages)
        token_savings = max(0, current_tokens - result_tokens)

        return CompressionResult(
            messages=result,
            compressed=len(old_messages),
            token_savings=token_savings,
        )


class AutoCompressingConversation:
    """带自动压缩的对话记忆。

    当准备请求时，如果消息超过 Token 预算，自动压缩。
    """

    def __init__(
        self,
        base_memory: ConversationMemory | None = None,
        compression_strategy: CompressionStrategy | None = None,
    ):
        self.base_memory = base_memory or InMemoryConversation()
        self.compression_strategy = compression_strategy or SimpleTruncationStrategy()
        self.last_compression_result: CompressionResult | None = None

    def get_context(self) -> list[dict[str, Any]]:
        return self.base_memory.get_context()

    def add_messages(self, messages: list[dict[str, Any]]) -> None:
        self.base_memory.add_messages(messages)

    def clear(self) -> None:
        self.base_memory.clear()
        self.last_compression_result = None

    def __len__(self) -> int:
        return len(self.base_memory)

    def compress_to(self, target_tokens: int) -> list[dict[str, Any]]:
        """压缩消息到目标 Token 数。

        Args:
            target_tokens: 目标 Token 数

        Returns:
            压缩后的消息列表
        """
        result = self.compression_strategy.compress(self.get_context(), target_tokens)
        self.last_compression_result = result
        return result.messages


class CompressingContextPolicy(ContextPolicy):
    """带压缩的上下文策略。

    包装现有策略，当上下文超限时自动压缩后重试。
    """

    def __init__(
        self,
        base_policy: ContextPolicy,
        compression_strategy: CompressionStrategy | None = None,
    ):
        self.base_policy = base_policy
        self.compression_strategy = compression_strategy or SimpleTruncationStrategy()
        self.last_compression: CompressionResult | None = None

    def prepare(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            return self.base_policy.prepare(messages, tools)
        except ContextBudgetExceeded:
            # 上下文超限，尝试压缩
            # 估算可用 Token

            if hasattr(self.base_policy, "context_window"):
                target = getattr(self.base_policy, "context_window") - 4096
            else:
                target = 60000  # 默认值

            result = self.compression_strategy.compress(messages, target)
            self.last_compression = result

            # 用压缩后的消息重试
            return self.base_policy.prepare(result.messages, tools)


# 为了循环引用
from .memory import InMemoryConversation
